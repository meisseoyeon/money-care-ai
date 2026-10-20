# 체험 사용자와 인증

`feat/7-auth`는 실제 이메일 입력·발송 없이 사용자별 체험 통장과 서버 인증을 제공합니다. 실제 은행 거래는 처리하지 않습니다.

체험 송금은 `POST /transfers`로 DB 잔액을 차감하고 거래 원본을 저장합니다. `GET /transactions`는 자신의 거래내역만 반환하며, 프런트는 송금 후 잔액과 거래내역을 다시 읽습니다. 모니터링 미동의·철회 시 송금은 403, 조회는 허용됩니다. 내 설정에서 동의하고 켜기를 누른 뒤 송금할 수 있습니다. 탐지·알림 생성은 아직 별도 기능입니다.

송금 요청의 UUID `request_id`는 사용자와 조합해 고유 거래 ID로 변환합니다. 동일 요청의 재전송은 같은 거래를 반환하고, 금액이나 상대가 다르면 409입니다. 세션 → 사용자 → 계좌 순서의 DB 잠금으로 동시 송금과 동의 철회를 조정하고, 거래 저장 실패 시 잔액 변경도 롤백합니다. 기존 V4까지 적용된 DB 구조를 사용하므로 추가 마이그레이션은 없습니다.

## 실행

저장소 루트의 PowerShell에서 실행합니다. 기존 `.env`는 덮어쓰지 않습니다.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`backend/.env`의 `DATABASE_URL`을 루트 `.env`의 서비스 DB 계정과 맞추세요. `DEMO_JWT_SECRET`이 비어 있으면 다음 명령으로 생성한 값을 넣습니다. 키는 서버에서만 사용하며 Git에 커밋하지 않습니다. 기존 키를 바꾸면 기존 JWT를 사용할 수 없게 됩니다.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

```dotenv
DEMO_JWT_SECRET=생성한_32바이트_이상의_무작위_키
DEMO_SESSION_TTL_SECONDS=86400
```

DB를 시작하고 마이그레이션합니다. 기존 볼륨을 지우거나 V1을 수정할 필요가 없습니다.

```powershell
docker compose -f .\compose.yaml up -d --wait db
docker compose -f .\compose.yaml run --rm flyway migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Windows의 자동 재시작 자식 프로세스에서 `WinError 10014`가 발생할 수 있어 기본 명령은 `--reload` 없이 실행합니다. 이 경우 백엔드 코드 변경 후 `Ctrl+C`로 종료하고 같은 명령으로 다시 시작합니다. 단일 프로세스에서도 오류가 나면 같은 문제라고 단정하지 말고 새 오류 로그를 확인합니다.

별도 터미널에서 프런트엔드를 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
```

기본값은 서버 API 모드입니다. 기존 `frontend/.env.local`에 `VITE_API_MODE=mock`이 있다면 `api`로 변경하고 개발 서버를 재시작하세요.

```dotenv
VITE_API_MODE=api
VITE_API_BASE_URL=http://localhost:8000
```

브라우저에서 http://localhost:5173 을 열고 안내를 확인한 뒤 체험 시작을 누릅니다. 기존 테스트 계정 시연이 필요할 때만 `VITE_API_MODE=mock`으로 설정합니다.

## 구현된 API

| 메서드 | 경로 | 역할 |
|---|---|---|
| POST | `/demo/sessions` | 생성, 유효 세션 재사용, 명시적 재시작 |
| GET | `/demo/me` | 인증 사용자와 자신의 계좌·생활비 설정·예정 지출·만료 시각 |
| GET | `/demo/recipients` | 실제 계좌와 분리한 합성 수취인 목록 |
| GET | `/demo/accounts/{account_id}` | 자신의 계좌만 조회. 다른 사용자의 계좌는 404 |
| PUT | `/demo/me/monitoring-consent` | 동의 또는 철회 |
| DELETE | `/demo/sessions/current` | 서버 세션을 폐기하고 체험 종료 |

생성 요청에는 `Idempotency-Key` UUID 헤더를 보내고 다음 JSON을 사용합니다. `acknowledged`와 동의 값은 실제 boolean이어야 합니다. 사용자 ID·이메일·잔액 등의 추가 필드는 거절합니다.

```json
{
  "acknowledged": true,
  "monitoring_consented": true,
  "restart": false
}
```

응답은 `access_token`, `token_type: bearer`, `expires_at`, 공개 사용자 정보를 포함합니다. 이후 보호된 API에 `Authorization: Bearer <access_token>`을 전달합니다. 토큰·생성 요청 키는 URL이나 로그에 남기지 않습니다. 서버 응답에는 비밀번호 해시를 포함하지 않습니다.

## 생성과 중복 방지

- 서버가 사용자와 계좌에 각각 UUID를 생성합니다. 이메일은 `demo-<UUID>@example.invalid`이고 실제 메일은 발송하지 않습니다.
- `password_hash`에는 폐기할 무작위 비밀번호의 scrypt 해시를 저장합니다. 사용자에게 비밀번호를 발급하지 않고 체험 인증은 JWT만 사용합니다.
- 사용자, 계좌, 생활비 설정, 예정 지출 두 건, 세션을 하나의 DB 트랜잭션으로 생성합니다. 실패하면 전부 롤백합니다.
- 초기 잔액은 80만 원, 다음 수입일은 한국 날짜 기준 20일 뒤, 하루 생활비는 2만 원, 월세와 통신비는 합계 15만 원입니다.
- 프런트엔드는 연속 클릭을 하나의 요청으로 합치고, 처리 중에는 동의 입력도 잠급니다.
- 서버는 생성 요청 키의 해시에 UNIQUE 제약을 둡니다. 같은 키의 동시 요청은 같은 세션으로 수렴하고, 다른 요청 내용이면 409입니다.
- 응답 유실 후에는 새로고침·백그라운드 조회도 먼저 저장된 생성 요청을 복구합니다. 새 사용자 생성이나 토큰 만료 연장을 하지 않습니다.
- 유효 토큰을 함께 보낸 최초 생성 요청 재시도는 토큰 사용자와 생성 키 소유자가 같아야 합니다. 다른 사용자의 생성 키를 보내도 해당 사용자로 전환되지 않습니다. 토큰 없이 최초 생성 응답을 복구하는 생성 키도 인증 정보처럼 취급합니다.

## 만료, 재시작과 철회

JWT에는 `sub`, `sid`, `iat`, `exp`, `iss`, `aud`를 넣고 HS256으로 서명합니다. 서버는 허용 알고리즘을 고정하고 서명·필수 클레임·만료와 DB 세션의 사용자 일치·만료·폐기·사용자 상태를 매 요청마다 확인합니다. `X-User-Id`는 인증에 사용하지 않습니다.

`sessionStorage`에 토큰을 저장하므로 같은 탭의 새로고침은 세션을 유지하고, 별도 브라우저나 독립 탭은 별도 체험을 만듭니다. 브라우저 종료 이후의 유지나 탭 간 공유는 이 기능의 범위가 아닙니다.

내 설정의 `처음부터 다시 체험`에서 안내와 새 동의를 확인하면 새로운 요청 키로 `restart: true`를 보냅니다. 이전 세션 폐기와 새 사용자·세션 생성은 한 트랜잭션으로 처리합니다. 이전 데이터는 즉시 삭제하지 않지만 이전 토큰으로는 조회할 수 없습니다.

프런트엔드는 이전 토큰으로 보낸 늦은 응답을 새 체험에 적용하지 않습니다. 401 처리에서는 로컬 인증만 정리하며, 명시적 로그아웃의 서버 세션 폐기와 구분합니다. 새 세션을 발급한 뒤 초기 데이터 조회가 실패하면 이전 사용자의 데이터 대신 재조회 화면을 표시합니다.

재시작 응답 유실에 한해서, 서명이 유효한 원본 토큰과 동일 생성 키로 이미 발급된 새 세션을 복구할 수 있습니다. 원본 토큰이 만료돼도 복구 대상 새 세션은 유효해야 합니다. 만료된 원본 토큰으로 **새로운** 재시작 요청을 하거나 일반 API를 조회하는 것은 401입니다.

| 상태 | 자신의 데이터 조회 | 동의가 필요한 가상 송금·탐지 |
|---|---|---|
| 유효 세션 + 동의 | 허용 | 허용 |
| 유효 세션 + 미동의·철회 | 허용 | 403 |
| 만료·폐기·비활성 사용자 | 401 | 401 |

## 다른 기능 연결

이 브랜치는 체험 생성·인증·초기 데이터 조회와 가상 송금·거래 목록을 구현합니다. 알림 조회·공유와 생활비 계산 API는 각 담당 기능 브랜치와 연결해야 합니다. API 모드 어댑터는 서버 데이터를 읽으며, mock 데이터나 다른 사용자의 기록으로 대체하지 않습니다.

알림·조회 라우터는 `get_current_user_id` 또는 `get_current_demo_user`를 사용하고 모든 DB 조회에 인증된 `user_id` 조건을 붙입니다. 다른 브랜치의 임시 `X-User-Id` 인증 코드를 되살리지 마세요.

```python
from fastapi import Depends
from app.core.auth import get_current_user_id, require_monitoring_consent

# 일반 조회: user_id = Depends(get_current_user_id)
# 동의가 필요한 쓰기: principal = Depends(require_monitoring_consent)
# 이 의존성과 같은 get_db 세션에서 실제 작업을 수행한 뒤 commit합니다.
```

동의가 필요한 작업은 세션 → 사용자 순서로 행 잠금을 잡습니다. 동의 철회와 실제 작업이 같은 사용자 행 잠금을 사용해야 경쟁 상태를 제어할 수 있습니다.

Airflow도 토큰 인증과 별도로 체험 만료를 확인해야 합니다. `app.services.demo_monitoring.monitored_demo_user_ids` 또는 아래 조건을 적용하세요. 이 함수는 배치 대상 조회 도구이며 현재 비어 있는 Airflow DAG를 자동 구현하지는 않습니다.

```sql
SELECT u.user_id
FROM users u
JOIN demo_sessions s ON s.user_id = u.user_id
WHERE u.status = 'ACTIVE'
  AND u.monitoring_consented_at IS NOT NULL
  AND u.monitoring_revoked_at IS NULL
  AND s.revoked_at IS NULL
  AND s.expires_at > CURRENT_TIMESTAMP;
```

## 마이그레이션과 검증

- V1은 최초 적용본(`cb9ef6d`, 체크섬 `-1931401808`)으로 유지합니다. 이미 적용한 V1은 수정하지 않습니다.
- 다른 알림 브랜치에 있던 V2는 같은 내용을 그대로 포함했습니다. 새 체험 세션 테이블은 V3입니다.
- 이후 V1에 들어갔던 `transactions.source`의 `DEMO` 허용 변경은 V4로 분리했습니다. 기존 DB와 새 DB 모두 V1 → V2 → V3 → V4 순서로 적용합니다.
- V1 체크섬 `-1931401808` / `1779955927` 불일치는 기존 V1을 수정했던 이력 때문입니다. 이 브랜치의 복원된 V1과 V4를 사용하면 최초 V1이 적용된 DB는 `migrate`로 이어서 적용할 수 있습니다. `repair`는 테이블 구조를 바꾸지 않으므로 무조건 실행하지 않습니다.
- 서비스 시작 시 `create_all`을 호출하지 않습니다. DB 구조는 Flyway로 적용합니다.
- 일반 테스트는 임시 SQLite DB를 사용하며 PostgreSQL 동시성 테스트는 건너뜁니다.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
Push-Location frontend
npm test
npm run build
Pop-Location
```

PostgreSQL 통합 테스트에는 **별도의 테스트용 DB**를 사용합니다. 각 테스트가 고유한 `auth_test_<UUID>` 스키마에 모든 버전의 실제 DDL을 순서대로 적용하고 해당 스키마만 제거합니다. pgvector가 설치되어 있어야 하며 테스트 계정은 스키마·확장 생성 권한이 필요합니다.

```powershell
$env:DEMO_TEST_DATABASE_URL='postgresql+psycopg://사용자:비밀번호@127.0.0.1:15433/인증테스트DB'
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
Remove-Item Env:DEMO_TEST_DATABASE_URL
```

검증 범위는 생성·새로고침·독립 사용자·중복 클릭·동시 생성/재시작·응답 유실 복구·위조/만료/폐기 토큰·소유권·동의 철회·초기화 실패 롤백입니다.
