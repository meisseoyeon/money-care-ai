"""현재 생활비 입력을 고정해 저장합니다. 트랜잭션 종료는 호출자 책임입니다."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.budgets.constants import BUDGET_CALCULATION_VERSION
from app.budgets.models import BudgetInputSnapshot, BudgetSetting, ScheduledExpense
from app.users.models import User

SEOUL = timezone(timedelta(hours=9))


def get_budget_input_snapshot(
    db: Session, *, user_id: str, as_of: datetime,
    calculation_version: str = BUDGET_CALCULATION_VERSION,
) -> BudgetInputSnapshot | None:
    """다른 사용자의 입력이나 다른 시각·버전으로 대체하지 않고 정확히 조회합니다."""
    return db.scalar(select(BudgetInputSnapshot).where(
        BudgetInputSnapshot.user_id == user_id,
        BudgetInputSnapshot.as_of == _utc(as_of),
        BudgetInputSnapshot.calculation_version == calculation_version,
    ))


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("시간대가 있는 datetime이 필요합니다.")
    return value.astimezone(timezone.utc)


def ensure_budget_input_snapshot(
    db: Session, *, user_id: str, run_id: str, reuse_current: bool = False,
) -> BudgetInputSnapshot:
    """사용자·실행 ID·계산 버전당 최초의 현재 입력을 저장/재사용합니다.

    입력을 잠근 후 DB clock_timestamp()로 기준 시각을 정합니다. 과거 입력을
    현재 데이터로 새로 만들지 않습니다. 과거 재처리는 기존 행을 조회합니다.
    reuse_current=True이면 같은 한국 날짜·버전의 최신 입력이 현재 값과 같을 때
    재사용합니다. PostgreSQL READ COMMITTED에서 사용하며 호출자가 commit/rollback합니다.
    """
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 100:
        raise ValueError("user_id는 공백이 아닌 1~100자여야 합니다.")
    if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 250:
        raise ValueError("run_id는 공백이 아닌 1~250자 실행 식별자여야 합니다.")
    # 송금과 동일하게 사용자 → 계좌 순서. 같은 사용자의 실행을 직렬화합니다.
    if db.scalar(select(User.user_id).where(User.user_id == user_id).with_for_update()) is None:
        raise LookupError("생활비 입력을 만들 사용자를 찾을 수 없습니다.")
    existing = db.scalar(select(BudgetInputSnapshot).where(
        BudgetInputSnapshot.user_id == user_id,
        BudgetInputSnapshot.airflow_run_id == run_id,
        BudgetInputSnapshot.calculation_version == BUDGET_CALCULATION_VERSION,
    ))
    if existing is not None:
        return existing

    # 컬럼 행을 읽어 같은 Session에 남은 오래된 ORM 객체의 영향을 피합니다.
    accounts = db.execute(select(
        Account.account_id, Account.current_balance, Account.balance_as_of,
    ).where(Account.user_id == user_id).order_by(Account.account_id).with_for_update()).all()
    if not accounts:
        raise ValueError("생활비 계산에 사용할 계좌가 없습니다.")
    settings = db.execute(select(
        BudgetSetting.next_income_date, BudgetSetting.expected_income_amount,
        BudgetSetting.daily_living_budget, BudgetSetting.updated_at,
    ).where(BudgetSetting.user_id == user_id).with_for_update()).one_or_none()
    if settings is None:
        raise ValueError("생활비 설정이 없습니다.")
    # 모든 예정 지출 행을 먼저 잠근 뒤 한국 날짜와 상태로 포함 대상을 결정합니다.
    expenses = db.execute(select(
        ScheduledExpense.id, ScheduledExpense.amount, ScheduledExpense.due_date,
        ScheduledExpense.status, ScheduledExpense.updated_at,
    ).where(ScheduledExpense.user_id == user_id).order_by(ScheduledExpense.id).with_for_update()).all()
    as_of = _utc(db.scalar(select(func.clock_timestamp())))
    today = as_of.astimezone(SEOUL).date()
    if settings.next_income_date < today:
        raise ValueError("다음 수입일을 오늘 이후로 수정해 주세요.")
    if (any(_utc(account.balance_as_of) > as_of for account in accounts)
            or _utc(settings.updated_at) > as_of
            or any(_utc(expense.updated_at) > as_of for expense in expenses)):
        raise ValueError("입력 기준 시각이 현재보다 미래입니다. 원본 데이터를 확인해 주세요.")
    included = [expense for expense in expenses
                if expense.status == "PLANNED" and today <= expense.due_date < settings.next_income_date]
    values = dict(
        user_id=user_id, as_of=as_of, captured_at=as_of, calculation_version=BUDGET_CALCULATION_VERSION,
        airflow_run_id=run_id, balance_as_of=min(_utc(account.balance_as_of) for account in accounts),
        next_income_date=settings.next_income_date, expected_income_amount=settings.expected_income_amount,
        daily_living_budget=settings.daily_living_budget,
        current_balance=sum(account.current_balance for account in accounts),
        scheduled_expense_total=sum(expense.amount for expense in included),
        accounts_snapshot=[dict(account_id=account.account_id, current_balance=account.current_balance,
                                balance_as_of=_utc(account.balance_as_of).isoformat()) for account in accounts],
        expenses_snapshot=[dict(id=expense.id, amount=expense.amount, due_date=expense.due_date.isoformat(),
                                status=expense.status) for expense in included],
    )
    if reuse_current:
        day_start = datetime.combine(today, datetime.min.time(), tzinfo=SEOUL).astimezone(timezone.utc)
        latest = db.scalar(select(BudgetInputSnapshot).where(
            BudgetInputSnapshot.user_id == user_id,
            BudgetInputSnapshot.calculation_version == BUDGET_CALCULATION_VERSION,
            BudgetInputSnapshot.as_of >= day_start,
            BudgetInputSnapshot.as_of < day_start + timedelta(days=1),
        ).order_by(BudgetInputSnapshot.as_of.desc(), BudgetInputSnapshot.id.desc())
                           .execution_options(populate_existing=True).limit(1))
        input_fields = ("balance_as_of", "next_income_date", "expected_income_amount", "daily_living_budget",
                        "current_balance", "scheduled_expense_total", "accounts_snapshot", "expenses_snapshot")
        if latest is not None and all(getattr(latest, name) == values[name] for name in input_fields):
            return latest
    stored = db.scalar(insert(BudgetInputSnapshot).values(**values).on_conflict_do_nothing(
        index_elements=["user_id", "as_of", "calculation_version"],
    ).returning(BudgetInputSnapshot))
    if stored is None:
        stored = get_budget_input_snapshot(db, user_id=user_id, as_of=as_of)
    if stored is None:
        raise RuntimeError("생활비 입력 저장 결과를 확인할 수 없습니다.")
    return stored
