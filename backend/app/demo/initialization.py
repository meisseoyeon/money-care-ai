"""로그인 후 필요한 통계·생활비 결과만 준비합니다. 원본 데이터는 변경하지 않습니다."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baselines.calculator import CALCULATION_VERSION as BASELINE_VERSION
from app.baselines.service import ensure_baseline, get_baseline
from app.budgets.constants import BUDGET_CALCULATION_VERSION
from app.budgets.forecasts import ensure_budget_forecast, get_budget_forecast
from app.budgets.snapshots import ensure_budget_input_snapshot
from app.demo.models import InitializationRun
from app.users.models import User


def ensure_initial_preparation(db: Session, *, user_id: str, run_id: str) -> dict:
    """같은 실행·버전은 최초 결과를 반환하며, 실패하면 이 작업을 savepoint까지 되돌립니다.

    최종 commit은 호출자 책임입니다. 새 작업에는 새 run_id를 전달해야 합니다.
    """
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 100:
        raise ValueError("user_id는 공백이 아닌 1~100자여야 합니다.")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 250:
        raise ValueError("run_id는 공백이 아닌 1~250자 실행 식별자여야 합니다.")
    with db.begin_nested():
        if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update()) is None:
            raise LookupError("초기 준비를 수행할 사용자를 찾을 수 없습니다.")
        run = db.scalar(select(InitializationRun).where(
            InitializationRun.user_id == user_id, InitializationRun.run_id == run_id,
            InitializationRun.baseline_version == BASELINE_VERSION,
            InitializationRun.budget_version == BUDGET_CALCULATION_VERSION,
        ).execution_options(populate_existing=True))
        if run is not None:
            baseline = get_baseline(db, user_id=user_id, base_date=run.baseline_date,
                                    calculation_version=run.baseline_version)
            forecast = get_budget_forecast(db, user_id=user_id, snapshot_id=run.snapshot_id)
            if baseline is None or forecast is None:
                raise RuntimeError("초기 준비 실행 기록과 결과가 일치하지 않습니다.")
            return _summary(baseline, forecast)

        snapshot = ensure_budget_input_snapshot(db, user_id=user_id, run_id=run_id, reuse_current=True)
        baseline = ensure_baseline(db, user_id=user_id, as_of=snapshot.as_of, run_id=run_id)
        forecast = ensure_budget_forecast(db, user_id=user_id, snapshot_id=snapshot.id)
        _record_completed_run(db, user_id=user_id, run_id=run_id, baseline=baseline, forecast=forecast)
        return _summary(baseline, forecast)


def _record_completed_run(db, *, user_id, run_id, baseline, forecast):
    db.add(InitializationRun(
        user_id=user_id, run_id=run_id, baseline_version=baseline.calculation_version,
        budget_version=forecast.calculation_version, baseline_date=baseline.base_date,
        budget_as_of=forecast.as_of, snapshot_id=forecast.snapshot_id,
    ))
    db.flush()


def _summary(baseline, forecast) -> dict:
    return {
        "status": "READY",
        "baseline_date": baseline.base_date,
        "baseline_as_of": baseline.as_of,
        "baseline_version": baseline.calculation_version,
        "snapshot_id": forecast.snapshot_id,
        "forecast_id": forecast.id,
        "forecast_as_of": forecast.as_of,
        "forecast_version": forecast.calculation_version,
    }
