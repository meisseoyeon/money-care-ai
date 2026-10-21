-- 이미 적용된 V1을 유지하고, 체험 거래의 DEMO 출처를 별도 버전으로 허용합니다.
ALTER TABLE transactions DROP CONSTRAINT transactions_source_check;

ALTER TABLE transactions ADD CONSTRAINT transactions_source_check
    CHECK (source IN ('SYNTHETIC', 'DEMO'));
