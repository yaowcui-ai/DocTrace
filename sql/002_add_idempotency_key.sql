-- Run once in MySQL Workbench using the administrator connection.
-- Existing records retain NULL; application code does not use this column yet.
USE doctrace;

ALTER TABLE qa_records
    ADD COLUMN idempotency_key CHAR(36)
        CHARACTER SET ascii COLLATE ascii_bin NULL,
    ADD UNIQUE INDEX uq_qa_records_idempotency_key (idempotency_key);

SHOW COLUMNS FROM qa_records LIKE 'idempotency_key';
SHOW INDEX FROM qa_records
    WHERE Key_name = 'uq_qa_records_idempotency_key';
