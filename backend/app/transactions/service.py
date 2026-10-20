import hashlib

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.core.time import aware, utc_now
from app.accounts.models import Account
from app.transactions.models import Transaction
from app.recipients.catalog import RECIPIENTS


def transaction_response(transaction):
    return {"id": transaction.id, "account_id": transaction.account_id,
            "user_id": transaction.user_id, "occurred_at": aware(transaction.occurred_at),
            "direction": transaction.direction, "amount": transaction.amount,
            "balance_after": transaction.balance_after, "tx_type": transaction.tx_type,
            "counterparty_id": transaction.counterparty_id,
            "description": transaction.description, "source": transaction.source}


def create_transfer(db, principal, payload):
    recipient = next((item for item in RECIPIENTS if item["id"] == payload.counterparty_id), None)
    if not recipient:
        raise HTTPException(404, "받는 사람을 찾을 수 없어요. 목록에서 다시 선택해 주세요.")
    user_id = principal.user.user_id
    # 사용자별 요청 ID를 거래 PK로 사용하므로 별도 테이블 없이 재전송을 식별합니다.
    transaction_id = "demo-" + hashlib.sha256(f"{user_id}:{payload.request_id}".encode()).hexdigest()
    # require_monitoring_consent가 먼저 세션 → 사용자 잠금을 획득합니다.
    account = db.scalar(select(Account).where(Account.user_id == user_id).with_for_update())
    if not account:
        raise HTTPException(404, "체험 계좌를 찾을 수 없어요.")
    existing = db.get(Transaction, transaction_id)
    if existing:
        if (existing.user_id != user_id or existing.account_id != account.account_id
                or existing.source != "DEMO" or existing.tx_type != "TRANSFER"
                or existing.amount != payload.amount or existing.counterparty_id != payload.counterparty_id):
            raise HTTPException(409, "같은 송금 요청으로 금액이나 받는 사람을 바꿀 수 없어요.")
        return {"transaction": transaction_response(existing), "alert_ids": [], "forecast": None}
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
    # 거래 기록 저장과 잔액 변경은 함께 성공하거나 함께 롤백합니다.
    db.commit()
    return {"transaction": transaction_response(transaction), "alert_ids": [], "forecast": None}


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
