-- Run once in MySQL Workbench using the administrator connection.
-- Only token hashes are persisted; raw session credentials belong in cookies.
-- This creates no sessions and does not modify accounts or QA records.
USE doctrace;

CREATE TABLE app_sessions (
    session_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    user_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    created_at DATETIME(6) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at DATETIME(6) NULL,
    PRIMARY KEY (session_id),
    UNIQUE INDEX uq_app_sessions_token_hash (token_hash),
    INDEX idx_app_sessions_user (user_id),
    INDEX idx_app_sessions_expiry (expires_at),
    CONSTRAINT fk_app_sessions_user FOREIGN KEY (user_id)
        REFERENCES app_users (user_id),
    CONSTRAINT chk_app_sessions_expiry CHECK (expires_at > created_at)
) ENGINE=InnoDB
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

GRANT SELECT, INSERT, UPDATE ON doctrace.app_sessions
    TO 'doctrace_app'@'127.0.0.1';

DESCRIBE app_sessions;
SHOW INDEX FROM app_sessions WHERE Key_name = 'uq_app_sessions_token_hash';
SELECT COUNT(*) AS session_count FROM app_sessions;
