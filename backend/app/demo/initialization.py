"""로그인 후 필요한 통계·생활비 결과만 준비합니다. 원본 데이터는 변경하지 않습니다."""

from sqlalchemy.orm import Session

from app.baselines.service import ensure_baseline
from app.budgets.forecasts import ensure_budget_forecast
from app.budgets.snapshots import ensure_budget_input_snapshot


def ensure_initial_preparation(db: Session, *, user_id: str, run_id: str) -> dict:
    """호출자의 트랜잭션에서 통계·입력·결과를 함께 준비합니다."""
    snapshot = ensure_budget_input_snapshot(db, user_id=user_id, run_id=run_id, reuse_current=True)
    baseline = ensure_baseline(db, user_id=user_id, as_of=snapshot.as_of, run_id=run_id)
    forecast = ensure_budget_forecast(db, user_id=user_id, snapshot_id=snapshot.id)
    return {
        "status": "READY",
        "baseline_date": baseline.base_date,
        "baseline_as_of": baseline.as_of,
        "baseline_version": baseline.calculation_version,
        "snapshot_id": snapshot.id,
        "forecast_id": forecast.id,
        "forecast_as_of": forecast.as_of,
        "forecast_version": forecast.calculation_version,
    }
