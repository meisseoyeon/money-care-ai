-- 탐지 규칙 '처음 보는 상대'(NEW_COUNTERPARTY)를 detection_type 허용 목록에 추가.
-- 프런트엔드 ALERT_LABELS와 rules.py가 같은 이름을 사용함.

ALTER TABLE detections DROP CONSTRAINT detections_detection_type_check;

ALTER TABLE detections ADD CONSTRAINT detections_detection_type_check
    CHECK (detection_type IN (
        'LARGE_OUTFLOW',
        'REPEATED_OUTFLOW',
        'NEW_COUNTERPARTY',
        'NEW_COUNTERPARTY_REPEAT',
        'BUDGET_SHORTAGE',
        'UNUSUAL_TRANSACTION'
    ));