from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthPrincipal, get_current_user
from app.baselines.schemas import BaselineResponse
from app.baselines.service import get_current_baseline
from app.db.session import get_db

router = APIRouter(prefix="/baselines", tags=["baselines"])
DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]


@router.get("/current", response_model=BaselineResponse)
def current_baseline(db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    row = get_current_baseline(db, user_id=principal.user.user_id)
    if row is None:
        raise HTTPException(404, "오늘의 기준 통계가 아직 준비되지 않았어요. 다시 로그인해 주세요.",
                            headers={"Cache-Control": "no-store"})
    return row
