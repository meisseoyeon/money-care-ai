"""기준 통계 조회와 최초 저장. commit/rollback은 호출자가 담당합니다."""

from dataclasses import asdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.baselines.calculator import CALCULATION_VERSION, calculate_baseline
from app.baselines.models import UserBaseline
from app.transactions.models import Transaction
from app.users.models import User


def get_baseline(
    db: Session, *, user_id: str, base_date: date,
    calculation_version: str = CALCULATION_VERSION,
) -> UserBaseline | None:
    """지정된 날짜·버전만 조회합니다. 과거 결과로 자동 대체하지 않습니다."""
    # savepoint rollback 후 identity map에 남은 Core INSERT 결과를 재사용하지 않습니다.
    return db.scalar(select(UserBaseline).where(
        UserBaseline.user_id == user_id, UserBaseline.base_date == base_date,
        UserBaseline.calculation_version == calculation_version,
    ).execution_options(populate_existing=True))


def ensure_baseline(
    db: Session, *, user_id: str, as_of: datetime, run_id: str,
) -> UserBaseline:
    """사용자·한국 날짜·현재 계산 버전당 처음 저장한 결과를 재사용합니다.

    사용자 → 계좌 순서인 기존 송금 잠금 규칙에 맞춰 사용자를 먼저 잠급니다.
    PostgreSQL READ COMMITTED에서 사용하며, 호출자가 트랜잭션을 끝낼 때까지
    잠금을 유지합니다. 실패하면 호출자는 rollback해야 합니다.
    """
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 250:
        raise ValueError("run_id는 공백이 아닌 1~250자 실행 식별자여야 합니다.")
    # 거래를 읽기 전에 사용자·시각을 검증하고 UTC 구간과 한국 날짜를 고정합니다.
    window = calculate_baseline([], user_id=user_id, as_of=as_of)
    if len(user_id) > 100:
        raise ValueError("user_id는 100자 이하여야 합니다.")
    locked_user = db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update())
    if locked_user is None:
        raise LookupError("기준 통계를 만들 사용자를 찾을 수 없습니다.")

    existing = get_baseline(db, user_id=user_id, base_date=window.base_date)
    if existing is not None:
        return existing

    # 평가용 label/source는 읽지 않습니다. 필요한 출금 행만 DB에서 선택합니다.
    rows = db.execute(select(
        Transaction.user_id, Transaction.occurred_at, Transaction.direction, Transaction.amount,
    ).where(
        Transaction.user_id == user_id,
        Transaction.direction == "OUT",
        Transaction.occurred_at >= window.window_start,
        Transaction.occurred_at < window.window_end,
    ))
    result = calculate_baseline(rows, user_id=user_id, as_of=window.as_of)
    # 외부 실행이 같은 키를 삽입하더라도 기존 결과를 덮어쓰지 않습니다.
    statement = insert(UserBaseline).values(**asdict(result), airflow_run_id=run_id)
    db.execute(statement.on_conflict_do_nothing(
        index_elements=["user_id", "base_date", "calculation_version"],
    ))
    stored = get_baseline(db, user_id=user_id, base_date=result.base_date)
    if stored is None:
        raise RuntimeError("기준 통계 저장 결과를 확인할 수 없습니다.")
    return stored
