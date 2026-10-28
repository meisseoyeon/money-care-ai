"""저장한 입력만으로 생활비 결과를 재현하는 공통 계산."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from app.budgets.constants import BUDGET_CALCULATION_VERSION

SEOUL = timezone(timedelta(hours=9))
BIGINT_MIN = -(2**63)
BIGINT_MAX = 2**63 - 1


class BudgetInput(Protocol):
    id: int
    user_id: str
    as_of: datetime
    balance_as_of: datetime
    next_income_date: date
    current_balance: int
    scheduled_expense_total: int
    daily_living_budget: int
    calculation_version: str


@dataclass(frozen=True)
class ForecastResult:
    snapshot_id: int
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


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("시간대가 있는 datetime이 필요합니다.")
    return value.astimezone(timezone.utc)


def _money(value: int, *, nonnegative: bool = False) -> int:
    minimum = 0 if nonnegative else BIGINT_MIN
    if type(value) is not int or not minimum <= value <= BIGINT_MAX:
        raise ValueError("금액은 허용된 BIGINT 범위의 정수 원 단위여야 합니다.")
    return value


def calculate_forecast(snapshot: BudgetInput) -> ForecastResult:
    """budget-v1: 잔액 - 예정 지출 - 남은 일수 × 하루 생활비.

    현재 시각이나 최신 잔액을 읽지 않습니다. 예상 수입액도 잔액에 더하지
    않습니다. 미래 버전을 현재 공식으로 조용히 재계산하지 않습니다.
    """
    if snapshot.calculation_version != BUDGET_CALCULATION_VERSION:
        raise ValueError("지원하지 않는 생활비 계산 버전입니다.")
    as_of = _utc(snapshot.as_of)
    balance_as_of = _utc(snapshot.balance_as_of)
    if balance_as_of > as_of:
        raise ValueError("잔액 기준 시각은 계산 기준 시각보다 늦을 수 없습니다.")
    remaining_days = (snapshot.next_income_date - as_of.astimezone(SEOUL).date()).days
    if remaining_days < 0:
        raise ValueError("다음 수입일은 스냅샷 기준 날짜보다 과거일 수 없습니다.")
    balance = _money(snapshot.current_balance)
    expenses = _money(snapshot.scheduled_expense_total, nonnegative=True)
    daily = _money(snapshot.daily_living_budget, nonnegative=True)
    living = _money(remaining_days * daily, nonnegative=True)
    available = _money(balance - expenses - living)
    shortage = _money(max(0, -available), nonnegative=True)
    return ForecastResult(
        snapshot_id=snapshot.id, user_id=snapshot.user_id,
        as_of=as_of, balance_as_of=balance_as_of,
        next_income_date=snapshot.next_income_date, remaining_days=remaining_days,
        current_balance=balance, scheduled_expense_total=expenses,
        daily_living_budget=daily, expected_living_cost=living,
        available_amount=available, shortage_amount=shortage,
        calculation_version=snapshot.calculation_version,
    )
