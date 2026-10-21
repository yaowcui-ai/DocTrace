-- MySQL 8.0.45. Execute in Workbench after creating the doctrace database.
-- The backend supplies UTC timestamps; completed means processing completed,
-- not that the policy answer has been independently verified as correct.
USE doctrace;

CREATE TABLE IF NOT EXISTS qa_records (
    request_id CHAR(36) NOT NULL,
    question TEXT NOT NULL,
    answer MEDIUMTEXT NULL,
    references_json JSON NULL,
    retrieval_json JSON NULL,
    corpus_id VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    http_status SMALLINT UNSIGNED NULL,
    error_stage VARCHAR(32) NULL,
    error_message TEXT NULL,
    llm_generated BOOLEAN NULL,
    duration_ms BIGINT UNSIGNED NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (request_id),
    INDEX idx_qa_records_created_at (created_at),
    CONSTRAINT chk_qa_records_status
        CHECK (status IN ('processing', 'completed', 'failed'))
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

DESCRIBE qa_records;
