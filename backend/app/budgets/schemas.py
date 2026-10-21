from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class ForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    snapshot_id: str
    user_id: str
    as_of: datetime
    balance_as_of: datetime
    next_income_date: date
    remaining_days: int
    current_balance: int
    scheduled_expense_total: int
    daily_living_budget: int
    expected_living_cost: int
    available_amount: int
    shortage_amount: int
    calculation_version: str

    @field_validator("id", "snapshot_id", mode="before")
    @classmethod
    def stringify_id(cls, value):
        return str(value)
