"""생활비 설정과 예정 지출 저장. 저장 후 생활비 결과를 새 입력으로 다시 계산합니다."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budgets.forecasts import ensure_budget_forecast
from app.budgets.models import BudgetSetting, ScheduledExpense
from app.budgets.snapshots import SEOUL, ensure_budget_input_snapshot
from app.users.models import User
from app.users.roles import user_role


def _lock_owner(db: Session, user_id: str) -> None:
    if user_role(user_id) != "OWNER":
        raise HTTPException(403, "생활비는 당사자만 수정할 수 있어요.")
    # 송금과 같은 순서로 사용자 행을 먼저 잠가 저장과 계산을 직렬화합니다.
    if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update()) is None:
        raise HTTPException(404, "사용자를 찾을 수 없어요.")


def _recalculate(db: Session, user_id: str) -> None:
    """입력이 바뀌면 이전 결과는 쓸 수 없으므로 새 입력과 결과를 함께 저장합니다."""
    try:
        snapshot = ensure_budget_input_snapshot(db, user_id=user_id, run_id=f"budget-edit:{uuid4()}")
        ensure_budget_forecast(db, user_id=user_id, snapshot_id=snapshot.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def save_settings(db: Session, user_id: str, payload) -> dict:
    try:
        _lock_owner(db, user_id)
        now = db.scalar(select(func.clock_timestamp()))
        if payload.next_income_date < now.astimezone(SEOUL).date():
            raise HTTPException(422, "다음 수입일을 오늘 이후로 바꿔 주세요.")
        settings = db.get(BudgetSetting, user_id, populate_existing=True)
        if settings is None:
            raise HTTPException(404, "생활비 설정을 찾을 수 없어요.")
        settings.next_income_date = payload.next_income_date
        settings.expected_income_amount = payload.expected_income_amount
        settings.daily_living_budget = payload.daily_living_budget
        settings.updated_at = now
        db.flush()
        _recalculate(db, user_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"user_id": user_id, "next_income_date": payload.next_income_date,
            "expected_income_amount": payload.expected_income_amount,
            "daily_living_budget": payload.daily_living_budget}


def _expense_response(expense: ScheduledExpense) -> dict:
    return {"id": str(expense.id), "user_id": expense.user_id, "title": expense.title,
            "amount": expense.amount, "due_date": expense.due_date, "status": expense.status}


def create_expense(db: Session, user_id: str, payload) -> dict:
    try:
        _lock_owner(db, user_id)
        now = db.scalar(select(func.clock_timestamp()))
        expense = ScheduledExpense(user_id=user_id, title=payload.title, amount=payload.amount,
                                   due_date=payload.due_date, status=payload.status,
                                   created_at=now, updated_at=now)
        db.add(expense)
        db.flush()
        _recalculate(db, user_id)
        response = _expense_response(expense)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response


def update_expense(db: Session, user_id: str, expense_id: int, payload) -> dict:
    try:
        _lock_owner(db, user_id)
        expense = db.scalar(select(ScheduledExpense).where(
            ScheduledExpense.id == expense_id, ScheduledExpense.user_id == user_id,
        ).with_for_update().execution_options(populate_existing=True))
        if expense is None:
            raise HTTPException(404, "지출을 찾을 수 없어요.")
        expense.title = payload.title
        expense.amount = payload.amount
        expense.due_date = payload.due_date
        expense.status = payload.status
        expense.updated_at = db.scalar(select(func.clock_timestamp()))
        db.flush()
        _recalculate(db, user_id)
        response = _expense_response(expense)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response
