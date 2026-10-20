from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.auth import (DemoPrincipal, bearer, decode_token, get_current_demo_user,
                           resolve_principal, utc_now)
from app.db.session import get_db
from app.schemas.demo import DemoSessionCreate, MonitoringConsent
from app.services import demo_service
from app.services.demo_seed import RECIPIENTS

router = APIRouter(prefix="/demo", tags=["demo"])
DB = Annotated[Session, Depends(get_db)]
Current = Annotated[DemoPrincipal, Depends(get_current_demo_user)]


@router.post("/sessions")
def create_demo(payload: DemoSessionCreate, db: DB, response: Response,
                creation_key: Annotated[UUID, Header(alias="Idempotency-Key")],
                credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    response.headers["Cache-Control"] = "no-store"
    # 재시작 응답 유실의 재시도는 원본 토큰의 서명과 이전 세션 ID로 검증합니다.
    # 만료 토큰으로 새 세션을 만드는 것은 서비스의 DB 검증에서 차단합니다.
    claims = decode_token(credentials.credentials, allow_expired=payload.restart) if credentials else None
    return demo_service.create_session(db, payload, creation_key, claims)


@router.get("/me")
def demo_me(db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return demo_service.demo_context(db, principal)


@router.get("/recipients")
def recipients(principal: Current):
    # 실제 사용자·계좌 목록은 수취인 목록에 포함하지 않습니다.
    return RECIPIENTS


@router.get("/accounts/{account_id}")
def get_account(account_id: str, db: DB, principal: Current):
    return demo_service.own_account(db, principal.user.user_id, account_id)


@router.put("/me/monitoring-consent")
def monitoring(payload: MonitoringConsent, db: DB, principal: Current):
    return demo_service.set_monitoring(db, principal, payload.consented)


@router.delete("/sessions/current", status_code=204)
def end_session(db: DB, principal: Current):
    fresh = resolve_principal(db, {"sid": principal.session.session_id, "sub": principal.user.user_id}, lock=True)
    fresh.session.revoked_at = utc_now()
    db.commit()
