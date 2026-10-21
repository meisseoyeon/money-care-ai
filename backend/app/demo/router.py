from typing import Annotated
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.auth.dependencies import AuthPrincipal, get_current_user
from app.db.session import get_db
from app.demo.service import demo_context

DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/me")
def demo_me(db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return demo_context(db, principal)
