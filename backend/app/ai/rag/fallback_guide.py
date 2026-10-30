GUIDE_TEMPLATE_VERSION = "guide-fallback-v1"

# 알림 유형별 고정 대응 단계. DB 규칙상 3~5단계.
FALLBACK_STEPS = {
    "TRANSFER_HELP": [
        "도움받을 사람의 답을 기다리는 동안 돈을 보내지 말아요.",
        "받는 사람이 맞는지 원래 알고 있던 전화번호로 물어봐요.",
        "누군가 급하게 보내라고 재촉하면, 도움받을 사람에게 그 내용을 말해요.",
    ],
    "NEW_COUNTERPARTY": [
        "더 보내기 전에 잠깐 멈춰요.",
        "받는 사람에게 원래 알고 있던 전화번호로 직접 물어봐요.",
        "모르는 사람이 돈을 부탁했다면, 믿을 수 있는 사람에게 이 알림을 보여줘요.",
    ],
    "LARGE_OUTFLOW": [
        "보낸 금액이 맞는지 통장 기록에서 다시 확인해 봐요.",
        "이 돈을 보내고도 다음 수입일까지 생활비가 괜찮은지 살펴봐요.",
        "누군가 급하게 부탁해서 보낸 돈이라면, 그 사람에게 원래 알던 번호로 다시 물어봐요.",
        "걱정되면 믿을 수 있는 사람에게 이 알림을 보여줘요.",
    ],
}


def get_fallback_steps(alert_type: str) -> list[str]:
    steps = FALLBACK_STEPS.get(alert_type)
    if not steps:
        raise ValueError(f"고정 안내가 없는 알림 유형이에요: {alert_type}")
    return steps