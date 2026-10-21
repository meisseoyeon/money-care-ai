import os
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.auth.dependencies import issue_token, signing_key
from app.core.time import utc_now
from app.auth.passwords import hash_password, verify_password
from app.auth.models import AuthSession
from app.users.models import User
from app.users.serializers import user_response

# 존재하지 않는 아이디도 비밀번호 해시 계산을 거칩니다.
DUMMY_HASH = hash_password("not-an-account")


def login(db, payload):
    signing_key()
    try:
        ttl = int(os.getenv("AUTH_SESSION_TTL_SECONDS", os.getenv("DEMO_SESSION_TTL_SECONDS", "86400")))
    except ValueError:
        raise HTTPException(503, "로그인 유효 시간 설정이 올바르지 않아요.") from None
    if not 60 <= ttl <= 604800:
        raise HTTPException(503, "로그인 유효 시간은 60초에서 7일 사이로 설정해 주세요.")
    user = db.get(User, payload.username)
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or user.status != "ACTIVE":
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않아요.", headers={"WWW-Authenticate": "Bearer"})
    now = utc_now()
    session = AuthSession(session_id=str(uuid4()), user_id=user.user_id, created_at=now,
                          expires_at=now + timedelta(seconds=ttl), revoked_at=None)
    db.add(session)
    token = issue_token(session)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_at": session.expires_at,
            "user": user_response(user)}
