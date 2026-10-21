# 架构与代码阅读路线

DocTrace 是业务应用，LightRAG 是基础入库与检索框架。模型服务分别负责向量表达、候选重排和基于证据生成答案。

## 正常问答

1. `app/web/question.js` 读取问题和模式，保留账号所属的幂等键；浏览器不持有模型 API Key。
2. `app/main.py` / `app/auth_routes.py` / `app/auth_http.py` 校验会话、请求来源、用户归属及输入。
3. `app/recorded_qa.py` / `app/idempotency.py` / `app/qa_records.py` 用短事务认领请求、保存 processing。同键已有结果可复用，不再次调用模型；问题、库或模式不一致拒绝复用。
4. `app/qa_pipeline.py` 按所选模式编排。naive 调用 `app/retrieval_client.py` 进行向量召回，再在 DocTrace 内重排和筛选。mix 使用 LightRAG 的图与向量候选和项目接入的截断前策略。
5. `app/context_builder.py` 将最终片段转换为模型上下文和一致的引用编号；`app/answer_client.py` 调用回答服务。
6. `app/recorded_qa.py` 保存完成或失败结果，再返回浏览器。执行模型请求期间不保持长数据库事务。
7. `app/web/record-view.js` / `conversation.js` 渲染对话、Markdown 和每条记录自己的原文引用；`record-detail.js` 只读历史，不重新生成。

## mix 扩展位置

`deploy/build_hr_prelimit.py` 从固定 digest 镜像读取 `operate.py`，验证唯一插入边界，生成运行时覆盖文件。接入点位于完整候选合并之后、`process_chunks_unified` 执行 top-k / token 截断之前。

`app/prelimit_adapter.py` 调用重排服务，校验候选身份，缓存相同模型/URL/问题/候选输入，并记录降级。`app/facet_policy.py` 只对明确的复合句式进行保守拆分和去重融合，不使用评测答案或文件名挑选证据。

如果证据在截断前已被丢掉，截断后的重排无法恢复它；这也是前移重排的实际动机。重排本身不会新增候选池以外的证据。

## 故障与边界

- 无可用证据与外部超时是两种状态，不能用“没找到答案”掩盖供应商故障。
- 模型返回答案而最终落库失败时，尚未持久化的答案可能丢失；幂等不等于跨进程保存内存结果。
- 个人记录 API 校验所有者；公开示例独立审核发布，不直接公开整个私人历史。
- 日志按阶段和 request_id 追踪，避免记录模型鉴权信息或未经处理的外部错误正文。
- 连续对话是展示与回放形式，当前请求不会自动附带全部历史作为多轮模型上下文。

## 在线演示与实际应用

`docs/demo.js` 仅从 `docs/data/demo.json` 读取已保存结果，复用实际应用的渲染、引用和对话模块。它不连接 `app/main.py`，不伪造实时检索、不模拟登录成功。完整后台源码、认证和故障路径通过 `tests/` 中的离线测试核验；本地实际调用需配置服务与模型。
