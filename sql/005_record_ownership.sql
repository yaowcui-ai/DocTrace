-- Run once with the administrator connection in MySQL Workbench.
-- Keeps every existing record; ownership remains NULL until explicitly assigned.
USE doctrace;

ALTER TABLE qa_records
    ADD COLUMN owner_user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD COLUMN legacy_idempotency_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin
        GENERATED ALWAYS AS (CASE WHEN owner_user_id IS NULL THEN idempotency_key ELSE NULL END) STORED,
    DROP INDEX uq_qa_records_idempotency_key,
    ADD UNIQUE INDEX uq_qa_records_owner_key (owner_user_id, idempotency_key),
    ADD UNIQUE INDEX uq_qa_records_legacy_key (legacy_idempotency_key),
    ADD INDEX ix_qa_records_owner_created (owner_user_id, created_at, request_id),
    ADD CONSTRAINT fk_qa_records_owner FOREIGN KEY (owner_user_id) REFERENCES app_users(user_id);

SHOW COLUMNS FROM qa_records LIKE 'owner_user_id';
SHOW INDEX FROM qa_records WHERE Key_name IN ('uq_qa_records_owner_key', 'uq_qa_records_legacy_key');
SELECT COUNT(*) AS preserved_records, SUM(owner_user_id IS NULL) AS unassigned_records FROM qa_records;
