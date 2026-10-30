from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthPrincipal, get_current_user
from app.budgets import settings as budget_settings
from app.budgets.queries import current_budget_forecast
from app.budgets.schemas import BudgetSettingsUpdate, ExpenseSave, ForecastResponse
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


settings_router = APIRouter(tags=["budgets"])
ExpenseId = Annotated[int, PathParam(gt=0, le=9223372036854775807)]


@settings_router.put("/budget-settings")
def put_budget_settings(payload: BudgetSettingsUpdate, db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return budget_settings.save_settings(db, principal.user.user_id, payload)


@settings_router.post("/scheduled-expenses", status_code=201)
def post_expense(payload: ExpenseSave, db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return budget_settings.create_expense(db, principal.user.user_id, payload)


@settings_router.patch("/scheduled-expenses/{expense_id}")
def patch_expense(expense_id: ExpenseId, payload: ExpenseSave, db: DB, principal: Current, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return budget_settings.update_expense(db, principal.user.user_id, expense_id, payload)
