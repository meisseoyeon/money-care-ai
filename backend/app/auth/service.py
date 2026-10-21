import os
import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import issue_token, signing_key
from app.core.time import utc_now
from app.auth.passwords import hash_password, verify_password
from app.auth.models import AuthSession
from app.users.models import User
from app.users.serializers import user_response
from app.demo.initialization import ensure_initial_preparation

logger = logging.getLogger(__name__)

# 존재하지 않는 아이디도 비밀번호 해시 계산을 거칩니다.
DUMMY_HASH = hash_password("not-an-account")


def login(db, payload):
    signing_key()
    try:
        ttl = int(os.getenv("AUTH_SESSION_TTL_SECONDS", os.getenv("DEMO_SESSION_TTL_SECONDS", "86400")))
    except ValueError:
        raise HTTPException(503, "로그인 유효 시간 설정이 올바르지 않아요.") from None
    if not 60 <= ttl <= 604800:
        raise HTTPException(503, "로그인 유효 시간은 60초에서 7일 사이로 설정해 주세요.")
    user = db.get(User, payload.username)
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or user.status != "ACTIVE":
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않아요.", headers={"WWW-Authenticate": "Bearer"})
    try:
        verified_hash = user.password_hash
        # 잠금 순서는 기존 송금과 동일하게 유지합니다.
        db.refresh(user, with_for_update=True)
        if user.status != "ACTIVE" or (user.password_hash != verified_hash
                                          and not verify_password(payload.password, user.password_hash)):
            raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않아요.", headers={"WWW-Authenticate": "Bearer"})
        session_id = str(uuid4())
        initialization = ensure_initial_preparation(db, user_id=user.user_id, run_id=f"init:login:{session_id}")
        now = utc_now()
        session = AuthSession(session_id=session_id, user_id=user.user_id, created_at=now,
                              expires_at=now + timedelta(seconds=ttl), revoked_at=None)
        db.add(session)
        token = issue_token(session)
        result = {"access_token": token, "token_type": "bearer", "expires_at": session.expires_at,
                  "user": user_response(user), "initialization": initialization}
        # 세션 저장·토큰 생성·최종 commit 실패까지 같은 롤백 범위에 둡니다.
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("로그인 초기 준비에 실패했습니다.")
        detail = (str(exc) if isinstance(exc, (ValueError, LookupError))
                  else "DB 마이그레이션과 연결 상태를 확인해 주세요." if isinstance(exc, SQLAlchemyError)
                  else "잠시 후 다시 시도해 주세요.")
        raise HTTPException(503, f"체험 데이터를 준비하지 못했어요. {detail}") from exc
