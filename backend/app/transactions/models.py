from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str] = mapped_column(String(3))
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    tx_type: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(255))
    counterparty_id: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20))
