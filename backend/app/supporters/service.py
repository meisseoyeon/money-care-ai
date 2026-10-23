"""지원자 공유. 변경 함수는 호출자가 commit/rollback합니다."""

from fastapi import HTTPException
from sqlalchemy import text

from app.alerts.service import ALERT_SELECT, _to_dto


def lock_owner(db, owner_id):
    # 응답·공유 철회·연결 철회는 모두 사용자 → 연결/알림 순으로 직렬화합니다.
    row = db.execute(text("SELECT user_id FROM users WHERE user_id=:owner AND status='ACTIVE' FOR UPDATE"),
                     {"owner": owner_id}).first()
    if not row:
        raise HTTPException(404, "사용자를 찾을 수 없어요.")


def ensure_alert_share(db, owner_id, alert_id):
    """호출자는 먼저 lock_owner와 알림 소유권 검사를 수행해야 합니다."""
    links = db.execute(text("""
        SELECT l.id FROM supporter_links l
        JOIN users u ON u.user_id=l.supporter_user_id AND u.status='ACTIVE'
        WHERE l.owner_user_id=:owner AND l.status='ACTIVE'
        ORDER BY l.id FOR UPDATE OF l
    """), {"owner": owner_id}).scalars().all()
    if not links:
        raise HTTPException(409, "연결된 지원자가 없어 도움 요청을 전달하지 못했어요.")
    for link_id in links:
        existing = db.execute(text("""
            SELECT status FROM alert_shares
            WHERE alert_id=CAST(:alert AS uuid) AND supporter_link_id=:link
        """), {"alert": alert_id, "link": link_id}).scalar_one_or_none()
        if existing == "REVOKED":
            raise HTTPException(409, "철회한 알림은 다시 공유할 수 없어요.")
        db.execute(text("""
            INSERT INTO alert_shares (alert_id,supporter_link_id,owner_user_id)
            VALUES (CAST(:alert AS uuid),:link,:owner)
            ON CONFLICT (alert_id,supporter_link_id) DO NOTHING
        """), {"alert": alert_id, "link": link_id, "owner": owner_id})


def list_links(db, owner_id):
    return [dict(row) for row in db.execute(text("""
        SELECT l.id,l.status,l.created_at,l.accepted_at,l.revoked_at,u.display_name AS supporter_name
        FROM supporter_links l JOIN users u ON u.user_id=l.supporter_user_id
        WHERE l.owner_user_id=:owner ORDER BY l.id
    """), {"owner": owner_id}).mappings()]


def list_shares(db, owner_id):
    return [dict(row) for row in db.execute(text("""
        SELECT s.id,s.alert_id,s.supporter_link_id,s.status,s.shared_at,s.revoked_at,
               u.display_name AS supporter_name
        FROM alert_shares s JOIN supporter_links l ON l.id=s.supporter_link_id
        JOIN users u ON u.user_id=l.supporter_user_id
        WHERE s.owner_user_id=:owner ORDER BY s.shared_at DESC,s.id DESC
    """), {"owner": owner_id}).mappings()]


def revoke_share(db, owner_id, share_id):
    lock_owner(db, owner_id)
    row = db.execute(text("""
        UPDATE alert_shares SET status='REVOKED',revoked_at=COALESCE(revoked_at,statement_timestamp())
        WHERE id=:id AND owner_user_id=:owner RETURNING id,status,revoked_at
    """), {"id": share_id, "owner": owner_id}).mappings().first()
    if not row:
        raise HTTPException(404, "공유를 찾을 수 없어요.")
    return dict(row)


def revoke_link(db, owner_id, link_id):
    lock_owner(db, owner_id)
    row = db.execute(text("""
        UPDATE supporter_links SET status='REVOKED',revoked_at=COALESCE(revoked_at,statement_timestamp())
        WHERE id=:id AND owner_user_id=:owner RETURNING id,status,revoked_at
    """), {"id": link_id, "owner": owner_id}).mappings().first()
    if not row:
        raise HTTPException(404, "지원자 연결을 찾을 수 없어요.")
    db.execute(text("""
        UPDATE alert_shares SET status='REVOKED',revoked_at=COALESCE(revoked_at,statement_timestamp())
        WHERE supporter_link_id=:id AND owner_user_id=:owner AND status='ACTIVE'
    """), {"id": link_id, "owner": owner_id})
    return dict(row)


def list_shared_alerts(db, supporter_id):
    # 항상 활성 공유와 연결을 함께 확인합니다. 당사자 알림 전체 조회 권한은 부여하지 않습니다.
    rows = db.execute(text("""
        SELECT a.*,s.id AS share_id,s.shared_at,owner_user.display_name AS owner_name
        FROM (""" + ALERT_SELECT + """) a
        JOIN alert_shares s ON s.alert_id=a.id AND s.owner_user_id=a.user_id
        JOIN supporter_links l ON l.id=s.supporter_link_id AND l.owner_user_id=s.owner_user_id
        JOIN users owner_user ON owner_user.user_id=a.user_id AND owner_user.status='ACTIVE'
        WHERE l.supporter_user_id=:supporter AND l.status='ACTIVE' AND s.status='ACTIVE'
        ORDER BY s.shared_at DESC,s.id DESC
    """), {"supporter": supporter_id}).mappings().all()
    return [_shared_dto(row) for row in rows]


def _shared_dto(row):
    alert = _to_dto(row)
    return {"share_id": row["share_id"], "alert_id": alert["id"],
            "owner_name": row["owner_name"], "shared_at": row["shared_at"],
            "title": alert["title"], "alert_type": alert["alert_type"],
            "explanation": alert["explanation"], "guide": alert["guide"],
            "amount": alert["evidence"]["amount"], "created_at": alert["created_at"]}
