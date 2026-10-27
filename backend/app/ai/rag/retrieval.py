from functools import lru_cache

from sqlalchemy.orm import Session

from app.documents.evaluate import query_embedding, search_for_evaluation

RETRIEVAL_VERSION = "retrieval-v1"
TOP_K = 3
# 근거 부족 기준(코사인 거리). 평가 10문항: 정답 ≤0.35, 자료 밖 질문 ≥0.476 (10/27 측정)
MAX_DISTANCE = 0.40

# 알림 유형별 검색 계획. 우리 알림은 송금 "후"에 뜨므로 AFTER_TRANSFER로 거름.
SEARCH_PLANS = {
    "NEW_COUNTERPARTY": {
        "query": "처음 보내는 사람에게 돈을 보냈는데 잘 모르는 사람이면 어떻게 해야 하나요",
        "stage": "AFTER_TRANSFER",
        "situation_tags": ["TRANSFER_SCAM"],
    },
    "LARGE_OUTFLOW": {
        "query": "평소보다 큰 금액을 보냈는데 잘 모르는 사람이면 어떻게 해야 하나요",
        "stage": "AFTER_TRANSFER",
        "situation_tags": ["TRANSFER_SCAM"],
    },
}


@lru_cache
def _query_vector(alert_type: str) -> tuple[float, ...]:
    """알림 유형마다 질문이 고정이라, 질문 벡터를 한 번만 만들어 재사용."""
    return tuple(query_embedding(SEARCH_PLANS[alert_type]["query"]))


def retrieve_chunks(db: Session, alert_type: str) -> list[dict]:
    """알림 유형에 맞는 공식 문서 문단을 가까운 순서로 최대 TOP_K개."""
    plan = SEARCH_PLANS[alert_type]
    return search_for_evaluation(
        db.get_bind(), list(_query_vector(alert_type)),
        stage=plan["stage"], situation_tags=plan["situation_tags"], top_k=TOP_K, max_distance=MAX_DISTANCE,
    )