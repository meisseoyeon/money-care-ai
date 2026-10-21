import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alerts import service as alert_service
from app.auth.dependencies import get_current_user_id
from app.db.session import get_db

router = APIRouter(prefix="/alerts", tags=["alerts"])


class ResponseIn(BaseModel):
    # 이 3개 말고 다른 값이 오면 FastAPI가 자동으로 422 에러를 돌려줌
    response: Literal["PLANNED", "UNSURE", "HELP_REQUESTED"]


def _check_id(alert_id: str) -> None:
    try:
        uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없어요.")


@router.get("")
def get_alerts(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return alert_service.list_alerts(db, user_id)


@router.post("/{alert_id}/seen")
def post_seen(alert_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _check_id(alert_id)
    alert = alert_service.mark_seen(db, user_id, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없어요.")
    return alert


@router.post("/{alert_id}/response")
def post_response(alert_id: str, body: ResponseIn,
                  user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _check_id(alert_id)
    alert = alert_service.save_response(db, user_id, alert_id, body.response)
    if alert is None:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없어요.")
    return alert