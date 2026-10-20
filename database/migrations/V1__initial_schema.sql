-- Money Care AI: 최종2 기반 17개 테이블 (동의 테이블 제거) / PostgreSQL 17+ + pgvector
-- 신규 DB의 public 스키마에서 전체 실행. 기존 테이블 변경/삭제용 SQL 아님.
-- 기존 FastAPI 모델은 transactions.id / tx_type 등 아래 컬럼 이름에 맞춰 수정해야 함.
-- 모니터링 동의는 users의 시각 2개로 관리. 최초 가입 시 모두 NULL(미동의).
-- 알림 ID는 UUID 유지. 기타 내부 BIGINT ID는 자동 생성.
-- embedding은 최종2의 vector(1024) 유지: 문서/질문 모두 실제 API 출력 1024차원으로 설정.
-- 트랜잭션과 실패 시 ROLLBACK은 Flyway가 관리. 기존 스키마와 섞어 실행하지 말 것.

SET LOCAL search_path = public, pg_catalog;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- 1. 사용자
CREATE TABLE users (
    user_id VARCHAR(100) PRIMARY KEY CHECK (btrim(user_id) <> ''),
    email VARCHAR(254) NOT NULL CHECK (email=btrim(email) AND email<>''),
    password_hash TEXT NOT NULL CHECK (btrim(password_hash) <> ''),
    display_name VARCHAR(100) NOT NULL CHECK (btrim(display_name) <> ''),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    monitoring_consented_at TIMESTAMPTZ,
    monitoring_revoked_at TIMESTAMPTZ,
    CONSTRAINT ck_users_monitoring_consent CHECK (
        (monitoring_consented_at IS NULL AND monitoring_revoked_at IS NULL)
        OR (monitoring_consented_at IS NOT NULL AND (
            monitoring_revoked_at IS NULL OR monitoring_revoked_at >= monitoring_consented_at
        ))
    )
);
CREATE UNIQUE INDEX uq_users_email ON users(lower(email));

-- 2. 계좌 최신 잔액. 음수 잔액 허용.
CREATE TABLE accounts (
    account_id VARCHAR(100) PRIMARY KEY CHECK (btrim(account_id)<>''),
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    display_name VARCHAR(100) NOT NULL CHECK (btrim(display_name)<>''),
    current_balance BIGINT NOT NULL,
    balance_as_of TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id,user_id)
);
CREATE INDEX ix_accounts_user ON accounts(user_id);

-- 3. 거래 원본. 재전송에는 동일 id 사용.
CREATE TABLE transactions (
    id VARCHAR(100) PRIMARY KEY CHECK (btrim(id)<>''),
    account_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    direction VARCHAR(3) NOT NULL CHECK (direction IN ('IN','OUT')),
    amount BIGINT NOT NULL CHECK (amount>0),
    balance_after BIGINT NOT NULL,
    tx_type VARCHAR(20) NOT NULL CHECK (tx_type IN
        ('PURCHASE','TRANSFER','INCOME','REFUND','WITHDRAWAL','DEPOSIT')),
    -- 경제적 거래 유형과 실행 채널은 구분.
    channel VARCHAR(20) CHECK (channel IN ('CARD','BANK_TRANSFER','DIRECT_DEBIT','ATM','OTHER')),
    description VARCHAR(255),
    counterparty_id VARCHAR(100),
    source VARCHAR(20) NOT NULL DEFAULT 'SYNTHETIC' CHECK (source IN ('SYNTHETIC', 'DEMO')),
    scenario_label VARCHAR(50),
    UNIQUE(id,user_id),
    FOREIGN KEY(account_id,user_id) REFERENCES accounts(account_id,user_id),
    CHECK (tx_type='TRANSFER'
        OR (tx_type IN ('PURCHASE','WITHDRAWAL') AND direction='OUT')
        OR (tx_type IN ('INCOME','REFUND','DEPOSIT') AND direction='IN'))
);
CREATE INDEX ix_transactions_user_time ON transactions(user_id,occurred_at DESC);
CREATE INDEX ix_transactions_account_time ON transactions(account_id,occurred_at DESC);
CREATE INDEX ix_transactions_counterparty_time ON transactions(user_id,counterparty_id,occurred_at DESC)
    WHERE counterparty_id IS NOT NULL;

-- 4. 사용자별 생활비 설정
CREATE TABLE budget_settings (
    user_id VARCHAR(100) PRIMARY KEY REFERENCES users(user_id),
    next_income_date DATE NOT NULL,
    expected_income_amount BIGINT NOT NULL CHECK (expected_income_amount>=0),
    daily_living_budget BIGINT NOT NULL CHECK (daily_living_budget>=0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. 예정 지출. PAID는 수동 표시도 가능, 실제 거래 연결은 선택.
CREATE TABLE scheduled_expenses (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    title VARCHAR(100) NOT NULL CHECK (btrim(title)<>''),
    amount BIGINT NOT NULL CHECK (amount>0),
    due_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PLANNED' CHECK (status IN ('PLANNED','PAID','CANCELLED')),
    paid_transaction_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paid_transaction_id,user_id) REFERENCES transactions(id,user_id),
    CHECK (paid_transaction_id IS NULL OR status='PAID')
);
CREATE INDEX ix_expenses_user_status_date ON scheduled_expenses(user_id,status,due_date);
CREATE INDEX ix_expenses_paid_transaction ON scheduled_expenses(paid_transaction_id,user_id)
    WHERE paid_transaction_id IS NOT NULL;

-- 6. 재처리용 입력 스냅샷. 사용자/기준 시각/계산 버전별 한 입력.
-- accounts_snapshot=[{account_id,current_balance,balance_as_of}, ...]
-- expenses_snapshot=[{id,amount,due_date,status}, ...]
CREATE TABLE budget_input_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    as_of TIMESTAMPTZ NOT NULL,
    calculation_version VARCHAR(30) NOT NULL CHECK (btrim(calculation_version)<>''),
    airflow_run_id VARCHAR(250) NOT NULL CHECK (btrim(airflow_run_id)<>''),
    balance_as_of TIMESTAMPTZ NOT NULL,
    next_income_date DATE NOT NULL,
    expected_income_amount BIGINT NOT NULL CHECK (expected_income_amount>=0),
    daily_living_budget BIGINT NOT NULL CHECK (daily_living_budget>=0),
    current_balance BIGINT NOT NULL,
    scheduled_expense_total BIGINT NOT NULL CHECK (scheduled_expense_total>=0),
    accounts_snapshot JSONB NOT NULL CHECK (jsonb_typeof(accounts_snapshot)='array' AND jsonb_array_length(accounts_snapshot)>0),
    expenses_snapshot JSONB NOT NULL CHECK (jsonb_typeof(expenses_snapshot)='array'),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id,as_of,calculation_version),
    UNIQUE(id,user_id,as_of,calculation_version),
    CHECK (balance_as_of<=as_of),
    CHECK (next_income_date>=(as_of AT TIME ZONE 'Asia/Seoul')::date)
);

-- 7. 생활비 계산 결과. 최종2 입력 요약 컬럼을 유지해 조회를 간단하게 함.
CREATE TABLE budget_forecasts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id BIGINT NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    as_of TIMESTAMPTZ NOT NULL,
    balance_as_of TIMESTAMPTZ NOT NULL,
    next_income_date DATE NOT NULL,
    remaining_days INTEGER NOT NULL CHECK (remaining_days>=0),
    current_balance BIGINT NOT NULL,
    scheduled_expense_total BIGINT NOT NULL CHECK (scheduled_expense_total>=0),
    daily_living_budget BIGINT NOT NULL CHECK (daily_living_budget>=0),
    expected_living_cost BIGINT NOT NULL CHECK (expected_living_cost>=0),
    available_amount BIGINT NOT NULL,
    shortage_amount BIGINT NOT NULL CHECK (shortage_amount>=0),
    calculation_version VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id,as_of,calculation_version),
    UNIQUE(id,user_id),
    FOREIGN KEY(snapshot_id,user_id,as_of,calculation_version)
        REFERENCES budget_input_snapshots(id,user_id,as_of,calculation_version),
    CHECK (balance_as_of<=as_of),
    CHECK (remaining_days=next_income_date-(as_of AT TIME ZONE 'Asia/Seoul')::date),
    CHECK (expected_living_cost::numeric=remaining_days::numeric*daily_living_budget::numeric),
    CHECK (available_amount::numeric=current_balance::numeric-scheduled_expense_total::numeric-expected_living_cost::numeric),
    CHECK (shortage_amount::numeric=greatest(0::numeric,-available_amount::numeric))
);

-- 8. 일일 최근 30일 출금 통계. 거래 0건과 통계값 0은 구분.
CREATE TABLE user_baselines (
    base_date DATE NOT NULL,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    calculation_version VARCHAR(30) NOT NULL CHECK (btrim(calculation_version)<>''),
    as_of TIMESTAMPTZ NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    out_count_30d INTEGER NOT NULL CHECK (out_count_30d>=0),
    avg_out_amount NUMERIC(24,4),
    std_out_amount NUMERIC(24,4),
    p95_out_amount NUMERIC(24,4),
    avg_daily_spend NUMERIC(24,4),
    airflow_run_id VARCHAR(250) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id,base_date,calculation_version),
    CHECK (base_date=(as_of AT TIME ZONE 'Asia/Seoul')::date),
    CHECK (window_start<window_end AND window_end=as_of AND window_end-window_start=INTERVAL '30 days'),
    CHECK (avg_out_amount IS NULL OR (avg_out_amount>=0 AND avg_out_amount<'Infinity'::numeric)),
    CHECK (std_out_amount IS NULL OR (std_out_amount>=0 AND std_out_amount<'Infinity'::numeric)),
    CHECK (p95_out_amount IS NULL OR (p95_out_amount>=0 AND p95_out_amount<'Infinity'::numeric)),
    CHECK (avg_daily_spend IS NULL OR (avg_daily_spend>=0 AND avg_daily_spend<'Infinity'::numeric)),
    CHECK ((out_count_30d=0 AND avg_out_amount IS NULL AND std_out_amount IS NULL AND p95_out_amount IS NULL AND avg_daily_spend IS NULL)
        OR (out_count_30d>0 AND avg_out_amount IS NOT NULL AND p95_out_amount IS NOT NULL AND avg_daily_spend IS NOT NULL)),
    CHECK ((out_count_30d<2 AND std_out_amount IS NULL) OR (out_count_30d>=2 AND std_out_amount IS NOT NULL))
);

-- 9. 탐지 결과. 모델 비교용 결과는 SHADOW, 실제 알림용은 LIVE.
CREATE TABLE detections (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    transaction_id VARCHAR(100),
    forecast_id BIGINT,
    baseline_date DATE,
    baseline_version VARCHAR(30),
    detection_type VARCHAR(30) NOT NULL CHECK (detection_type IN
        ('LARGE_OUTFLOW','REPEATED_OUTFLOW','NEW_COUNTERPARTY_REPEAT','BUDGET_SHORTAGE','UNUSUAL_TRANSACTION')),
    detection_method VARCHAR(10) NOT NULL CHECK (detection_method IN ('RULE','IFOREST')),
    detector_version VARCHAR(50) NOT NULL CHECK (btrim(detector_version)<>''),
    execution_mode VARCHAR(10) NOT NULL CHECK (execution_mode IN ('LIVE','SHADOW')),
    event_key VARCHAR(200) NOT NULL CHECK (btrim(event_key)<>''),
    score DOUBLE PRECISION CHECK (score IS NULL OR (score>'-Infinity'::float8 AND score<'Infinity'::float8)),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence)='object'),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id,event_key,detection_type,detection_method,detector_version,execution_mode),
    UNIQUE(id,user_id,detection_type,execution_mode),
    FOREIGN KEY(transaction_id,user_id) REFERENCES transactions(id,user_id),
    FOREIGN KEY(forecast_id,user_id) REFERENCES budget_forecasts(id,user_id),
    FOREIGN KEY(user_id,baseline_date,baseline_version) REFERENCES user_baselines(user_id,base_date,calculation_version),
    CHECK ((baseline_date IS NULL AND baseline_version IS NULL) OR (baseline_date IS NOT NULL AND baseline_version IS NOT NULL)),
    CHECK ((detection_type='BUDGET_SHORTAGE' AND forecast_id IS NOT NULL AND transaction_id IS NULL
            AND baseline_date IS NULL AND detection_method='RULE')
        OR (detection_type<>'BUDGET_SHORTAGE' AND transaction_id IS NOT NULL AND forecast_id IS NULL)),
    CHECK (detection_method<>'IFOREST' OR (execution_mode='SHADOW' AND score IS NOT NULL))
);
CREATE INDEX ix_detections_user_time ON detections(user_id,detected_at DESC);
CREATE INDEX ix_detections_transaction ON detections(transaction_id,user_id) WHERE transaction_id IS NOT NULL;
CREATE INDEX ix_detections_forecast ON detections(forecast_id,user_id) WHERE forecast_id IS NOT NULL;
CREATE INDEX ix_detections_baseline ON detections(user_id,baseline_date,baseline_version) WHERE baseline_date IS NOT NULL;

-- 10. 실제 사용자 알림. 최종2의 alert_type은 유지하되 탐지 유형과 FK로 일치시킴.
-- transaction_id/forecast_id/detection_method/score/evidence는 detections로 이동.
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    detection_id BIGINT NOT NULL UNIQUE,
    detection_mode VARCHAR(10) NOT NULL DEFAULT 'LIVE' CHECK (detection_mode='LIVE'),
    alert_type VARCHAR(30) NOT NULL,
    dedupe_key VARCHAR(200) NOT NULL CHECK (btrim(dedupe_key)<>''),
    status VARCHAR(20) NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW','SEEN','ANSWERED')),
    user_response VARCHAR(20) CHECK (user_response IN ('PLANNED','UNSURE','HELP_REQUESTED')),
    seen_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id,dedupe_key),
    UNIQUE(id,user_id),
    FOREIGN KEY(detection_id,user_id,alert_type,detection_mode)
        REFERENCES detections(id,user_id,detection_type,execution_mode),
    CHECK ((status='NEW' AND seen_at IS NULL AND user_response IS NULL AND responded_at IS NULL)
        OR (status='SEEN' AND seen_at IS NOT NULL AND user_response IS NULL AND responded_at IS NULL)
        OR (status='ANSWERED' AND seen_at IS NOT NULL AND user_response IS NOT NULL AND responded_at IS NOT NULL)),
    CHECK (seen_at IS NULL OR seen_at>=created_at),
    CHECK (responded_at IS NULL OR responded_at>=seen_at)
);
CREATE INDEX ix_alerts_user_time ON alerts(user_id,created_at DESC);

-- 11. 알림당 현재 쉬운 설명 한 건. 생성 시도 이력은 구조화 로그로 관리.
CREATE TABLE alert_explanations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id UUID NOT NULL UNIQUE REFERENCES alerts(id),
    generation_status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (generation_status IN ('PENDING','SUCCEEDED','FAILED')),
    text TEXT,
    method VARCHAR(10) CHECK (method IN ('LLM','FALLBACK','CACHE')),
    model VARCHAR(100),
    prompt_version VARCHAR(30),
    template_version VARCHAR(30),
    validated BOOLEAN,
    validation_error_code VARCHAR(50),
    latency_ms INTEGER CHECK (latency_ms>=0),
    generated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((generation_status='SUCCEEDED' AND text IS NOT NULL AND btrim(text)<>'' AND method IS NOT NULL
            AND validated IS TRUE AND generated_at IS NOT NULL AND latency_ms IS NOT NULL)
        OR (generation_status<>'SUCCEEDED' AND text IS NULL)),
    CHECK (method IS DISTINCT FROM 'LLM' OR (model IS NOT NULL AND prompt_version IS NOT NULL)),
    CHECK (method IS DISTINCT FROM 'FALLBACK' OR template_version IS NOT NULL)
);

-- 12. 지원자 연결. 재연결은 기존 행 갱신, 현재 MVP는 관계별 한 행.
CREATE TABLE supporter_links (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    supporter_user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACTIVE','REVOKED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    UNIQUE(owner_user_id,supporter_user_id),
    UNIQUE(id,owner_user_id),
    CHECK (owner_user_id<>supporter_user_id),
    CHECK ((status='PENDING' AND accepted_at IS NULL AND revoked_at IS NULL)
        OR (status='ACTIVE' AND accepted_at IS NOT NULL AND revoked_at IS NULL)
        OR (status='REVOKED' AND revoked_at IS NOT NULL)),
    CHECK (accepted_at IS NULL OR accepted_at>=created_at),
    CHECK (revoked_at IS NULL OR (revoked_at>=created_at AND (accepted_at IS NULL OR revoked_at>=accepted_at)))
);
CREATE INDEX ix_links_supporter_status ON supporter_links(supporter_user_id,status);

-- 13. 개별 알림 공유. 다른 사용자의 알림과 지원자 관계를 연결하지 못하게 검증.
CREATE TABLE alert_shares (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id UUID NOT NULL,
    supporter_link_id BIGINT NOT NULL,
    owner_user_id VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED')),
    shared_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ,
    UNIQUE(alert_id,supporter_link_id),
    FOREIGN KEY(alert_id,owner_user_id) REFERENCES alerts(id,user_id),
    FOREIGN KEY(supporter_link_id,owner_user_id) REFERENCES supporter_links(id,owner_user_id),
    CHECK ((status='ACTIVE' AND revoked_at IS NULL)
        OR (status='REVOKED' AND revoked_at IS NOT NULL AND revoked_at>=shared_at))
);
CREATE INDEX ix_shares_link_status ON alert_shares(supporter_link_id,status);

-- 14. 공식 문서. 동일 URL이라도 내용 수정 시 새 id/버전으로 저장.
CREATE TABLE documents (
    id VARCHAR(100) PRIMARY KEY CHECK (btrim(id)<>''),
    title VARCHAR(255) NOT NULL CHECK (btrim(title)<>''),
    org VARCHAR(100) NOT NULL CHECK (btrim(org)<>''),
    doc_type VARCHAR(20) NOT NULL CHECK (doc_type IN ('SCAM_CASE','RESPONSE','WELFARE','EASY_TERM')),
    url TEXT NOT NULL CHECK (btrim(url)<>''),
    document_version VARCHAR(50) NOT NULL,
    content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    collected_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    license TEXT,
    status VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url,document_version)
);

-- 15. 문서 청크. 태그 JSON 배열의 항목은 서버에서 문자열로 검증.
CREATE TABLE doc_chunks (
    id VARCHAR(100) PRIMARY KEY CHECK (btrim(id)<>''),
    document_id VARCHAR(100) NOT NULL REFERENCES documents(id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index>=0),
    content TEXT NOT NULL CHECK (btrim(content)<>''),
    content_hash VARCHAR(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    chunking_version VARCHAR(30) NOT NULL,
    situation_tags JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(situation_tags)='array'),
    embedding_model VARCHAR(100) NOT NULL,
    embedding_version VARCHAR(30) NOT NULL,
    embedding_status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (embedding_status IN ('PENDING','READY','FAILED')),
    embedding VECTOR(1024),
    embedded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id,chunk_index,chunking_version,embedding_model,embedding_version),
    CHECK ((embedding_status='READY' AND embedding IS NOT NULL AND embedded_at IS NOT NULL)
        OR (embedding_status<>'READY' AND embedding IS NULL AND embedded_at IS NULL))
);
CREATE INDEX ix_chunks_document ON doc_chunks(document_id);
CREATE INDEX ix_chunks_tags ON doc_chunks USING gin(situation_tags);
-- 초기에는 정확 검색. 근사 검색 인덱스는 규모/지연/Recall@5 측정 후 추가.

-- 16. 알림당 현재 대응 안내 한 건. steps=[{step_no:1,instruction:"..."}, ...].
CREATE TABLE alert_guides (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id UUID NOT NULL UNIQUE REFERENCES alerts(id),
    generation_status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (generation_status IN ('PENDING','SUCCEEDED','FAILED')),
    steps JSONB,
    method VARCHAR(10) CHECK (method IN ('RAG','FALLBACK')),
    model VARCHAR(100),
    prompt_version VARCHAR(30),
    retrieval_version VARCHAR(30),
    embedding_model VARCHAR(100),
    embedding_version VARCHAR(30),
    template_version VARCHAR(30),
    validated BOOLEAN,
    validation_error_code VARCHAR(50),
    latency_ms INTEGER CHECK (latency_ms>=0),
    generated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (steps IS NULL OR (jsonb_typeof(steps)='array' AND jsonb_array_length(steps) BETWEEN 3 AND 5)),
    CHECK ((generation_status='SUCCEEDED' AND steps IS NOT NULL AND method IS NOT NULL AND validated IS TRUE
            AND generated_at IS NOT NULL AND latency_ms IS NOT NULL)
        OR (generation_status<>'SUCCEEDED' AND steps IS NULL)),
    CHECK (method IS DISTINCT FROM 'RAG' OR (model IS NOT NULL AND prompt_version IS NOT NULL
        AND retrieval_version IS NOT NULL AND embedding_model IS NOT NULL AND embedding_version IS NOT NULL)),
    CHECK (method IS DISTINCT FROM 'FALLBACK' OR template_version IS NOT NULL)
);

-- 17. 단계별 근거. JSON 단계 번호 존재/연속성/근거별 모델 일치는 서버에서 검증.
CREATE TABLE guide_citations (
    step_no INTEGER NOT NULL CHECK (step_no BETWEEN 1 AND 5),
    guide_id BIGINT NOT NULL REFERENCES alert_guides(id),
    chunk_id VARCHAR(100) NOT NULL REFERENCES doc_chunks(id),
    retrieval_rank INTEGER CHECK (retrieval_rank>0),
    PRIMARY KEY(guide_id,step_no,chunk_id)
);
CREATE INDEX ix_citations_chunk ON guide_citations(chunk_id);

-- 수정 시각 자동 갱신
CREATE FUNCTION moneycare_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := statement_timestamp();
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_accounts_updated BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_settings_updated BEFORE UPDATE ON budget_settings FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_expenses_updated BEFORE UPDATE ON scheduled_expenses FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_alerts_updated BEFORE UPDATE ON alerts FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_explanations_updated BEFORE UPDATE ON alert_explanations FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();
CREATE TRIGGER trg_guides_updated BEFORE UPDATE ON alert_guides FOR EACH ROW EXECUTE FUNCTION moneycare_set_updated_at();

-- 스냅샷과 계산 결과는 불변. 다시 계산하려면 새 계산 버전으로 저장.
CREATE FUNCTION moneycare_reject_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is immutable; use a new calculation version', TG_TABLE_NAME;
END;
$$;
CREATE TRIGGER trg_snapshots_immutable BEFORE UPDATE ON budget_input_snapshots FOR EACH ROW EXECUTE FUNCTION moneycare_reject_update();
CREATE TRIGGER trg_forecasts_immutable BEFORE UPDATE ON budget_forecasts FOR EACH ROW EXECUTE FUNCTION moneycare_reject_update();
CREATE TRIGGER trg_baselines_immutable BEFORE UPDATE ON user_baselines FOR EACH ROW EXECUTE FUNCTION moneycare_reject_update();

-- 예측 결과의 입력 요약이 원래 스냅샷과 일치하는지 검증.
CREATE FUNCTION moneycare_validate_forecast_input() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    s budget_input_snapshots%ROWTYPE;
BEGIN
    SELECT * INTO STRICT s FROM budget_input_snapshots WHERE id=NEW.snapshot_id;
    IF ROW(NEW.user_id,NEW.as_of,NEW.calculation_version,NEW.balance_as_of,NEW.next_income_date,
           NEW.current_balance,NEW.scheduled_expense_total,NEW.daily_living_budget)
       IS DISTINCT FROM ROW(s.user_id,s.as_of,s.calculation_version,s.balance_as_of,s.next_income_date,
           s.current_balance,s.scheduled_expense_total,s.daily_living_budget) THEN
        RAISE EXCEPTION 'forecast input summary does not match its snapshot';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_forecast_input BEFORE INSERT ON budget_forecasts FOR EACH ROW EXECUTE FUNCTION moneycare_validate_forecast_input();

-- 문서·청크의 본문과 식별 정보를 보호. 새 버전 수집은 새 행 생성.
CREATE FUNCTION moneycare_protect_document() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.id,NEW.title,NEW.org,NEW.doc_type,NEW.url,NEW.document_version,NEW.content_hash,
           NEW.collected_at,NEW.published_at,NEW.license)
       IS DISTINCT FROM ROW(OLD.id,OLD.title,OLD.org,OLD.doc_type,OLD.url,OLD.document_version,OLD.content_hash,
           OLD.collected_at,OLD.published_at,OLD.license) THEN
        RAISE EXCEPTION 'document content is immutable; create a new document version';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_documents_content BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION moneycare_protect_document();

CREATE FUNCTION moneycare_protect_chunk() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.id,NEW.document_id,NEW.chunk_index,NEW.content,NEW.content_hash,NEW.chunking_version,
           NEW.situation_tags,NEW.embedding_model,NEW.embedding_version)
       IS DISTINCT FROM ROW(OLD.id,OLD.document_id,OLD.chunk_index,OLD.content,OLD.content_hash,OLD.chunking_version,
           OLD.situation_tags,OLD.embedding_model,OLD.embedding_version)
       OR (OLD.embedding_status='READY' AND ROW(NEW.embedding,NEW.embedding_status,NEW.embedded_at)
           IS DISTINCT FROM ROW(OLD.embedding,OLD.embedding_status,OLD.embedded_at)) THEN
        RAISE EXCEPTION 'chunk content is immutable; create a new chunk version';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_chunks_content BEFORE UPDATE ON doc_chunks FOR EACH ROW EXECUTE FUNCTION moneycare_protect_chunk();

COMMENT ON COLUMN users.monitoring_consented_at IS '최근 금융 모니터링 동의 시각. NULL이면 미동의';
COMMENT ON COLUMN users.monitoring_revoked_at IS '최근 동의의 철회 시각. 동의 시각 존재 + 철회 시각 NULL이면 동의 중';
COMMENT ON TABLE budget_input_snapshots IS 'Airflow 재처리 전에 고정한 입력. 과거 입력이 없으면 최신 값으로 과거 계산을 재현할 수 없음';
COMMENT ON TABLE detections IS '탐지 결과와 평가 점수. LIVE만 alerts에 연결 가능';
COMMENT ON COLUMN accounts.balance_as_of IS '계좌 잔액이 유효한 실제 기준 시각';
COMMENT ON COLUMN transactions.scenario_label IS '합성 데이터 평가 정답. 학습/추론 특징 입력에서 반드시 제외';
COMMENT ON COLUMN budget_input_snapshots.balance_as_of IS '입력에 포함한 계좌 잔액 중 가장 오래된 기준 시각';
COMMENT ON COLUMN budget_forecasts.available_amount IS '현재 잔액 - 예정 지출 - 예상 생활비, 음수 가능';
COMMENT ON COLUMN user_baselines.std_out_amount IS '표본 표준편차. 출금 표본 2건 미만이면 NULL';
COMMENT ON COLUMN user_baselines.p95_out_amount IS '최근 30일 출금액 95분위수. 큰 출금 기준을 그대로 뜻하지는 않음';
COMMENT ON COLUMN user_baselines.avg_daily_spend IS '최근 30일 총 출금 / 30. 거래한 날짜 수로 나누지 않음';
COMMENT ON COLUMN detections.score IS '사기 확률이 아닌 이상 정도. 점수 방향/변환은 detector_version별 정의';
COMMENT ON COLUMN detections.event_key IS '재전송/같은 사건 범위 탐지 중복 방지 키';
COMMENT ON COLUMN alerts.dedupe_key IS '사용자별 같은 사건/알림 유형의 중복 방지 키';
COMMENT ON COLUMN alerts.detection_mode IS 'LIVE 고정 컬럼. 복합 FK로 SHADOW 결과의 알림 생성을 차단';
COMMENT ON COLUMN alert_shares.owner_user_id IS '알림 소유자와 지원자 연결 당사자 일치 검증용';
COMMENT ON COLUMN doc_chunks.embedding IS '최종2의 1024차원 유지. 수집/검색 동일 모델, 동일 출력 차원 사용';
COMMENT ON COLUMN alert_guides.steps IS '3~5개 {step_no,instruction} 객체 배열. 내부 형식은 서버 검증';

-- 구현 규칙: DDL만으로 서비스를 완성할 수 없음.
-- 1) 수집/탐지/계산 전에 users.status='ACTIVE', monitoring_consented_at IS NOT NULL,
--    monitoring_revoked_at IS NULL 모두 확인. FK는 동의 상태를 대신하지 않음.
-- 2) 동의 철회/실행 경합은 사용자 기준 트랜잭션과 잠금으로 제어.
--    동의: 동의 시각 기록, 철회 시각 NULL. 철회: 철회 시각 기록.
--    동일 상태 반복 요청은 기존 시각 유지. 재동의: 새 동의 시각 기록, 철회 시각 NULL.
--    현재/최근 동의 상태만 보관하며 약관 버전과 전체 동의 이력은 보관하지 않음.
-- 3) 거래 저장과 최신 계좌 잔액 갱신은 같은 트랜잭션. 지연 도착/동일시각 거래 순서 정책 적용.
-- 4) 동일 id 재전송에서 다른 payload면 충돌 처리. 기존 거래를 덮어쓰지 않음.
-- 5) Airflow as_of를 실행마다 고정. 첫 입력 수집은 일관된 DB 스냅샷으로 수행.
-- 6) 입력 배열의 사용자/계좌 소유/금액 합계/지출 기간/상태를 수집 코드에서 검증.
-- 7) 생활비 기간은 한국 날짜 기준 기준일 포함, 수입일 제외. 미래 수입을 미리 잔액에 더하지 않음.
-- 8) snapshot/forecast/baseline 동일 키 재실행은 ON CONFLICT DO NOTHING 후 기존 행 조회.
-- 9) 사용자 입력 누락/오래된 잔액은 계산 제외와 오류 코드 기록. 부족 금액 0원으로 대체하지 않음.
-- 10) Isolation Forest는 현재 SHADOW로 비교. 알림 판단에 사용하려면 별도 정책/제약 마이그레이션.
-- 11) 알림 dedupe_key 사건 범위는 백엔드 정책으로 통일. 새 탐지 ID가 생성돼도 같은 사건은 한 번 알림.
-- 12) 지원자 조회는 로그인 지원자 일치 + 연결 ACTIVE + 공유 ACTIVE 모두 확인.
-- 13) 연결 철회 시 기존 공유도 같은 트랜잭션으로 REVOKED 처리. 재연결만으로 옛 공유 재활성화 금지.
-- 14) 재연결/재공유는 기존 행의 상태/시각 갱신. 전체 행동 이력은 구조화 로그로 별도 기록.
-- 15) 설명/안내 생성 시도별 모델/프롬프트/입력 지문/검증 오류/API 오류/지연을 구조화 로그에 남김.
-- 16) LLM 실패는 로그 기록 후 버전된 대체 문구로 전환. 탐지와 알림 저장은 LLM 성공에 의존하지 않음.
-- 17) 캐시 설명은 구조화 근거/모델/프롬프트 버전 키가 같은 경우만 재사용하고 사실 검증 수행.
-- 18) RAG는 ACTIVE 문서, READY 청크, 동일 embedding_model/version, 상황 태그 조건으로 검색.
-- 19) 안내 JSON은 1부터 연속된 3~5단계, 문자열 instruction, 단계별 실제 청크/기관/연락처 검증.
-- 20) steps와 citations를 같은 트랜잭션으로 저장. 같은 안내 생성은 행 잠금 또는 UNIQUE로 제어.
-- 21) 템플릿/탐지유형별 검색 태그/평가 질의·정답은 버전된 코드/설정/평가 파일로 관리.
-- 22) 데이터 보존·삭제·최소 권한 DB 계정·개인정보 로그 제한은 별도 구성. 연쇄 삭제는 사용하지 않음.
