"""실제 Flyway DDL을 적용한 별도 스키마에서 실행하는 PostgreSQL 테스트."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.baselines.models import UserBaseline
from app.baselines.calculator import calculate_baseline
from app.baselines.service import ensure_baseline, get_baseline

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class BaselineServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_engine = create_engine(os.environ["DEMO_TEST_DATABASE_URL"])
        cls.schema = "baseline_test_" + uuid4().hex
        with cls.base_engine.begin() as conn:
            conn.execute(CreateSchema(cls.schema))
        cls.addClassCleanup(cls.drop_schema)
        with cls.base_engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.exec_driver_sql(f'SET LOCAL search_path = "{cls.schema}", public, pg_catalog')
            migrations = sorted((ROOT / "database/migrations").glob("V*__*.sql"),
                                key=lambda path: int(path.name.split("__")[0][1:]))
            for path in migrations:
                sql = path.read_text(encoding="utf-8").replace(
                    "SET LOCAL search_path = public, pg_catalog;",
                    f'SET LOCAL search_path = "{cls.schema}", public, pg_catalog;')
                with conn.connection.driver_connection.cursor() as cursor:
                    cursor.execute(sql, prepare=False)
        # 기존 DDL의 trigger 내부 비한정 테이블 조회도 같은 테스트 스키마로 제한합니다.
        @event.listens_for(cls.base_engine, "checkout")
        def set_search_path(connection, record, proxy):
            previous = connection.autocommit
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET search_path = "{cls.schema}", public, pg_catalog')
            finally:
                connection.autocommit = previous
        cls.engine = cls.base_engine.execution_options(schema_translate_map={None: cls.schema})

    @classmethod
    def drop_schema(cls):
        assert cls.schema.startswith("baseline_test_") and len(cls.schema) == 46
        try:
            with cls.base_engine.begin() as conn:
                conn.execute(DropSchema(cls.schema, cascade=True))
        finally:
            cls.base_engine.dispose()

    def setUp(self):
        self.as_of = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
        self.user_id = "baseline-" + uuid4().hex
        self.create_user(self.user_id)

    def create_user(self, user_id):
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO users(user_id,email,password_hash,display_name)
                VALUES (:id,:email,'test-only','통계 테스트')"""),
                         {"id": user_id, "email": user_id + "@example.invalid"})
            conn.execute(text("""INSERT INTO accounts(account_id,user_id,display_name,current_balance,balance_as_of)
                VALUES (:id,:id,'테스트 계좌',800000,:as_of)"""), {"id": user_id, "as_of": self.as_of})

    def add_transaction(self, amount, *, user_id=None, occurred_at=None, direction="OUT"):
        user_id = user_id or self.user_id
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO transactions
                (id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type,source)
                VALUES (:id,:user_id,:user_id,:occurred_at,:direction,:amount,800000,:tx_type,'SYNTHETIC')"""),
                         dict(id=uuid4().hex, user_id=user_id, amount=amount, direction=direction,
                              occurred_at=occurred_at or self.as_of - timedelta(days=1),
                              tx_type="PURCHASE" if direction == "OUT" else "INCOME"))

    def ensure(self, db, **overrides):
        arguments = dict(user_id=self.user_id, as_of=self.as_of, run_id="init:test")
        arguments.update(overrides)
        return ensure_baseline(db, **arguments)

    def test_persists_exact_values_and_filtered_window(self):
        self.add_transaction(1000, occurred_at=self.as_of - timedelta(days=30))
        for amount in (2000, 3000, 4000):
            self.add_transaction(amount)
        self.add_transaction(9000, direction="IN")
        self.add_transaction(9000, occurred_at=self.as_of)
        self.add_transaction(9000, occurred_at=self.as_of - timedelta(days=30, microseconds=1))
        other = "baseline-" + uuid4().hex
        self.create_user(other)
        self.add_transaction(9000, user_id=other)
        with Session(self.engine) as db, db.begin():
            self.ensure(db)
        with Session(self.engine) as db:
            row = get_baseline(db, user_id=self.user_id, base_date=self.as_of.date())
            self.assertEqual(row.out_count_30d, 4)
            self.assertEqual(row.avg_out_amount, Decimal("2500.0000"))
            self.assertEqual(row.std_out_amount, Decimal("1290.9944"))
            self.assertEqual(row.p95_out_amount, Decimal("3850.0000"))
            self.assertEqual(row.avg_daily_spend, Decimal("333.3333"))
            self.assertEqual(row.as_of, self.as_of)
            self.assertEqual(row.window_start, self.as_of - timedelta(days=30))
            self.assertEqual(row.window_end, row.as_of)
            self.assertEqual(row.airflow_run_id, "init:test")
            self.assertIsNotNone(row.created_at)

    def test_same_day_preserves_first_input_and_run(self):
        self.add_transaction(1000)
        with Session(self.engine) as db, db.begin():
            self.ensure(db)
        self.add_transaction(9000)
        with Session(self.engine) as db, db.begin():
            row = self.ensure(db, as_of=self.as_of + timedelta(hours=1), run_id="airflow:retry")
            self.assertEqual(row.out_count_30d, 1)
            self.assertEqual(row.as_of, self.as_of)
            self.assertEqual(row.airflow_run_id, "init:test")
            count = db.scalar(select(func.count()).select_from(UserBaseline).where(UserBaseline.user_id == self.user_id))
            self.assertEqual(count, 1)

    def test_seoul_next_date_creates_new_row_and_version_lookup_is_exact(self):
        with Session(self.engine) as db, db.begin():
            first = self.ensure(db)
            second = self.ensure(db, as_of=self.as_of + timedelta(hours=14))
            self.assertEqual(first.base_date.isoformat(), "2026-10-21")
            self.assertEqual(second.base_date.isoformat(), "2026-10-22")
            self.assertIsNone(get_baseline(db, user_id=self.user_id, base_date=first.base_date,
                                          calculation_version="baseline-v0"))
            self.assertIsNone(get_baseline(db, user_id="someone-else", base_date=first.base_date))

    def test_zero_and_one_outflow_follow_real_ddl_null_constraints(self):
        with Session(self.engine) as db, db.begin():
            zero = self.ensure(db)
            self.assertEqual(zero.out_count_30d, 0)
            for field in ("avg_out_amount", "std_out_amount", "p95_out_amount", "avg_daily_spend"):
                self.assertIsNone(getattr(zero, field))
        self.add_transaction(3000)
        with Session(self.engine) as db, db.begin():
            one = self.ensure(db, as_of=self.as_of + timedelta(days=1))
            self.assertEqual(one.out_count_30d, 1)
            self.assertIsNone(one.std_out_amount)
            self.assertEqual(one.avg_daily_spend, Decimal("100.0000"))

    def test_new_calculation_version_does_not_reuse_old_version(self):
        from dataclasses import asdict

        values = asdict(calculate_baseline([], user_id=self.user_id, as_of=self.as_of))
        values["calculation_version"] = "baseline-v0"
        with Session(self.engine) as db, db.begin():
            db.execute(insert(UserBaseline).values(**values, airflow_run_id="init:old-version"))
        self.add_transaction(3000)
        with Session(self.engine) as db, db.begin():
            current = self.ensure(db)
            old = get_baseline(db, user_id=self.user_id, base_date=self.as_of.date(),
                               calculation_version="baseline-v0")
            self.assertEqual(current.calculation_version, "baseline-v1")
            self.assertEqual(current.out_count_30d, 1)
            self.assertEqual(old.out_count_30d, 0)

    def test_caller_can_roll_back_baseline_and_retry(self):
        with Session(self.engine) as db:
            self.ensure(db)
            db.rollback()
        with Session(self.engine) as db, db.begin():
            self.assertIsNone(get_baseline(db, user_id=self.user_id, base_date=self.as_of.date()))
            self.assertEqual(self.ensure(db).out_count_30d, 0)

    def test_concurrent_initializations_return_same_row(self):
        self.add_transaction(2000)
        barrier = Barrier(2)

        def initialize(index):
            with Session(self.engine) as db, db.begin():
                barrier.wait(timeout=10)
                row = self.ensure(db, as_of=self.as_of + timedelta(minutes=index), run_id=f"init:{index}")
                return row.as_of, row.airflow_run_id, row.out_count_30d

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(initialize, (0, 1)))
        self.assertEqual(results[0], results[1])
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(UserBaseline)
                                       .where(UserBaseline.user_id == self.user_id)), 1)

    def test_invalid_inputs_and_unknown_user_do_not_create_rows(self):
        for overrides, error in (({"run_id": " "}, ValueError), ({"run_id": "x" * 251}, ValueError),
                                 ({"as_of": self.as_of.replace(tzinfo=None)}, ValueError),
                                 ({"user_id": "missing-user"}, LookupError)):
            with self.subTest(overrides=overrides), Session(self.engine) as db:
                with self.assertRaises(error):
                    self.ensure(db, **overrides)
                db.rollback()
        with Session(self.engine) as db:
            self.assertIsNone(get_baseline(db, user_id=self.user_id, base_date=self.as_of.date()))

    def test_existing_ddl_rejects_overwriting_results(self):
        with Session(self.engine) as db, db.begin():
            self.ensure(db)
        with Session(self.engine) as db:
            with self.assertRaises(DBAPIError):
                db.execute(update(UserBaseline).where(UserBaseline.user_id == self.user_id)
                           .values(airflow_run_id="overwrite"))
            db.rollback()


if __name__ == "__main__":
    unittest.main()
