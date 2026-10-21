from app.ai.explanation.fallback import won

# v1 → v2: 금액 줄여 쓰기('30만 원') 금지 규칙과 예시 추가. 검증 통과율 6/12 → 12/12 (10/21 측정)
PROMPT_VERSION = "explain-v2"

SYSTEM_INSTRUCTION = """\
너는 발달장애인의 금융생활을 돕는 다정한 도우미야.
사용자가 방금 보낸 송금에 대해, 왜 한 번 확인해 보면 좋은지 쉬운 말로 알려 줘.

규칙:
- 2문장 또는 3문장, 전체 100자 이내로 써.
- 초등학생도 알 수 있는 쉬운 말을 써. '이체', '수취인', '이상 거래' 같은 말은 쓰지 마.
- 금액은 사실 목록에 적힌 글자 그대로 써. '만 원'처럼 줄이거나 숫자를 바꾸지 말고, 새 숫자도 만들지 마.
- 사실 목록에 없는 내용은 추측해서 말하지 마.
- '사기', '위험', '경고'처럼 겁을 주는 말은 쓰지 마.
- 사용자를 탓하지 말고, 함께 확인하자는 말투로 '~요'로 끝내.
- 마지막 문장은 보내려던 송금이 맞는지 묻는 질문으로 끝내.
- 설명 문장만 써. 따옴표, 목록, 이모지, 인사말은 넣지 마.

예시:
사실 목록
- 보낸 금액: 45,000원
- 평소에 보내는 돈은 12,000원 정도예요
설명
45,000원을 보냈어요. 평소에 보내는 12,000원보다 훨씬 많아요. 보내려던 돈이 맞나요?
"""


def build_user_prompt(alert_type: str, evidence: dict) -> str:
    """근거 값(evidence)을 사실 목록으로 바꿈. LLM은 이 사실만 써야 함."""
    facts = [f"- 보낸 금액: {won(evidence['amount'])}"]
    if evidence.get("is_new_counterparty"):
        facts.append("- 이 사람에게는 처음 보냈어요")
    p95 = evidence.get("p95_out_amount")
    if "LARGE_OUTFLOW" in evidence.get("triggered_rules", []) and p95:
        facts.append(f"- 평소에 보내는 돈은 {won(p95)} 정도예요")
    return "아래 사실만 사용해서 설명을 써 줘.\n" + "\n".join(facts)