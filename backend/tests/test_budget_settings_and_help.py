import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai.rag import guide_service
from app.ai.rag.fallback_guide import FALLBACK_STEPS
from app.alerts.service import list_alerts
from app.budgets import settings as budget_settings
from app.budgets.queries import current_budget_forecast
from app.budgets.schemas import BudgetSettingsUpdate, ExpenseSave
from app.core.config import DATABASE_URL
from app.supporters.service import list_shared_alerts
from app.transactions.help import create_transfer_help
from app.transactions.schemas import TransferCreate

OWNER = "test-budget-owner"
SUPPORTER = "test-budget-supporter"
ACCOUNT = "test-budget-account"
PAYEE = "demo-payee-1"
SEOUL = timezone(timedelta(hours=9))

engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5}) if DATABASE_URL else None


def db_available() -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT to_regclass('alert_shares') IS NOT NULL")).scalar_one()
    except Exception:
        return False


def today():
    return datetime.now(SEOUL).date()


@unittest.skipUnless(db_available(), "로컬 DB(5433)가 켜져 있어야 실행됨")
class DbTestCase(unittest.TestCase):
    """실제 DB 제약으로 확인하고, 끝나면 rollback으로 되돌림."""

    def setUp(self):
        self.conn = engine.connect()
        self.outer = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        now = datetime.now(timezone.utc)
        for user_id, consent in ((OWNER, now - timedelta(days=1)), (SUPPORTER, None)):
            self.db.execute(text("""
                INSERT INTO users (user_id, email, password_hash, display_name, monitoring_consented_at)
                VALUES (:u, :email, 'x', :u, :consent)
            """), {"u": user_id, "email": f"{user_id}@example.com", "consent": consent})
        self.db.execute(text("""
            INSERT INTO accounts (account_id, user_id, display_name, current_balance, balance_as_of)
            VALUES (:a, :u, '생활비 통장', 800000, :t)
        """), {"a": ACCOUNT, "u": OWNER, "t": now - timedelta(minutes=1)})
        self.db.execute(text("""
            INSERT INTO budget_settings (user_id, next_income_date, expected_income_amount, daily_living_budget, updated_at)
            VALUES (:u, :d, 1000000, 20000, :t)
        """), {"u": OWNER, "d": today() + timedelta(days=20), "t": now - timedelta(minutes=1)})
        self.db.commit()
        self.principal = SimpleNamespace(user=SimpleNamespace(user_id=OWNER))

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.conn.close()

    def link_supporter(self):
        self.db.execute(text("""
            INSERT INTO supporter_links (owner_user_id, supporter_user_id, status, accepted_at)
            VALUES (:o, :s, 'ACTIVE', CURRENT_TIMESTAMP)
        """), {"o": OWNER, "s": SUPPORTER})
        self.db.commit()

    def count(self, table):
        return self.db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": OWNER}).scalar_one()


class BudgetSettingsTests(DbTestCase):
    def settings(self, days=10, budget=30000):
        return BudgetSettingsUpdate(next_income_date=today() + timedelta(days=days),
                                    expected_income_amount=500000, daily_living_budget=budget)

    def expense(self, amount=70000, status="PLANNED", days=3):
        return ExpenseSave(title=" 통신비 ", amount=amount, due_date=today() + timedelta(days=days), status=status)

    def test_save_settings_recalculates_forecast_so_transfers_stay_ready(self):
        budget_settings.save_settings(self.db, OWNER, self.settings())
        forecast = current_budget_forecast(self.db, user_id=OWNER)  # 입력과 다르면 409가 남
        self.assertEqual(forecast.daily_living_budget, 30000)
        self.assertEqual(forecast.remaining_days, 10)
        self.assertEqual(forecast.available_amount, 800000 - 300000)

    def test_past_income_date_is_rejected_without_change(self):
        with self.assertRaises(HTTPException) as caught:
            budget_settings.save_settings(self.db, OWNER, self.settings(days=-1))
        self.assertEqual(caught.exception.status_code, 422)
        stored = self.db.execute(text("SELECT daily_living_budget FROM budget_settings WHERE user_id = :u"),
                                 {"u": OWNER}).scalar_one()
        self.assertEqual(stored, 20000)

    def test_supporter_cannot_edit(self):
        with self.assertRaises(HTTPException) as caught:
            budget_settings.save_settings(self.db, "supporter1", self.settings())
        self.assertEqual(caught.exception.status_code, 403)

    def test_expense_create_and_cancel_change_forecast(self):
        created = budget_settings.create_expense(self.db, OWNER, self.expense())
        self.assertEqual(created["title"], "통신비")
        self.assertEqual(current_budget_forecast(self.db, user_id=OWNER).scheduled_expense_total, 70000)
        budget_settings.update_expense(self.db, OWNER, int(created["id"]), self.expense(status="CANCELLED"))
        self.assertEqual(current_budget_forecast(self.db, user_id=OWNER).scheduled_expense_total, 0)

    def test_other_users_expense_is_not_found(self):
        created = budget_settings.create_expense(self.db, OWNER, self.expense())
        with self.assertRaises(HTTPException) as caught:
            budget_settings.update_expense(self.db, "someone-else", int(created["id"]), self.expense())
        self.assertEqual(caught.exception.status_code, 404)


class TransferHelpTests(DbTestCase):
    def payload(self, request_id=None, amount=50000):
        return TransferCreate(request_id=request_id or uuid4(), counterparty_id=PAYEE, amount=amount)

    def test_help_creates_answered_alert_and_share_without_sending_money(self):
        self.link_supporter()
        result = create_transfer_help(self.db, self.principal, self.payload())
        alert = list_alerts(self.db, OWNER)[0]
        self.assertEqual(alert["id"], result["alert_id"])
        self.assertEqual(alert["alert_type"], "TRANSFER_HELP")
        self.assertEqual(alert["status"], "ANSWERED")
        self.assertEqual(alert["user_response"], "HELP_REQUESTED")
        self.assertEqual(alert["evidence"]["stage"], "BEFORE_TRANSFER")
        self.assertEqual(alert["evidence"]["amount"], 50000)
        self.assertIn("50,000원", alert["explanation"])
        self.assertEqual(self.count("transactions"), 0)
        balance = self.db.execute(text("SELECT current_balance FROM accounts WHERE user_id = :u"),
                                  {"u": OWNER}).scalar_one()
        self.assertEqual(balance, 800000)
        shared = list_shared_alerts(self.db, SUPPORTER)
        self.assertEqual([s["alert_id"] for s in shared], [result["alert_id"]])
        self.assertEqual(shared[0]["amount"], 50000)

    def test_retry_returns_same_result_and_changed_body_conflicts(self):
        self.link_supporter()
        request_id = uuid4()
        first = create_transfer_help(self.db, self.principal, self.payload(request_id))
        again = create_transfer_help(self.db, self.principal, self.payload(request_id))
        self.assertEqual(first, again)
        self.assertEqual(self.count("alerts"), 1)
        with self.assertRaises(HTTPException) as caught:
            create_transfer_help(self.db, self.principal, self.payload(request_id, amount=60000))
        self.assertEqual(caught.exception.status_code, 409)

    def test_without_supporter_nothing_is_saved(self):
        with self.assertRaises(HTTPException) as caught:
            create_transfer_help(self.db, self.principal, self.payload())
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.count("alerts"), 0)
        self.assertEqual(self.count("detections"), 0)

    def test_amount_over_balance_is_rejected(self):
        self.link_supporter()
        with self.assertRaises(HTTPException) as caught:
            create_transfer_help(self.db, self.principal, self.payload(amount=900000))
        self.assertEqual(caught.exception.status_code, 409)

    def test_guide_uses_fixed_steps_without_calling_gemini(self):
        self.link_supporter()
        result = create_transfer_help(self.db, self.principal, self.payload())
        guide = guide_service.get_or_create_guide(self.db, OWNER, result["alert_id"])
        self.assertEqual(guide["method"], "FALLBACK")
        self.assertEqual(guide["steps"], FALLBACK_STEPS["TRANSFER_HELP"])


if __name__ == "__main__":
    unittest.main()
