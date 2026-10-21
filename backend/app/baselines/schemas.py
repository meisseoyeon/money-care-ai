from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BaselineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    base_date: date
    calculation_version: str
    as_of: datetime
    window_start: datetime
    window_end: datetime
    out_count_30d: int
    avg_out_amount: Decimal | None
    std_out_amount: Decimal | None
    p95_out_amount: Decimal | None
    avg_daily_spend: Decimal | None
