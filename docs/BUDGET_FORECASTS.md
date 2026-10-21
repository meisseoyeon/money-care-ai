# 생활비 결과 계산·저장

## 목적과 이번 구현 범위

저장된 `budget_input_snapshots` 한 건으로 생활비를 계산하고 기존 `budget_forecasts` 테이블에 저장합니다. 계좌나 설정의 최신 값을 다시 읽지 않으므로 나중에도 당시 계산을 재현할 수 있습니다.

- `budgets/calculator.py`: DB·FastAPI·Airflow에 의존하지 않는 공통 계산 함수.
- `budgets/models.py`의 `BudgetForecast`: 기존 Flyway 테이블 매핑.
- `budgets/forecasts.py`: 사용자 소유 스냅샷 확인·최초 결과 저장·조회.

로그인 초기 준비와 송금 후 잔액 변경에서 자동 호출합니다. `GET /budget-forecasts/latest`로 현재 입력과 일치하는 결과를 조회하며, 없으면 404·오래됐으면 409입니다. 프론트에서도 서버 결과를 표시합니다. 자세한 계약은 [PREPARED_QUERIES.md](PREPARED_QUERIES.md)와 [TRANSFER_BUDGETS.md](TRANSFER_BUDGETS.md)를 참고하세요. Airflow DAG는 아직 추가하지 않았습니다. 생활비 부족 여부를 알림으로 만드는 탐지·알림 로직은 와우 담당입니다. 기존 테이블과 제약을 사용하므로 새 마이그레이션은 필요 없습니다.

## 계산 규칙: budget-v1

```text
기준 날짜 = 스냅샷 as_of를 한국 시간으로 변환한 날짜
남은 일수 = 다음 수입일 - 기준 날짜
예상 생활비 = 남은 일수 × 하루 생활비
여유 금액 = 스냅샷 잔액 - 스냅샷 예정 지출 합계 - 예상 생활비
부족 금액 = max(0, -여유 금액)
```

예상 수입액은 아직 들어오지 않은 돈이므로 잔액에 더하지 않습니다. 예정 지출을 다시 필터링하거나 최신 원본으로 합계를 재계산하지 않습니다. 이전 단계에서 고정한 입력 요약값을 사용합니다.

예를 들어 잔액 800,000원, 남은 일수 20일, 하루 생활비 20,000원, 예정 지출 150,000원이면 다음과 같습니다.

```text
예상 생활비: 400,000원
여유 금액:   250,000원
부족 금액:         0원
```

같은 조건에서 잔액이 500,000원인 새 스냅샷이면 여유 금액은 -50,000원, 부족 금액은 50,000원입니다. 여유 금액을 0으로 덮어쓰지 않습니다.

- 다음 수입일이 기준 날짜와 같으면 남은 일수와 예상 생활비는 0입니다.
- 다음 수입일이 기준 날짜보다 과거면 오류입니다. 스냅샷이 과거 기록이라는 이유만으로 오류로 보지는 않습니다.
- 음수 잔액과 0원 하루 생활비를 허용합니다.
- 잔액 기준 시각은 `as_of`보다 미래일 수 없습니다.
- 모든 금액은 정수 원 단위로 계산합니다. 입력과 결과가 DB BIGINT 범위를 벗어나면 저장 전에 오류로 처리합니다.
- 시간대 없는 시각은 거부합니다. 현재 시각이나 서버 운영체제의 날짜를 사용하지 않습니다.
- 현재 구현하지 않은 계산 버전의 입력을 `budget-v1` 공식으로 계산하지 않습니다. 해당 버전으로 이미 저장된 결과의 조회·재사용은 가능합니다.

## 저장과 재실행

1. 사용자 행을 잠가 같은 사용자의 작업을 직렬화합니다.
2. 스냅샷 ID와 사용자 ID가 모두 일치하는 입력을 조회합니다.
3. 스냅샷에 결과가 이미 있으면 기존 행을 그대로 반환합니다.
4. 없으면 입력의 기준 시각·버전과 요약값으로 계산합니다.
5. `ON CONFLICT (snapshot_id) DO NOTHING`으로 저장합니다.

DB에는 스냅샷당 한 결과만 허용하는 유일 제약과 `(user_id, as_of, calculation_version)` 유일 제약이 있습니다. 스냅샷과 결과의 사용자·기준 시각·버전을 묶는 복합 외래키, 입력 요약값 일치 trigger, 계산 식 CHECK, 결과 수정 금지 trigger도 그대로 적용합니다.

같은 스냅샷을 반복·동시 처리해도 최초 결과 ID와 생성 시각을 유지합니다. 잔액·설정이 달라졌다면 새 실행 ID로 새 스냅샷을 만든 뒤 그 입력의 결과를 저장해야 합니다. 기존 결과를 수정하지 않습니다.

서비스는 PostgreSQL 기본 격리 수준 READ COMMITTED를 사용하며 호출자가 commit/rollback합니다. 잠금을 유지하는 동안 외부 API나 LLM을 호출하며 기다리지 않습니다.

## 스냅샷과 결과를 함께 저장하는 호출 예

```python
from uuid import uuid4
from app.budgets.snapshots import ensure_budget_input_snapshot
from app.budgets.forecasts import ensure_budget_forecast, get_budget_forecast
from app.db.session import session_factory

run_id = f"init:{uuid4()}"  # 동일 작업 재시도 시 최초 실행 ID 재사용

with session_factory()() as db, db.begin():
    snapshot = ensure_budget_input_snapshot(db, user_id="user1", run_id=run_id)
    forecast = ensure_budget_forecast(db, user_id="user1", snapshot_id=snapshot.id)
    snapshot_id = snapshot.id
    print(forecast.remaining_days, forecast.available_amount, forecast.shortage_amount)
# 두 저장이 함께 commit됩니다. 도중에 예외가 발생하면 둘 다 rollback됩니다.

with session_factory()() as db:
    forecast = get_budget_forecast(db, user_id="user1", snapshot_id=snapshot_id)
```

과거 스냅샷 ID를 전달하면 그 입력으로 결과를 계산하며 최신 잔액을 가져오지 않습니다. 입력이 없으면 자동으로 새로 만들지 않습니다.

`ensure_budget_forecast`는 사용자 또는 소유한 스냅샷이 없으면 `LookupError`, 잘못된 인수나 계산 불가능한 입력은 `ValueError`를 발생시킵니다. 예외를 잡아 처리하는 호출자도 DB 트랜잭션을 rollback해야 합니다. `get_budget_forecast`는 해당 사용자의 정확한 스냅샷 결과가 없으면 `None`입니다.

API에 연결할 때 사용자 ID는 인증된 사용자에서 가져옵니다. 다른 사용자 스냅샷으로 결과를 생성하거나 조회할 수 없습니다.

## 검증

`backend`에서 계산 테스트는 DB 없이 실행할 수 있습니다.

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_budget_calculator -v
```

테스트용 pgvector PostgreSQL의 접속 주소를 `DEMO_TEST_DATABASE_URL`에 지정한 뒤 다음 명령으로 계산·저장·입력 회귀 테스트를 실행합니다.

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_budget_calculator tests.test_budget_forecasts tests.test_budget_snapshots -v
```

33개 테스트로 계산 정답, 한국 날짜·월말·윤년, 부족·여유·0원, 큰 금액과 오버플로, 고정 입력 재사용, 사용자 분리, 중복·동시 실행, 원자적 롤백, 실제 DDL의 입력 일치·수정 금지 제약을 검증합니다. DB 테스트는 별도 테스트 스키마만 사용하며 환경변수가 없으면 건너뜁니다.
