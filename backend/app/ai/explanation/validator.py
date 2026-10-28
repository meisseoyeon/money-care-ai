import re

from app.ai.explanation.fallback import won

MAX_LENGTH = 100
BANNED_WORDS = ["사기", "위험", "경고", "이체", "수취인"]


def _allowed_numbers(evidence: dict) -> set[str]:
    """문장에 나와도 되는 숫자들. 예: {"160,000", "151,500"}"""
    allowed = {f"{evidence['amount']:,}"}
    if evidence.get("p95_out_amount"):
        allowed.add(f"{evidence['p95_out_amount']:,}")
    return allowed


def validate_explanation(text: str, evidence: dict) -> str | None:
    """문제가 없으면 None, 있으면 오류 코드(문자열)를 돌려줌."""
    text = text.strip()

    # 1. 비어 있으면 → "EMPTY"
    if not text:
        return "EMPTY"

    # 2. MAX_LENGTH(100자)보다 길면 → "TOO_LONG"
    if len(text) > MAX_LENGTH:
        return "TOO_LONG"

    # 3. 보낸 금액이 evidence 그대로 들어 있지 않으면 → "AMOUNT_MISSING"
    if won(evidence["amount"]) not in text:
        return "AMOUNT_MISSING"

    # 4. BANNED_WORDS 중 하나라도 들어 있으면 → "BANNED_WORD"
    for word in BANNED_WORDS:
        if word in text:
            return "BANNED_WORD"

    # 5. 근거에 없는 숫자가 있으면 → "UNKNOWN_NUMBER"
    for number in re.findall(r"\d[\d,]*", text):
        if number not in _allowed_numbers(evidence):
            return "UNKNOWN_NUMBER"

    return None