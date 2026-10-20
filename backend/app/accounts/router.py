from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth.dependencies import AuthPrincipal, get_current_user
from app.db.session import get_db
from app.accounts.service import own_account

DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]

router = APIRouter(prefix="/demo/accounts", tags=["accounts"])


@router.get("/{account_id}")
def get_account(account_id: str, db: DB, principal: Current):
    return own_account(db, principal.user.user_id, account_id)
