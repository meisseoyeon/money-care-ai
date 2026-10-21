"""스냅샷별 생활비 결과 저장·조회. commit/rollback은 호출자가 관리합니다."""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.budgets.calculator import calculate_forecast
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.users.models import User


def get_budget_forecast(db: Session, *, user_id: str, snapshot_id: int) -> BudgetForecast | None:
    """사용자와 입력 스냅샷이 정확히 일치하는 결과만 반환합니다."""
    return db.scalar(select(BudgetForecast).where(
        BudgetForecast.user_id == user_id, BudgetForecast.snapshot_id == snapshot_id,
    ))


def ensure_budget_forecast(db: Session, *, user_id: str, snapshot_id: int) -> BudgetForecast:
    """기존 입력의 버전·시각을 유지해 계산하고 스냅샷당 한 결과를 저장합니다."""
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 100:
        raise ValueError("user_id는 공백이 아닌 1~100자여야 합니다.")
    if type(snapshot_id) is not int or not 0 < snapshot_id <= 2**63 - 1:
        raise ValueError("snapshot_id는 양수 BIGINT 범위의 정수여야 합니다.")
    if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update()) is None:
        raise LookupError("생활비 결과를 만들 사용자를 찾을 수 없습니다.")
    # 새 스냅샷을 만들거나 다른 사용자의 입력을 자동 선택하지 않습니다.
    snapshot = db.scalar(select(BudgetInputSnapshot).where(
        BudgetInputSnapshot.id == snapshot_id, BudgetInputSnapshot.user_id == user_id,
    ).execution_options(populate_existing=True))
    if snapshot is None:
        raise LookupError("생활비 입력 스냅샷을 찾을 수 없습니다.")
    existing = get_budget_forecast(db, user_id=user_id, snapshot_id=snapshot_id)
    if existing is not None:
        return existing
    result = calculate_forecast(snapshot)
    stored = db.scalar(insert(BudgetForecast).values(**asdict(result)).on_conflict_do_nothing(
        index_elements=["snapshot_id"],
    ).returning(BudgetForecast))
    if stored is None:
        stored = get_budget_forecast(db, user_id=user_id, snapshot_id=snapshot_id)
    if stored is None:
        raise RuntimeError("생활비 결과 저장을 확인할 수 없습니다.")
    return stored
