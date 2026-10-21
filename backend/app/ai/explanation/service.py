import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.explanation.llm import generate_llm_explanation
from app.ai.explanation.validator import validate_explanation
from app.alerts import service as alert_service
from app.db.session import session_factory

logger = logging.getLogger(__name__)


def upgrade_explanation(db: Session, user_id: str, alert_id: str) -> bool:
    """대체 문구로 저장된 설명을 LLM 설명으로 바꿈. 바꿨으면 True."""
    alert = alert_service.get_alert(db, user_id, alert_id)
    if alert is None or alert["explanation_method"] != "FALLBACK":
        return False  # 알림이 없거나 이미 LLM 설명이면 그대로 둠

    result = generate_llm_explanation(alert["alert_type"], alert["evidence"])
    error_code = validate_explanation(result.text, alert["evidence"])
    if error_code is not None:
        # 검사 실패: 대체 문구는 그대로 두고, LLM이 왜 실패했는지만 기록
        db.execute(
            text("""
                UPDATE alert_explanations SET validation_error_code = :code
                WHERE alert_id = CAST(:alert_id AS uuid) AND method = 'FALLBACK'
            """),
            {"alert_id": alert_id, "code": error_code},
        )
        db.commit()
        logger.info("LLM explanation rejected (%s): %s", error_code, alert_id)
        return False
    
    # 대체 문구일 때만 덮어씀. 그 사이 다른 요청이 먼저 바꿨으면 아무것도 안 함.
    updated = db.execute(
        text("""
            UPDATE alert_explanations
            SET text = :text, method = 'LLM', model = :model,
                prompt_version = :prompt_version, template_version = NULL,
                validated = TRUE, validation_error_code = NULL,
                latency_ms = :latency_ms, generated_at = CURRENT_TIMESTAMP
            WHERE alert_id = CAST(:alert_id AS uuid) AND method = 'FALLBACK'
        """),
        {"alert_id": alert_id, "text": result.text, "model": result.model,
         "prompt_version": result.prompt_version, "latency_ms": result.latency_ms},
    ).rowcount
    db.commit()
    return updated == 1


def upgrade_explanation_in_background(user_id: str, alert_id: str) -> None:
    """송금 응답을 보낸 뒤 실행. 실패해도 대체 문구가 그대로 남음."""
    with session_factory()() as db:
        try:
            upgrade_explanation(db, user_id, alert_id)
        except Exception:
            db.rollback()
            logger.exception("LLM explanation failed: %s", alert_id)