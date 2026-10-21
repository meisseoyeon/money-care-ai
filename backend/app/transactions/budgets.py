"""송금 준비 검사와 거래별 생활비 결과. 탐지·알림 판단은 포함하지 않습니다."""

from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baselines.service import get_current_baseline
from app.budgets.forecasts import ensure_budget_forecast, get_budget_forecast
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.budgets.queries import current_budget_forecast
from app.budgets.snapshots import ensure_budget_input_snapshot
from app.transactions.models import Transaction


def check_transfer_preparation(db: Session, *, user_id: str) -> date:
    """사용자 잠금을 가진 호출자만 현재 준비 상태를 검사합니다. 자동 초기화하지 않습니다."""
    baseline = get_current_baseline(db, user_id=user_id)
    if baseline is None:
        raise HTTPException(409, "오늘의 송금 기준 통계가 준비되지 않았어요. 다시 로그인해 주세요.")
    try:
        current_budget_forecast(db, user_id=user_id)
    except HTTPException as exc:
        if exc.status_code not in (404, 409):
            raise
        raise HTTPException(409, f"송금에 필요한 생활비 준비를 확인해 주세요. {exc.detail}") from exc
    return baseline.base_date


def _run_id(transaction_id: str) -> str:
    return f"transfer:{transaction_id}"


def create_transfer_forecast(db: Session, *, user_id: str, transaction: Transaction) -> BudgetForecast:
    """같은 거래 ID는 동일 실행 키를 사용합니다. 최종 commit은 송금 서비스가 담당합니다."""
    snapshot = ensure_budget_input_snapshot(db, user_id=user_id, run_id=_run_id(transaction.id))
    return ensure_budget_forecast(db, user_id=user_id, snapshot_id=snapshot.id)


def find_transfer_forecast(db: Session, *, user_id: str, transaction_id: str) -> BudgetForecast | None:
    """재전송은 당시 스냅샷을 찾으며 현재 잔액으로 과거 결과를 만들지 않습니다."""
    snapshot = db.execute(select(BudgetInputSnapshot).where(
        BudgetInputSnapshot.user_id == user_id,
        BudgetInputSnapshot.airflow_run_id == _run_id(transaction_id),
    ).execution_options(populate_existing=True)).scalar_one_or_none()
    if snapshot is None:
        # 기능 도입 전 완료된 거래에는 입력 기록이 없을 수 있습니다.
        return None
    forecast = get_budget_forecast(db, user_id=user_id, snapshot_id=snapshot.id)
    if forecast is None:
        raise HTTPException(503, "이미 완료된 송금의 생활비 결과를 찾지 못했어요. 거래내역을 확인해 주세요.")
    return forecast

