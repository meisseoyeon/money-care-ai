-- 공용 체험 계정: user1 / demo1234!
-- normal-v1 / seed=42. 최초 1회만 생성하며 재실행해도 기존 데이터를 초기화하지 않습니다.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
DO $seed$
DECLARE
    v_as_of TIMESTAMPTZ := CURRENT_TIMESTAMP;
    v_seed CONSTANT BIGINT := 42;
    v_opening BIGINT;
    v_final BIGINT;
    v_minimum BIGINT;
    v_day DATE;
    v_metadata demo_seed_metadata%ROWTYPE;
BEGIN
    INSERT INTO users (user_id, email, password_hash, display_name, status)
    VALUES ('user1', 'user1@example.invalid', 'scrypt$16384$8$1$0a988079fcfff4def5ce228fbbd68be0$9b8d87cc25f49d43c2930099072ee1af99c80dd26065bf67e19b735339869edc057df57be413c50b3f8846adfa184e7bf7d8de1759198e0dfc4ca052a5b3c033', '체험 사용자', 'ACTIVE')
    ON CONFLICT (user_id) DO NOTHING;
    -- 송금과 동일하게 사용자 → 계좌 순서로 잠급니다.
    PERFORM 1 FROM users WHERE user_id = 'user1' FOR UPDATE;
    INSERT INTO accounts (account_id, user_id, display_name, current_balance, balance_as_of)
    VALUES ('user1-account', 'user1', '체험 생활비 통장', 800000, v_as_of)
    ON CONFLICT (account_id) DO NOTHING;
    PERFORM 1 FROM accounts WHERE account_id = 'user1-account' AND user_id = 'user1' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'user1-account belongs to another user; no data changed';
    END IF;

    SELECT * INTO v_metadata FROM demo_seed_metadata WHERE user_id = 'user1';
    IF FOUND THEN
        IF v_metadata.dataset_version <> 'normal-v1' OR v_metadata.seed <> v_seed
           OR v_metadata.transaction_count <> 30
           OR (SELECT count(*) FROM transactions WHERE user_id = 'user1'
               AND account_id = 'user1-account' AND id LIKE 'seed:user1:normal-v1:%') <> 30 THEN
            RAISE EXCEPTION 'Existing seed metadata is inconsistent; no data changed';
        END IF;
        RAISE NOTICE 'normal-v1 already exists; keeping balances, settings and all transactions';
        RETURN;
    END IF;
    -- 이미 송금한 계정에 초기 이력을 덧붙여 잔액 정합성을 깨뜨리지 않습니다.
    IF EXISTS (SELECT 1 FROM transactions WHERE user_id = 'user1') THEN
        RAISE EXCEPTION 'user1 already has transactions; manual reconciliation required, no data changed';
    END IF;
    IF (SELECT current_balance FROM accounts WHERE account_id = 'user1-account') <> 800000 THEN
        RAISE EXCEPTION 'user1 balance was changed; no data changed';
    END IF;
    v_day := (v_as_of AT TIME ZONE 'Asia/Seoul')::DATE;

    CREATE TEMP TABLE seed_user1_rows ON COMMIT DROP AS
    WITH profile(seq, days_before, at_time, direction, base_amount, tx_type, channel, description, counterparty_id) AS (
        VALUES
        ( 1,29,TIME '12:10','OUT',   8500,'PURCHASE','CARD','식비 · 점심',NULL),
        ( 2,28,TIME '08:15','OUT',   1800,'PURCHASE','CARD','교통비 · 버스',NULL),
        ( 3,27,TIME '17:10','OUT',  12000,'PURCHASE','CARD','소액 구매 · 생활용품',NULL),
        ( 4,26,TIME '18:20','OUT',  11000,'PURCHASE','CARD','식비 · 저녁',NULL),
        ( 5,25,TIME '15:10','OUT',  15000,'TRANSFER','BANK_TRANSFER','박민수님에게 송금','demo-payee-1'),
        ( 6,24,TIME '08:30','OUT',   2200,'PURCHASE','CARD','교통비 · 지하철',NULL),
        ( 7,23,TIME '12:20','OUT',   9000,'PURCHASE','CARD','식비 · 점심',NULL),
        ( 8,22,TIME '18:10','OUT',  12500,'PURCHASE','CARD','식비 · 저녁',NULL),
        ( 9,21,TIME '08:20','OUT',   1600,'PURCHASE','CARD','교통비 · 버스',NULL),
        (10,20,TIME '12:10','OUT',  10500,'PURCHASE','CARD','식비 · 점심',NULL),
        (11,19,TIME '16:10','OUT',  14000,'PURCHASE','CARD','소액 구매 · 생필품',NULL),
        (12,18,TIME '18:10','OUT',   2400,'PURCHASE','CARD','교통비 · 지하철',NULL),
        (13,17,TIME '12:10','OUT',   8000,'PURCHASE','CARD','식비 · 점심',NULL),
        (14,16,TIME '14:10','OUT',  18000,'TRANSFER','BANK_TRANSFER','김하늘님에게 송금','demo-payee-2'),
        (15,15,TIME '18:10','OUT',  13000,'PURCHASE','CARD','식비 · 저녁',NULL),
        (16,14,TIME '08:10','OUT',   1900,'PURCHASE','CARD','교통비 · 버스',NULL),
        (17,13,TIME '12:10','OUT',   9500,'PURCHASE','CARD','식비 · 점심',NULL),
        (18,12,TIME '16:10','OUT',  16000,'PURCHASE','CARD','소액 구매 · 생활용품',NULL),
        (19,11,TIME '08:10','OUT',   2100,'PURCHASE','CARD','교통비 · 지하철',NULL),
        (20,10,TIME '09:00','IN', 1000000,'INCOME','BANK_TRANSFER','정기 수입',NULL),
        (21, 9,TIME '14:10','OUT',  25000,'TRANSFER','BANK_TRANSFER','박민수님에게 송금','demo-payee-1'),
        (22, 8,TIME '15:10','OUT',  22000,'TRANSFER','BANK_TRANSFER','김하늘님에게 송금','demo-payee-2'),
        (23, 7,TIME '12:10','OUT',  12000,'PURCHASE','CARD','식비 · 점심',NULL),
        (24, 6,TIME '16:10','OUT',  30000,'TRANSFER','BANK_TRANSFER','정수진님에게 송금','demo-payee-3'),
        (25, 5,TIME '17:10','OUT',  24000,'PURCHASE','CARD','소액 구매 · 생필품',NULL),
        (26, 4,TIME '15:10','OUT',  28000,'TRANSFER','BANK_TRANSFER','최영호님에게 송금','demo-payee-4'),
        (27, 3,TIME '18:10','OUT',  11500,'PURCHASE','CARD','식비 · 저녁',NULL),
        (28, 2,TIME '14:10','OUT',  26000,'TRANSFER','BANK_TRANSFER','정수진님에게 송금','demo-payee-3'),
        (29, 1,TIME '08:10','OUT',   2500,'PURCHASE','CARD','교통비 · 버스',NULL),
        (30, 0,TIME '18:10','OUT',  27000,'TRANSFER','BANK_TRANSFER','최영호님에게 송금','demo-payee-4')
    ), varied AS (
        SELECT *, CASE WHEN direction = 'IN' THEN base_amount ELSE
            base_amount + 100 * (get_byte(decode(md5(v_seed::TEXT || ':amount:' || seq), 'hex'), 0) % 5) END::BIGINT AS amount,
            get_byte(decode(md5(v_seed::TEXT || ':time:' || seq), 'hex'), 0) % 900 AS jitter_seconds
        FROM profile
    )
    SELECT *, CASE WHEN days_before = 0 THEN v_as_of - (1 + jitter_seconds) * INTERVAL '1 second'
             ELSE ((v_day - days_before) + at_time) AT TIME ZONE 'Asia/Seoul'
                  + jitter_seconds * INTERVAL '1 second' END AS occurred_at,
           CASE WHEN direction = 'IN' THEN amount ELSE -amount END AS signed_amount
    FROM varied;

    SELECT 800000 - sum(signed_amount) INTO v_opening FROM seed_user1_rows;
    ALTER TABLE seed_user1_rows ADD COLUMN balance_after BIGINT;
    WITH balances AS (
        SELECT seq, v_opening + sum(signed_amount) OVER (ORDER BY seq) AS balance
        FROM seed_user1_rows
    )
    UPDATE seed_user1_rows r SET balance_after = b.balance FROM balances b WHERE b.seq = r.seq;
    SELECT balance_after INTO v_final FROM seed_user1_rows ORDER BY seq DESC LIMIT 1;
    SELECT min(balance_after) INTO v_minimum FROM seed_user1_rows;
    IF v_opening < 0 OR v_minimum < 0 OR v_final <> 800000
       OR (SELECT count(*) FROM seed_user1_rows) <> 30
       OR EXISTS (SELECT 1 FROM seed_user1_rows WHERE occurred_at < v_as_of - INTERVAL '30 days' OR occurred_at >= v_as_of)
       OR EXISTS (SELECT 1 FROM (SELECT occurred_at, lag(occurred_at) OVER (ORDER BY seq) AS previous FROM seed_user1_rows) ordered
                  WHERE occurred_at <= previous) THEN
        RAISE EXCEPTION 'Initial ledger validation failed; no data changed';
    END IF;

    INSERT INTO budget_settings (user_id, next_income_date, expected_income_amount, daily_living_budget)
    VALUES ('user1', v_day + 20, 1000000, 20000)
    ON CONFLICT (user_id) DO NOTHING;
    INSERT INTO scheduled_expenses (user_id, title, amount, due_date)
    SELECT 'user1', e.title, e.amount, v_day + e.days_after
    FROM (VALUES ('월세',100000,5), ('통신비',50000,10)) e(title,amount,days_after)
    WHERE NOT EXISTS (SELECT 1 FROM scheduled_expenses s WHERE s.user_id = 'user1' AND s.title = e.title AND s.status = 'PLANNED');

    INSERT INTO transactions (id, account_id, user_id, occurred_at, received_at, direction,
                              amount, balance_after, tx_type, channel, description, counterparty_id, source, scenario_label)
    SELECT 'seed:user1:normal-v1:' || lpad(seq::TEXT, 3, '0'), 'user1-account', 'user1', occurred_at, v_as_of,
           direction, amount, balance_after, tx_type, channel, description, counterparty_id, 'SYNTHETIC', 'NORMAL'
    FROM seed_user1_rows ORDER BY seq;
    -- 마지막 거래에서 계산한 잔액을 사용하며 임의 보정하지 않습니다.
    UPDATE accounts SET current_balance = v_final, balance_as_of = v_as_of WHERE account_id = 'user1-account';
    INSERT INTO demo_seed_metadata (user_id, account_id, dataset_version, seed, as_of, opening_balance, target_balance, transaction_count)
    VALUES ('user1', 'user1-account', 'normal-v1', v_seed, v_as_of, v_opening, v_final, 30);
    RAISE NOTICE 'Created normal-v1: 30 transactions, opening=%, final=%', v_opening, v_final;
END;
$seed$;
COMMIT;
