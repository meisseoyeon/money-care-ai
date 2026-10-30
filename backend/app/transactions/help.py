"""송금 전 도움 요청. 돈은 보내지 않고, 예정 내용을 알림으로 만들어 지원자에게 공유합니다."""

import json

from fastapi import HTTPException
from sqlalchemy import select, text

from app.accounts.models import Account
from app.ai.explanation.fallback import won
from app.budgets.queries import current_budget_forecast
from app.recipients.catalog import RECIPIENTS
from app.supporters.service import ensure_alert_share, lock_owner

DETECTOR_VERSION = "transfer-help-v1"
ALERT_TYPE = "TRANSFER_HELP"


def _shortage_after(db, user_id: str, amount: int) -> int:
    """이 돈을 보내면 다음 수입일까지 부족해지는 금액. 생활비 결과가 없으면 0."""
    try:
        forecast = current_budget_forecast(db, user_id=user_id)
    except HTTPException:
        return 0
    return max(0, amount - forecast.available_amount)


def _explanation(name: str, amount: int, shortage: int) -> str:
    text_ = f"{name}님에게 {won(amount)}을 보내기 전에 도움을 요청했어요. 아직 돈은 보내지 않았어요."
    if shortage > 0:
        text_ += f" 이 돈을 보내면 다음 수입일까지 생활비가 {won(shortage)} 부족할 수 있어요."
    return text_


def _share_id(db, alert_id: str) -> str:
    share = db.execute(text("""
        SELECT id FROM alert_shares
        WHERE alert_id = CAST(:alert_id AS uuid) AND status = 'ACTIVE'
        ORDER BY id LIMIT 1
    """), {"alert_id": alert_id}).scalar_one()
    return str(share)


def _existing_request(db, user_id: str, key: str, payload) -> dict | None:
    """같은 요청 번호의 재전송은 기존 결과를, 내용이 다르면 충돌을 돌려줌."""
    row = db.execute(text("""
        SELECT a.id, d.evidence
        FROM alerts a JOIN detections d ON d.id = a.detection_id
        WHERE a.user_id = :user_id AND a.dedupe_key = :key
    """), {"user_id": user_id, "key": key}).mappings().first()
    if row is None:
        return None
    evidence = row["evidence"]
    if evidence["amount"] != payload.amount or evidence["counterparty_id"] != payload.counterparty_id:
        raise HTTPException(409, "같은 요청 번호에 다른 송금 정보가 들어왔어요.")
    return {"alert_id": str(row["id"]), "share_id": _share_id(db, str(row["id"]))}


def create_transfer_help(db, principal, payload) -> dict:
    user_id = principal.user.user_id
    key = f"transfer-help:{payload.request_id}"
    try:
        lock_owner(db, user_id)
        existing = _existing_request(db, user_id, key, payload)
        if existing is not None:
            db.commit()
            return existing

        recipient = next((item for item in RECIPIENTS if item["id"] == payload.counterparty_id), None)
        if recipient is None:
            raise HTTPException(404, "받는 사람을 찾을 수 없어요. 목록에서 다시 선택해 주세요.")
        account = db.scalar(select(Account).where(Account.user_id == user_id).order_by(Account.account_id))
        if account is None:
            raise HTTPException(404, "체험 계좌를 찾을 수 없어요.")
        if payload.amount > account.current_balance:
            raise HTTPException(409, "통장에 있는 돈보다 많이 보낼 수 없어요.")

        shortage = _shortage_after(db, user_id, payload.amount)
        evidence = {"stage": "BEFORE_TRANSFER", "amount": payload.amount,
                    "counterparty_id": recipient["id"], "counterparty_name": recipient["name"],
                    "shortage_amount": shortage}
        detection_id = db.execute(text("""
            INSERT INTO detections (user_id, detection_type, detection_method, detector_version,
                                    execution_mode, event_key, evidence)
            VALUES (:user_id, :alert_type, 'RULE', :version, 'LIVE', :key, CAST(:evidence AS jsonb))
            RETURNING id
        """), {"user_id": user_id, "alert_type": ALERT_TYPE, "version": DETECTOR_VERSION, "key": key,
               "evidence": json.dumps(evidence, ensure_ascii=False)}).scalar_one()
        # 사용자가 직접 도움을 요청한 것이므로 처음부터 응답 완료 상태로 저장합니다.
        alert_id = str(db.execute(text("""
            INSERT INTO alerts (user_id, detection_id, alert_type, dedupe_key, status,
                                user_response, seen_at, responded_at)
            VALUES (:user_id, :detection_id, :alert_type, :key, 'ANSWERED', 'HELP_REQUESTED',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
        """), {"user_id": user_id, "detection_id": detection_id, "alert_type": ALERT_TYPE, "key": key}).scalar_one())
        db.execute(text("""
            INSERT INTO alert_explanations (alert_id, generation_status, text, method,
                                            template_version, validated, latency_ms, generated_at)
            VALUES (CAST(:alert_id AS uuid), 'SUCCEEDED', :text, 'FALLBACK', :version, TRUE, 0, CURRENT_TIMESTAMP)
        """), {"alert_id": alert_id, "text": _explanation(recipient["name"], payload.amount, shortage),
               "version": DETECTOR_VERSION})
        ensure_alert_share(db, user_id, alert_id)  # 연결된 지원자가 없으면 409로 전체 취소
        result = {"alert_id": alert_id, "share_id": _share_id(db, alert_id)}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
