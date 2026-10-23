from sqlalchemy import text
from sqlalchemy.orm import Session

# 알림 + 거래 금액 + 설명 + 걸린 규칙들을 한 번에 가져오는 SQL
ALERT_SELECT = """
    SELECT a.id, a.user_id, a.alert_type, a.status, a.user_response, a.created_at,
           d.transaction_id, t.amount,
           e.text AS explanation, e.method AS explanation_method,
           (SELECT array_agg(d2.detection_type ORDER BY d2.detection_type)
              FROM detections d2
             WHERE d2.user_id = a.user_id AND d2.event_key = d.event_key
               AND d2.execution_mode = 'LIVE') AS triggered_rules,
           (SELECT (d3.evidence->>'p95_out_amount')::bigint
              FROM detections d3
             WHERE d3.user_id = a.user_id AND d3.event_key = d.event_key
               AND d3.detection_type = 'LARGE_OUTFLOW' AND d3.execution_mode = 'LIVE'
             LIMIT 1) AS p95_out_amount
    FROM alerts a
    JOIN detections d ON d.id = a.detection_id
    LEFT JOIN transactions t ON t.id = d.transaction_id AND t.user_id = a.user_id
    LEFT JOIN alert_explanations e ON e.alert_id = a.id AND e.generation_status = 'SUCCEEDED'
"""


def make_title(alert_type: str, triggered_rules: list[str]) -> str:
    """알림 목록에 보일 짧은 제목."""
    if "LARGE_OUTFLOW" in triggered_rules and "NEW_COUNTERPARTY" in triggered_rules:
        return "처음 보내는 사람에게 큰돈을 보냈어요"
    if alert_type == "LARGE_OUTFLOW":
        return "평소보다 큰 금액을 보냈어요"
    if alert_type == "NEW_COUNTERPARTY":
        return "처음 보내는 사람에게 돈을 보냈어요"
    return "확인이 필요한 알림이에요"


def _to_dto(row) -> dict:
    """DB 한 줄 → 프런트가 읽는 모양(API_CONTRACT.md의 Alert)으로 변환."""
    rules = list(row["triggered_rules"] or [])
    return {
        "id": str(row["id"]),
        "user_id": row["user_id"],
        "alert_type": row["alert_type"],
        "title": make_title(row["alert_type"], rules),
        "explanation": row["explanation"],
        "explanation_method": row["explanation_method"],
        "transaction_id": row["transaction_id"],
        "status": row["status"],
        "user_response": row["user_response"],
        "created_at": row["created_at"].isoformat(),
        "evidence": {
            "amount": row["amount"],
            "is_new_counterparty": "NEW_COUNTERPARTY" in rules,
            "p95_out_amount": row["p95_out_amount"],
            "triggered_rules": rules,
        },
        "guide": None,  # 대응 안내는 10/24~26(E)에 추가
    }


def list_alerts(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(
        text(ALERT_SELECT + " WHERE a.user_id = :user_id ORDER BY a.created_at DESC"),
        {"user_id": user_id},
    ).mappings().all()
    return [_to_dto(r) for r in rows]


def get_alert(db: Session, user_id: str, alert_id: str) -> dict | None:
    row = db.execute(
        text(ALERT_SELECT + " WHERE a.user_id = :user_id AND a.id = CAST(:alert_id AS uuid)"),
        {"user_id": user_id, "alert_id": alert_id},
    ).mappings().first()
    return _to_dto(row) if row else None


def mark_seen(db: Session, user_id: str, alert_id: str) -> dict | None:
    # NEW일 때만 SEEN으로. 이미 SEEN/ANSWERED면 그대로 둠.
    db.execute(
        text("""
            UPDATE alerts SET status = 'SEEN', seen_at = CURRENT_TIMESTAMP
            WHERE id = CAST(:alert_id AS uuid) AND user_id = :user_id AND status = 'NEW'
        """),
        {"user_id": user_id, "alert_id": alert_id},
    )
    db.commit()
    return get_alert(db, user_id, alert_id)


def save_response(db: Session, user_id: str, alert_id: str, response: str) -> dict | None:
    from app.supporters.service import ensure_alert_share, lock_owner

    try:
        lock_owner(db, user_id)
        owned = db.execute(text("""
            SELECT id FROM alerts WHERE id=CAST(:alert_id AS uuid) AND user_id=:user_id FOR UPDATE
        """), {"user_id": user_id, "alert_id": alert_id}).first()
        if not owned:
            db.rollback()
            return None
        if response == "HELP_REQUESTED":
            ensure_alert_share(db, user_id, alert_id)
        result = _save_response(db, user_id, alert_id, response)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def _save_response(db: Session, user_id: str, alert_id: str, response: str):
    # 보지 않고 바로 응답한 경우도 있으니 seen_at이 비어 있으면 같이 채움.
    db.execute(
        text("""
            UPDATE alerts
            SET status = 'ANSWERED',
                user_response = CAST(:response AS varchar(20)),
                seen_at = COALESCE(seen_at, statement_timestamp()),
                responded_at = CASE WHEN user_response IS DISTINCT FROM CAST(:response AS varchar(20))
                                    THEN statement_timestamp() ELSE responded_at END
            WHERE id = CAST(:alert_id AS uuid) AND user_id = :user_id
        """),
        {"user_id": user_id, "alert_id": alert_id, "response": response},
    )
    return get_alert(db, user_id, alert_id)
