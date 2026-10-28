from datetime import date, datetime
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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


class BudgetInputSnapshot(Base):
    """Flyway로 생성한 불변 생활비 입력. JSONB는 테스트 SQLite에서만 JSON 사용."""

    __tablename__ = "budget_input_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "as_of", "calculation_version"),
        UniqueConstraint("id", "user_id", "as_of", "calculation_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    calculation_version: Mapped[str] = mapped_column(String(30))
    airflow_run_id: Mapped[str] = mapped_column(String(250))
    balance_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_income_date: Mapped[date] = mapped_column(Date)
    expected_income_amount: Mapped[int] = mapped_column(BigInteger)
    daily_living_budget: Mapped[int] = mapped_column(BigInteger)
    current_balance: Mapped[int] = mapped_column(BigInteger)
    scheduled_expense_total: Mapped[int] = mapped_column(BigInteger)
    accounts_snapshot: Mapped[list[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    expenses_snapshot: Mapped[list[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetForecast(Base):
    """기존 budget_forecasts 테이블. 결과는 입력 스냅샷당 한 번 저장합니다."""

    __tablename__ = "budget_forecasts"
    __table_args__ = (
        UniqueConstraint("user_id", "as_of", "calculation_version"),
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(
            ["snapshot_id", "user_id", "as_of", "calculation_version"],
            ["budget_input_snapshots.id", "budget_input_snapshots.user_id",
             "budget_input_snapshots.as_of", "budget_input_snapshots.calculation_version"],
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    balance_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_income_date: Mapped[date] = mapped_column(Date)
    remaining_days: Mapped[int] = mapped_column(Integer)
    current_balance: Mapped[int] = mapped_column(BigInteger)
    scheduled_expense_total: Mapped[int] = mapped_column(BigInteger)
    daily_living_budget: Mapped[int] = mapped_column(BigInteger)
    expected_living_cost: Mapped[int] = mapped_column(BigInteger)
    available_amount: Mapped[int] = mapped_column(BigInteger)
    shortage_amount: Mapped[int] = mapped_column(BigInteger)
    calculation_version: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
