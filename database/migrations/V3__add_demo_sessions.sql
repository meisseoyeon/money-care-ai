-- 체험 인증만 관리합니다. 토큰 원문, 생성 요청 키 원문은 저장하지 않습니다.
CREATE TABLE demo_sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL UNIQUE REFERENCES users(user_id),
    creation_key_hash VARCHAR(64) NOT NULL UNIQUE,
    request_fingerprint VARCHAR(64) NOT NULL,
    replaces_session_id UUID REFERENCES demo_sessions(session_id),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX ix_demo_sessions_expiry ON demo_sessions(expires_at);
