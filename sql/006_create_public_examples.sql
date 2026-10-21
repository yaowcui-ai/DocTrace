-- Run once using the administrator connection in MySQL Workbench.
-- No private QA content is copied or published by this script.
USE doctrace;

CREATE TABLE public_examples (
    example_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    question TEXT NOT NULL,
    answer MEDIUMTEXT NOT NULL,
    references_json JSON NOT NULL,
    corpus_id VARCHAR(64) NOT NULL,
    status VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'draft',
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    published_at DATETIME(6) NULL,
    PRIMARY KEY (example_id),
    INDEX idx_public_examples_status_published (status, published_at, example_id),
    CONSTRAINT chk_public_examples_status
        CHECK (status IN ('draft', 'published', 'withdrawn')),
    CONSTRAINT chk_public_examples_published_time
        CHECK (status <> 'published' OR published_at IS NOT NULL)
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

GRANT SELECT, INSERT, UPDATE ON doctrace.public_examples
    TO 'doctrace_app'@'127.0.0.1';

DESCRIBE public_examples;
SELECT COUNT(*) AS example_count FROM public_examples;
