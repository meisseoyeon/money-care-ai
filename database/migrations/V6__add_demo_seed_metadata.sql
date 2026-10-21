-- 수동 초기 데이터의 기준 시각과 잔액 계산 근거를 기록합니다.
CREATE TABLE demo_seed_metadata (
    user_id VARCHAR(100) PRIMARY KEY REFERENCES users(user_id),
    account_id VARCHAR(100) NOT NULL,
    dataset_version VARCHAR(50) NOT NULL,
    seed BIGINT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    opening_balance BIGINT NOT NULL CHECK (opening_balance >= 0),
    target_balance BIGINT NOT NULL CHECK (target_balance >= 0),
    transaction_count INTEGER NOT NULL CHECK (transaction_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id, user_id) REFERENCES accounts(account_id, user_id)
);
