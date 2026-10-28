import unittest

from app.ai.detection.rules import check_large_outflow, check_new_counterparty


class NewCounterpartyTests(unittest.TestCase):
    def test_new_counterparty_is_detected(self):
        result = check_new_counterparty("kim", {"lee", "park"})
        self.assertIsNotNone(result)
        self.assertEqual(result.detection_type, "NEW_COUNTERPARTY")

    def test_known_counterparty_is_not_detected(self):
        result = check_new_counterparty("lee", {"lee", "park"})
        self.assertIsNone(result)

    def test_no_counterparty_is_not_detected(self):
        result = check_new_counterparty(None, {"lee", "park"})
        self.assertIsNone(result)


class LargeOutflowTests(unittest.TestCase):
    def test_same_as_p95_is_not_detected(self):
        result = check_large_outflow(100000, 100000)
        self.assertIsNone(result)

    def test_above_p95_is_detected(self):
        result = check_large_outflow(100001, 100000)
        self.assertIsNotNone(result)
        self.assertEqual(result.detection_type, "LARGE_OUTFLOW")
        self.assertEqual(result.evidence["amount"], 100001)
        self.assertEqual(result.evidence["p95_out_amount"], 100000)

    def test_no_p95_is_not_detected(self):
        result = check_large_outflow(100000, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()