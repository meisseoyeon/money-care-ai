TEMPLATE_VERSION = "fallback-v1"


def won(amount: int) -> str:
    """300000 → '300,000원'"""
    return f"{amount:,}원"


def build_fallback_explanation(alert_type: str, evidence: dict) -> str:
    amount = evidence["amount"]

    if alert_type == "LARGE_OUTFLOW":
        p95 = evidence["p95_out_amount"]
        text = f"{won(amount)}을 보냈어요. 평소에 보내는 돈({won(p95)})보다 많아요."
        if evidence.get("is_new_counterparty"):
            text += " 처음 보내는 사람이기도 해요."
        text += " 계획한 송금인지 한 번 확인해 봐요."
        return text

    if alert_type == "NEW_COUNTERPARTY":
        text = f"{won(amount)}을 보냈어요."
        text += " 처음 보내는 사람이에요."     # 처음 보내는 사람이라는 걸 알려주는 문장
        text += " 이 사람이 맞나요?"     # 확인해 보자는 말
        return text


    raise ValueError(f"대체 문구가 없는 알림 유형이에요: {alert_type}")