import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import timedelta, timezone
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.budgets.calculator import calculate_forecast
from app.budgets.forecasts import ensure_budget_forecast, get_budget_forecast
from app.budgets.models import BudgetForecast, BudgetInputSnapshot
from app.budgets.snapshots import ensure_budget_input_snapshot
from tests.postgres_support import PostgresSchemaTestCase


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class BudgetForecastTests(PostgresSchemaTestCase):
    def setUp(self):
        self.user_id = "forecast-" + uuid4().hex
        self.create_user(self.user_id)

    def create_user(self, user_id):
        with self.engine.begin() as conn:
            now = conn.scalar(select(func.clock_timestamp()))
            today = now.astimezone(timezone(timedelta(hours=9))).date()
            conn.execute(text("""INSERT INTO users(user_id,email,password_hash,display_name)
                VALUES (:id,:email,'test-only','생활비 결과 테스트')"""),
                         dict(id=user_id, email=user_id + "@example.invalid"))
            conn.execute(text("""INSERT INTO accounts(account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:id,:id,'생활비 통장',800000,:now)"""), dict(id=user_id, now=now))
            conn.execute(text("""INSERT INTO budget_settings
                (user_id,next_income_date,expected_income_amount,daily_living_budget)
                VALUES (:id,:income_date,1000000,20000)"""), dict(id=user_id, income_date=today + timedelta(days=20)))
            conn.execute(text("""INSERT INTO scheduled_expenses(user_id,title,amount,due_date)
                VALUES (:id,'월세',150000,:due_date)"""), dict(id=user_id, due_date=today + timedelta(days=5)))

    def snapshot(self, run_id="init:test"):
        with Session(self.engine) as db, db.begin():
            return ensure_budget_input_snapshot(db, user_id=self.user_id, run_id=run_id).id

    def ensure(self, db, snapshot_id, **overrides):
        arguments = dict(user_id=self.user_id, snapshot_id=snapshot_id)
        arguments.update(overrides)
        return ensure_budget_forecast(db, **arguments)

    def test_persists_forecast_and_matches_snapshot_summary(self):
        snapshot_id = self.snapshot()
        with Session(self.engine) as db, db.begin():
            self.ensure(db, snapshot_id)
        with Session(self.engine) as db:
            row = get_budget_forecast(db, user_id=self.user_id, snapshot_id=snapshot_id)
            snapshot = db.get(BudgetInputSnapshot, snapshot_id)
            self.assertEqual(row.remaining_days, 20)
            self.assertEqual(row.expected_living_cost, 400000)
            self.assertEqual(row.available_amount, 250000)
            self.assertEqual(row.shortage_amount, 0)
            self.assertIsNotNone(row.created_at)
            for field, value in asdict(calculate_forecast(snapshot)).items():
                self.assertEqual(getattr(row, field), value, field)

    def test_original_snapshot_is_used_after_current_data_changes(self):
        snapshot_id = self.snapshot()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET current_balance=500000,balance_as_of=clock_timestamp() WHERE user_id=:id"),
                         dict(id=self.user_id))
            conn.execute(text("UPDATE budget_settings SET daily_living_budget=30000 WHERE user_id=:id"), dict(id=self.user_id))
            conn.execute(text("UPDATE scheduled_expenses SET status='PAID' WHERE user_id=:id"), dict(id=self.user_id))
        with Session(self.engine) as db, db.begin():
            old = self.ensure(db, snapshot_id)
            self.assertEqual(old.current_balance, 800000)
            self.assertEqual(old.available_amount, 250000)
            snapshot = ensure_budget_input_snapshot(db, user_id=self.user_id, run_id="init:changed")
            new = self.ensure(db, snapshot.id)
            self.assertNotEqual(old.id, new.id)
            self.assertEqual(new.current_balance, 500000)
            self.assertEqual(new.expected_living_cost, 600000)
            self.assertEqual(new.scheduled_expense_total, 0)
            self.assertEqual(new.available_amount, -100000)
            self.assertEqual(new.shortage_amount, 100000)

    def test_same_snapshot_retry_preserves_result_and_created_at(self):
        snapshot_id = self.snapshot()
        with Session(self.engine) as db, db.begin():
            first = self.ensure(db, snapshot_id)
            identity = first.id, first.created_at
        with Session(self.engine) as db, db.begin():
            second = self.ensure(db, snapshot_id)
            self.assertEqual((second.id, second.created_at), identity)
            self.assertEqual(db.scalar(select(func.count()).select_from(BudgetForecast)
                                       .where(BudgetForecast.user_id == self.user_id)), 1)

    def test_same_snapshot_concurrent_requests_create_one_result(self):
        snapshot_id = self.snapshot()
        barrier = Barrier(2)

        def create(index):
            with Session(self.engine) as db, db.begin():
                barrier.wait(timeout=10)
                row = self.ensure(db, snapshot_id)
                return row.id, row.created_at

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (0, 1)))
        self.assertEqual(results[0], results[1])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(BudgetForecast)
                                       .where(BudgetForecast.snapshot_id == snapshot_id)), 1)

    def test_owner_is_enforced_for_create_and_read(self):
        snapshot_id = self.snapshot()
        other = "forecast-" + uuid4().hex
        self.create_user(other)
        with Session(self.engine) as db, db.begin():
            self.ensure(db, snapshot_id)
        with Session(self.engine) as db:
            with self.assertRaises(LookupError):
                self.ensure(db, snapshot_id, user_id=other)
            db.rollback()
            self.assertIsNone(get_budget_forecast(db, user_id=other, snapshot_id=snapshot_id))
            with self.assertRaises(LookupError):
                self.ensure(db, 2**63 - 1)
            db.rollback()
            with self.assertRaises(LookupError):
                self.ensure(db, snapshot_id, user_id="missing-user")
            db.rollback()

    def test_input_and_result_can_commit_or_roll_back_together(self):
        with Session(self.engine) as db:
            with self.assertRaisesRegex(RuntimeError, "later-step-failed"):
                with db.begin():
                    snapshot = ensure_budget_input_snapshot(db, user_id=self.user_id, run_id="init:atomic")
                    self.ensure(db, snapshot.id)
                    raise RuntimeError("later-step-failed")
        with Session(self.engine) as db, db.begin():
            for model in (BudgetInputSnapshot, BudgetForecast):
                self.assertEqual(db.scalar(select(func.count()).select_from(model).where(model.user_id == self.user_id)), 0)
            snapshot = ensure_budget_input_snapshot(db, user_id=self.user_id, run_id="init:atomic")
            self.assertEqual(self.ensure(db, snapshot.id).available_amount, 250000)

    def test_unsupported_version_is_not_recalculated_as_current_version(self):
        snapshot_id = self.snapshot()
        with Session(self.engine) as db, db.begin():
            source = db.get(BudgetInputSnapshot, snapshot_id)
            values = {column.name: getattr(source, column.name) for column in BudgetInputSnapshot.__table__.columns
                      if column.name != "id"}
            values["calculation_version"] = "budget-v0"
            old_id = db.scalar(insert(BudgetInputSnapshot).values(**values).returning(BudgetInputSnapshot.id))
        with Session(self.engine) as db:
            with self.assertRaisesRegex(ValueError, "버전"):
                self.ensure(db, old_id)
            db.rollback()
            self.assertIsNone(get_budget_forecast(db, user_id=self.user_id, snapshot_id=old_id))

    def test_real_ddl_rejects_summary_mismatch_and_result_updates(self):
        snapshot_id = self.snapshot()
        with Session(self.engine) as db:
            values = asdict(calculate_forecast(db.get(BudgetInputSnapshot, snapshot_id)))
            values["current_balance"] += 1
            values["available_amount"] += 1
            # 계산 식은 맞아도 입력 스냅샷과 잔액이 다르면 trigger가 거부해야 합니다.
            with self.assertRaises(DBAPIError):
                db.execute(insert(BudgetForecast).values(**values))
            db.rollback()
        with Session(self.engine) as db, db.begin():
            forecast_id = self.ensure(db, snapshot_id).id
        with Session(self.engine) as db:
            with self.assertRaises(DBAPIError):
                db.execute(update(BudgetForecast).where(BudgetForecast.id == forecast_id).values(available_amount=1))
            db.rollback()

    def test_invalid_identifiers_are_rejected_without_writes(self):
        for user_id, snapshot_id in ((" ", 1), ("x" * 101, 1), (self.user_id, 0),
                                     (self.user_id, True), (self.user_id, 2**63)):
            with self.subTest(user_id=user_id, snapshot_id=snapshot_id), Session(self.engine) as db:
                with self.assertRaises(ValueError):
                    ensure_budget_forecast(db, user_id=user_id, snapshot_id=snapshot_id)


if __name__ == "__main__":
    unittest.main()
