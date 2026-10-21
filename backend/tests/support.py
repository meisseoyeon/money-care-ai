import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from app.auth.dependencies import require_monitoring_consent
from app.core.time import utc_now
from app.baselines.calculator import SEOUL
from app.auth.passwords import hash_password
from app.db.session import get_db
from app.db.base import Base
from app.users.models import User
from app.auth.models import AuthSession
from app.accounts.models import Account
from app.budgets.models import BudgetSetting, ScheduledExpense
from app.transactions.models import Transaction
from app.auth.router import router as auth_router
from app.demo.router import router as demo_router
from app.accounts.router import router as accounts_router
from app.recipients.router import router as recipients_router
from app.monitoring.router import router as monitoring_router
from app.transactions.router import router as transactions_router
from app.baselines.router import router as baselines_router
from app.budgets.router import router as budgets_router

TEST_SECRET = "auth-unit-tests-only-" + "x" * 48
ROOT = Path(__file__).resolve().parents[2]


class AuthTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DEMO_JWT_SECRET": TEST_SECRET, "DEMO_SESSION_TTL_SECONDS": "86400"})
        self.env.start()
        self.postgres = os.getenv("DEMO_TEST_DATABASE_URL")
        if self.postgres:
            self.base_engine = create_engine(self.postgres, pool_pre_ping=True)
            self.schema = "auth_test_" + uuid4().hex
            with self.base_engine.begin() as conn:
                conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                conn.execute(CreateSchema(self.schema))
                conn.exec_driver_sql(f'SET LOCAL search_path = "{self.schema}", public, pg_catalog')
                migrations = sorted((ROOT / "database/migrations").glob("V*__*.sql"),
                                    key=lambda path: tuple(int(part) for part in path.name.split("__")[0][1:].split(".")))
                for migration in migrations:
                    script = migration.read_text(encoding="utf-8")
                    script = script.replace("SET LOCAL search_path = public, pg_catalog;", f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')
                    # 매개변수가 없는 전체 DDL을 전달합니다. 함수 본문의 %도 보존합니다.
                    with conn.connection.driver_connection.cursor() as cursor:
                        cursor.execute(script, prepare=False)
            # ORM의 스키마 변환뿐 아니라 DDL trigger 안의 테이블 조회도 격리합니다.
            @event.listens_for(self.base_engine, "checkout")
            def set_search_path(connection, record, proxy):
                previous = connection.autocommit
                connection.autocommit = True
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(f'SET search_path = "{self.schema}", public, pg_catalog')
                finally:
                    connection.autocommit = previous
            self.engine = self.base_engine.execution_options(schema_translate_map={None: self.schema})
        else:
            self.temp = tempfile.TemporaryDirectory()
            self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "auth.db"), connect_args={"check_same_thread": False})
            Base.metadata.create_all(self.engine)
            # 통계·생활비 저장은 PostgreSQL 통합 테스트에서 실제 실행합니다.
            # 기존 SQLite 인증/송금 단위 테스트에는 명시적으로 준비 서비스를 대체합니다.
            preparation = patch("app.auth.service.ensure_initial_preparation", return_value={"status": "READY"})
            preparation.start()
            self.addCleanup(preparation.stop)
            # 송금 준비·생활비 저장은 PostgreSQL 전용 통합 테스트에서 실제 검증합니다.
            forecasts = {}

            def fake_forecast(db, *, user_id, transaction):
                forecast = SimpleNamespace(
                    id=transaction.id, snapshot_id=transaction.id, user_id=user_id,
                    as_of=transaction.occurred_at, balance_as_of=transaction.occurred_at,
                    next_income_date=transaction.occurred_at.date(), remaining_days=0,
                    current_balance=transaction.balance_after, scheduled_expense_total=0,
                    daily_living_budget=0, expected_living_cost=0, available_amount=transaction.balance_after,
                    shortage_amount=0, calculation_version="test-only",
                )
                forecasts[transaction.id] = forecast
                return forecast

            for name, options in (
                ("check_transfer_preparation", {"side_effect": lambda db, *, user_id: utc_now().astimezone(SEOUL).date()}),
                ("create_transfer_forecast", {"side_effect": fake_forecast}),
                ("find_transfer_forecast", {"side_effect": lambda db, *, user_id, transaction_id: forecasts.get(transaction_id)}),
            ):
                replacement = patch(f"app.transactions.service.{name}", **options)
                replacement.start()
                self.addCleanup(replacement.stop)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(auth_router)
        self.app.include_router(demo_router)
        self.app.include_router(accounts_router)
        self.app.include_router(recipients_router)
        self.app.include_router(monitoring_router)
        self.app.include_router(transactions_router)
        self.app.include_router(baselines_router)
        self.app.include_router(budgets_router)

        @self.app.get("/test/transfer-guard")
        def protected(principal=Depends(require_monitoring_consent)):
            return {"user_id": principal.user.user_id}

        def override_db():
            with self.sessions() as db:
                try:
                    yield db
                except Exception:
                    db.rollback()
                    raise

        self.app.dependency_overrides[get_db] = override_db
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")


    async def asyncTearDown(self):
        await self.client.aclose()
        if self.postgres:
            assert self.schema.startswith("auth_test_") and len(self.schema) == 42
            with self.base_engine.begin() as conn:
                conn.execute(DropSchema(self.schema, cascade=True))
            self.base_engine.dispose()
        else:
            self.engine.dispose()
            self.temp.cleanup()
        self.env.stop()


    async def login(self, username="user1", password="demo1234!"):
        return await self.client.post("/auth/login", json={"username": username, "password": password})


    async def create(self, *, consent=True):
        # 테스트 fixture만 계정을 준비합니다. 운영 로그인은 사용자를 생성하지 않습니다.
        username = "user" + str(self.count(User) + 1)
        now = utc_now()
        with self.sessions() as db:
            db.add(User(user_id=username, email=f"{username}@example.invalid",
                        password_hash=hash_password("demo1234!"), display_name="체험 사용자", status="ACTIVE",
                        created_at=now, updated_at=now, monitoring_consented_at=now if consent else None))
            db.flush()
            db.add(Account(account_id=username + "-account", user_id=username, display_name="체험 생활비 통장",
                           current_balance=800000, balance_as_of=now, created_at=now, updated_at=now))
            db.add(BudgetSetting(user_id=username, next_income_date=now.date()+timedelta(days=20),
                                expected_income_amount=1000000, daily_living_budget=20000, updated_at=now))
            db.commit()
        return await self.login(username)


    def auth(self, response):
        return {"Authorization": "Bearer " + response.json()["access_token"]}


    def count(self, model):
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))


    async def send(self, session, *, amount=120000, request_id=None, recipient="demo-payee-1"):
        return await self.client.post("/transfers", headers=self.auth(session),
                                      json={"request_id": request_id or str(uuid4()),
                                            "counterparty_id": recipient, "amount": amount})

