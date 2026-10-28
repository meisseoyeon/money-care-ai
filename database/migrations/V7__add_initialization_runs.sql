-- 동일 실행이 기존 입력을 재사용했더라도 최초 결과를 다시 찾을 수 있게 기록합니다.
CREATE TABLE initialization_runs (
    user_id VARCHAR(100) NOT NULL REFERENCES users(user_id),
    run_id VARCHAR(250) NOT NULL CHECK (btrim(run_id) <> ''),
    baseline_version VARCHAR(30) NOT NULL CHECK (btrim(baseline_version) <> ''),
    budget_version VARCHAR(30) NOT NULL CHECK (btrim(budget_version) <> ''),
    baseline_date DATE NOT NULL,
    budget_as_of TIMESTAMPTZ NOT NULL,
    snapshot_id BIGINT NOT NULL REFERENCES budget_forecasts(snapshot_id) ON DELETE CASCADE,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, run_id, baseline_version, budget_version),
    FOREIGN KEY (user_id, baseline_date, baseline_version)
        REFERENCES user_baselines(user_id, base_date, calculation_version) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id, user_id, budget_as_of, budget_version)
        REFERENCES budget_input_snapshots(id, user_id, as_of, calculation_version) ON DELETE CASCADE
);

CREATE TRIGGER trg_initialization_runs_immutable
    BEFORE UPDATE ON initialization_runs
    FOR EACH ROW EXECUTE FUNCTION moneycare_reject_update();

COMMENT ON TABLE initialization_runs IS
    '통계·생활비 초기 준비 완료 기록. 결과와 같은 트랜잭션에 저장하며 같은 실행·버전 재시도는 최초 결과를 반환';
