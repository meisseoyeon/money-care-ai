# 생활비 입력 스냅샷

## 목적과 구현 범위

스냅샷은 생활비 계산에 사용한 입력을 그대로 보관하는 기록입니다. 나중에 잔액·설정·예정 지출이 바뀌더라도 저장한 입력으로 당시 계산을 재현할 수 있습니다.

`backend/app/budgets/snapshots.py`에서 현재 입력 조회·고정·저장과 기존 스냅샷 조회를 제공합니다. 저장된 입력의 생활비 결과 계산·저장은 [BUDGET_FORECASTS.md](BUDGET_FORECASTS.md)를 참고하세요. 로그인 초기 준비에 연결되어 있으며 현재 생활비 결과 조회 API도 제공합니다. 스냅샷 JSON 원문 조회 API와 송금 자동 호출, 프론트 결과 연결, Airflow DAG는 다음 작업입니다. 탐지·알림 로직은 포함하지 않습니다.

기존 Flyway의 `budget_input_snapshots` 테이블을 사용하므로 새 마이그레이션이나 적용한 V1 수정은 필요 없습니다. 모델은 `budgets/models.py`의 `BudgetInputSnapshot`입니다.

## 저장하는 입력

| 컬럼 | 의미 |
|---|---|
| `user_id` | 입력의 소유자 |
| `as_of` | 원본 입력을 잠근 후 DB 시계로 고정한 기준 시각 |
| `calculation_version` | 생활비 계산 규칙 버전, 현재 `budget-v1` |
| `airflow_run_id` | 초기화 또는 Airflow 실행 식별자 |
| `current_balance` | 사용자 소유 계좌의 잔액 합계 |
| `balance_as_of` | 포함한 계좌 중 가장 오래된 잔액 기준 시각 |
| `accounts_snapshot` | 계좌별 ID·잔액·잔액 기준 시각의 JSON 배열 |
| `next_income_date` | 다음 수입일 |
| `expected_income_amount` | 예상 수입액, 아직 잔액에 더하지 않음 |
| `daily_living_budget` | 하루 생활비 |
| `scheduled_expense_total` | 이번 구간에 포함한 예정 지출 합계 |
| `expenses_snapshot` | 포함한 지출의 ID·금액·예정일·상태의 JSON 배열 |
| `captured_at` | 실제 입력 고정 시각, 서비스에서는 `as_of`와 동일 |

계좌는 ID 순서, 예정 지출은 ID 순서로 저장합니다. JSON의 시각은 UTC ISO 문자열, 날짜는 `YYYY-MM-DD`, 금액은 정수 원 단위입니다.

예정 지출은 한국 날짜 기준으로 다음 조건을 모두 만족하는 것만 포함합니다.

```text
status = PLANNED
오늘 <= due_date < 다음 수입일
```

납부·취소한 지출, 지난 지출, 다음 수입일 당일 및 이후 지출은 제외합니다. 포함할 지출이 없으면 빈 배열과 합계 0을 저장합니다. 다음 수입일이 오늘이면 이번 구간은 비어 있습니다.

여러 계좌는 모두 합산하며 음수 잔액도 그대로 반영합니다. 계좌가 없거나 생활비 설정이 없거나 다음 수입일이 이미 지난 경우에는 오류를 반환하고 저장하지 않습니다. 어느 한 계좌라도 잔액 기준 시각이 현재보다 미래이면 거부합니다. 설정·예정 지출의 미래 수정 시각도 거부합니다.

## 동시성·기준 시각·재시도

1. 사용자 행을 잠급니다. 같은 사용자의 기존 송금과 초기화 작업을 직렬화합니다.
2. 같은 사용자·실행 ID·계산 버전의 스냅샷이 있으면 그대로 반환합니다.
3. 계좌 → 생활비 설정 → 예정 지출 순서로 원본 행을 잠그고 읽습니다.
4. 모든 입력을 확보한 후 PostgreSQL `clock_timestamp()`로 기준 시각을 정합니다.
5. 한국 날짜와 지출 포함 범위를 결정하고 JSON·요약값을 함께 저장합니다.

시각을 호출자 PC에서 미리 정하지 않으므로, 송금 잠금을 기다리다가 새 잔액이 반영되더라도 그 잔액보다 앞선 시각으로 저장하지 않습니다. 같은 Session에 남아 있는 오래된 ORM 객체 대신 DB 컬럼을 직접 조회합니다.

서비스는 PostgreSQL 기본 격리 수준인 READ COMMITTED를 사용합니다. 입력 변경 서비스도 사용자 → 계좌 → 설정 → 예정 지출 순서의 잠금 규칙을 따라야 합니다. 호출자는 잠금을 유지하는 동안 외부 API나 LLM을 기다리지 않습니다.

DB에서는 `(user_id, as_of, calculation_version)` 유일 제약으로 중복을 방지합니다. 서비스는 사용자 잠금 아래 실행 ID를 추가로 확인하므로 동시에 같은 실행을 시작해도 하나의 스냅샷을 재사용합니다. 실행 ID로 재사용하는 규칙은 이 서비스를 통해 저장할 때 적용됩니다.

- 초기화 실행 ID 예: `init:<UUID>`.
- Airflow에서는 실제 실행 ID를 사용합니다.
- 동일 작업 재시도는 **같은 실행 ID**를 사용합니다. 기준 시각·JSON·최초 실행 정보를 덮어쓰지 않습니다.
- 잔액·설정 변경 후 새 계산을 원하면 **새 실행 ID**로 새 스냅샷을 만듭니다.
- 새 계산 규칙을 적용할 때는 `budgets/constants.py`의 버전을 변경합니다. 향후 생활비 결과도 같은 버전을 사용해야 합니다.
- 저장된 스냅샷의 수정은 기존 DB immutable trigger가 차단합니다.

로그인 초기 준비는 `reuse_current=True`로 호출합니다. 새 실행 ID라도 같은 한국 날짜·버전의 최신 스냅샷과 현재 입력이 같으면 그 행을 재사용합니다. 날짜 또는 잔액·설정·포함 지출이 달라지면 새 행을 저장합니다. 기본값은 `False`이므로 명시적으로 새 실행을 저장하는 기존 호출 방식은 유지합니다.

서비스는 임의의 과거 시각으로 현재 데이터를 저장하는 기능을 제공하지 않습니다. 과거 재처리는 정확한 시각·버전의 기존 스냅샷을 조회해야 합니다. 해당 입력이 없으면 `None`을 반환하며 최신 입력으로 대체하지 않습니다.

## 호출 예

```python
from uuid import uuid4
from app.budgets.snapshots import ensure_budget_input_snapshot, get_budget_input_snapshot
from app.db.session import session_factory

run_id = f"init:{uuid4()}"  # 재시도 시에는 처음 만든 실행 ID를 다시 전달

with session_factory()() as db, db.begin():
    snapshot = ensure_budget_input_snapshot(db, user_id="user1", run_id=run_id)
    as_of = snapshot.as_of
    # forecasts.ensure_budget_forecast로 결과도 같은 트랜잭션에 저장 가능
# 정상 종료하면 commit, 예외가 나면 rollback

with session_factory()() as db:
    snapshot = get_budget_input_snapshot(db, user_id="user1", as_of=as_of)
```

서비스는 commit/rollback하지 않고 호출자가 관리합니다. 계산이나 이후 저장이 실패하면 스냅샷도 함께 롤백할 수 있습니다. 오류를 잡아 처리할 때도 호출자가 rollback해야 합니다. 사용자가 없으면 `LookupError`, 필수 입력이 없거나 잘못되면 `ValueError`입니다.

API에 연결할 때 사용자 ID는 요청 본문이 아닌 인증된 사용자에서 가져와야 합니다. 로그인에서는 검증한 사용자 ID로 자동 준비하며 송금 자동 호출은 아직 연결하지 않았습니다. 로그인은 원본 잔액·거래·설정을 변경하지 않습니다.

## 검증

테스트용 pgvector PostgreSQL의 접속 주소를 `DEMO_TEST_DATABASE_URL`에 지정하고 `backend`에서 실행합니다.

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_budget_snapshots -v
```

별도 `budget_test_<UUID>` 스키마에 실제 마이그레이션을 적용하고 종료 시 해당 스키마만 제거합니다. 테스트용 DB와 스키마 생성 권한이 필요합니다. 환경변수가 없으면 PostgreSQL 테스트를 건너뜁니다.

입력 JSON·요약값 일치, 지출 경계와 상태, 타 사용자 제외, 다중 계좌, 같은 실행 재시도, 새 실행의 변경 입력 반영, 잘못된 입력, 동시 실행, 송금 경합, 롤백, DB 수정 금지를 검증합니다.
