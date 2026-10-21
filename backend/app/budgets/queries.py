"""새 계산 없이 현재 입력과 일치하는 최신 생활비 결과를 조회합니다."""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budgets.constants import BUDGET_CALCULATION_VERSION
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.budgets.snapshots import read_current_budget_inputs, snapshot_matches_inputs
from app.users.models import User


def current_budget_forecast(db: Session, *, user_id: str) -> BudgetForecast:
    # 조회끼리는 공유 잠금이 가능하며, 송금의 사용자 배타 잠금과는 직렬화됩니다.
    if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update(read=True)) is None:
        raise HTTPException(404, "사용자를 찾을 수 없습니다.")
    now = db.scalar(select(func.clock_timestamp()))
    snapshot = db.scalar(select(BudgetInputSnapshot).where(
        BudgetInputSnapshot.user_id == user_id,
        BudgetInputSnapshot.calculation_version == BUDGET_CALCULATION_VERSION,
        BudgetInputSnapshot.as_of <= now,
    ).order_by(BudgetInputSnapshot.as_of.desc(), BudgetInputSnapshot.id.desc())
                         .execution_options(populate_existing=True).limit(1))
    if snapshot is None:
        raise HTTPException(404, "생활비 입력이 아직 준비되지 않았어요. 다시 로그인해 주세요.")
    # 최신 입력에 결과가 없을 때 과거 결과로 조용히 대체하지 않습니다.
    forecast = db.scalar(select(BudgetForecast).where(
        BudgetForecast.user_id == user_id, BudgetForecast.snapshot_id == snapshot.id,
        BudgetForecast.calculation_version == BUDGET_CALCULATION_VERSION,
    ).execution_options(populate_existing=True))
    if forecast is None:
        raise HTTPException(404, "생활비 결과가 아직 준비되지 않았어요. 다시 로그인해 주세요.")
    try:
        values = read_current_budget_inputs(db, user_id=user_id, shared_lock=True)
    except ValueError as exc:
        raise HTTPException(409, f"현재 생활비 입력을 확인해 주세요. {exc}") from exc
    if not snapshot_matches_inputs(snapshot, values):
        raise HTTPException(409, "생활비 입력이 바뀌어 다시 계산해야 해요. 다시 로그인해 주세요.")
    return forecast
