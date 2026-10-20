from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthPrincipal, get_current_user, resolve_principal
from app.db.session import get_db
from app.core.time import utc_now
from app.auth.schemas import LoginRequest
from app.auth import service as auth_service
from app.users.serializers import user_response

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]


@router.post("/login")
def login(payload: LoginRequest, db: DB, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return auth_service.login(db, payload)


@router.get("/me")
def me(principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_response(principal.user), "expires_at": principal.session.expires_at}


@router.post("/logout", status_code=204)
def logout(db: DB, principal: Current):
    fresh = resolve_principal(db, {"sid": principal.session.session_id, "sub": principal.user.user_id}, lock=True)
    fresh.session.revoked_at = utc_now()
    db.commit()
