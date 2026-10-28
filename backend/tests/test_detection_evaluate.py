import unittest

from app.ai.detection.evaluate import predict, score


class ScoreTests(unittest.TestCase):
    def test_counts_four_cells_and_metrics(self):
        rows = [
            {"label": "RISK", "alerted": True},     # 잡음
            {"label": "RISK", "alerted": True},     # 잡음
            {"label": "RISK", "alerted": False},    # 놓침
            {"label": "NORMAL", "alerted": True},   # 괜히 울림
            {"label": "NORMAL", "alerted": False},  # 조용
        ]
        result = score(rows)
        self.assertEqual((result["tp"], result["fn"], result["fp"], result["tn"]), (2, 1, 1, 1))
        self.assertAlmostEqual(result["recall"], 2 / 3)
        self.assertAlmostEqual(result["precision"], 2 / 3)

    def test_no_risk_and_no_alert_gives_none_instead_of_error(self):
        result = score([{"label": "NORMAL", "alerted": False}])
        self.assertIsNone(result["recall"])
        self.assertIsNone(result["precision"])


class PredictTests(unittest.TestCase):
    def test_uses_same_rules_as_service(self):
        known = {"friend"}
        self.assertEqual(predict({"counterparty_id": "friend", "amount": 10000}, known, 27760), [])
        self.assertEqual(predict({"counterparty_id": "stranger", "amount": 10000}, known, 27760), ["NEW_COUNTERPARTY"])
        self.assertEqual(predict({"counterparty_id": "friend", "amount": 27761}, known, 27760), ["LARGE_OUTFLOW"])


if __name__ == "__main__":
    unittest.main()
