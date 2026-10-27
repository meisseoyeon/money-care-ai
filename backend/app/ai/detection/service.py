import json
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.detection.rules import (
    DETECTOR_VERSION,
    RuleResult,
    check_large_outflow,
    check_new_counterparty,
)
from app.ai.explanation.fallback import TEMPLATE_VERSION, build_fallback_explanation

# ---------- 1~3. DB에서 읽어오기 ----------

def _load_transaction(db: Session, transaction_id: str):
    return db.execute(
        text("""
            SELECT id, user_id, direction, amount, counterparty_id, occurred_at
            FROM transactions
            WHERE id = :id
        """),
        {"id": transaction_id},
    ).mappings().first()


def _is_monitoring_on(db: Session, user_id: str) -> bool:
    # DDL 구현 규칙 1번: ACTIVE + 동의함 + 철회 안 함 일 때만 탐지
    row = db.execute(
        text("""
            SELECT 1 FROM users
            WHERE user_id = :user_id
              AND status = 'ACTIVE'
              AND monitoring_consented_at IS NOT NULL
              AND monitoring_revoked_at IS NULL
        """),
        {"user_id": user_id},
    ).first()
    return row is not None


def _past_counterparty_ids(db: Session, tx) -> set[str]:
    # "이번 송금 전"의 거래만 봄. 이번 거래를 넣으면 항상 아는 상대가 되어버림.
    rows = db.execute(
        text("""
            SELECT DISTINCT counterparty_id FROM transactions
            WHERE user_id = :user_id
              AND id <> :tx_id
              AND occurred_at < :occurred_at
              AND counterparty_id IS NOT NULL
        """),
        {"user_id": tx["user_id"], "tx_id": tx["id"], "occurred_at": tx["occurred_at"]},
    ).scalars()
    return set(rows)


def _latest_baseline(db: Session, tx):
    # 송금한 날(한국 날짜) 이전의 가장 최근 평소 지출 통계 (서연님이 계산해서 넣는 표)
    return db.execute(
        text("""
            SELECT base_date, calculation_version, p95_out_amount
            FROM user_baselines
            WHERE user_id = :user_id
              AND base_date <= (CAST(:occurred_at AS timestamptz) AT TIME ZONE 'Asia/Seoul')::date
            ORDER BY base_date DESC, created_at DESC
            LIMIT 1
        """),
        {"user_id": tx["user_id"], "occurred_at": tx["occurred_at"]},
    ).mappings().first()


# ---------- 5~6. DB에 저장하기 ----------

def _save_detection(db: Session, tx, result: RuleResult, baseline) -> int:
    uses_baseline = result.detection_type == "LARGE_OUTFLOW" and baseline is not None
    params = {
        "user_id": tx["user_id"],
        "tx_id": tx["id"],
        "baseline_date": baseline["base_date"] if uses_baseline else None,
        "baseline_version": baseline["calculation_version"] if uses_baseline else None,
        "detection_type": result.detection_type,
        "detector_version": DETECTOR_VERSION,
        "event_key": f"transaction:{tx['id']}",
        "evidence": json.dumps(result.evidence, ensure_ascii=False),
    }
    # 같은 거래를 두 번 탐지해도 한 줄만 남도록 ON CONFLICT DO NOTHING
    detection_id = db.execute(
        text("""
            INSERT INTO detections (
                user_id, transaction_id, baseline_date, baseline_version,
                detection_type, detection_method, detector_version, execution_mode,
                event_key, evidence
            ) VALUES (
                :user_id, :tx_id, :baseline_date, :baseline_version,
                :detection_type, 'RULE', :detector_version, 'LIVE',
                :event_key, CAST(:evidence AS jsonb)
            )
            ON CONFLICT (user_id, event_key, detection_type, detection_method, detector_version, execution_mode)
            DO NOTHING
            RETURNING id
        """),
        params,
    ).scalar()
    if detection_id is None:  # 이미 저장돼 있던 경우 기존 id 사용
        detection_id = db.execute(
            text("""
                SELECT id FROM detections
                WHERE user_id = :user_id AND event_key = :event_key
                  AND detection_type = :detection_type AND detection_method = 'RULE'
                  AND detector_version = :detector_version AND execution_mode = 'LIVE'
            """),
            params,
        ).scalar_one()
    return detection_id


def _save_alert(db: Session, user_id: str, detection_id: int, alert_type: str, dedupe_key: str) -> str:
    params = {"user_id": user_id, "detection_id": detection_id,
              "alert_type": alert_type, "dedupe_key": dedupe_key}
    alert_id = db.execute(
        text("""
            INSERT INTO alerts (user_id, detection_id, alert_type, dedupe_key)
            VALUES (:user_id, :detection_id, :alert_type, :dedupe_key)
            ON CONFLICT (user_id, dedupe_key) DO NOTHING
            RETURNING id
        """),
        params,
    ).scalar()
    if alert_id is None:
        alert_id = db.execute(
            text("SELECT id FROM alerts WHERE user_id = :user_id AND dedupe_key = :dedupe_key"),
            params,
        ).scalar_one()
    return str(alert_id)
def _save_fallback_explanation(db: Session, alert_id: str, alert_type: str, evidence: dict) -> None:
    started = time.perf_counter()
    explanation = build_fallback_explanation(alert_type, evidence)
    latency_ms = int((time.perf_counter() - started) * 1000)
    # 알림당 설명 1개. 이미 있으면(재실행) 그대로 둠.
    db.execute(
        text("""
            INSERT INTO alert_explanations (
                alert_id, generation_status, text, method,
                template_version, validated, latency_ms, generated_at
            ) VALUES (
                CAST(:alert_id AS uuid), 'SUCCEEDED', :text, 'FALLBACK',
                :template_version, TRUE, :latency_ms, CURRENT_TIMESTAMP
            )
            ON CONFLICT (alert_id) DO NOTHING
        """),
        {"alert_id": alert_id, "text": explanation,
         "template_version": TEMPLATE_VERSION, "latency_ms": latency_ms},
    )

# ---------- 전체 흐름 ----------

def run_transaction_detection(db: Session, transaction_id: str) -> list[str]:
    """송금 1건을 탐지하고, 만든 알림 id 목록을 돌려줌. 걸린 게 없으면 빈 목록."""
    tx = _load_transaction(db, transaction_id)
    if tx is None:
        raise ValueError(f"거래를 찾을 수 없어요: {transaction_id}")

    # 2. 출금만, 동의한 사용자만
    if tx["direction"] != "OUT":
        return []
    if not _is_monitoring_on(db, tx["user_id"]):
        return []

    # 3. 판단 재료
    past_ids = _past_counterparty_ids(db, tx)
    baseline = _latest_baseline(db, tx)
    p95 = None
    if baseline is not None and baseline["p95_out_amount"] is not None:
        p95 = int(round(baseline["p95_out_amount"]))

    # 4. 규칙 실행
    results: list[RuleResult] = []

    # 규칙 1: 처음 보는 상대인가?
    new_cp = check_new_counterparty(tx["counterparty_id"], past_ids)
    if new_cp is not None:
        results.append(new_cp)

    # 규칙 2: 평소보다 큰 금액인가?
    large_outflow = check_large_outflow(tx["amount"], p95)
    if large_outflow is not None:
        results.append(large_outflow)

    if not results:
        return []

    # 5. 걸린 규칙마다 detections 1줄
    detection_ids = {}
    for result in results:
        detection_ids[result.detection_type] = _save_detection(db, tx, result, baseline)

    # 6. 알림은 송금 1건당 1개. 둘 다 걸렸으면 큰 금액을 대표 유형으로.
    alert_type = "LARGE_OUTFLOW" if "LARGE_OUTFLOW" in detection_ids else "NEW_COUNTERPARTY"
    alert_id = _save_alert(
        db, tx["user_id"], detection_ids[alert_type], alert_type, f"transaction:{tx['id']}"
    )
    # 7. 쉬운 설명(대체 문구) 저장
    alert_evidence = {
        "amount": tx["amount"],
        "is_new_counterparty": "NEW_COUNTERPARTY" in detection_ids,
        "p95_out_amount": p95,
        "triggered_rules": list(detection_ids),
    }
    _save_fallback_explanation(db, alert_id, alert_type, alert_evidence)

    db.commit()
    return [alert_id]