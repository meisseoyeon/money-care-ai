from sqlalchemy import select
from app.auth.models import AuthSession
from app.users.models import User
from app.auth.dependencies import resolve_principal
from app.core.time import utc_now
from app.users.serializers import user_response


def set_monitoring(db, principal, consented):
    # 잠금 순서는 다른 보호 작업과 동일하게 세션 → 사용자로 통일합니다.
    user = resolve_principal(db, {"sid": principal.session.session_id, "sub": principal.user.user_id}, lock=True).user
    now = utc_now()
    if consented and (not user.monitoring_consented_at or user.monitoring_revoked_at):
        user.monitoring_consented_at, user.monitoring_revoked_at = now, None
    elif not consented and user.monitoring_consented_at and not user.monitoring_revoked_at:
        user.monitoring_revoked_at = now
    user.updated_at = now
    db.commit()
    return user_response(user)


def monitored_demo_user_ids(db):
    """배치도 동의뿐 아니라 체험 세션의 만료·폐기를 반드시 확인합니다."""
    return list(db.scalars(
        select(User.user_id).where(
            User.status == "ACTIVE",
            User.monitoring_consented_at.is_not(None),
            User.monitoring_revoked_at.is_(None),
            select(AuthSession.session_id).where(
                AuthSession.user_id == User.user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utc_now(),
            ).exists(),
        )
    ))
