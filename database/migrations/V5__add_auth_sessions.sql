-- 공용 계정에도 브라우저마다 독립된 로그인 세션을 발급합니다.
-- 이전 demo_sessions와 기존 사용자 데이터는 삭제하지 않습니다.
CREATE TABLE auth_sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX ix_auth_sessions_expiry ON auth_sessions(expires_at);
