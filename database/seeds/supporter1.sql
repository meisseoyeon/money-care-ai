-- 고정 체험 지원자: supporter1 / demo1234!
-- user1.sql 적용 후 실행. 재실행 시 철회한 연결과 공유를 되살리지 않습니다.
BEGIN;
SET LOCAL search_path = public, pg_catalog;
DO $seed$
BEGIN
    PERFORM 1 FROM users WHERE user_id='user1' AND status='ACTIVE' FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Apply user1.sql first; active user1 is required';
    END IF;
    INSERT INTO users (user_id,email,password_hash,display_name,status)
    VALUES ('supporter1','supporter1@example.invalid',
            'scrypt$16384$8$1$0a988079fcfff4def5ce228fbbd68be0$9b8d87cc25f49d43c2930099072ee1af99c80dd26065bf67e19b735339869edc057df57be413c50b3f8846adfa184e7bf7d8de1759198e0dfc4ca052a5b3c033',
            '체험 지원자','ACTIVE')
    ON CONFLICT (user_id) DO NOTHING;
    INSERT INTO supporter_links (owner_user_id,supporter_user_id,status,accepted_at)
    VALUES ('user1','supporter1','ACTIVE',CURRENT_TIMESTAMP)
    ON CONFLICT (owner_user_id,supporter_user_id) DO NOTHING;
END
$seed$;
COMMIT;
