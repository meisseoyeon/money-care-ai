from sqlalchemy import select
from app.budgets.models import BudgetSetting, ScheduledExpense


def budget_context(db, user_id):
    settings = db.get(BudgetSetting, user_id)
    expenses = db.scalars(select(ScheduledExpense).where(ScheduledExpense.user_id == user_id).order_by(ScheduledExpense.id)).all()
    return {"settings": {"user_id": user_id, "next_income_date": settings.next_income_date,
                         "expected_income_amount": settings.expected_income_amount, "daily_living_budget": settings.daily_living_budget},
            "expenses": [{"id": str(e.id), "user_id": user_id, "title": e.title, "amount": e.amount,
                          "due_date": e.due_date, "status": e.status} for e in expenses]}
