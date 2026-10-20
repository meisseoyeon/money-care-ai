from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth.dependencies import AuthPrincipal, get_current_user
from app.db.session import get_db
from app.recipients.service import list_recipients

DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]

router = APIRouter(prefix="/demo/recipients", tags=["recipients"])


@router.get("")
def recipients(db: DB, principal: Current):
    return list_recipients(db, principal.user.user_id)
