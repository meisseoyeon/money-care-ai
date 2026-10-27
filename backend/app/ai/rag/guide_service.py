import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.rag.fallback_guide import GUIDE_TEMPLATE_VERSION, get_fallback_steps
from app.alerts import service as alert_service


def get_or_create_guide(db: Session, user_id: str, alert_id: str) -> dict | None:
    """알림의 대응 안내를 돌려줌. 아직 없으면 고정 단계로 만들어 저장. 알림이 없으면 None."""
    alert = alert_service.get_alert(db, user_id, alert_id)
    if alert is None:
        return None
    if alert["guide"] is not None:
        return alert["guide"]  # 이미 만든 안내는 다시 만들지 않음

    steps = [{"step_no": i, "instruction": instruction}
             for i, instruction in enumerate(get_fallback_steps(alert["alert_type"]), start=1)]
    # 알림당 안내 1개. 동시에 두 번 요청돼도 UNIQUE(alert_id)로 한 줄만 남음.
    db.execute(
        text("""
            INSERT INTO alert_guides (
                alert_id, generation_status, steps, method,
                template_version, validated, latency_ms, generated_at
            ) VALUES (
                CAST(:alert_id AS uuid), 'SUCCEEDED', CAST(:steps AS jsonb), 'FALLBACK',
                :template_version, TRUE, 0, CURRENT_TIMESTAMP
            )
            ON CONFLICT (alert_id) DO NOTHING
        """),
        {"alert_id": alert_id, "steps": json.dumps(steps, ensure_ascii=False),
         "template_version": GUIDE_TEMPLATE_VERSION},
    )
    db.commit()
    return alert_service.get_alert(db, user_id, alert_id)["guide"]