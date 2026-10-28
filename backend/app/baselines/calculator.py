"""DB와 웹 프레임워크에 의존하지 않는 최근 30일 출금 통계 계산."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Protocol


CALCULATION_VERSION = "baseline-v1"
WINDOW_DAYS = 30
SEOUL = timezone(timedelta(hours=9))
SCALE = Decimal("0.0001")


class TransactionInput(Protocol):
    """SQLAlchemy Transaction 또는 동일 속성을 제공하는 입력."""

    user_id: str
    occurred_at: datetime
    direction: str
    amount: int


@dataclass(frozen=True)
class BaselineResult:
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


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("시간대가 있는 datetime이 필요합니다.")
    return value.astimezone(timezone.utc)


def calculate_baseline(
    transactions: Iterable[TransactionInput], *, user_id: str, as_of: datetime
) -> BaselineResult:
    """[as_of - 30일, as_of)의 사용자 출금을 집계합니다.

    as_of는 호출자가 한 번 정해 전달합니다. 평가 중인 거래의 occurred_at을
    as_of로 전달하면 그 거래와 이후 거래는 제외됩니다. 중복 없는 원장 행을
    전달해야 하며, source/scenario_label로 정상 여부를 선별하지 않습니다.
    """
    if not user_id or not user_id.strip():
        raise ValueError("user_id가 필요합니다.")
    end = _utc(as_of)
    start = end - timedelta(days=WINDOW_DAYS)
    amounts = []
    for transaction in transactions:
        if transaction.user_id != user_id or transaction.direction != "OUT":
            continue
        if not start <= _utc(transaction.occurred_at) < end:
            continue
        if type(transaction.amount) is not int or not 0 < transaction.amount <= 2**63 - 1:
            raise ValueError("출금액은 양수 BIGINT 범위의 정수 원 단위여야 합니다.")
        amounts.append(Decimal(transaction.amount))

    count = len(amounts)
    average = std = p95 = daily = None
    if count:
        # 금융 금액의 float 오차와 호출자의 Decimal 정밀도 설정을 피합니다.
        with localcontext() as context:
            context.prec = 60
            context.rounding = ROUND_HALF_UP
            total = sum(amounts, Decimal(0))
            mean = total / count
            if count >= 2:
                variance = sum(((amount - mean) ** 2 for amount in amounts), Decimal(0)) / (count - 1)
                std = variance.sqrt().quantize(SCALE)
            ordered = sorted(amounts)
            # 0부터 시작하는 위치 (n-1)*0.95에서 인접 두 값을 선형 보간합니다.
            position = Decimal(count - 1) * Decimal("0.95")
            lower = int(position)
            upper = min(lower + 1, count - 1)
            percentile = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
            average = mean.quantize(SCALE)
            p95 = percentile.quantize(SCALE)
            daily = (total / WINDOW_DAYS).quantize(SCALE)

    return BaselineResult(
        user_id=user_id, base_date=end.astimezone(SEOUL).date(),
        calculation_version=CALCULATION_VERSION, as_of=end,
        window_start=start, window_end=end, out_count_30d=count,
        avg_out_amount=average, std_out_amount=std,
        p95_out_amount=p95, avg_daily_spend=daily,
    )
