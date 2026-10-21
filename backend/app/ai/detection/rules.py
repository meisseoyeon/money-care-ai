from dataclasses import dataclass

DETECTOR_VERSION = "rules-v1"


@dataclass
class RuleResult:
    detection_type: str      # "NEW_COUNTERPARTY" 또는 "LARGE_OUTFLOW"
    evidence: dict           # 왜 걸렸는지 근거 값


def check_new_counterparty(counterparty_id: str | None, past_counterparty_ids: set[str]) -> RuleResult | None:
    if counterparty_id is None:
        return None
    if counterparty_id in past_counterparty_ids:
        return None
    return RuleResult(
        detection_type="NEW_COUNTERPARTY",
        evidence={"is_new_counterparty": True},
    )


def check_large_outflow(amount: int, p95_out_amount: float | None) -> RuleResult | None:
    if p95_out_amount is None:
        return None
    if amount > p95_out_amount:
        return RuleResult(
            detection_type="LARGE_OUTFLOW",
            evidence={"amount": amount, "p95_out_amount": p95_out_amount},
        )
    return None
