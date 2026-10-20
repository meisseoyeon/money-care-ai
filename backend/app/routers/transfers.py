from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.auth import DemoPrincipal, get_current_demo_user, require_monitoring_consent
from app.db.session import get_db
from app.schemas.transfer import TransferCreate
from app.services import transfer as service

router = APIRouter(tags=["transactions"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/transfers")
def transfer(payload: TransferCreate, db: DB, response: Response,
             principal: Annotated[DemoPrincipal, Depends(require_monitoring_consent)]):
    response.headers["Cache-Control"] = "no-store"
    return service.create_transfer(db, principal, payload)


@router.get("/transactions")
def transactions(db: DB, response: Response,
                 principal: Annotated[DemoPrincipal, Depends(get_current_demo_user)],
                 limit: Annotated[int, Query(ge=1, le=200)] = 100,
                 cursor: Annotated[str | None, Query(min_length=1, max_length=100)] = None):
    response.headers["Cache-Control"] = "no-store"
    return service.list_transactions(db, principal.user.user_id, limit, cursor)
