# money-care-ai
발달장애인의 자발적 동의를 기반으로 생활비 부족과 이상 거래 징후를 알리고, 쉬운 설명과 선택적 도움 요청을 제공하는 AI 금융생활 지원 서비스

## 폴더 구조

```text
money-care-ai/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   └── ai/
│   │       ├── detection/
│   │       ├── explanation/
│   │       └── rag/
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── services/
│   │   ├── context/
│   │   ├── lib/
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── tests/
│   ├── package.json
│   ├── package-lock.json
│   └── .env.example
├── airflow/
│   ├── dags/
│   ├── plugins/
│   ├── docker-compose.yaml
│   └── .env.example
├── database/
│   ├── migrations/
│   └── seeds/
├── docs/
├── compose.yaml
├── .env.example
├── .gitignore
└── README.md
```

루트 `compose.yaml`은 서비스 PostgreSQL과 Flyway 실행용입니다. Airflow의 실행 설정은 `airflow/docker-compose.yaml`로 분리합니다. 기존 루트 `.venv`는 계속 사용할 수 있습니다.

현재 백엔드는 `/health`, `/demo` 체험 생성·인증, `/transfers` 가상 송금, `/transactions` 거래내역 API를 제공합니다. 프런트엔드는 기본 API 모드에서 이메일 입력 없이 체험을 시작합니다. 기존 더미데이터 시연은 `VITE_API_MODE=mock`으로 선택합니다. 탐지·알림 등의 API는 각 담당 기능을 별도로 연결해야 합니다. 자세한 실행 방법은 [체험 인증 안내](docs/AUTH.md)를 참고하세요.

## 환경변수 준비

저장소 루트의 PowerShell에서 실행합니다. 기존 환경 파일은 덮어쓰지 않습니다.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (!(Test-Path frontend/.env.local)) { Copy-Item frontend/.env.example frontend/.env.local }
```

- 루트 `.env`: 서비스 DB와 Flyway의 `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
- `backend/.env`: FastAPI의 `DATABASE_URL`, `CORS_ORIGINS`, 서버 전용 AI 키. DB 접속 정보는 루트 `.env`와 맞춥니다.
- `frontend/.env.local`: `VITE_API_MODE`, `VITE_API_BASE_URL`. `VITE_` 변수는 브라우저에 노출되므로 DB 비밀번호나 AI 키를 넣지 않습니다.
- `airflow/.env`: Airflow 전용 설정. 아래 Airflow 절차에서 준비합니다.

## DB와 Flyway 실행

```powershell
docker compose -f .\compose.yaml up -d --wait db
docker compose -f .\compose.yaml run --rm flyway migrate
docker compose -f .\compose.yaml run --rm flyway info
```

마이그레이션은 `database/migrations`에 저장합니다. 이미 적용한 파일은 수정하지 않고 다음 버전의 SQL 파일을 추가합니다. 폴더 이동 후에도 기존 PostgreSQL 볼륨과 Flyway 이력을 그대로 사용합니다. `database/seeds`는 추후 개발용 더미데이터를 두는 곳이며 자동 실행되지 않습니다.

## 백엔드 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

기존 `.venv`가 있다면 생성 명령은 생략합니다. API 문서는 http://127.0.0.1:8000/docs, 상태 확인은 http://127.0.0.1:8000/health 입니다.

백엔드 내부 import는 `from app.routers import health`처럼 `app`을 기준으로 작성합니다. `backend` 폴더에서 실행할 경우 `..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`도 사용할 수 있습니다.

Windows에서 `--reload` 실행 중 자식 프로세스의 `sock.listen()`에 `WinError 10014`가 발생하면 위의 단일 프로세스 명령을 사용하세요. 이 실행 방식에서는 백엔드 코드 수정 후 `Ctrl+C`로 종료하고 다시 실행해야 합니다. 자동 재시작이 필요하면 정상 동작하는 환경에서 `--reload --reload-dir backend`를 선택적으로 사용합니다.

백엔드 테스트:

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
```

## 프런트엔드 실행

Node.js 22.12 이상이 필요합니다.

```powershell
cd frontend
npm ci
npm run dev
```

기본 주소는 http://localhost:5173 입니다. 자세한 화면 설명과 테스트 계정은 [프런트엔드 README](frontend/README.md)를 참고하세요.

```powershell
npm test
npm run build
```

## Airflow 실행

현재 브랜치에는 기존 Airflow Compose와 DAG 소스가 없어, [Apache Airflow 3.3.2 공식 개발용 Compose](https://airflow.apache.org/docs/apache-airflow/3.3.2/howto/docker-compose/index.html)를 추가했습니다. 예제 DAG는 비활성화했고, DAG와 플러그인 폴더는 비어 있습니다. 다른 브랜치의 DAG는 별도로 병합해야 합니다.

저장소 루트에서 실행합니다.

```powershell
if (!(Test-Path airflow/.env)) { Copy-Item airflow/.env.example airflow/.env }
```

`airflow/.env`의 `FERNET_KEY`가 비어 있으면 아래 명령으로 키를 생성해 넣습니다. 기존에 사용하던 키가 있으면 유지합니다. JWT 비밀키도 팀의 로컬 설정에 맞게 지정합니다.

```powershell
docker run --rm --entrypoint python apache/airflow:3.3.2 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```powershell
docker compose --env-file airflow/.env -f airflow/docker-compose.yaml up airflow-init
docker compose --env-file airflow/.env -f airflow/docker-compose.yaml up -d
```

Airflow UI는 http://localhost:8080 입니다. 기본 로컬 계정은 `airflow` / `airflow`입니다. Airflow의 메타데이터 DB는 서비스 DB와 별도입니다. 추후 DAG의 `moneycare_db` 연결은 Docker Desktop 기준 호스트 `host.docker.internal`, 포트 `5433`과 서비스 DB 계정으로 등록합니다.

## 문서

- [전체 구성과 폴더별 역할](docs/ARCHITECTURE.md)
- [체험 생성·인증 실행과 검증](docs/AUTH.md)
- [API 연결 계약 초안](docs/API_CONTRACT.md)
- DB 스키마 원본: `database/migrations/V1__initial_schema.sql`
