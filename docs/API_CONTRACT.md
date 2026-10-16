# FastAPI 연결 계약 (제안)

현재 UI가 읽는 DTO와 경로입니다. 최종 DDL의 테이블을 그대로 반환할 필요는 없습니다. 아래처럼 조회 전용 DTO로 조합하거나 src/services/httpApi.js에서 변환하세요. **이 경로가 기존 서버에 이미 구현되어 있다는 뜻은 아닙니다.**

## 공통

- Authorization: Bearer access_token. 로그인만 인증 없이 호출합니다.
- user_id는 인증 토큰에서 결정하고, 요청에 들어온 타인 ID를 신뢰하지 않습니다.
- 날짜 YYYY-MM-DD, 일시 ISO8601 오프셋 포함. 금액 JSON 정수(현재 UI는 입력 10억 원 이하), ID는 문자열 권장(BIGINT도 JS 정밀도 범위를 넘기면 문자열).
- 목록 응답은 배열 또는 {items: [...]}입니다. 현재 어댑터는 다음 페이지를 자동 수집하지 않습니다.
- 오류는 적절한 HTTP 상태 코드 + {detail: "메시지"}. 401은 재로그인, 403은 권한 없음, 404는 미존재, 409는 잔액·요청 충돌에 사용합니다.
- 테스트 계정 생성은 백엔드 seed 작업입니다. 사용자 role은 화면 분기용 DTO이며 기존 users 테이블에 동일 컬럼을 추가해야 한다는 뜻은 아닙니다. 서버가 계정과 연결 관계로 결정할 수 있습니다.

## 경로

| 메서드 | 경로 | 요청 / 응답 |
|---|---|---|
| POST | /auth/login | {email,password} → {access_token} |
| GET | /users/me | User |
| GET | /accounts | Account[] |
| GET | /budget-settings | BudgetSettings |
| GET | /scheduled-expenses | Expense[] |
| GET | /budget-forecasts/latest | Forecast; 아직 없으면 404 |
| GET | /recipients | Recipient[] |
| GET | /transactions | Transaction[]; occurred_at 내림차순 |
| GET | /alerts | Alert[]; created_at 내림차순 |
| GET | /supporter-links | SupporterLink[] |
| GET | /alert-shares | Share[]; 당사자가 만든 공유만 |
| GET | /shared-alerts | SharedAlert[]; 유효한 공유·연결만 |
| POST | /transfers | {request_id,counterparty_id,amount} → {transaction,alert_ids,forecast} |
| POST | /alerts/{id}/seen | NEW → SEEN; 응답 완료 상태는 유지 |
| POST | /alerts/{id}/response | {response: PLANNED 또는 UNSURE 또는 HELP_REQUESTED} |
| POST | /alerts/{id}/guide | Guide |
| PUT | /budget-settings | {next_income_date,expected_income_amount,daily_living_budget} |
| POST | /scheduled-expenses | {title,amount,due_date,status} |
| PATCH | /scheduled-expenses/{id} | {id,title,amount,due_date,status} |
| PUT | /users/me/monitoring-consent | {consented:boolean} |
| POST | /alert-shares/{id}/revoke | 해당 공유 철회 |
| POST | /supporter-links/{id}/revoke | 연결·관련 공유 철회 |
| POST | /supporter-links/{id}/accept | 준비된 연결 재연결: 실제 권한·수락 플로에 맞게 어댑터 변경 |

마지막 accept 경로는 mock의 재연결 버튼용 제안입니다. 실제 지원자 수락을 구현하면 당사자가 지원자 대신 수락할 수 없도록 별도 요청/수락 API와 화면으로 변경하세요. 예정 지출 변경과 모니터링 변경 등은 성공 시 JSON 또는 204를 반환할 수 있습니다. guide와 transfer는 반드시 위 응답 본문이 필요합니다.

## 필수 DTO

```js
User = {user_id, email, display_name, role: 'OWNER'|'SUPPORTER',
  monitoring_consented_at: string|null, monitoring_revoked_at: string|null}
Account = {account_id, user_id, display_name, current_balance, balance_as_of}
BudgetSettings = {next_income_date, expected_income_amount, daily_living_budget}
Expense = {id, title, amount, due_date, status: 'PLANNED'|'PAID'|'CANCELLED'}
Forecast = {as_of, next_income_date, remaining_days, current_balance,
  scheduled_expense_total, daily_living_budget, expected_living_cost,
  available_amount, shortage_amount, calculation_version}
Recipient = {id, name, bank, account_hint, initial, familiar: boolean}
Transaction = {id, occurred_at, direction:'IN'|'OUT', amount, balance_after,
  tx_type, counterparty_id, description, source:'SYNTHETIC'}
SupporterLink = {id, owner_user_id, supporter_user_id, supporter_name,
  status:'PENDING'|'ACTIVE'|'REVOKED'}
Share = {id, alert_id, supporter_link_id, status:'ACTIVE'|'REVOKED', shared_at}
Alert = {id, user_id, alert_type, title, explanation, explanation_method,
  transaction_id, status:'NEW'|'SEEN'|'ANSWERED', user_response:null|string,
  created_at, evidence, guide:null|Guide}
Guide = {id, alert_id, method:'RAG'|'FALLBACK', steps:[string],
  citations:[{title, url, org, collected_at}], generated_at}
SharedAlert = {...Alert, share_id, shared_at, owner_name, guide:null|Guide}
```

Guide.steps는 문자열 또는 {instruction: "문장"}을 지원합니다. citations의 상세 필드는 src/components/Guide.jsx에서 확인하세요. 근거 문서·청크·인용을 서버에서 조합해 URL과 수집일을 반환하세요. 스크립트 URL은 UI 링크로 사용하지 않습니다.

현재 화면의 alert_type은 LARGE_OUTFLOW, NEW_COUNTERPARTY, BUDGET_SHORTAGE이며 서버가 LARGE_OUT, SHORTAGE 등을 쓰면 어댑터에서 변환하세요. user_response의 HELP_REQUESTED도 팀의 HELP 코드와 매핑할 수 있습니다.

거래 알림 evidence = {amount,counterparty_name,is_new_counterparty,p95_out_amount,triggered_rules}. 생활비 알림 evidence는 Forecast 스냅샷이며 remaining_days, shortage_amount를 사용합니다. 설명은 alert_explanations.text, 안내는 alert_guides.steps, 출처는 guide_citations·doc_chunks·documents 조인 결과를 Alert에 합쳐 제공합니다. 탐지 결과 테이블은 프런트엔드에서 직접 변경하지 않습니다.

## 서버가 보장할 사항

1. 송금 저장·계좌 잔액 차감은 같은 DB 트랜잭션에서 잠금 또는 원자적 UPDATE로 처리합니다.
2. request_id는 인증 사용자와 묶어 UNIQUE로 관리합니다. 같은 요청·본문은 기존 결과, 같은 요청·다른 본문은 409입니다. 이 계약에는 서버 측 멱등성 저장 구조가 필요합니다.
3. 새 상대 여부는 현재 송금을 넣기 전 과거 거래로 판단합니다. 탐지·알림은 LLM 성공과 분리합니다.
4. HELP 응답과 공유 생성은 원자적으로 처리하고 유효 연결을 확인합니다. 같은 알림의 공유 중복을 막습니다.
5. 공유 조회 때마다 당사자 공유와 지원자 연결이 모두 유효한지 확인합니다. 연결 재수락으로 과거 철회 공유가 살아나면 안 됩니다.
6. /alerts의 설명·안내는 최신 저장 결과를 반환합니다. 비동기 생성 결과는 현재 10초 폴링으로 반영합니다.
7. 거래 이력은 시간순 정렬·권한 검사하고, 여러 계좌를 지원하려면 첫 계좌만 쓰는 현재 UI를 계좌 선택 방식으로 확장합니다.

JavaScript에 VITE_ 환경변수는 모두 공개됩니다. DB 비밀번호·LLM 키는 서버 환경변수에만 저장하세요. 현재 토큰 저장은 시연용 sessionStorage입니다. 실제 배포의 인증 저장 방식·만료·갱신 정책은 서버와 함께 정하고 어댑터를 변경하세요.
