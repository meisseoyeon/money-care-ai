import hashlib
import logging

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.core.time import aware, utc_now
from app.accounts.models import Account
from app.ai.detection.service import run_transaction_detection
from app.transactions.models import Transaction
from app.recipients.catalog import RECIPIENTS
from app.budgets.schemas import ForecastResponse
from app.baselines.calculator import SEOUL
from app.transactions.budgets import check_transfer_preparation, create_transfer_forecast, find_transfer_forecast
from app.users.models import User

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


def detect_alerts(db, transaction_id):
    # 송금은 이미 저장됐으므로 탐지가 실패해도 송금 응답은 그대로 돌려줍니다.
    # 탐지 SQL은 PostgreSQL 전용이라 SQLite 단위 테스트에서는 건너뜁니다.
    if db.get_bind().dialect.name != "postgresql":
        return []
    try:
        return run_transaction_detection(db, transaction_id)
    except Exception:
        db.rollback()
        logger.exception("transaction detection failed: %s", transaction_id)
        return []


def transaction_response(transaction):
    return {"id": transaction.id, "account_id": transaction.account_id,
            "user_id": transaction.user_id, "occurred_at": aware(transaction.occurred_at),
            "direction": transaction.direction, "amount": transaction.amount,
            "balance_after": transaction.balance_after, "tx_type": transaction.tx_type,
            "counterparty_id": transaction.counterparty_id,
            "description": transaction.description, "source": transaction.source}


def create_transfer(db, principal, payload):
    try:
        result = _create_transfer(db, principal, payload)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("송금·생활비 결과 저장에 실패했습니다.")
        raise HTTPException(
            503,
            "송금 처리를 완료하지 못했어요. "
            "거래내역을 확인한 뒤 다시 시도해 주세요.",
        ) from exc

    # 송금과 생활비 결과가 저장된 뒤 탐지를 실행합니다.
    # 완료된 요청의 재전송도 같은 거래 ID로 탐지에 전달합니다.
    result["alert_ids"] = detect_alerts(db, result["transaction"]["id"])
    return result
  
def _forecast_response(forecast):
    return ForecastResponse.model_validate(forecast).model_dump(mode="json") if forecast is not None else None


def _create_transfer(db, principal, payload):
    recipient = next((item for item in RECIPIENTS if item["id"] == payload.counterparty_id), None)
    user_id = principal.user.user_id
    # 사용자별 요청 ID를 거래 PK로 사용하므로 별도 테이블 없이 재전송을 식별합니다.
    transaction_id = "demo-" + hashlib.sha256(f"{user_id}:{payload.request_id}".encode()).hexdigest()
    # API에서는 세션 → 사용자 순서로 잠급니다. 내부 호출도 사용자 잠금 아래 처리합니다.
    if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update()) is None:
        raise HTTPException(404, "사용자를 찾을 수 없어요.")
    existing = db.scalar(select(Transaction).where(Transaction.id == transaction_id)
                         .execution_options(populate_existing=True))
    if existing:
        if (existing.user_id != user_id
                or existing.source != "DEMO" or existing.tx_type != "TRANSFER"
                or existing.amount != payload.amount or existing.counterparty_id != payload.counterparty_id):
            raise HTTPException(409, "같은 송금 요청으로 금액이나 받는 사람을 바꿀 수 없어요.")
        forecast = find_transfer_forecast(db, user_id=user_id, transaction_id=existing.id)
        return {"transaction": transaction_response(existing), "alert_ids": [], "forecast": _forecast_response(forecast)}
    # 이미 완료된 요청은 준비가 바뀌었어도 재차 차감하지 않고 최초 결과를 반환합니다.
    if not recipient:
        raise HTTPException(404, "받는 사람을 찾을 수 없어요. 목록에서 다시 선택해 주세요.")
    preparation_date = check_transfer_preparation(db, user_id=user_id)
    account = db.scalar(select(Account).where(Account.user_id == user_id).order_by(Account.account_id)
                        .with_for_update().execution_options(populate_existing=True))
    if not account:
        raise HTTPException(404, "체험 계좌를 찾을 수 없어요.")
    if payload.amount > account.current_balance:
        raise HTTPException(409, "통장 잔액이 부족해요. 금액을 다시 확인해 주세요.")
    now = utc_now()
    account.current_balance -= payload.amount
    account.balance_as_of = account.updated_at = now
    transaction = Transaction(id=transaction_id, account_id=account.account_id, user_id=user_id,
                              occurred_at=now, received_at=now, direction="OUT", amount=payload.amount,
                              balance_after=account.current_balance, tx_type="TRANSFER", channel="BANK_TRANSFER",
                              description=f"{recipient['name']}님에게 송금", counterparty_id=recipient["id"], source="DEMO")
    db.add(transaction)
    db.flush()
    forecast = create_transfer_forecast(db, user_id=user_id, transaction=transaction)
    if forecast is None:
        raise RuntimeError("송금 후 생활비 결과가 생성되지 않았습니다.")
    if aware(forecast.as_of).astimezone(SEOUL).date() != preparation_date:
        raise HTTPException(409, "송금 중 날짜가 바뀌었어요. 다시 로그인해 오늘의 준비를 마쳐 주세요.")
    # 거래·잔액·입력·생활비 결과는 상위 함수에서 함께 commit/rollback합니다.
    return {"transaction": transaction_response(transaction), "alert_ids": [], "forecast": _forecast_response(forecast)}


def list_transactions(db, user_id, limit, cursor):
    query = select(Transaction).where(Transaction.user_id == user_id)
    if cursor:
        previous = db.scalar(select(Transaction).where(Transaction.id == cursor, Transaction.user_id == user_id))
        if not previous:
            raise HTTPException(404, "거래 조회 위치를 찾을 수 없어요.")
        query = query.where(or_(Transaction.occurred_at < previous.occurred_at,
                                and_(Transaction.occurred_at == previous.occurred_at, Transaction.id < previous.id)))
    rows = db.scalars(query.order_by(Transaction.occurred_at.desc(), Transaction.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {"items": [transaction_response(row) for row in items],
            "next_cursor": items[-1].id if len(rows) > limit else None}
