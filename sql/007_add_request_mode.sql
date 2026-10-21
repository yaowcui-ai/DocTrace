-- 在 MySQL Workbench 管理员连接中执行一次。
-- 记录请求选定的检索模式，供幂等重试比较；不改变既有答案和引用。
USE doctrace;

ALTER TABLE qa_records
    ADD COLUMN request_mode VARCHAR(8) NOT NULL DEFAULT 'mix'
    COMMENT 'Requested mode for idempotency; legacy rows use mix compatibility default';

-- mix 是旧接口的兼容默认值，不是重新评测旧记录所得的真实模式。
-- 历史答案实际使用的模式仍以 retrieval_json 中已保存的信息为准。
SHOW COLUMNS FROM qa_records LIKE 'request_mode';
