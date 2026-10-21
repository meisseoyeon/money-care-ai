# 프로젝트 구성

## 실행 단위

| 위치 | 역할 | 기본 포트 |
|---|---|---|
| `backend` | FastAPI, 인증·거래·AI 기능 | 8000 |
| `frontend` | React 화면과 API 호출 | 5173 |
| 루트 `compose.yaml` | 서비스 PostgreSQL, Flyway | 호스트 5433 → 컨테이너 5432 |
| `airflow/docker-compose.yaml` | 배치 작업과 별도 Airflow 메타데이터 DB | 8080 |

현재 백엔드는 상태 확인과 공용 계정 비밀번호 인증·세션 유지·모니터링 동의·가상 송금·거래내역 API를 제공합니다. 프런트엔드는 기본 API 모드로 체험 인증과 송금·거래내역에 연결합니다. 탐지·설명·RAG API는 담당 기능 병합 시 연결해야 합니다. 전체 화면의 더미 시연은 `VITE_API_MODE=mock`으로 실행합니다. 인증 구성과 실행 방법은 [AUTH.md](AUTH.md)를 참고하세요.

## 백엔드 패키지

기술 계층별 최상위 폴더 대신 기능별 패키지를 사용합니다. 각 기능에 필요한 파일만 둡니다.

```text
backend/app/
  main.py                    # 앱 생성, CORS, 기능별 라우터 등록
  auth/                      # 로그인·로그아웃·JWT·비밀번호 검증
    router.py
    schemas.py
    service.py
    models.py                # AuthSession
    dependencies.py          # 현재 사용자와 동의 검사
    passwords.py
  users/                     # 사용자 모델과 공개 응답 변환
    models.py
    serializers.py
  accounts/                  # 계좌 모델·본인 계좌 조회
    router.py
    models.py
    service.py
  budgets/                   # 생활비 설정·예정 지출·입력·결과
    models.py                # 설정·지출·기존 snapshots/forecasts 테이블 매핑
    service.py
    constants.py             # 생활비 입력·결과 공통 계산 버전
    snapshots.py             # 현재 입력 고정·최초 저장·조회, 호출자가 commit
    calculator.py            # 고정 입력으로 남은 일수·생활비·여유·부족 계산
    forecasts.py             # 입력별 최초 결과 저장·조회, 호출자가 commit
    queries.py               # 현재 입력과 같은 최신 결과 읽기, 오래됐으면 409
    router.py                # 인증 사용자 생활비 조회 API
    schemas.py               # 조회 응답 필드 제한·ID 문자열 변환
  baselines/                 # 최근 30일 출금 기준 통계 계산·저장
    calculator.py            # DB·API와 독립적인 공통 계산 함수
    models.py                # 기존 user_baselines 테이블 매핑
    service.py               # 날짜·버전별 최초 저장·조회, 호출자가 commit
    router.py                # 인증 사용자의 오늘 기준 통계 조회
    schemas.py               # 소수점 정밀도를 유지하는 조회 DTO
  transactions/              # 가상 송금·거래내역
    router.py
    models.py
    schemas.py
    service.py
  recipients/                # 합성 수취인과 사용자별 친숙 여부
    router.py
    catalog.py
    service.py
  monitoring/                # 동의·철회·배치 대상 사용자 조회
    router.py
    schemas.py
    service.py
  demo/                      # 화면 초기 데이터를 모아 반환
    router.py
    service.py
    initialization.py        # 로그인 시 통계·현재 입력·생활비 결과 준비
    models.py                # V7 initialization_runs: 실행별 최초 결과 연결
  health/
    router.py
  core/                      # 여러 기능이 쓰는 설정·시간 함수
    config.py
    time.py
  db/                        # 공통 DB 연결·세션·모델 Base
    base.py
    session.py
  ai/
    detection/
    explanation/
    rag/
```

- `router.py`는 요청·인증 의존성과 HTTP 응답을 처리합니다.
- `schemas.py`는 요청 데이터 검증, `service.py`는 기능 처리와 트랜잭션을 담당합니다.
- 모든 SQLAlchemy 모델은 `app.db.base.Base`를 공유합니다. 기능별 모델 파일로 옮겨도 테이블 이름과 DB 구조는 바뀌지 않습니다.
- `demo`는 계좌·생활비·사용자 기능의 결과를 모읍니다. 인증 기능이 demo 서비스에 의존하지 않도록 사용자 응답 변환은 users로 분리합니다.
- 다른 기능은 인증 의존성을 `app.auth.dependencies`에서 가져옵니다. 단순 시간 처리는 인증과 분리한 `app.core.time`을 사용합니다.
- 배치 대상 조회는 `app.monitoring.service.monitored_demo_user_ids`에 있습니다.
- `core/config.py`는 실행 위치에 관계없이 `backend/.env`를 읽습니다.
- API 주소는 기존 `/auth/*`, `/demo/*`, `/transfers`, `/transactions`, `/health`를 유지합니다.

백엔드 내부 import는 `from app.auth.dependencies import get_current_user`처럼 기능 패키지를 기준으로 작성합니다. 루트 실행 명령은 `uvicorn app.main:app --app-dir backend`를 유지합니다.

테스트는 `backend/tests/test_auth.py`, `test_transactions.py`, `test_seed.py`, `test_app.py`로 나누며 공통 계정·DB fixture는 `tests/support.py`에 둡니다.

## DB 변경

Flyway가 `database/migrations`의 SQL을 읽어 서비스 DB에 적용합니다. 기존 SQL의 내용과 버전, 루트 Compose의 프로젝트 이름 및 PostgreSQL 볼륨은 유지했습니다. `database/seeds`는 개발 데이터용으로만 사용하며 실제 데이터를 Git에 저장하지 않습니다.

## 프런트엔드와 문서

프런트엔드는 기능별로 `frontend/src/features`에 모읍니다.

- `auth`: 로그인 화면·세션 처리.
- `home`: 홈 화면.
- `transfers`: 송금 화면·사전 확인 계산·송금 API.
- `transactions`: 거래내역 화면과 페이지 조회.
- `alerts`: 알림 화면·대응 안내·문구·API.
- `budgets`: 생활비 화면·예측 계산·설정 API.
- `supporters`: 지원자 화면·연결·공유 API.
- `settings`: 설정 모달과 모니터링 설정 API.

`src/app`은 라우팅·레이아웃·Provider·API 조합을 담당합니다. `src/shared`에는 공통 UI·HTTP 클라이언트·Context·순수 도구·스타일을 두며 기능 코드에 의존하지 않습니다. 각 기능은 공통 request를 전달받는 API 모듈을 사용합니다. `mocks`는 여러 기능을 함께 시연하는 브라우저용 더미 API와 fixture를 보관합니다.

진입점은 `src/main.jsx`, 실행 명령은 `npm run dev`이며 화면 주소와 API 주소는 유지합니다. 테스트는 `frontend/tests`에서 로그인·HTTP 연결·mock·송금 사전 확인을 검증합니다. 자세한 트리는 [프런트엔드 안내](../frontend/README.md)에 있습니다. 공통 API 계약은 `docs/API_CONTRACT.md`에서 관리합니다.

## Airflow

현재 브랜치에 없던 실행 설정은 Apache의 개발용 Compose를 기반으로 추가했습니다. 기존 로컬 `airflow/.env`와 로그는 유지합니다. 실행 설정의 `.env` 변수 치환을 위해 루트에서는 항상 `--env-file airflow/.env`를 지정합니다. DAG, 플러그인은 각각 `airflow/dags`, `airflow/plugins`에 둡니다. 생성되는 로그와 `airflow.cfg`는 Git에서 제외합니다.
