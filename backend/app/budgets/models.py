from datetime import date, datetime
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class BudgetSetting(Base):
    __tablename__ = "budget_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    next_income_date: Mapped[date] = mapped_column(Date)
    expected_income_amount: Mapped[int] = mapped_column(BigInteger)
    daily_living_budget: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScheduledExpense(Base):
    __tablename__ = "scheduled_expenses"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    title: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(BigInteger)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
