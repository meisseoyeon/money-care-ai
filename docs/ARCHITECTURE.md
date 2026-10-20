# 프로젝트 구성

## 실행 단위

| 위치 | 역할 | 기본 포트 |
|---|---|---|
| `backend` | FastAPI, 인증·거래·AI 기능 | 8000 |
| `frontend` | React 화면과 API 호출 | 5173 |
| 루트 `compose.yaml` | 서비스 PostgreSQL, Flyway | 호스트 5433 → 컨테이너 5432 |
| `airflow/docker-compose.yaml` | 배치 작업과 별도 Airflow 메타데이터 DB | 8080 |

현재 백엔드는 상태 확인과 체험 사용자 생성·토큰 인증·세션 재사용·모니터링 동의·가상 송금·거래내역 API를 제공합니다. 프런트엔드는 기본 API 모드로 체험 인증과 송금·거래내역에 연결합니다. 탐지·설명·RAG API는 담당 기능 병합 시 연결해야 합니다. 전체 화면의 더미 시연은 `VITE_API_MODE=mock`으로 실행합니다. 인증 구성과 실행 방법은 [AUTH.md](AUTH.md)를 참고하세요.

## 백엔드 패키지

- `app/main.py`: 앱 생성, CORS와 라우터 등록.
- `app/core`: 환경변수, 인증 등 공통 설정. `.env`는 현재 작업 디렉터리와 관계없이 `backend/.env`에서 읽습니다.
- `app/db`: DB 엔진과 세션 구현 위치.
- `app/models`: SQLAlchemy 테이블 모델 구현 위치.
- `app/schemas`: 요청·응답 데이터 모델 구현 위치.
- `app/routers`: HTTP 요청과 오류 응답 처리. 현재 `/health`, `/demo` 구현.
- `app/services`: 서비스 처리 규칙과 트랜잭션 구현 위치.
- `app/ai/detection`: 규칙과 Isolation Forest 구현 위치.
- `app/ai/explanation`: Gemini 설명 생성 구현 위치.
- `app/ai/rag`: 검색과 대응 안내 구현 위치.
- `tests`: 백엔드 검증 코드.

백엔드 내부 import는 `app`을 기준으로 통일합니다. 루트에서 실행할 때 Uvicorn에 `--app-dir backend`를 전달합니다.

## DB 변경

Flyway가 `database/migrations`의 SQL을 읽어 서비스 DB에 적용합니다. 기존 SQL의 내용과 버전, 루트 Compose의 프로젝트 이름 및 PostgreSQL 볼륨은 유지했습니다. `database/seeds`는 개발 데이터용으로만 사용하며 실제 데이터를 Git에 저장하지 않습니다.

## 프런트엔드와 문서

기존 8개 화면과 컴포넌트는 `frontend/src`에 유지합니다. 프런트엔드 전용 테스트도 `frontend/tests`에 유지합니다. 공통 API 계약은 `docs/API_CONTRACT.md`에서 관리합니다. ERD와 확정 API 명세도 `docs`에 추가합니다.

## Airflow

현재 브랜치에 없던 실행 설정은 Apache의 개발용 Compose를 기반으로 추가했습니다. 기존 로컬 `airflow/.env`와 로그는 유지합니다. 실행 설정의 `.env` 변수 치환을 위해 루트에서는 항상 `--env-file airflow/.env`를 지정합니다. DAG, 플러그인은 각각 `airflow/dags`, `airflow/plugins`에 둡니다. 생성되는 로그와 `airflow.cfg`는 Git에서 제외합니다.
