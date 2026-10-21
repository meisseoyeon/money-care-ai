# 공용 체험 계정 로그인

아이디·비밀번호를 입력해 DB에 준비된 공용 계정으로 로그인합니다. 로그인할 때 사용자·계좌·거래를 생성하거나 초기화하지 않습니다.

- 아이디: `user1`
- 비밀번호: `demo1234!`
- 위 정보는 합성 데이터만 사용하는 공개 체험 계정이며 로그인 화면에도 표시합니다.
- 같은 계정으로 로그인한 사람들은 잔액·거래내역·모니터링 설정을 공유합니다.
- 로그인 세션은 브라우저별로 발급하므로 한 브라우저의 로그아웃은 다른 로그인에 영향을 주지 않습니다.

## 최초 준비

루트와 backend의 `.env`를 기존 설정에 맞춰 준비하고 의존성을 설치합니다. 기존 `.env`는 덮어쓰지 않습니다.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`backend/.env`의 DATABASE_URL은 호스트의 서비스 DB를 가리켜야 합니다. 기존 `DEMO_JWT_SECRET`을 서버 JWT 서명키로 계속 사용하며 최소 32바이트여야 합니다. 없는 경우 아래 명령으로 생성해 `.env`에 넣습니다. 실제 키는 Git에 커밋하지 않습니다.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

로그인 유효 시간은 `AUTH_SESSION_TTL_SECONDS=86400`(기본 24시간)입니다. 기존 `DEMO_SESSION_TTL_SECONDS`도 하위 호환으로 읽습니다. 허용 범위는 60초~7일입니다.

```powershell
docker compose -f .\compose.yaml up -d --wait db
docker compose -f .\compose.yaml run --rm flyway migrate
Get-Content -Raw -Encoding UTF8 .\database\seeds\user1.sql | docker compose -f .\compose.yaml exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

V5가 `auth_sessions`, V6가 `demo_seed_metadata`를 추가합니다. 공용 계정에 여러 로그인 세션을 발급할 수 있습니다. V1~V5 SQL은 수정하지 않으며 기존 사용자·거래·옛 demo_sessions는 삭제하지 않습니다. 옛 자동 생성 토큰은 새 인증에서 받아들이지 않습니다.

V7은 초기 준비 실행과 최초 결과를 연결하는 `initialization_runs`를 추가합니다. 새 코드를 받으면 로그인 API를 사용하기 전에 위 `flyway migrate`를 실행합니다. 재실행·동시 실행·실패 복구 규칙은 [RERUNS.md](RERUNS.md)를 참고하세요.

`user1.sql`은 사용자·계좌·생활비 설정·예정 지출 2건·정상 거래 30건을 준비합니다. 거래별 잔액을 계산한 마지막 잔액은 80만 원입니다. 최초 적용 후 재실행해도 기존 송금·잔액·설정·비밀번호를 덮어쓰지 않습니다. SQL은 로그인이나 서버 시작 때 자동 실행하지 않습니다. 생성 규칙과 적용 조건은 [초기 데이터 안내](../database/seeds/README.md)를 참고하세요.

## 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Windows 소켓 오류가 발생했던 `--reload`를 기본 명령에서 제외했습니다. 백엔드 코드를 바꾸면 `Ctrl+C`로 종료한 뒤 다시 실행합니다.

별도 터미널에서 다음을 실행하고 http://localhost:5173 에서 위 계정 정보를 입력합니다.

```powershell
cd frontend
npm ci
npm run dev
```

기본 모드는 실제 API입니다. 기존 `frontend/.env.local`에 mock이 지정돼 있다면 다음으로 변경하고 Vite를 재시작합니다.

```dotenv
VITE_API_MODE=api
VITE_API_BASE_URL=http://localhost:8000
```

## 인증 API

| 메서드 | 경로 | 역할 |
|---|---|---|
| POST | `/auth/login` | `{username,password}` 검증·초기 준비 후 `{access_token,token_type,expires_at,user,initialization}` |
| GET | `/auth/me` | 현재 로그인 사용자·만료 시각 |
| POST | `/auth/logout` | 현재 서버 세션만 폐기, 204 |
| GET | `/demo/me` | 계좌·생활비 설정·예정 지출 |
| GET | `/demo/recipients` | 합성 수취인 목록 |
| GET | `/demo/accounts/{account_id}` | 인증 사용자의 계좌만 조회 |
| PUT | `/demo/me/monitoring-consent` | `{consented:boolean}`으로 동의·철회 |
| POST | `/transfers` | 가상 송금. 유효 세션과 모니터링 동의 필요 |
| GET | `/transactions` | 내 거래 최신순, limit/cursor 지원 |
| GET | `/baselines/current` | 오늘·현재 버전의 기준 통계, 없으면 404 |
| GET | `/budget-forecasts/latest` | 현재 입력과 일치하는 생활비 결과, 없으면 404·오래됐으면 409 |

`POST /demo/sessions`와 체험 재시작 API는 제거했습니다. 새로고침 시 미완료 자동 생성 요청을 재실행하지 않습니다. 회원가입 API도 제공하지 않습니다.

## 로그인 직후 초기 준비

로그인 비밀번호 검증을 통과한 기존 사용자는 다음 순서로 준비합니다. `user1` 외에도 동일한 계좌·설정이 준비된 사용자는 같은 규칙을 적용합니다.

```text
비밀번호 검증 → 사용자 잠금·최신 상태 확인
→ 오늘의 현재 입력 스냅샷 조회·비교 또는 생성
→ 최근 30일 기준 통계 조회 또는 생성
→ 스냅샷의 생활비 결과 조회 또는 생성
→ 로그인 세션 저장·토큰 발급 → 전체 commit
```

`app.demo.initialization.ensure_initial_preparation`이 이미 구현한 공통 계산·저장 서비스를 호출합니다. Airflow 실행을 기다리거나 초기 SQL을 다시 실행하지 않습니다. 사용자·계좌·잔액·설정·원본 거래를 생성하거나 초기화하지 않습니다.

- 통계는 사용자·한국 날짜·`baseline-v1`별 최초 결과를 재사용합니다.
- 생활비 입력은 같은 한국 날짜·`budget-v1`의 최신 스냅샷과 현재 계좌·설정·포함 지출을 비교합니다. 같으면 기존 스냅샷을 재사용합니다.
- 잔액·생활비 설정·포함 지출이 바뀌거나 한국 날짜가 바뀌면 새 스냅샷과 생활비 결과를 만듭니다. 과거 결과는 보존합니다.
- 스냅샷만 있고 생활비 결과가 없으면 해당 입력으로 누락 결과만 생성합니다. 통계만 누락돼도 복구합니다.
- 동시 로그인은 같은 사용자 잠금으로 직렬화해 결과를 중복 생성하지 않습니다. 로그인 세션은 각각 발급합니다.
- 준비와 새 로그인 세션은 한 트랜잭션으로 확정합니다. 준비 중 실패하면 새 통계·입력·결과는 롤백되고 토큰을 반환하지 않습니다. 기존 결과와 기존 로그인 세션은 보존합니다.
- 초기 준비는 savepoint로 보호하며 완료 실행 기록도 함께 저장합니다. 같은 실행 ID·버전은 최초 결과를 반환하고, 토큰 생성·세션 저장·최종 commit 실패도 rollback합니다.

성공 응답에는 다음 준비 정보가 추가됩니다. 프론트의 기존 로그인 코드는 응답이 완료된 뒤 토큰을 저장하므로 준비가 끝나기 전에 새 로그인으로 진입하지 않습니다.

```json
{
  "initialization": {
    "status": "READY",
    "baseline_date": "2026-10-21",
    "baseline_as_of": "2026-10-21T06:00:00Z",
    "baseline_version": "baseline-v1",
    "snapshot_id": 1,
    "forecast_id": 1,
    "forecast_as_of": "2026-10-21T06:00:00Z",
    "forecast_version": "budget-v1"
  }
}
```

응답의 ID·시각은 실제 준비 결과입니다. 이미 오늘 통계가 있으면 `baseline_as_of`는 새 생활비 결과 시각보다 이전일 수 있습니다.

계좌·생활비 설정 누락, 지난 다음 수입일, 잘못된 입력, 마이그레이션·DB 오류로 준비할 수 없으면 HTTP 503으로 안내합니다. 원인을 수정한 후 다시 로그인하면 필요한 결과를 재생성합니다. 비밀번호가 틀리거나 비활성 계정이면 기존처럼 401이며 준비 서비스를 호출하지 않습니다.

새로고침의 `/auth/me`는 로그인 확인만 하며 재계산하지 않습니다. 이미 발급된 토큰으로 새로고침한 경우에는 이번 초기 준비를 실행하지 않으므로, 기존 이용자는 로그아웃 후 다시 로그인해야 합니다. 결과 조회 API는 [PREPARED_QUERIES.md](PREPARED_QUERIES.md)에 설명합니다. 송금 때 결과 갱신·준비 상태 검사, 프론트 결과 연결, 탐지·알림 실행은 별도 작업입니다.

현재 PostgreSQL 통합 테스트는 준비 서비스를 실제 호출합니다. 기존 SQLite 인증·송금 단위 테스트에서는 PostgreSQL 전용 준비 서비스를 명시적으로 대체합니다. 초기 SQL을 적용한 user1 로그인·재로그인·입력 변경·날짜 변경·누락 복구·동시 로그인·실패 롤백은 `tests.test_login_initialization`에서 실제 PostgreSQL로 검증합니다.

비밀번호는 scrypt 해시로 검증하고 원문을 DB나 브라우저 저장소에 저장하지 않습니다. 토큰은 같은 탭의 sessionStorage에 저장해 새로고침에도 유지합니다. 매 요청에서 JWT 서명·알고리즘·만료·발급자·대상과 DB 세션 상태·사용자 상태를 확인합니다. 요청 body나 X-User-Id로 인증 사용자를 바꿀 수 없습니다.

만료·폐기·비활성 계정은 401입니다. 비밀번호가 틀리거나 아이디가 없어도 동일한 401 메시지를 반환하며 계정을 생성하지 않습니다. 미동의·철회 상태에서는 송금이 403이고 기존 데이터 조회는 가능합니다. 공용 계정이므로 모니터링 변경도 모든 이용자에게 반영됩니다.

송금 중복 차감 방지와 거래·잔액의 원자적 저장은 유지합니다. 탐지·알림·공유 API는 별도 기능입니다. 배치 대상 조회는 `app.monitoring.service.monitored_demo_user_ids`를 사용할 수 있으며, 여러 유효 세션이 있어도 사용자 ID는 한 번만 반환합니다.

## 검증

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
Push-Location frontend
npm test
npm run build
Pop-Location
```

PostgreSQL 통합 테스트는 별도의 DB에 `DEMO_TEST_DATABASE_URL`을 지정합니다. 테스트는 고유한 auth_test_UUID 스키마에 모든 마이그레이션을 적용하고 해당 스키마만 제거합니다. 운영·서비스 DB를 테스트 DB로 지정하지 않습니다.
