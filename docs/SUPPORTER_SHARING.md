# 지원자 공유 MVP

고정 체험 계정 `user1`과 `supporter1`을 사용합니다. 둘 다 비밀번호는 `demo1234!`입니다.
서버의 `app.users.roles.user_role()`에서 고정 계정 역할을 결정합니다. 토큰의 사용자 ID를 사용하며 요청에서 역할·소유자 ID를 받지 않습니다.
일반 회원의 역할 관리, 초대·이메일, 수락, 재연결, 재공유는 이번 범위에 없습니다.

## 개발 DB 준비

기존 마이그레이션과 `database/seeds/user1.sql`이 적용된 DB에서 프로젝트 루트 PowerShell로 실행합니다.
새 테이블이 없으므로 이번 작업을 위한 Flyway 마이그레이션은 없습니다.

```powershell
Get-Content -Raw -Encoding UTF8 .\database\seeds\supporter1.sql | docker compose -f .\compose.yaml exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
```

SQL은 지원자 계정과 ACTIVE 연결이 없을 때만 생성합니다. 기존 잔액·거래·비밀번호·철회 상태를 덮어쓰지 않습니다.
지원자는 계좌와 생활비 설정이 필요 없고 로그인 시 초기 통계·생활비 계산을 실행하지 않습니다.

## API와 트랜잭션

| API | 권한 | 기능 |
| --- | --- | --- |
| POST /alerts/{alert_id}/response | 알림 소유자 | HELP_REQUESTED 응답과 공유를 함께 저장 |
| GET /supporter-links | 당사자 | 본인의 연결 목록 |
| GET /alert-shares | 당사자 | 본인의 공유 목록(철회 포함) |
| POST /alert-shares/{share_id}/revoke | 공유 소유자 | 개별 공유 철회 |
| POST /supporter-links/{link_id}/revoke | 연결 소유자 | 연결과 기존 활성 공유 일괄 철회 |
| GET /shared-alerts | 지원자 | 본인에게 활성 연결로 공유된 알림만 조회 |

`ensure_alert_share()`와 철회 서비스는 commit하지 않습니다. 알림 응답 서비스는 사용자 행을 잠그고 알림 소유권·활성 연결을 확인한 뒤 응답과 공유를 함께 commit합니다. 예외 시 함께 rollback합니다.
철회 API도 같은 사용자 행을 먼저 잠급니다. 도움 요청과 철회가 경합해도 철회된 연결에 활성 공유를 남기지 않습니다.
DB의 `(alert_id, supporter_link_id)` 유일 제약을 재사용합니다. 같은 도움 요청은 기존 공유와 최초 응답·공유 시각을 유지합니다.

- 다른 사람의 알림·공유·연결: 404.
- 활성 지원자 연결 없음/지원자 비활성/철회된 공유 재공유: 409, 기존 응답 유지.
- 역할 불일치: 403. 인증 없음·만료·비활성 사용자: 401.
- 철회를 반복해도 최초 철회 시각을 유지합니다. 다른 응답으로 바꿔도 공유는 자동 철회되지 않습니다.

## 조회 정보와 담당 경계

공유 조회는 ACTIVE 공유 + ACTIVE 연결 + 현재 지원자 ID + ACTIVE 당사자를 한 SQL에서 확인합니다.
공유 ID·알림 ID·당사자 표시 이름·제목·유형·설명·안내·관련 거래 금액·알림/공유 시각만 반환합니다.
전체 거래·계좌 잔액·계좌번호·통계·생활비 설정은 공유 DTO에 포함하지 않습니다.
기존 계좌·거래 API도 토큰의 사용자 ID로 범위를 제한하므로 지원자가 user1을 지정해 조회할 수 없습니다.

탐지·설명·RAG 생성은 변경하지 않습니다. 기존 알림 조회 SQL과 DTO를 재사용하고 허용 필드만 선택합니다.
현재 알림 DTO의 guide는 null이므로 화면은 기본 도움 문구를 표시합니다. 와우님이 공통 조회 DTO에 안내를 연결하면 같은 값을 공유 화면에서도 사용합니다.
현재 없는 `/alerts/{id}/guide` 생성 API는 실제 API 모드에서 호출하지 않습니다.
송금 전 미저장 초안(`/transfer-help-requests`) 공유는 별도 기능이며 이번 구현은 저장된 알림의 도움 요청을 대상으로 합니다.

## 화면 확인

1. 일반 브라우저에서 user1 로그인, 다른 브라우저나 시크릿 창에서 supporter1 로그인.
2. user1의 저장된 알림에서 도와주세요 → 공유하고 도움받기.
3. supporter1의 공유받은 알림에서 이름·제목·설명 확인. 미공유 알림은 표시되지 않아야 합니다.
4. user1의 설정 → 공유한 알림 또는 알림 상세에서 개별 공유 철회.
5. supporter1에서 새로고침하면 해당 알림이 없어집니다. 화면 활성 중에는 기존 10초 자동 조회도 적용됩니다.
6. 설정 → 도움받을 사람에서 연결을 해제하면 그 연결의 모든 기존 공유가 철회됩니다. 다시 연결 버튼은 표시하지 않습니다.

철회는 이후 서버 조회 권한을 제거합니다. 이미 상대가 읽은 내용을 회수하는 기능은 아닙니다.

## 검증

PostgreSQL 테스트는 별도 DB URL을 사용하며 매 테스트마다 독립 스키마에 실제 마이그레이션을 적용하고 제거합니다.

```powershell
# backend 폴더, DEMO_TEST_DATABASE_URL에 별도 PostgreSQL 테스트 DB 설정 후
..\.venv\Scripts\python.exe -m unittest tests.test_supporters tests.test_auth tests.test_app
# frontend 폴더
npm test
npm run build
```
