import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from threading import Barrier, Event
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.budgets.models import BudgetInputSnapshot, BudgetSetting
from app.budgets.snapshots import ensure_budget_input_snapshot, get_budget_input_snapshot
from tests.postgres_support import PostgresSchemaTestCase


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class BudgetSnapshotTests(PostgresSchemaTestCase):
    def setUp(self):
        self.user_id = "budget-" + uuid4().hex
        with self.engine.begin() as conn:
            self.now = conn.scalar(select(func.clock_timestamp()))
        self.today = self.now.astimezone(timezone(timedelta(hours=9))).date()
        self.create_user(self.user_id)

    def create_user(self, user_id):
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO users(user_id,email,password_hash,display_name)
                VALUES (:id,:email,'test-only','생활비 테스트')"""),
                         dict(id=user_id, email=user_id + "@example.invalid"))
            conn.execute(text("""INSERT INTO accounts
                (account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:id,:id,'생활비 통장',800000,:now)"""), dict(id=user_id, now=self.now))
            conn.execute(text("""INSERT INTO budget_settings
                (user_id,next_income_date,expected_income_amount,daily_living_budget)
                VALUES (:id,:income_date,1000000,20000)"""),
                         dict(id=user_id, income_date=self.today + timedelta(days=20)))

    def expense(self, amount=150000, *, days=5, status="PLANNED", user_id=None):
        with self.engine.begin() as conn:
            return conn.scalar(text("""INSERT INTO scheduled_expenses(user_id,title,amount,due_date,status)
                VALUES (:user_id,'예정 지출',:amount,:due_date,:status) RETURNING id"""),
                               dict(user_id=user_id or self.user_id, amount=amount,
                                    due_date=self.today + timedelta(days=days), status=status))

    def capture(self, db, **overrides):
        arguments = dict(user_id=self.user_id, run_id="init:test")
        arguments.update(overrides)
        return ensure_budget_input_snapshot(db, **arguments)

    def test_saves_complete_inputs_and_json_and_exact_lookup(self):
        expense_id = self.expense()
        with Session(self.engine) as db, db.begin():
            row = self.capture(db)
            as_of = row.as_of
            snapshot_id = row.id
        with Session(self.engine) as db:
            row = get_budget_input_snapshot(db, user_id=self.user_id, as_of=as_of)
            self.assertEqual(row.id, snapshot_id)
            self.assertEqual(row.current_balance, 800000)
            self.assertEqual(row.next_income_date, self.today + timedelta(days=20))
            self.assertEqual(row.expected_income_amount, 1000000)
            self.assertEqual(row.daily_living_budget, 20000)
            self.assertEqual(row.scheduled_expense_total, 150000)
            self.assertEqual(row.balance_as_of, self.now)
            self.assertEqual(row.accounts_snapshot, [dict(account_id=self.user_id, current_balance=800000,
                                                         balance_as_of=self.now.isoformat())])
            self.assertEqual(row.expenses_snapshot, [dict(id=expense_id, amount=150000,
                                                         due_date=(self.today + timedelta(days=5)).isoformat(), status="PLANNED")])
            self.assertEqual(row.calculation_version, "budget-v1")
            self.assertEqual(row.airflow_run_id, "init:test")
            self.assertEqual(row.captured_at, row.as_of)
            self.assertGreaterEqual(row.as_of, self.now)
            self.assertIsNone(get_budget_input_snapshot(db, user_id="other", as_of=as_of))
            self.assertIsNone(get_budget_input_snapshot(db, user_id=self.user_id, as_of=as_of,
                                                       calculation_version="budget-v0"))
            self.assertIsNone(get_budget_input_snapshot(db, user_id=self.user_id, as_of=as_of - timedelta(days=1)))

    def test_filters_paid_cancelled_overdue_income_day_and_other_user(self):
        self.expense(100, days=0)
        self.expense(200, days=19)
        self.expense(1000, days=-1)
        self.expense(1000, days=20)
        self.expense(1000, days=21)
        self.expense(1000, status="PAID")
        self.expense(1000, status="CANCELLED")
        other = "budget-" + uuid4().hex
        self.create_user(other)
        self.expense(1000, user_id=other)
        with Session(self.engine) as db, db.begin():
            row = self.capture(db)
            self.assertEqual(row.scheduled_expense_total, 300)
            self.assertEqual(len(row.expenses_snapshot), 2)
            self.assertEqual(len(row.accounts_snapshot), 1)

    def test_multiple_accounts_sum_balance_and_use_oldest_balance_time(self):
        old_time = self.now - timedelta(days=2)
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO accounts
                (account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:account_id,:user_id,'다른 통장',-10000,:old_time)"""),
                         dict(account_id=self.user_id + "-2", user_id=self.user_id, old_time=old_time))
        with Session(self.engine) as db, db.begin():
            row = self.capture(db)
            self.assertEqual(row.current_balance, 790000)
            self.assertEqual(row.balance_as_of, old_time)
            self.assertEqual(len(row.accounts_snapshot), 2)
            self.assertEqual(sum(a["current_balance"] for a in row.accounts_snapshot), row.current_balance)

    def test_same_run_reuses_frozen_inputs_new_run_captures_changes(self):
        expense_id = self.expense()
        with Session(self.engine) as db, db.begin():
            first = self.capture(db)
            first_id, first_as_of = first.id, first.as_of
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE accounts SET current_balance=700000,balance_as_of=clock_timestamp() WHERE user_id=:id"),
                         dict(id=self.user_id))
            conn.execute(text("UPDATE budget_settings SET daily_living_budget=30000 WHERE user_id=:id"), dict(id=self.user_id))
            conn.execute(text("UPDATE scheduled_expenses SET status='PAID' WHERE id=:id"), dict(id=expense_id))
        with Session(self.engine) as db, db.begin():
            retry = self.capture(db)
            self.assertEqual((retry.id, retry.as_of, retry.current_balance, retry.scheduled_expense_total),
                             (first_id, first_as_of, 800000, 150000))
            self.assertEqual(retry.daily_living_budget, 20000)
            changed = self.capture(db, run_id="init:new-input")
            self.assertNotEqual(changed.id, first_id)
            self.assertEqual(changed.current_balance, 700000)
            self.assertEqual(changed.daily_living_budget, 30000)
            self.assertEqual(changed.scheduled_expense_total, 0)
            self.assertEqual(changed.expenses_snapshot, [])

    def test_no_expenses_and_income_today_are_allowed(self):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE budget_settings SET next_income_date=:today WHERE user_id=:id"),
                         dict(today=self.today, id=self.user_id))
        self.expense(days=0)
        with Session(self.engine) as db, db.begin():
            row = self.capture(db)
            self.assertEqual(row.scheduled_expense_total, 0)
            self.assertEqual(row.expenses_snapshot, [])

    def test_missing_accounts_settings_and_expired_income_leave_no_snapshot(self):
        for problem in ("account", "settings", "income_date"):
            user_id = "budget-" + uuid4().hex
            self.create_user(user_id)
            with self.engine.begin() as conn:
                if problem == "account":
                    conn.execute(text("DELETE FROM accounts WHERE user_id=:id"), dict(id=user_id))
                elif problem == "settings":
                    conn.execute(text("DELETE FROM budget_settings WHERE user_id=:id"), dict(id=user_id))
                else:
                    conn.execute(text("UPDATE budget_settings SET next_income_date=:past WHERE user_id=:id"),
                                 dict(id=user_id, past=self.today - timedelta(days=1)))
            with self.subTest(problem=problem), Session(self.engine) as db:
                with self.assertRaises(ValueError):
                    self.capture(db, user_id=user_id)
                db.rollback()
                self.assertEqual(db.scalar(select(func.count()).select_from(BudgetInputSnapshot)
                                           .where(BudgetInputSnapshot.user_id == user_id)), 0)

    def test_future_input_time_is_rejected_even_when_oldest_account_is_valid(self):
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO accounts
                (account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:account_id,:id,'미래 통장',1000,clock_timestamp()+interval '1 day')"""),
                         dict(account_id=self.user_id + "-future", id=self.user_id))
        with Session(self.engine) as db:
            with self.assertRaises(ValueError):
                self.capture(db)
            db.rollback()

    def test_caller_rollback_undoes_snapshot(self):
        with Session(self.engine) as db:
            first_id = self.capture(db).id
            db.rollback()
        with Session(self.engine) as db, db.begin():
            row = self.capture(db)
            self.assertNotEqual(row.id, first_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(BudgetInputSnapshot)
                                       .where(BudgetInputSnapshot.user_id == self.user_id)), 1)

    def test_concurrent_same_run_creates_one_snapshot(self):
        barrier = Barrier(2)

        def capture(index):
            with Session(self.engine) as db, db.begin():
                barrier.wait(timeout=10)
                row = self.capture(db)
                return row.id, row.as_of

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(capture, (0, 1)))
        self.assertEqual(results[0], results[1])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(BudgetInputSnapshot)
                                       .where(BudgetInputSnapshot.user_id == self.user_id)), 1)

    def test_waits_for_transfer_then_captures_committed_balance(self):
        locked = Event()
        capture_started = Event()
        release = Event()

        def transfer():
            with self.engine.begin() as conn:
                conn.execute(text("SELECT user_id FROM users WHERE user_id=:id FOR UPDATE"), dict(id=self.user_id))
                conn.execute(text("UPDATE accounts SET current_balance=600000,balance_as_of=clock_timestamp() WHERE user_id=:id"),
                             dict(id=self.user_id))
                locked.set()
                if not release.wait(10):
                    raise TimeoutError("테스트 송금 잠금 해제 시간 초과")

        def capture():
            if not locked.wait(10):
                raise TimeoutError("테스트 송금 시작 시간 초과")
            capture_started.set()
            with Session(self.engine) as db, db.begin():
                row = self.capture(db)
                return row.current_balance, row.balance_as_of, row.as_of

        with ThreadPoolExecutor(max_workers=2) as pool:
            transfer_future = pool.submit(transfer)
            capture_future = pool.submit(capture)
            try:
                self.assertTrue(capture_started.wait(10))
                # 송금이 사용자 잠금을 유지하므로 스냅샷은 먼저 완료될 수 없습니다.
                self.assertFalse(capture_future.done())
            finally:
                release.set()
            transfer_future.result(timeout=10)
            balance, balance_as_of, as_of = capture_future.result(timeout=10)
        self.assertEqual(balance, 600000)
        self.assertLessEqual(balance_as_of, as_of)

    def test_uses_fresh_database_values_instead_of_cached_setting(self):
        with Session(self.engine) as db:
            cached = db.get(BudgetSetting, self.user_id)
            with self.engine.begin() as conn:
                conn.execute(text("UPDATE budget_settings SET daily_living_budget=25000 WHERE user_id=:id"), dict(id=self.user_id))
            self.assertEqual(cached.daily_living_budget, 20000)
            self.assertEqual(self.capture(db).daily_living_budget, 25000)
            db.rollback()

    def test_existing_ddl_blocks_snapshot_updates(self):
        with Session(self.engine) as db, db.begin():
            snapshot_id = self.capture(db).id
        with Session(self.engine) as db:
            with self.assertRaises(DBAPIError):
                db.execute(update(BudgetInputSnapshot).where(BudgetInputSnapshot.id == snapshot_id)
                           .values(current_balance=1))
            db.rollback()

    def test_invalid_identifiers_unknown_user_and_naive_query_time(self):
        for overrides in (dict(user_id=" "), dict(user_id="x" * 101), dict(run_id=" "), dict(run_id="x" * 251)):
            with self.subTest(overrides=overrides), Session(self.engine) as db:
                with self.assertRaises(ValueError):
                    self.capture(db, **overrides)
        with Session(self.engine) as db:
            with self.assertRaises(LookupError):
                self.capture(db, user_id="missing")
            db.rollback()
            with self.assertRaises(ValueError):
                get_budget_input_snapshot(db, user_id=self.user_id, as_of=self.now.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
