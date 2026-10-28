import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.rag.fallback_guide import GUIDE_TEMPLATE_VERSION, get_fallback_steps
from app.ai.rag.generator import generate_rag_steps
from app.ai.rag.guide_validator import validate_guide
from app.ai.rag.retrieval import RETRIEVAL_VERSION, retrieve_chunks
from app.alerts import service as alert_service
from app.documents.prepare import EMBEDDING_VERSION, MODEL as EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def get_or_create_guide(db: Session, user_id: str, alert_id: str) -> dict | None:
    """알림의 대응 안내를 돌려줌. 없으면 RAG로 만들고, 안 되면 고정 단계로. 알림이 없으면 None."""
    alert = alert_service.get_alert(db, user_id, alert_id)
    if alert is None:
        return None
    if alert["guide"] is not None:
        return alert["guide"]  # 이미 만든 안내는 다시 만들지 않음

    error_code = _create_rag_guide(db, alert)
    if error_code is not None:
        _create_fallback_guide(db, alert, error_code)
    db.commit()
    return alert_service.get_alert(db, user_id, alert_id)["guide"]


def _create_rag_guide(db: Session, alert: dict) -> str | None:
    """RAG 안내를 저장. 성공하면 None, 못 만들면 이유(오류 코드)."""
    try:
        chunks = retrieve_chunks(db, alert["alert_type"])
        if not chunks:
            return "NO_EVIDENCE"  # 근거 부족 기준(MAX_DISTANCE) 안에 문단이 없음
        result = generate_rag_steps(chunks)
    except Exception:
        logger.exception("RAG guide generation failed: %s", alert["id"])
        return "LLM_ERROR"

    error_code = validate_guide(result.steps, chunks)
    if error_code is not None:
        logger.info("RAG guide rejected (%s): %s", error_code, alert["id"])
        return error_code

    steps = [{"step_no": i, "instruction": step["instruction"].strip()}
             for i, step in enumerate(result.steps, start=1)]
    # steps와 출처(citations)는 같은 트랜잭션으로 저장 (DDL 구현 규칙 20)
    guide_id = db.execute(
        text("""
            INSERT INTO alert_guides (
                alert_id, generation_status, steps, method, model, prompt_version,
                retrieval_version, embedding_model, embedding_version,
                validated, latency_ms, generated_at
            ) VALUES (
                CAST(:alert_id AS uuid), 'SUCCEEDED', CAST(:steps AS jsonb), 'RAG', :model, :prompt_version,
                :retrieval_version, :embedding_model, :embedding_version,
                TRUE, :latency_ms, CURRENT_TIMESTAMP
            )
            ON CONFLICT (alert_id) DO NOTHING
            RETURNING id
        """),
        {"alert_id": alert["id"], "steps": json.dumps(steps, ensure_ascii=False),
         "model": result.model, "prompt_version": result.prompt_version,
         "retrieval_version": RETRIEVAL_VERSION, "embedding_model": EMBEDDING_MODEL,
         "embedding_version": EMBEDDING_VERSION, "latency_ms": result.latency_ms},
    ).scalar()
    if guide_id is None:
        return None  # 그 사이 다른 요청이 먼저 안내를 만듦

    # 단계마다 근거 문단 저장. retrieval_rank = 검색 순위(1이 가장 가까움)
    for step_no, step in enumerate(result.steps, start=1):
        for source in sorted(set(step["sources"])):
            db.execute(
                text("""
                    INSERT INTO guide_citations (step_no, guide_id, chunk_id, retrieval_rank)
                    VALUES (:step_no, :guide_id, :chunk_id, :rank)
                """),
                {"step_no": step_no, "guide_id": guide_id,
                 "chunk_id": chunks[source - 1]["chunk_id"], "rank": source},
            )
    return None


def _create_fallback_guide(db: Session, alert: dict, error_code: str) -> None:
    """고정 단계 안내를 저장. RAG를 못 쓴 이유는 validation_error_code에 남김."""
    steps = [{"step_no": i, "instruction": instruction}
             for i, instruction in enumerate(get_fallback_steps(alert["alert_type"]), start=1)]
    # 알림당 안내 1개. 동시에 두 번 요청돼도 UNIQUE(alert_id)로 한 줄만 남음.
    db.execute(
        text("""
            INSERT INTO alert_guides (
                alert_id, generation_status, steps, method,
                template_version, validated, validation_error_code, latency_ms, generated_at
            ) VALUES (
                CAST(:alert_id AS uuid), 'SUCCEEDED', CAST(:steps AS jsonb), 'FALLBACK',
                :template_version, TRUE, :error_code, 0, CURRENT_TIMESTAMP
            )
            ON CONFLICT (alert_id) DO NOTHING
        """),
        {"alert_id": alert["id"], "steps": json.dumps(steps, ensure_ascii=False),
         "template_version": GUIDE_TEMPLATE_VERSION, "error_code": error_code},
    )
