from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator


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


MAX_MONEY = 1_000_000_000


class BudgetSettingsUpdate(BaseModel):
    next_income_date: date
    expected_income_amount: Annotated[StrictInt, Field(ge=0, le=MAX_MONEY)]
    daily_living_budget: Annotated[StrictInt, Field(ge=0, le=MAX_MONEY)]


class ExpenseSave(BaseModel):
    # 수정 화면은 id, user_id도 함께 보내므로 모르는 값은 무시하고 경로의 id만 사용합니다.
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    amount: Annotated[StrictInt, Field(gt=0, le=MAX_MONEY)]
    due_date: date
    status: Literal["PLANNED", "PAID", "CANCELLED"] = "PLANNED"
