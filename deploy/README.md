# AWS EC2 배포

EC2 한 대에서 Docker Compose로 DB(PostgreSQL + pgvector), 백엔드(FastAPI), 웹서버(Caddy + 프런트 빌드)를 함께 실행합니다.
프런트와 백엔드는 같은 주소를 쓰고, `/api/*` 요청만 Caddy가 백엔드로 넘깁니다. Airflow는 포함하지 않습니다.

```
브라우저 → Caddy(:80/:443) ─┬─ /       → 프런트 빌드 파일
                            └─ /api/*  → backend:8000 → db:5432
```

## 1. EC2 만들기

- 리전: 아시아 태평양(서울)
- AMI: Ubuntu Server 24.04 LTS (64비트 x86)
- 인스턴스 유형: 프리티어 표시가 있는 t2.micro 또는 t3.micro
- 키 페어: 새로 만들고 `.pem` 파일 보관 (다시 받을 수 없음)
- 스토리지: 20GB 이상
- 보안 그룹 인바운드: SSH 22(내 IP만), HTTP 80(0.0.0.0/0), HTTPS 443(0.0.0.0/0)

먼저 Billing → Budgets에서 요금 알림을 설정합니다. 사용이 끝나면 인스턴스를 종료합니다.

## 2. 서버 준비

```bash
ssh -i money-care.pem ubuntu@서버_퍼블릭_IP
```

메모리가 1GB라 이미지 빌드 중 멈추지 않도록 스왑 2GB를 추가합니다.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Docker 설치 후 다시 접속합니다.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

## 3. 코드와 비밀값

```bash
git clone -b main https://github.com/meisseoyeon/money-care-ai.git
cd money-care-ai/deploy
cp .env.example .env
nano .env
```

| 값 | 넣을 것 |
|---|---|
| `POSTGRES_PASSWORD` | 영문·숫자만 긴 값 |
| `PUBLIC_ORIGIN` | `http://서버_퍼블릭_IP` (도메인 연결 후 `https://도메인`) |
| `SITE_ADDRESS` | 비워 둠 (도메인 연결 후 도메인) |
| `GEMINI_API_KEY` | 서버 전용 키 |
| `DEMO_JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` 결과 |

## 4. 실행과 DB 준비

```bash
docker compose up -d --build
docker compose --profile migration run --rm flyway
cat ../database/seeds/user1.sql | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
cat ../database/seeds/supporter1.sql | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec backend python -m app.documents /database/documents/manifest.json --apply
```

평소 지출 통계와 생활비 예측은 로그인할 때 자동으로 계산됩니다.

확인:

```bash
curl http://localhost/api/health
```

브라우저에서 `http://서버_퍼블릭_IP`로 접속해 `user1 / demo1234!`로 로그인합니다.

## 5. HTTPS (선택)

무료 도메인(예: DuckDNS)을 서버 퍼블릭 IP에 연결한 뒤 `.env`를 바꾸고 다시 실행합니다. Caddy가 인증서를 자동으로 발급합니다.

```
SITE_ADDRESS=moneycare.duckdns.org
PUBLIC_ORIGIN=https://moneycare.duckdns.org
```

```bash
docker compose up -d
```

EC2를 중지했다가 다시 켜면 퍼블릭 IP가 바뀝니다. 고정하려면 탄력적 IP를 연결합니다(인스턴스에 연결해 두지 않으면 요금이 나옵니다).

## 6. 업데이트

```bash
cd ~/money-care-ai && git pull
cd deploy
docker compose up -d --build
docker compose --profile migration run --rm flyway
```

로그 확인: `docker compose logs -f backend`
