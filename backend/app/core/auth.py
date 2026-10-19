from fastapi import Header, HTTPException


def get_current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    """임시 인증: X-User-Id 헤더로 사용자를 받음.
    서연님의 게스트 로그인(토큰)이 생기면 이 함수 안만 바꾸면 됨."""
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="로그인이 필요해요.")
    return x_user_id.strip()