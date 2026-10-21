"""Flyway가 관리하는 user_baselines 테이블 매핑."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserBaseline(Base):
    __tablename__ = "user_baselines"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    base_date: Mapped[date] = mapped_column(Date, primary_key=True)
    calculation_version: Mapped[str] = mapped_column(String(30), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    out_count_30d: Mapped[int] = mapped_column(Integer)
    avg_out_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    std_out_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    p95_out_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    avg_daily_spend: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    airflow_run_id: Mapped[str] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
