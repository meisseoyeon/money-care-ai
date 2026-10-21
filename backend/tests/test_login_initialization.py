import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, literal, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.auth.passwords import hash_password
from app.auth.schemas import LoginRequest
from app.auth.service import login
from app.baselines.models import UserBaseline
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.budgets.snapshots import SEOUL
from app.transactions.models import Transaction
from tests.postgres_support import PostgresSchemaTestCase
from tests.support import TEST_SECRET


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class LoginInitializationTests(PostgresSchemaTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"DEMO_JWT_SECRET": TEST_SECRET, "AUTH_SESSION_TTL_SECONDS": "86400"})
        env.start()
        self.addCleanup(env.stop)
        self.user_id = "login-init-" + uuid4().hex
        with self.engine.begin() as conn:
            self.now = conn.scalar(select(func.clock_timestamp()))
            self.today = self.now.astimezone(SEOUL).date()
            conn.execute(text("""INSERT INTO users(user_id,email,password_hash,display_name)
                VALUES (:id,:email,:password,'로그인 준비 테스트')"""),
                         dict(id=self.user_id, email=self.user_id + "@example.invalid", password=hash_password("demo1234!")))
            conn.execute(text("""INSERT INTO accounts(account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:id,:id,'생활비 통장',800000,:now)"""), dict(id=self.user_id, now=self.now))
            conn.execute(text("""INSERT INTO budget_settings
                (user_id,next_income_date,expected_income_amount,daily_living_budget)
                VALUES (:id,:income_date,1000000,20000)"""),
                         dict(id=self.user_id, income_date=self.today + timedelta(days=20)))
            conn.execute(text("""INSERT INTO scheduled_expenses(user_id,title,amount,due_date)
                VALUES (:id,'예정 지출',150000,:due_date)"""), dict(id=self.user_id, due_date=self.today + timedelta(days=5)))
            conn.execute(text("""INSERT INTO transactions
                (id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type)
                VALUES (:tx,:id,:id,:occurred_at,'OUT',10000,800000,'PURCHASE')"""),
                         dict(tx=uuid4().hex, id=self.user_id, occurred_at=self.now - timedelta(days=1)))

    def login(self, *, username=None, password="demo1234!"):
        with Session(self.engine, expire_on_commit=False) as db:
            return login(db, LoginRequest(username=username or self.user_id, password=password))

    def counts(self, *, user_id=None):
        with Session(self.engine) as db:
            return tuple(db.scalar(select(func.count()).select_from(model).where(model.user_id == (user_id or self.user_id)))
                         for model in (UserBaseline, BudgetInputSnapshot, BudgetForecast, AuthSession))

    def test_login_returns_token_only_after_all_results_are_ready(self):
        result = self.login()
        ready = result["initialization"]
        self.assertTrue(result["access_token"])
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["baseline_date"], self.today)
        self.assertEqual(ready["baseline_version"], "baseline-v1")
        self.assertEqual(ready["forecast_version"], "budget-v1")
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        with Session(self.engine) as db:
            baseline = db.scalar(select(UserBaseline).where(UserBaseline.user_id == self.user_id))
            snapshot = db.get(BudgetInputSnapshot, ready["snapshot_id"])
            forecast = db.get(BudgetForecast, ready["forecast_id"])
            self.assertEqual(baseline.as_of, snapshot.as_of)
            self.assertEqual(baseline.out_count_30d, 1)
            self.assertEqual(forecast.as_of, snapshot.as_of)
            self.assertEqual(forecast.available_amount, 250000)

    def test_relogin_reuses_valid_results_but_issues_independent_session(self):
        first, second = self.login(), self.login()
        self.assertEqual(first["initialization"], second["initialization"])
        self.assertNotEqual(first["access_token"], second["access_token"])
        self.assertEqual(self.counts(), (1, 1, 1, 2))

    def test_balance_change_creates_new_forecast_without_resetting_original_data(self):
        first = self.login()["initialization"]
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET current_balance=500000,balance_as_of=clock_timestamp() WHERE user_id=:id"),
                         dict(id=self.user_id))
            conn.execute(text("""INSERT INTO transactions
                (id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type)
                VALUES (:tx,:id,:id,clock_timestamp(),'OUT',300000,500000,'TRANSFER')"""),
                         dict(tx=uuid4().hex, id=self.user_id))
        ready = self.login()["initialization"]
        self.assertNotEqual(first["forecast_id"], ready["forecast_id"])
        self.assertEqual(self.counts(), (1, 2, 2, 2))
        with Session(self.engine) as db:
            self.assertEqual(db.get(BudgetForecast, ready["forecast_id"]).shortage_amount, 50000)
            self.assertEqual(db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == self.user_id)), 2)
            self.assertEqual(db.scalar(text("SELECT current_balance FROM accounts WHERE user_id=:id"), dict(id=self.user_id)), 500000)
            baseline = db.scalar(select(UserBaseline).where(UserBaseline.user_id == self.user_id))
            self.assertEqual(baseline.out_count_30d, 1)

    def test_setting_and_scheduled_expense_changes_invalidate_existing_inputs(self):
        self.login()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE budget_settings SET daily_living_budget=30000 WHERE user_id=:id"), dict(id=self.user_id))
            conn.execute(text("UPDATE scheduled_expenses SET status='PAID' WHERE user_id=:id"), dict(id=self.user_id))
        ready = self.login()["initialization"]
        self.assertEqual(self.counts(), (1, 2, 2, 2))
        with Session(self.engine) as db:
            forecast = db.get(BudgetForecast, ready["forecast_id"])
            self.assertEqual(forecast.expected_living_cost, 600000)
            self.assertEqual(forecast.scheduled_expense_total, 0)
            self.assertEqual(forecast.available_amount, 200000)

    def test_missing_forecast_is_repaired_using_existing_snapshot(self):
        first = self.login()["initialization"]
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM budget_forecasts WHERE user_id=:id"), dict(id=self.user_id))
        ready = self.login()["initialization"]
        self.assertEqual(ready["snapshot_id"], first["snapshot_id"])
        self.assertNotEqual(ready["forecast_id"], first["forecast_id"])
        self.assertEqual(self.counts(), (1, 1, 1, 2))

    def test_missing_baseline_is_repaired_without_new_budget_results(self):
        first = self.login()["initialization"]
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM user_baselines WHERE user_id=:id"), dict(id=self.user_id))
        ready = self.login()["initialization"]
        self.assertEqual(ready["forecast_id"], first["forecast_id"])
        self.assertEqual(self.counts(), (1, 1, 1, 2))

    def test_new_seoul_date_prepares_new_daily_results(self):
        first = self.login()["initialization"]
        tomorrow = self.now + timedelta(days=1)
        with patch("app.budgets.snapshots.func.clock_timestamp", return_value=literal(tomorrow)):
            ready = self.login()["initialization"]
        self.assertEqual(ready["baseline_date"], self.today + timedelta(days=1))
        self.assertNotEqual(ready["forecast_id"], first["forecast_id"])
        self.assertEqual(self.counts(), (2, 2, 2, 2))
        with Session(self.engine) as db:
            self.assertEqual(db.get(BudgetForecast, ready["forecast_id"]).remaining_days, 19)

    def test_wrong_password_or_inactive_user_does_not_initialize(self):
        for username, password in ((self.user_id, "wrong"), ("missing-user", "demo1234!")):
            with self.subTest(username=username), self.assertRaises(HTTPException) as error:
                self.login(username=username, password=password)
            self.assertEqual(error.exception.status_code, 401)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE users SET status='INACTIVE' WHERE user_id=:id"), dict(id=self.user_id))
        with self.assertRaises(HTTPException) as error:
            self.login()
        self.assertEqual(error.exception.status_code, 401)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_preparation_failure_rolls_back_all_new_results_and_session(self):
        with patch("app.demo.initialization.ensure_budget_forecast", side_effect=SQLAlchemyError("forced failure")):
            with self.assertLogs("app.auth.service", level="ERROR"), self.assertRaises(HTTPException) as error:
                self.login()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        self.assertEqual(self.login()["initialization"]["status"], "READY")

    def test_missing_source_data_is_reported_without_auto_creation(self):
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM budget_settings WHERE user_id=:id"), dict(id=self.user_id))
        with self.assertLogs("app.auth.service", level="ERROR"), self.assertRaises(HTTPException) as error:
            self.login()
        self.assertEqual(error.exception.status_code, 503)
        self.assertIn("생활비 설정", error.exception.detail)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    def test_concurrent_logins_share_results_and_create_two_sessions(self):
        barrier = Barrier(2)

        def authenticate(index):
            barrier.wait(timeout=10)
            return self.login()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(authenticate, (0, 1)))
        self.assertEqual(first["initialization"], second["initialization"])
        self.assertNotEqual(first["access_token"], second["access_token"])
        self.assertEqual(self.counts(), (1, 1, 1, 2))

    def test_seeded_user1_is_ready_immediately_without_modifying_seed_data(self):
        script = (Path(__file__).resolve().parents[2] / "database/seeds/user1.sql").read_text(encoding="utf-8")
        script = script.replace("SET LOCAL search_path = public, pg_catalog;",
                                f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            with conn.connection.driver_connection.cursor() as cursor:
                cursor.execute(script, prepare=False)
        ready = self.login(username="user1")["initialization"]
        self.assertEqual(self.counts(user_id="user1"), (1, 1, 1, 1))
        with Session(self.engine) as db:
            baseline = db.scalar(select(UserBaseline).where(UserBaseline.user_id == "user1"))
            forecast = db.get(BudgetForecast, ready["forecast_id"])
            self.assertEqual(baseline.out_count_30d, 29)
            self.assertEqual(forecast.current_balance, 800000)
            self.assertEqual(db.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == "user1")), 30)


if __name__ == "__main__":
    unittest.main()
