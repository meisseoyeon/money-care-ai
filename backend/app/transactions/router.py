from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from app.ai.explanation.service import upgrade_explanation_in_background
from app.auth.dependencies import AuthPrincipal, get_current_user, require_monitoring_consent
from app.db.session import get_db
from app.transactions.schemas import TransferCreate
from app.transactions import help as transfer_help
from app.transactions import service

router = APIRouter(tags=["transactions"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/transfers")
def transfer(payload: TransferCreate, db: DB, response: Response, background_tasks: BackgroundTasks,
             principal: Annotated[AuthPrincipal, Depends(require_monitoring_consent)]):
    response.headers["Cache-Control"] = "no-store"
    result = service.create_transfer(db, principal, payload)
    # 송금 응답을 먼저 보내고, 쉬운 설명은 뒤에서 LLM으로 바꿈
    for alert_id in result["alert_ids"]:
        background_tasks.add_task(upgrade_explanation_in_background, principal.user.user_id, alert_id)
    return result


@router.post("/transfer-help-requests")
def transfer_help_request(payload: TransferCreate, db: DB, response: Response,
                          principal: Annotated[AuthPrincipal, Depends(require_monitoring_consent)]):
    response.headers["Cache-Control"] = "no-store"
    return transfer_help.create_transfer_help(db, principal, payload)


@router.get("/transactions")
def transactions(db: DB, response: Response,
                 principal: Annotated[AuthPrincipal, Depends(get_current_user)],
                 limit: Annotated[int, Query(ge=1, le=200)] = 100,
                 cursor: Annotated[str | None, Query(min_length=1, max_length=100)] = None):
    response.headers["Cache-Control"] = "no-store"
    return service.list_transactions(db, principal.user.user_id, limit, cursor)
