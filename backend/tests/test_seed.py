import hashlib
import os
import unittest
from collections import Counter
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.auth.passwords import verify_password
from app.recipients.service import list_recipients
from app.transactions.service import transaction_response
from app.transactions.models import Transaction

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class SeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["DEMO_TEST_DATABASE_URL"])
        self.schema = "seed_test_" + uuid4().hex
        with self.engine.begin() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.execute(CreateSchema(self.schema))
            for path in sorted((ROOT / "database/migrations").glob("V*__*.sql")):
                script = path.read_text(encoding="utf-8")
                script = script.replace("SET LOCAL search_path = public, pg_catalog;",
                                        f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')
                # V2 이후도 같은 테스트 스키마에 적용합니다.
                conn.exec_driver_sql(f'SET LOCAL search_path = "{self.schema}", public, pg_catalog')
                with conn.connection.driver_connection.cursor() as cursor:
                    cursor.execute(script, prepare=False)
        self.seed = (ROOT / "database/seeds/user1.sql").read_text(encoding="utf-8").replace(
            "SET LOCAL search_path = public, pg_catalog;",
            f'SET LOCAL search_path = "{self.schema}", public, pg_catalog;')

    def tearDown(self):
        assert self.schema.startswith("seed_test_") and len(self.schema) == 42
        with self.engine.begin() as conn:
            conn.execute(DropSchema(self.schema, cascade=True))
        self.engine.dispose()

    def execute_seed(self, script=None):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            with conn.connection.driver_connection.cursor() as cursor:
                try:
                    cursor.execute(script or self.seed, prepare=False)
                except Exception:
                    cursor.execute("ROLLBACK")
                    raise

    def rows(self, sql):
        with self.engine.begin() as conn:
            conn.exec_driver_sql(f'SET LOCAL search_path = "{self.schema}", public, pg_catalog')
            return conn.exec_driver_sql(sql).mappings().all()

    def change(self, sql):
        with self.engine.begin() as conn:
            conn.exec_driver_sql(f'SET LOCAL search_path = "{self.schema}", public, pg_catalog')
            conn.exec_driver_sql(sql)

    def test_initial_ledger_counts_dates_password_and_final_balance(self):
        self.execute_seed()
        rows = self.rows("SELECT * FROM transactions ORDER BY occurred_at,id")
        metadata = self.rows("SELECT * FROM demo_seed_metadata")[0]
        self.assertEqual(len(rows), 30)
        self.assertEqual(Counter(row["tx_type"] for row in rows), {"PURCHASE": 21, "TRANSFER": 8, "INCOME": 1})
        self.assertEqual(sum(row["description"].startswith("식비") for row in rows), 10)
        self.assertEqual(sum(row["description"].startswith("교통비") for row in rows), 7)
        self.assertEqual(sum(row["description"].startswith("소액 구매") for row in rows), 4)
        self.assertEqual(metadata["dataset_version"], "normal-v1")
        self.assertEqual(metadata["seed"], 42)
        balance = metadata["opening_balance"]
        for index, row in enumerate(rows, start=1):
            self.assertEqual(row["id"], f"seed:user1:normal-v1:{index:03d}")
            self.assertGreaterEqual(row["occurred_at"], metadata["as_of"] - timedelta(days=30))
            self.assertLess(row["occurred_at"], metadata["as_of"])
            balance += row["amount"] if row["direction"] == "IN" else -row["amount"]
            self.assertEqual(row["balance_after"], balance)
            self.assertGreaterEqual(balance, 0)
            self.assertEqual(row["scenario_label"], "NORMAL")
            self.assertEqual(row["source"], "SYNTHETIC")
        self.assertEqual(balance, 800000)
        self.assertEqual(self.rows("SELECT current_balance FROM accounts")[0]["current_balance"], balance)
        user = self.rows("SELECT * FROM users")[0]
        self.assertTrue(verify_password("demo1234!", user["password_hash"]))
        self.assertIsNone(user["monitoring_consented_at"])
        self.assertEqual(len(self.rows("SELECT * FROM budget_settings")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM scheduled_expenses")), 2)
        self.assertEqual(len(self.rows("SELECT * FROM alerts")), 0)
        self.assertEqual(len(self.rows("SELECT * FROM detections")), 0)

    def test_seed_is_deterministic_for_fixed_version_seed_and_as_of(self):
        fixed = self.seed.replace("v_as_of TIMESTAMPTZ := CURRENT_TIMESTAMP;",
                                  "v_as_of TIMESTAMPTZ := TIMESTAMPTZ '2026-10-20 15:01:00+00';")
        self.execute_seed(fixed)
        rows = self.rows("SELECT id,amount,occurred_at,balance_after FROM transactions ORDER BY id")
        # Python에서 seed=42 금액을 독립 계산해 SQL의 생성 규칙을 검증합니다.
        amounts = [8500,1800,12000,11000,15000,2200,9000,12500,1600,10500,14000,2400,8000,18000,13000,
                   1900,9500,16000,2100,1000000,25000,22000,12000,30000,24000,28000,11500,26000,2500,27000]
        for seq, row in enumerate(rows, start=1):
            delta = 0 if seq == 20 else 100 * (hashlib.md5(f"42:amount:{seq}".encode()).digest()[0] % 5)
            self.assertEqual(row["amount"], amounts[seq-1] + delta)
        self.execute_seed(fixed)
        self.assertEqual(rows, self.rows("SELECT id,amount,occurred_at,balance_after FROM transactions ORDER BY id"))

    def test_reexecution_preserves_new_transfer_settings_and_consent(self):
        self.execute_seed()
        self.change("""INSERT INTO transactions(id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type,source)
                       VALUES('demo-test','user1-account','user1',CURRENT_TIMESTAMP,'OUT',10000,790000,'TRANSFER','DEMO')""")
        self.change("UPDATE accounts SET current_balance=790000 WHERE account_id='user1-account'")
        self.change("UPDATE budget_settings SET daily_living_budget=7000")
        self.change("UPDATE users SET monitoring_consented_at=CURRENT_TIMESTAMP WHERE user_id='user1'")
        self.execute_seed()
        self.assertEqual(len(self.rows("SELECT * FROM transactions")), 31)
        self.assertEqual(self.rows("SELECT current_balance FROM accounts")[0]["current_balance"], 790000)
        self.assertEqual(self.rows("SELECT daily_living_budget FROM budget_settings")[0]["daily_living_budget"], 7000)
        self.assertIsNotNone(self.rows("SELECT monitoring_consented_at FROM users")[0]["monitoring_consented_at"])
        self.assertEqual(len(self.rows("SELECT * FROM scheduled_expenses")), 2)
        self.assertEqual(len(self.rows("SELECT * FROM demo_seed_metadata")), 1)

    def test_failure_rolls_back_new_user_account_settings_and_all_transactions(self):
        failing = self.seed.replace("INSERT INTO demo_seed_metadata", "RAISE EXCEPTION 'simulated seed failure';\n    INSERT INTO demo_seed_metadata")
        with self.assertRaises(Exception):
            self.execute_seed(failing)
        for table in ["users", "accounts", "budget_settings", "scheduled_expenses", "transactions", "demo_seed_metadata"]:
            self.assertEqual(len(self.rows(f"SELECT * FROM {table}")), 0)

    def test_preexisting_unseeded_transactions_are_not_overwritten(self):
        self.change("INSERT INTO users(user_id,email,password_hash,display_name) VALUES('user1','user1@example.invalid','hash','체험 사용자')")
        self.change("INSERT INTO accounts(account_id,user_id,display_name,current_balance,balance_as_of) VALUES('user1-account','user1','체험 통장',790000,CURRENT_TIMESTAMP)")
        self.change("""INSERT INTO transactions(id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type,source)
                       VALUES('demo-old','user1-account','user1',CURRENT_TIMESTAMP,'OUT',10000,790000,'TRANSFER','DEMO')""")
        with self.assertRaises(Exception):
            self.execute_seed()
        self.assertEqual(len(self.rows("SELECT * FROM transactions")), 1)
        self.assertEqual(self.rows("SELECT current_balance FROM accounts")[0]["current_balance"], 790000)
        self.assertEqual(len(self.rows("SELECT * FROM demo_seed_metadata")), 0)

    def test_recipient_history_is_scoped_and_evaluation_labels_are_not_exposed(self):
        self.execute_seed()
        mapped_engine = self.engine.execution_options(schema_translate_map={None: self.schema})
        with Session(mapped_engine) as db:
            recipients = list_recipients(db, "user1")
            self.assertEqual({r["id"] for r in recipients if r["familiar"]}, {f"demo-payee-{i}" for i in range(1,5)})
            self.assertEqual(len([r for r in recipients if not r["familiar"]]), 2)
            self.assertTrue(all(not r["familiar"] for r in list_recipients(db, "other-user")))
            transaction = db.scalar(select(Transaction))
            self.assertNotIn("scenario_label", transaction_response(transaction))
        counterparties = self.rows("SELECT counterparty_id,count(*) AS count FROM transactions WHERE tx_type='TRANSFER' GROUP BY counterparty_id")
        self.assertTrue(all(row["count"] == 2 for row in counterparties))
        self.change("""INSERT INTO transactions(id,account_id,user_id,occurred_at,direction,amount,balance_after,tx_type,counterparty_id,source)
                       VALUES('demo-new-recipient','user1-account','user1',CURRENT_TIMESTAMP,'OUT',1000,799000,'TRANSFER','demo-payee-5','DEMO')""")
        self.change("UPDATE accounts SET current_balance=799000 WHERE account_id='user1-account'")
        with Session(mapped_engine) as db:
            recipients = list_recipients(db, "user1")
            self.assertTrue(next(r for r in recipients if r["id"] == "demo-payee-5")["familiar"])
            self.assertFalse(next(r for r in recipients if r["id"] == "demo-payee-6")["familiar"])
