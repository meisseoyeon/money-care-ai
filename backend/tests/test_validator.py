import unittest

from app.ai.explanation.validator import validate_explanation

EVIDENCE = {"amount": 160000, "p95_out_amount": 151500}


class ValidatorTests(unittest.TestCase):
    def test_good_sentence_passes(self):
        text = "160,000원을 보냈어요. 평소 151,500원보다 많아요. 정말 보내려던 송금이 맞나요?"
        self.assertIsNone(validate_explanation(text, EVIDENCE))

    def test_real_llm_failure_changed_amount_format(self):
        # 10/21 실제로 Gemini가 만든 문장. 160,000원을 16만 원으로 바꿈.
        text = "16만 원을 보냈는데, 평소에 보내던 금액과 조금 달라요. 정말 보내려던 송금이 맞나요?"
        self.assertEqual(validate_explanation(text, EVIDENCE), "AMOUNT_MISSING")

    def test_empty(self):
        self.assertEqual(validate_explanation("   ", EVIDENCE), "EMPTY")

    def test_too_long(self):
        text = "160,000원을 보냈어요. " + "확인해 봐요. " * 20
        self.assertEqual(validate_explanation(text, EVIDENCE), "TOO_LONG")

    def test_banned_word(self):
        text = "160,000원을 보냈어요. 사기일 수 있어요. 맞나요?"
        self.assertEqual(validate_explanation(text, EVIDENCE), "BANNED_WORD")

    def test_made_up_number(self):
        text = "160,000원을 3번째 보냈어요. 맞나요?"
        self.assertEqual(validate_explanation(text, EVIDENCE), "UNKNOWN_NUMBER")

    def test_alert_without_p95(self):
        text = "20,000원을 보냈어요. 처음 보내는 사람이에요. 맞나요?"
        self.assertIsNone(validate_explanation(text, {"amount": 20000, "p95_out_amount": None}))


if __name__ == "__main__":
    unittest.main()