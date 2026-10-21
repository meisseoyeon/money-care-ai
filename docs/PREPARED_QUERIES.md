# 인증 사용자의 기준 통계·생활비 결과 조회

## 제공 API

| 메서드 | 경로 | 반환 내용 |
|---|---|---|
| GET | `/baselines/current` | 현재 한국 날짜·적용 버전의 출금 기준 통계 |
| GET | `/budget-forecasts/latest` | 현재 입력과 일치하는 최신 생활비 결과 |

두 API 모두 `Authorization: Bearer <access_token>`이 필요합니다. 기존 인증 함수가 JWT와 서버 세션의 만료·폐기, 사용자 상태를 검사합니다. 사용자 ID는 검증된 토큰에서 가져옵니다. URL이나 요청 본문으로 사용자 ID를 받지 않으며 임의의 `user_id` 쿼리나 `X-User-Id` 헤더로 다른 사용자 데이터를 선택할 수 없습니다.

모니터링 미동의·철회 상태도 유효한 로그인이라면 조회할 수 있습니다. 송금 권한과 조회 권한은 구분합니다. 공용 user1 계정으로 로그인한 브라우저들은 의도대로 같은 user1 데이터를 봅니다.

## 기준 통계

`baselines/service.py`의 `get_current_baseline`을 재사용할 수 있습니다. DB 시각에서 한국 날짜를 구하고 현재 `baseline-v1` 결과를 읽습니다. 전날 결과, 다른 버전, 미래 기준 시각의 결과로 대체하지 않습니다.

응답 필드:

```text
user_id, base_date, calculation_version,
as_of, window_start, window_end,
out_count_30d, avg_out_amount, std_out_amount,
p95_out_amount, avg_daily_spend
```

평균·표준편차·p95·하루 평균 지출은 소수점 정밀도를 보존하는 **문자열**로 반환합니다. 예: `"1000.0000"`, `"33.3333"`. 출금이 없으면 네 값은 `null`, 한 건이면 표준편차만 `null`입니다. 출금 횟수는 정수입니다.

기준 통계는 당일 최초 저장값을 유지합니다. 같은 날 새 송금이 생겼다는 이유로 조회 시 다시 계산하지 않습니다. 탐지 판단·알림 생성은 포함하지 않습니다.

## 현재 생활비 결과

`budgets/queries.py`의 `current_budget_forecast`를 재사용할 수 있습니다.

1. 사용자 행에 공유 잠금을 걸어 같은 사용자의 송금·초기 준비와 읽기 시점을 맞춥니다.
2. 현재 `budget-v1`이며 기준 시각이 미래가 아닌 최신 입력 스냅샷을 선택합니다.
3. 그 스냅샷의 결과가 존재하는지 확인합니다. 최신 입력에 결과가 없으면 오래된 다른 결과로 대체하지 않습니다.
4. 계좌·생활비 설정·예정 지출을 같은 순서의 공유 잠금으로 읽습니다.
5. 같은 한국 날짜인지, 계좌별 잔액·잔액 기준 시각·설정·포함 지출이 저장 입력과 같은지 비교합니다.
6. 유효하면 저장된 결과를 반환합니다.

입력 조회·비교 함수는 스냅샷 저장과 공통으로 사용합니다. 조회 과정에서 통계·스냅샷·결과·실행 기록을 추가하거나 수정하지 않으며 commit하지 않습니다. 요청 종료 시 DB 세션이 닫히면서 읽기 트랜잭션과 잠금이 해제됩니다. 내부 호출자는 자신의 트랜잭션을 끝내야 합니다.

응답 필드:

```text
id, snapshot_id, user_id, as_of, balance_as_of,
next_income_date, remaining_days, current_balance,
scheduled_expense_total, daily_living_budget,
expected_living_cost, available_amount, shortage_amount,
calculation_version
```

`id`, `snapshot_id`는 BIGINT 식별자의 JavaScript 정밀도 손실을 피하기 위해 문자열로 반환합니다. 금액·남은 일수는 정수이며 날짜·시각은 ISO 형식입니다. 입력 JSON 원문과 내부 실행 ID는 반환하지 않습니다.

## 상태 코드

| 상태 | 의미 |
|---|---|
| 200 | 요청한 사용자의 유효한 결과 |
| 401 | 토큰 없음·만료·폐기·위조 또는 비활성 사용자 |
| 404 | 오늘 통계 또는 최신 입력·결과가 아직 없음 |
| 409 | 저장된 생활비 결과가 현재 날짜·잔액·설정·예정 지출과 맞지 않음, 또는 현재 입력 오류 |

조회 성공과 404·409 응답에는 `Cache-Control: no-store`를 설정합니다. 결과가 없거나 오래돼도 GET 요청으로 초기화를 실행하지 않습니다. 현재 단계에서는 다시 로그인하면 필요한 결과가 준비됩니다. 송금 후 자동 계산은 다음 작업이므로, 송금 후 재로그인 전 생활비 조회는 409가 될 수 있습니다.

## PowerShell 호출 예

```powershell
$loginResult = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8000/auth/login' `
  -ContentType 'application/json' `
  -Body (@{ username = 'user1'; password = 'demo1234!' } | ConvertTo-Json)

$authHeaders = @{ Authorization = "Bearer $($loginResult.access_token)" }

Invoke-RestMethod -Uri 'http://127.0.0.1:8000/baselines/current' -Headers $authHeaders
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/budget-forecasts/latest' -Headers $authHeaders
```

FastAPI `/docs`에서도 로그인 응답 토큰을 Authorize에 입력해 호출할 수 있습니다. 새 마이그레이션은 필요 없습니다. 기준 통계와 생활비 입력·결과·실행 기록 테이블까지 기존 V1~V7을 적용한 DB를 사용합니다.

## 검증과 남은 연결

테스트용 pgvector PostgreSQL 주소를 `DEMO_TEST_DATABASE_URL`에 설정하고 `backend`에서 실행합니다.

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_prepared_queries tests.test_app -v
```

조회 API 11개 테스트와 라우팅·CORS 3개 테스트로 사용자 분리, 인증 실패, 현재 날짜·버전, 누락·오래된 결과, Decimal 직렬화, 조회 중 무변경을 검증합니다. 별도 테스트 스키마만 사용합니다. 프론트 데이터 연결과 준비 상태는 [FRONTEND_PREPARATION.md](FRONTEND_PREPARATION.md)를 참고하세요. 탐지 함수 호출은 포함하지 않습니다.
