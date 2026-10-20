import hashlib
import json
import os
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import aware, issue_token, resolve_principal, signing_key, unauthorized, utc_now
from app.models.demo_session import Account, BudgetSetting, DemoSession, ScheduledExpense, User
from app.services.demo_seed import seed_demo_user


def find_creation(db, key_hash):
    return db.scalar(select(DemoSession).where(DemoSession.creation_key_hash == key_hash))


def token_response(db, session):
    if session.revoked_at is not None or aware(session.expires_at) <= utc_now():
        raise unauthorized()
    user = db.get(User, session.user_id)
    if user.status != "ACTIVE":
        raise unauthorized()
    return {"access_token": issue_token(session), "token_type": "bearer",
            "expires_at": aware(session.expires_at), "user": user_response(user)}


def create_session(db, payload, creation_key, claims=None):
    signing_key()  # 키 설정 오류라면 DB를 변경하기 전에 중단합니다.
    key_hash = hashlib.sha256(str(creation_key).encode()).hexdigest()
    previous_id = claims["sid"] if payload.restart and claims else None
    fingerprint = hashlib.sha256(json.dumps({**payload.model_dump(), "previous": previous_id}, sort_keys=True).encode()).hexdigest()
    existing = find_creation(db, key_hash)
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "같은 생성 요청 키로 다른 체험을 만들 수 없어요.")
        if claims and not payload.restart:
            principal = resolve_principal(db, claims)
            if existing.user_id != principal.user.user_id:
                raise HTTPException(409, "다른 사용자의 체험 생성 요청은 재사용할 수 없어요.")
        return token_response(db, existing)
    if payload.restart and not claims:
        raise unauthorized()
    try:
        previous = resolve_principal(db, claims, lock=True) if claims else None
    except HTTPException as exc:
        # 같은 재시작 요청이 먼저 완료되어 기존 세션이 폐기된 경합도 재사용합니다.
        existing = find_creation(db, key_hash)
        if exc.status_code == 401 and existing and existing.request_fingerprint == fingerprint:
            return token_response(db, existing)
        raise
    if previous and not payload.restart:
        return token_response(db, previous.session)
    now = utc_now().replace(microsecond=0)
    try:
        ttl = int(os.getenv("DEMO_SESSION_TTL_SECONDS", "86400"))
    except ValueError:
        raise HTTPException(503, "체험 유효 시간 설정이 올바르지 않아요.") from None
    if ttl < 60 or ttl > 604800:
        raise HTTPException(503, "체험 유효 시간은 60초에서 7일 사이로 설정해 주세요.")
    try:
        # 동시 요청의 UNIQUE 충돌까지 이 범위 전체가 취소되어 고아 사용자가 남지 않습니다.
        with db.begin_nested():
            user = seed_demo_user(db, now, payload.monitoring_consented)
            if previous:
                previous.session.revoked_at = now
            session = DemoSession(session_id=str(uuid4()), user_id=user.user_id,
                                  creation_key_hash=key_hash, request_fingerprint=fingerprint,
                                  replaces_session_id=previous_id, created_at=now,
                                  expires_at=now + timedelta(seconds=ttl), revoked_at=None)
            db.add(session)
            db.flush()
    except IntegrityError:
        existing = find_creation(db, key_hash)
        if not existing:
            raise
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(409, "같은 생성 요청 키로 다른 체험을 만들 수 없어요.") from None
        return token_response(db, existing)
    db.commit()
    return token_response(db, session)


def user_response(user):
    # 비밀번호 해시와 내부 세션 생성 키는 응답하지 않습니다.
    return {"user_id": user.user_id, "email": user.email, "display_name": user.display_name,
            "role": "OWNER", "status": user.status,
            "monitoring_consented_at": aware(user.monitoring_consented_at) if user.monitoring_consented_at else None,
            "monitoring_revoked_at": aware(user.monitoring_revoked_at) if user.monitoring_revoked_at else None, "is_demo": True}


def account_response(account):
    return {"account_id": account.account_id, "user_id": account.user_id,
            "display_name": account.display_name, "current_balance": account.current_balance,
            "balance_as_of": aware(account.balance_as_of)}


def own_account(db, user_id, account_id):
    account = db.scalar(select(Account).where(Account.user_id == user_id, Account.account_id == account_id))
    if not account:
        raise HTTPException(404, "계좌를 찾을 수 없어요.")
    return account_response(account)


def demo_context(db, principal):
    user_id = principal.user.user_id
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    settings = db.get(BudgetSetting, user_id)
    expenses = db.scalars(select(ScheduledExpense).where(ScheduledExpense.user_id == user_id).order_by(ScheduledExpense.id)).all()
    return {"user": user_response(principal.user), "expires_at": aware(principal.session.expires_at),
            "account": account_response(account),
            "settings": {"user_id": user_id, "next_income_date": settings.next_income_date,
                         "expected_income_amount": settings.expected_income_amount, "daily_living_budget": settings.daily_living_budget},
            "expenses": [{"id": str(e.id), "user_id": user_id, "title": e.title, "amount": e.amount,
                          "due_date": e.due_date, "status": e.status} for e in expenses]}


def set_monitoring(db, principal, consented):
    # 잠금 순서는 다른 보호 작업과 동일하게 세션 → 사용자로 통일합니다.
    user = resolve_principal(db, {"sid": principal.session.session_id, "sub": principal.user.user_id}, lock=True).user
    now = utc_now()
    if consented and (not user.monitoring_consented_at or user.monitoring_revoked_at):
        user.monitoring_consented_at, user.monitoring_revoked_at = now, None
    elif not consented and user.monitoring_consented_at and not user.monitoring_revoked_at:
        user.monitoring_revoked_at = now
    user.updated_at = now
    db.commit()
    return user_response(user)
