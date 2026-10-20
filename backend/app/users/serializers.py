from app.core.time import aware


def user_response(user):
    # 비밀번호 해시와 내부 세션 생성 키는 응답하지 않습니다.
    return {"user_id": user.user_id, "email": user.email, "display_name": user.display_name,
            "role": "OWNER", "status": user.status,
            "monitoring_consented_at": aware(user.monitoring_consented_at) if user.monitoring_consented_at else None,
            "monitoring_revoked_at": aware(user.monitoring_revoked_at) if user.monitoring_revoked_at else None, "is_demo": True}
