import importlib.util
import math
import unittest
from datetime import datetime, timedelta, timezone

HAS_SKLEARN = importlib.util.find_spec("sklearn") is not None


@unittest.skipUnless(HAS_SKLEARN, "평가용 패키지(requirements-eval.txt)가 설치돼 있어야 실행됨")
class IsolationForestFeatureTests(unittest.TestCase):
    def test_features_are_log_amount_and_new_flag(self):
        from app.ai.detection.iforest_evaluate import make_features
        self.assertEqual(make_features(9999, True), [math.log1p(9999), 1.0])
        self.assertEqual(make_features(20000, False), [math.log1p(20000), 0.0])

    def test_history_marks_first_time_counterparty_in_time_order(self):
        from app.ai.detection.iforest_evaluate import history_features
        t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
        history = [
            {"occurred_at": t0 + timedelta(days=2), "direction": "OUT", "amount": 20000, "counterparty_id": "friend"},
            {"occurred_at": t0, "direction": "OUT", "amount": 10000, "counterparty_id": "friend"},
            {"occurred_at": t0 + timedelta(days=1), "direction": "IN", "amount": 50000, "counterparty_id": None},
            {"occurred_at": t0 + timedelta(days=3), "direction": "OUT", "amount": 3000, "counterparty_id": None},
        ]
        rows = history_features(history)
        # 입금은 빼고, friend는 처음(10/1)만 새 상대, 상대 없는 결제는 새 상대 아님
        self.assertEqual([r[1] for r in rows], [1.0, 0.0, 0.0])
        self.assertEqual(rows[0][0], math.log1p(10000))


if __name__ == "__main__":
    unittest.main()
