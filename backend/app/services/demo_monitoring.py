from sqlalchemy import select

from app.core.auth import utc_now
from app.models.demo_session import DemoSession, User


def monitored_demo_user_ids(db):
    """배치도 동의뿐 아니라 체험 세션의 만료·폐기를 반드시 확인합니다."""
    return list(db.scalars(
        select(User.user_id).join(DemoSession, DemoSession.user_id == User.user_id).where(
            User.status == "ACTIVE",
            User.monitoring_consented_at.is_not(None),
            User.monitoring_revoked_at.is_(None),
            DemoSession.revoked_at.is_(None),
            DemoSession.expires_at > utc_now(),
        )
    ))
