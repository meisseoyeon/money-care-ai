from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthPrincipal, get_current_user
from app.budgets.queries import current_budget_forecast
from app.budgets.schemas import ForecastResponse
from app.db.session import get_db

router = APIRouter(prefix="/budget-forecasts", tags=["budgets"])
DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]


@router.get("/latest", response_model=ForecastResponse)
def latest_forecast(db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return current_budget_forecast(db, user_id=principal.user.user_id)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
        raise
