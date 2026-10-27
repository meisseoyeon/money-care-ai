import re

from app.ai.explanation.validator import BANNED_WORDS

MIN_STEPS, MAX_STEPS = 3, 5  # alert_guides DB 규칙과 같음
MAX_STEP_LENGTH = 60


def validate_guide(steps: list[dict], chunks: list[dict]) -> str | None:
    """문제가 없으면 None, 있으면 오류 코드."""
    # 1. 단계 수가 MIN_STEPS~MAX_STEPS가 아니면 → "STEP_COUNT"
    if not MIN_STEPS <= len(steps) <= MAX_STEPS:
        return "STEP_COUNT"

    for step in steps:
        instruction = step.get("instruction", "").strip()
        sources = step.get("sources", [])

        # 2. instruction이 비었으면 → "EMPTY_STEP",  MAX_STEP_LENGTH보다 길면 → "STEP_TOO_LONG"
        if not instruction:
            return "EMPTY_STEP"
        if len(instruction) > MAX_STEP_LENGTH:
            return "STEP_TOO_LONG"

        # 3. BANNED_WORDS 중 하나라도 있으면 → "BANNED_WORD"
        for word in BANNED_WORDS:
            if word in instruction:
                return "BANNED_WORD"

        # 4. sources가 비었거나, 없는 문단 번호(1~len(chunks) 밖)가 있으면 → "BAD_SOURCE"
        if not sources:
            return "BAD_SOURCE"
        for s in sources:
            if not 1 <= s <= len(chunks):
                return "BAD_SOURCE"

        # 5. 안내 속 숫자(전화번호 등)가 근거로 쓴 문단에 실제로 없으면 → "UNKNOWN_NUMBER"
        cited = " ".join(chunks[s - 1]["content"] for s in sources)
        for number in re.findall(r"\d+", instruction):
            if number not in cited:
                return "UNKNOWN_NUMBER"

    return None
