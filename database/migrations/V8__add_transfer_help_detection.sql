-- 송금 전 "도움 요청하기"를 알림과 지원자 공유로 저장하기 위한 탐지 유형.
-- 아직 송금 전이라 거래가 없으므로 transaction_id와 forecast_id 없이 저장한다.

ALTER TABLE detections DROP CONSTRAINT detections_detection_type_check;
ALTER TABLE detections ADD CONSTRAINT detections_detection_type_check
    CHECK (detection_type IN (
        'LARGE_OUTFLOW',
        'REPEATED_OUTFLOW',
        'NEW_COUNTERPARTY',
        'NEW_COUNTERPARTY_REPEAT',
        'BUDGET_SHORTAGE',
        'UNUSUAL_TRANSACTION',
        'TRANSFER_HELP'
    ));

ALTER TABLE detections DROP CONSTRAINT detections_check1;
ALTER TABLE detections ADD CONSTRAINT detections_check1
    CHECK ((detection_type = 'BUDGET_SHORTAGE' AND forecast_id IS NOT NULL AND transaction_id IS NULL
            AND baseline_date IS NULL AND detection_method = 'RULE')
        OR (detection_type = 'TRANSFER_HELP' AND forecast_id IS NULL AND transaction_id IS NULL
            AND baseline_date IS NULL AND detection_method = 'RULE')
        OR (detection_type NOT IN ('BUDGET_SHORTAGE', 'TRANSFER_HELP')
            AND transaction_id IS NOT NULL AND forecast_id IS NULL));
