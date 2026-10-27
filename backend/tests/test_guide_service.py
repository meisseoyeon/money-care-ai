import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai.detection.service import run_transaction_detection
from app.ai.rag.fallback_guide import FALLBACK_STEPS
from app.ai.rag.guide_service import get_or_create_guide
from app.alerts.service import list_alerts
from app.core.config import DATABASE_URL

USER_ID = "test-guide-user"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5}) if DATABASE_URL else None


def db_available() -> bool:
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@unittest.skipUnless(db_available(), "로컬 DB(5433)가 켜져 있어야 실행됨")
class GuideServiceTests(unittest.TestCase):
    """처음 보내는 사람에게 송금 → 알림 생성 → 대응 안내 요청. 끝나면 rollback."""

    def setUp(self):
        self.conn = engine.connect()
        self.outer = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint")
        self.db.execute(text("""
            INSERT INTO users (user_id, email, password_hash, display_name, monitoring_consented_at)
            VALUES (:u, 'guide-test@example.com', 'x', '테스트', :t)
        """), {"u": USER_ID, "t": NOW - timedelta(days=40)})
        self.db.execute(text("""
            INSERT INTO accounts (account_id, user_id, display_name, current_balance, balance_as_of)
            VALUES ('test-guide-account', :u, '생활비 통장', 800000, :t)
        """), {"u": USER_ID, "t": NOW})
        self.db.execute(text("""
            INSERT INTO transactions (id, account_id, user_id, occurred_at, direction, amount,
                balance_after, tx_type, counterparty_id, source)
            VALUES ('tx-guide', 'test-guide-account', :u, :t, 'OUT', 20000, 0, 'TRANSFER', 'stranger', 'DEMO')
        """), {"u": USER_ID, "t": NOW})
        [self.alert_id] = run_transaction_detection(self.db, "tx-guide")

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.conn.close()

    def test_creates_fallback_guide_with_steps_in_order(self):
        guide = get_or_create_guide(self.db, USER_ID, self.alert_id)
        self.assertEqual(guide["method"], "FALLBACK")
        self.assertEqual(guide["steps"], FALLBACK_STEPS["NEW_COUNTERPARTY"])
        self.assertEqual(guide["citations"], [])

    def test_second_request_returns_same_guide(self):
        first = get_or_create_guide(self.db, USER_ID, self.alert_id)
        second = get_or_create_guide(self.db, USER_ID, self.alert_id)
        self.assertEqual(first["id"], second["id"])
        count = self.db.execute(text(
            "SELECT count(*) FROM alert_guides WHERE alert_id = CAST(:id AS uuid)"
        ), {"id": self.alert_id}).scalar_one()
        self.assertEqual(count, 1)

    def test_alert_list_includes_guide_after_creation(self):
        self.assertIsNone(list_alerts(self.db, USER_ID)[0]["guide"])
        get_or_create_guide(self.db, USER_ID, self.alert_id)
        self.assertEqual(list_alerts(self.db, USER_ID)[0]["guide"]["method"], "FALLBACK")

    def test_other_user_cannot_get_guide(self):
        self.assertIsNone(get_or_create_guide(self.db, "someone-else", self.alert_id))


if __name__ == "__main__":
    unittest.main()
