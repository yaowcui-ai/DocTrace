# DocTrace 增量全栈升级计划

**目标：**在保留现有运行项目与冻结实验的条件下，分阶段交付 React/FastAPI 产品及可复查的实验和工程证据。

**架构：**原 FastAPI 单体新增产品 router 和表；React/TypeScript/Vite 同源发布；现有认证、记录、LightRAG 和策略模块复用。上传库与 v3 冻结库隔离。

**执行：**当前会话按任务推进；独立模块使用限定文件范围的子任务，整合后重新执行测试。

- [x] 核对父级/公开仓库 Git 历史，新建升级分支；不提交已有私人资产。
- [x] 写 `docs/UPGRADE_AUDIT.md`，记录默认 pytest 98 项收集错误及原因。
- [x] 运行 `python -m pytest tests -q` 和原 JS 测试，保存命令、退出码、输出。
- [x] `pytest.ini` 明确 testpaths，先重现收集问题再修复验证。
- [x] 产品存储/API：`app/product/` 和 `tests/test_product_*.py`，先失败用例，再实现角色、会话、消息、反馈、搜索与引用归属；复用旧问答幂等。
- [x] React `frontend/`：真实认证/会话/问答/引用/反馈/个人历史/管理入口；测试 loading/error/retry/401/跨身份清理；`npm ci && npm run build`。
- [x] 知识库管理：限制文件与路径、管理员、持久化索引任务、独立 LightRAG 目标；mock 集成先验证，再实际小文件验收。
- [x] 评测协议与工具：证据标签分组、排名指标、分位数、不可评估状态；原始结果保持只读。
- [x] 独立题集：真实原文/版本 hash/质量与审核状态；冻结后不用于调参，来源逐条复核，无外部真人盲评。
- [ ] B0/B1/B2/B3 对照、生成核验、安全注入、资源与并发实测；未具备前提的分支明确说明，绝不填造数字。
- [x] 版本化只读管理报告 API 与 React 管理页；不允许任意文件读取或网页发起无限付费实验。
- [ ] Docker 增量部署与离线 CI；隔离数据库验收，不覆盖原库。
- [x] 最终七份文档、简历三四点与逐项证据；原计划中未完成项保留未勾选。

## 产品接口契约（新增，不替换旧 API）

- `GET /api/v1/me`：现有登录身份和角色。
- `GET/POST /api/v1/conversations`：本人的会话搜索/创建。
- `GET /api/v1/conversations/{id}`：本人的消息及答案证据。
- `POST /api/v1/conversations/{id}/messages`：`question, mode`；要求 `Idempotency-Key` UUID，服务端关联已有问答记录，未知/他人会话 404。
- `PUT /api/v1/messages/{request_id}/feedback`：`helpful: bool`、可选评论；只允许本人已完成消息。
- `GET /api/v1/citations/{request_id}/{reference_id}`：仅本人记录中存在的引用；不用客户端文件路径读取磁盘。
- `GET/POST /api/v1/admin/documents`、文档更新/撤销与任务状态：管理员、固定可写知识库、可追踪状态。
- `GET /api/v1/admin/reports` / `.../{report_id}`：管理员读取白名单公开实验摘要。

新 API 成功返回 `{data: ...}`，错误沿用 FastAPI `detail` 并加 no-store；旧接口响应不改。流式仅在真实模型流式与持久化生命周期实现并验证后启用，不伪装分段播放为流式。React 初版非流式显示明确等待状态。


## 执行验收与未完成边界（2026-10-29）

核心产品及隔离Docker部署已实际验收；1076项Python、真实MySQL3项、浏览器3流程、最新24项部署只读检查。完整记录见ENGINEERING_TEST_REPORT。

实验已执行112题检索尝试（109可评分）、四方案同候选消融、12题24次生成、安全3调用、模拟供应商并发及8项业务任务。仍未完成3题失败恢复、穷尽语义相关性/逐句引用标注、真实参与者任务测试、真实供应商高并发及新测试全集生成；不将有限覆盖勾成全面通过。CI配置已建立，远端执行结果另记。
