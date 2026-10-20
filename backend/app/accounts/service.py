from fastapi import HTTPException
from sqlalchemy import select
from app.core.time import aware
from app.accounts.models import Account


def account_response(account):
    return {"account_id": account.account_id, "user_id": account.user_id,
            "display_name": account.display_name, "current_balance": account.current_balance,
            "balance_as_of": aware(account.balance_as_of)}


def own_account(db, user_id, account_id):
    account = db.scalar(select(Account).where(Account.user_id == user_id, Account.account_id == account_id))
    if not account:
        raise HTTPException(404, "계좌를 찾을 수 없어요.")
    return account_response(account)
