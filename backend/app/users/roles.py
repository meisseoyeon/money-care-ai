"""고정 체험 계정용 역할. 요청 본문이나 프런트 설정으로 역할을 정하지 않습니다."""


def user_role(user_id: str) -> str:
    return "SUPPORTER" if user_id == "supporter1" else "OWNER"
