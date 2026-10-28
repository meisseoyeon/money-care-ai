import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ai.detection.service import run_transaction_detection
from app.ai.rag import guide_service
from app.ai.rag.fallback_guide import FALLBACK_STEPS
from app.ai.rag.generator import GuideLlmResult
from app.alerts.service import list_alerts
from app.core.config import DATABASE_URL

USER_ID = "test-guide-user"
CHUNK_ID = "test-guide-chunk"
CHUNK_TEXT = "피해가 생기면 즉시 경찰(112)이나 금융회사 콜센터에 연락하여 지급정지를 요청해야 한다."
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


def good_steps():
    return GuideLlmResult(
        steps=[
            {"instruction": "속은 것 같다면 경찰(112)에 연락해 봐요.", "sources": [1]},
            {"instruction": "금융회사 콜센터에도 연락해 봐요.", "sources": [1]},
            {"instruction": "보낸 돈을 멈춰 달라고 요청해요.", "sources": [1]},
        ],
        model="test-model", prompt_version="guide-test", latency_ms=5,
    )


@unittest.skipUnless(db_available(), "로컬 DB(5433)가 켜져 있어야 실행됨")
class GuideServiceTests(unittest.TestCase):
    """처음 보내는 사람에게 송금 → 알림 → 대응 안내. Gemini와 검색은 가짜로 바꾸고, 끝나면 rollback."""

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
        # 출처로 쓸 테스트 문서 1개, 문단 1개 (guide_citations가 실제 문단을 가리켜야 함)
        self.db.execute(text("""
            INSERT INTO documents (id, title, org, doc_type, url, document_version, content_hash, collected_at)
            VALUES ('test-guide-doc', '테스트 공식 문서', '테스트 기관', 'RESPONSE',
                    'https://example.com/guide-test', 'v1', :hash, :t)
        """), {"hash": "0" * 64, "t": NOW})
        self.db.execute(text("""
            INSERT INTO doc_chunks (id, document_id, chunk_index, content, content_hash, chunking_version,
                embedding_model, embedding_version)
            VALUES (:id, 'test-guide-doc', 0, :content, :hash, 'test', 'test', 'test')
        """), {"id": CHUNK_ID, "content": CHUNK_TEXT, "hash": "0" * 64})
        [self.alert_id] = run_transaction_detection(self.db, "tx-guide")
        self.chunks = [{"chunk_id": CHUNK_ID, "content": CHUNK_TEXT}]

    def tearDown(self):
        self.db.close()
        self.outer.rollback()
        self.conn.close()

    def _guide(self, *, chunks=None, llm=None, llm_error=None):
        with patch.object(guide_service, "retrieve_chunks", return_value=self.chunks if chunks is None else chunks), \
             patch.object(guide_service, "generate_rag_steps", return_value=llm, side_effect=llm_error):
            return guide_service.get_or_create_guide(self.db, USER_ID, self.alert_id)

    def _saved_error_code(self):
        return self.db.execute(text(
            "SELECT validation_error_code FROM alert_guides WHERE alert_id = CAST(:id AS uuid)"
        ), {"id": self.alert_id}).scalar_one()

    def test_rag_guide_saves_steps_and_citations(self):
        guide = self._guide(llm=good_steps())
        self.assertEqual(guide["method"], "RAG")
        self.assertEqual(guide["steps"][0], "속은 것 같다면 경찰(112)에 연락해 봐요.")
        self.assertEqual([c["title"] for c in guide["citations"]], ["테스트 공식 문서"])
        self.assertEqual(guide["citations"][0]["url"], "https://example.com/guide-test")

    def test_no_evidence_falls_back(self):
        guide = self._guide(chunks=[])
        self.assertEqual(guide["method"], "FALLBACK")
        self.assertEqual(guide["steps"], FALLBACK_STEPS["NEW_COUNTERPARTY"])
        self.assertEqual(guide["citations"], [])
        self.assertEqual(self._saved_error_code(), "NO_EVIDENCE")

    def test_llm_error_falls_back(self):
        guide = self._guide(llm_error=RuntimeError("quota"))
        self.assertEqual(guide["method"], "FALLBACK")
        self.assertEqual(self._saved_error_code(), "LLM_ERROR")

    def test_rejected_llm_steps_fall_back(self):
        too_few = good_steps()
        too_few.steps = too_few.steps[:2]
        guide = self._guide(llm=too_few)
        self.assertEqual(guide["method"], "FALLBACK")
        self.assertEqual(self._saved_error_code(), "STEP_COUNT")

    def test_second_request_returns_same_guide(self):
        first = self._guide(llm=good_steps())
        second = self._guide(llm_error=AssertionError("다시 만들면 안 됨"))
        self.assertEqual(first["id"], second["id"])

    def test_alert_list_includes_guide_after_creation(self):
        self.assertIsNone(list_alerts(self.db, USER_ID)[0]["guide"])
        self._guide(llm=good_steps())
        self.assertEqual(list_alerts(self.db, USER_ID)[0]["guide"]["method"], "RAG")

    def test_other_user_cannot_get_guide(self):
        self.assertIsNone(guide_service.get_or_create_guide(self.db, "someone-else", self.alert_id))


if __name__ == "__main__":
    unittest.main()
