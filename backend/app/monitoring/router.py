from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth.dependencies import AuthPrincipal, get_current_user
from app.db.session import get_db
from app.monitoring.schemas import MonitoringConsent
from app.monitoring.service import set_monitoring

DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]

router = APIRouter(prefix="/demo/me", tags=["monitoring"])


@router.put("/monitoring-consent")
def monitoring(payload: MonitoringConsent, db: DB, principal: Current):
    return set_monitoring(db, principal, payload.consented)
