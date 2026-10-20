import os
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.time import aware, utc_now
from app.auth.models import AuthSession
from app.users.models import User

bearer = HTTPBearer(auto_error=False)
ISSUER = "money-care-ai"
AUDIENCE = "money-care-login"


def signing_key():
    value = os.getenv("DEMO_JWT_SECRET", "")
    if len(value.encode()) < 32:
        raise HTTPException(503, "서버의 체험 인증 키 설정이 필요해요.")
    return value


def unauthorized():
    return HTTPException(401, "로그인이 만료되었거나 종료됐어요. 다시 로그인해 주세요.", headers={"WWW-Authenticate": "Bearer"})


def issue_token(session):
    return jwt.encode({"sub": session.user_id, "sid": session.session_id,
                       "iat": int(aware(session.created_at).timestamp()),
                       "exp": int(aware(session.expires_at).timestamp()),
                       "iss": ISSUER, "aud": AUDIENCE}, signing_key(), algorithm="HS256")


def decode_token(token):
    try:
        claims = jwt.decode(token, signing_key(), algorithms=["HS256"], issuer=ISSUER,
                            audience=AUDIENCE, options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"]})
        if not isinstance(claims["sub"], str) or not claims["sub"].strip() or len(claims["sub"]) > 100:
            raise ValueError("Invalid user ID")
        UUID(claims["sid"])
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized() from None


@dataclass
class AuthPrincipal:
    session: AuthSession
    user: User


def resolve_principal(db, claims, *, lock=False):
    session = db.get(AuthSession, claims["sid"], with_for_update=lock, populate_existing=lock)
    if (not session or session.user_id != claims["sub"] or session.revoked_at is not None
            or aware(session.expires_at) <= utc_now()):
        raise unauthorized()
    user = db.get(User, session.user_id, with_for_update=lock, populate_existing=lock)
    if not user or user.status != "ACTIVE":
        raise unauthorized()
    return AuthPrincipal(session, user)


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                          db: Session = Depends(get_db)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    return resolve_principal(db, decode_token(credentials.credentials))


def get_current_user_id(principal: AuthPrincipal = Depends(get_current_user)) -> str:
    # 기존 알림 API의 Depends(get_current_user_id)와 호환됩니다.
    return principal.user.user_id


def require_monitoring_consent(principal: AuthPrincipal = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    # 상태 변경과 경합하지 않도록 사용자 행을 잠근 뒤 최신 동의를 확인합니다.
    principal = resolve_principal(db, {"sid": principal.session.session_id, "sub": principal.user.user_id}, lock=True)
    user = principal.user
    if not user.monitoring_consented_at or user.monitoring_revoked_at:
        raise HTTPException(403, "모니터링에 동의한 뒤 가상 송금을 이용해 주세요.")
    return principal
