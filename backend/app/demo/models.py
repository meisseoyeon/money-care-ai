"""초기 준비 실행과 최초 결과의 연결 기록."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, ForeignKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InitializationRun(Base):
    __tablename__ = "initialization_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "baseline_date", "baseline_version"],
            ["user_baselines.user_id", "user_baselines.base_date", "user_baselines.calculation_version"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "user_id", "budget_as_of", "budget_version"],
            ["budget_input_snapshots.id", "budget_input_snapshots.user_id",
             "budget_input_snapshots.as_of", "budget_input_snapshots.calculation_version"],
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(250), primary_key=True)
    baseline_version: Mapped[str] = mapped_column(String(30), primary_key=True)
    budget_version: Mapped[str] = mapped_column(String(30), primary_key=True)
    baseline_date: Mapped[date] = mapped_column(Date)
    budget_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("budget_forecasts.snapshot_id", ondelete="CASCADE"))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
