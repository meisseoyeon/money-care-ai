import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai.detection.service import run_transaction_detection
from app.core.config import DATABASE_URL

USER_ID = "test-detection-user"
ACCOUNT_ID = "test-detection-account"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

# 실제 로컬 DB(backend/.env의 DATABASE_URL)에 접속. 테스트가 끝나면 rollback으로 되돌림.
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
class DetectionServiceTests(unittest.TestCase):
    """실제 DB에 테스트 데이터를 넣고 탐지를 돌린 뒤, 끝나면 전부 되돌림(rollback)."""

    def setUp(self):
        # 바깥 트랜잭션을 열고, 서비스의 commit()은 SAVEPOINT로만 처리되게 함.
        # → 테스트가 끝나면 rollback으로 DB가 원래대로 돌아감.
        self.conn = engine.connect()
        self.outer = self.conn.begin()
        self.db = Session(bind=self.conn, join_transaction_mode="create_savepoint")
        self._insert_base_data()

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.conn.close()

    # ---------- 테스트 데이터 ----------

    def _insert_base_data(self):
        self.db.execute(text("""
            INSERT INTO users (user_id, email, password_hash, display_name, monitoring_consented_at)
            VALUES (:u, 'detect-test@example.com', 'x', '테스트', :now)
        """), {"u": USER_ID, "now": NOW - timedelta(days=40)})
        self.db.execute(text("""
            INSERT INTO accounts (account_id, user_id, display_name, current_balance, balance_as_of)
            VALUES (:a, :u, '생활비 통장', 800000, :now)
        """), {"a": ACCOUNT_ID, "u": USER_ID, "now": NOW})
        # 예전에 'friend'에게 3만원 보낸 기록 → friend는 "아는 상대"
        self._insert_tx("past-1", "friend", 30000, NOW - timedelta(days=5))
        # 평소 지출 기준: p95 = 50,000원
        self.db.execute(text("""
            INSERT INTO user_baselines (base_date, user_id, calculation_version, as_of,
                window_start, window_end, out_count_30d, avg_out_amount, std_out_amount,
                p95_out_amount, avg_daily_spend, airflow_run_id)
            VALUES ((CAST(:as_of AS timestamptz) AT TIME ZONE 'Asia/Seoul')::date, :u, 'test-v1', :as_of,
                CAST(:as_of AS timestamptz) - INTERVAL '30 days', :as_of, 10, 20000, 10000,
                50000, 6000, 'test-run')
        """), {"u": USER_ID, "as_of": NOW - timedelta(hours=1)})
        self.db.flush()

    def _insert_tx(self, tx_id, counterparty_id, amount, occurred_at, direction="OUT"):
        self.db.execute(text("""
            INSERT INTO transactions (id, account_id, user_id, occurred_at, direction, amount,
                balance_after, tx_type, counterparty_id, source)
            VALUES (:id, :a, :u, :t, :dir, :amount, 0, 'TRANSFER', :cp, 'DEMO')
        """), {"id": tx_id, "a": ACCOUNT_ID, "u": USER_ID, "t": occurred_at,
               "dir": direction, "amount": amount, "cp": counterparty_id})

    def _detection_types(self, tx_id):
        return set(self.db.execute(text(
            "SELECT detection_type FROM detections WHERE transaction_id = :id"
        ), {"id": tx_id}).scalars())

    def _alert(self, alert_id):
        return self.db.execute(text(
            "SELECT alert_type, status FROM alerts WHERE id = CAST(:id AS uuid)"
        ), {"id": alert_id}).mappings().one()

    # ---------- 테스트 ----------

    def test_known_counterparty_small_amount_makes_no_alert(self):
        self._insert_tx("tx-normal", "friend", 20000, NOW)
        self.assertEqual(run_transaction_detection(self.db, "tx-normal"), [])

    def test_new_counterparty_makes_alert(self):
        self._insert_tx("tx-new", "stranger", 20000, NOW)
        alert_ids = run_transaction_detection(self.db, "tx-new")
        self.assertEqual(len(alert_ids), 1)
        self.assertEqual(self._alert(alert_ids[0])["alert_type"], "NEW_COUNTERPARTY")
        self.assertEqual(self._detection_types("tx-new"), {"NEW_COUNTERPARTY"})
        # 설명이 저장됐고, 금액이 근거 값 그대로 문장에 들어갔는지
        explanation = self.db.execute(text(
            "SELECT text FROM alert_explanations WHERE alert_id = CAST(:id AS uuid)"
        ), {"id": alert_ids[0]}).scalar_one()
        self.assertIn("20,000원", explanation)

    def test_large_amount_makes_alert(self):
        self._insert_tx("tx-large", "friend", 300000, NOW)
        alert_ids = run_transaction_detection(self.db, "tx-large")
        self.assertEqual(self._alert(alert_ids[0])["alert_type"], "LARGE_OUTFLOW")

    def test_new_and_large_makes_one_alert_with_two_detections(self):
        self._insert_tx("tx-both", "stranger", 300000, NOW)
        alert_ids = run_transaction_detection(self.db, "tx-both")
        self.assertEqual(len(alert_ids), 1)
        self.assertEqual(self._alert(alert_ids[0])["alert_type"], "LARGE_OUTFLOW")
        self.assertEqual(self._detection_types("tx-both"), {"NEW_COUNTERPARTY", "LARGE_OUTFLOW"})

    def test_running_twice_does_not_duplicate(self):
        self._insert_tx("tx-twice", "stranger", 20000, NOW)
        first = run_transaction_detection(self.db, "tx-twice")
        second = run_transaction_detection(self.db, "tx-twice")
        self.assertEqual(first, second)

    def test_no_consent_makes_no_alert(self):
        self.db.execute(text(
            "UPDATE users SET monitoring_revoked_at = :t WHERE user_id = :u"
        ), {"t": NOW - timedelta(days=1), "u": USER_ID})
        self._insert_tx("tx-revoked", "stranger", 300000, NOW)
        self.assertEqual(run_transaction_detection(self.db, "tx-revoked"), [])

    def test_incoming_money_is_not_checked(self):
        self.db.execute(text("""
            INSERT INTO transactions (id, account_id, user_id, occurred_at, direction, amount,
                balance_after, tx_type, counterparty_id, source)
            VALUES ('tx-in', :a, :u, :t, 'IN', 300000, 0, 'DEPOSIT', 'stranger', 'DEMO')
        """), {"a": ACCOUNT_ID, "u": USER_ID, "t": NOW})
        self.assertEqual(run_transaction_detection(self.db, "tx-in"), [])


if __name__ == "__main__":
    unittest.main()
