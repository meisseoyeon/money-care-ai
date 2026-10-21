# 최근 30일 출금 기준 통계

## 이번 구현 범위

`backend/app/baselines/calculator.py`의 `calculate_baseline`은 거래 목록으로 통계를 계산합니다. `service.py`의 `ensure_baseline`은 PostgreSQL에서 해당 거래를 조회하고 `user_baselines`에 결과를 저장합니다. 로그인 초기 준비에서 이 서비스를 호출합니다. `GET /baselines/current`는 토큰 사용자의 오늘 통계를 조회합니다. 송금은 오늘 기준이 없으면 409로 차단하며 통계를 새로 계산하지 않습니다. Airflow DAG는 아직 연결하지 않았습니다. 탐지 조건·알림은 와우 담당으로 남겨 둡니다.

같은 거래와 같은 기준 시각을 전달하면 같은 결과를 반환합니다. DB 연결이나 추가 라이브러리가 필요 없어 초기화 서비스와 Airflow에서 함께 사용할 수 있습니다.

## 입력과 집계 범위

- `transactions`: `user_id`, `direction`, `amount`, `occurred_at` 속성이 있는 중복 없는 거래 목록 또는 반복자. 현재 SQLAlchemy `Transaction` 객체도 그대로 전달할 수 있습니다.
- `user_id`: 집계할 사용자. API에 연결할 때는 요청 본문이 아닌 인증된 사용자에서 가져옵니다.
- `as_of`: 호출자가 한 번 정한, 시간대가 포함된 기준 시각. 함수 안에서 현재 시각을 다시 읽지 않습니다.
- 대상: 같은 사용자의 `OUT` 거래이며, `as_of - 30일 <= occurred_at < as_of`를 만족하는 거래.
- 입력 시각은 UTC로 변환하고 `base_date`는 한국 시간 날짜로 계산합니다. 시간대가 없는 시각은 오류로 처리합니다.
- 수입은 제외합니다. `tx_type`, `source`, `scenario_label`로 필터링하지 않습니다. 초기에는 정상 거래만 원장에 있으므로 정상 이력이 계산 대상이 됩니다.
- 출금액은 DB BIGINT 범위의 양수 정수 원 단위여야 합니다.
- 저장 서비스는 사용자·출금 방향·기간을 DB에서 필터링하고 계산에 필요한 네 컬럼만 읽습니다.

## 계산 규칙: baseline-v1

| 결과 필드 | 계산 |
|---|---|
| `out_count_30d` | 대상 출금 건수 n |
| `avg_out_amount` | 출금 합계 / n |
| `std_out_amount` | sqrt(각 출금액과 평균 차이의 제곱 합 / (n - 1)) |
| `p95_out_amount` | 오름차순 정렬 후 위치 `(n - 1) × 0.95`의 양옆 값을 선형 보간 |
| `avg_daily_spend` | 출금 합계 / 30. 거래한 날짜 수로 나누지 않음 |

금액 통계는 `Decimal`로 계산하고 최종 결과만 소수점 넷째 자리까지 사사오입(`ROUND_HALF_UP`)합니다. 표준편차는 반올림 전 평균으로 계산합니다. 계산 규칙을 바꾸면 버전도 변경해야 합니다.

출금 0건이면 횟수는 0이고 네 통계값은 모두 `None`입니다. 출금 1건이면 표준편차만 `None`입니다. 여러 건의 금액이 모두 같으면 표준편차는 0입니다. 기존 `user_baselines` DDL의 NULL 규칙과 일치합니다.

예를 들어 출금액이 1,000원·2,000원·3,000원·4,000원이면 다음과 같습니다.

```text
출금 횟수:        4
평균:            2500.0000
표본 표준편차:   1290.9944
95분위수:        3850.0000
하루 평균 지출:   333.3333
```

95분위수는 보간된 통계값입니다. 이 값을 넘는 거래가 위험한지 판단하는 코드는 포함하지 않습니다.

## 호출 예

```python
from datetime import datetime, timezone
from app.baselines.calculator import calculate_baseline

# transactions는 서비스에서 사용자별로 조회한 Transaction 객체 목록입니다.
result = calculate_baseline(
    transactions,
    user_id="user1",
    as_of=datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc),
)
print(result.out_count_30d)
print(result.p95_out_amount)
```

결과는 변경 불가능한 `BaselineResult`입니다. 다섯 통계 외에도 사용자·한국 기준 날짜·UTC 기준 시각·집계 시작/종료·계산 버전을 포함합니다. DB 저장 서비스에서 별도로 실행 식별자(`airflow_run_id`)를 부여해야 합니다.

평가 중인 거래의 `occurred_at`을 `as_of`로 전달하면 해당 시각의 거래와 이후 거래는 집계에서 제외됩니다. 탐지 단계에서는 이미 저장된 기준 통계를 사용할 수도 있으며, 어떤 기준을 선택할지는 탐지 연동 계약에서 정합니다.

## DB 저장·조회

기존 V1의 `user_baselines` 테이블을 `models.py`의 `UserBaseline`으로 매핑합니다. 새 마이그레이션이나 적용 완료된 V1 수정은 필요 없습니다. 테이블 생성은 계속 Flyway가 담당합니다.

저장 순서는 다음과 같습니다.

1. `as_of`를 UTC로 변환하고 한국 날짜와 30일 구간을 고정합니다.
2. 해당 사용자 행을 잠급니다. 기존 송금과 동일하게 사용자 → 계좌 잠금 순서를 지킵니다.
3. `(user_id, base_date, calculation_version)`에 해당하는 결과가 있으면 그대로 반환합니다.
4. 결과가 없으면 대상 거래를 조회하고 공통 계산 함수를 호출합니다.
5. `ON CONFLICT DO NOTHING`으로 저장한 뒤 실제 저장된 행을 반환합니다.

동일 사용자·한국 날짜·계산 버전에서는 **처음 저장한 결과가 기준**입니다. 같은 날 더 늦은 시각이나 다른 실행 ID로 요청해도 최초 기준 시각·집계 구간·통계·실행 ID를 보존합니다. 새 거래가 추가되어도 그날 결과를 덮어쓰지 않습니다. 다음 한국 날짜에는 새 행을 만들며, 계산 규칙 변경 시 코드의 계산 버전을 올려 별도 행으로 저장합니다. 기존 행의 수정은 DB의 immutable trigger도 차단합니다.

서비스는 PostgreSQL 기본 격리 수준인 READ COMMITTED에서 사용합니다. 사용자 잠금은 호출자의 트랜잭션이 끝날 때까지 유지되므로, 트랜잭션 안에서 외부 API나 LLM을 호출하며 기다리지 않습니다.

`ensure_baseline`은 스스로 commit/rollback하지 않습니다. 이후 생활비 초기화와 함께 성공하거나 함께 취소할 수 있도록 **호출자가 트랜잭션을 관리**합니다. 오류를 잡아서 처리할 때도 rollback해야 합니다.

```python
from datetime import datetime, timezone
from uuid import uuid4
from app.baselines.service import ensure_baseline, get_baseline
from app.db.session import session_factory

as_of = datetime.now(timezone.utc)  # 작업 시작 시 한 번만 결정
run_id = f"init:{uuid4()}"         # 같은 작업의 재시도에서는 동일 값 사용

with session_factory()() as db, db.begin():
    baseline = ensure_baseline(
        db, user_id="user1", as_of=as_of, run_id=run_id,
    )
    # 여기에서 다른 초기화 결과도 함께 저장할 수 있습니다.
    base_date = baseline.base_date
# 정상 종료 시 commit, 예외 발생 시 rollback

with session_factory()() as db:
    baseline = get_baseline(db, user_id="user1", base_date=base_date)
```

API에 연결할 때 `user_id`는 인증된 사용자에서 가져옵니다. 로그인에서는 비밀번호를 검증한 사용자 ID로 생성하고 송금에서는 현재 통계의 존재만 검사합니다. 없는 사용자는 생성하지 않고 `LookupError`를 발생시킵니다. `run_id`는 공백이 아닌 1~250자이며 DB의 필수 컬럼 `airflow_run_id`에 저장합니다. Airflow에서는 실제 실행 ID를 전달합니다.

`get_baseline`은 날짜와 버전이 정확히 일치하는 행만 반환하며, 없으면 `None`입니다. 오래된 날짜나 다른 버전으로 자동 대체하지 않습니다. `calculation_version`을 지정하면 과거 버전도 조회할 수 있습니다.

## 테스트

저장소 루트의 PowerShell에서 실행합니다.

```powershell
cd backend
..\.venv\Scripts\python.exe -m unittest tests.test_baseline_calculator -v
```

알려진 계산값, 집계 경계, 타 사용자·수입 제외, 0건·1건·동일 금액, 한국 날짜, 큰 정수 금액, 반올림, 잘못된 입력과 입력 불변성을 검증합니다.

DB 저장 테스트는 **테스트용 PostgreSQL**에 연결한 상태에서 실행합니다. 환경변수에는 실제 비밀번호가 포함될 수 있으므로 Git에 저장하지 않습니다.

```powershell
# 테스트용 DB 주소를 DEMO_TEST_DATABASE_URL 환경변수에 설정한 뒤 실행
..\.venv\Scripts\python.exe -m unittest tests.test_baseline_calculator tests.test_baseline_service -v
```

DB 테스트는 별도 `baseline_test_<UUID>` 스키마에 실제 마이그레이션을 적용하고 종료 시 해당 스키마만 제거합니다. pgvector가 설치된 PostgreSQL과 테스트 스키마 생성 권한이 필요합니다. 환경변수가 없으면 저장 테스트는 건너뜁니다. 최초 저장·동일 날짜 재실행·한국 날짜 변경·버전 분리·동시 실행·롤백·DB 수정 금지 제약을 검증합니다.
