# 简历陈述与核查证据

## 可使用的项目经历（4点）

**DocTrace 企业HR政策AI全栈问答系统**
Python · React/TypeScript · FastAPI · LightRAG · BGE-M3/BGE Reranker · MySQL · Docker

- 基于68份公开HR政策、318个片段，增量开发React工作台及FastAPI接口，支持多轮提问、个人历史搜索与恢复、原文引用、反馈和管理员文档索引管理。
- 基于固定版LightRAG源码接入完整候选池自定义排序及条件性子问题融合；建立B0/B1/B2/B3同候选对照，核实原生同样支持重排后截断，保留收益、等价与退化结果。
- 冻结112道内部测试及原文/代码哈希，109道可评题的证据组覆盖从关闭重排的109/124提升至开启重排的122/124；原生与自定义重排结果相同，不将该收益归为自研独占提升。
- 使用MySQL实现Cookie身份、账号级幂等、会话/引用权限及持久化索引任务；通过1076项Python测试、3项真实MySQL集成与3条Playwright流程，完成独立Docker Compose构建和部署验收。

面向简历篇幅可不写所有数字。若面试官问独特算法贡献，应讲失败定位、候选池挂钩、保守融合、边界验证和诚实对照；不要把原生已有的排序位置说成原创算法。

## 对应位置

| 陈述 | 代码 | 可核查结果 |
|---|---|---|
| React接真实API | frontend/src/App.tsx、state.ts、RequestStatistics.tsx | frontend/tests/browser/actual-api.spec.ts；浏览器实际API测试 |
| 契约与业务分层 | app/product/api.py、schemas.py、service.py、repository.py | tests/test_product_api.py、test_product_contract.py |
| 用户/引用隔离与幂等 | app/auth_routes.py、recorded_qa.py、product/service.py | tests/integration/test_mysql_upgrade.py、test_identity_permissions.py |
| 文档与版本/索引 | app/knowledge/、app/managed_query.py | test_knowledge_worker.py、test_managed_query.py、真实managed recovery报告 |
| LightRAG源码挂钩 | deploy/build_hr_prelimit.py、app/prelimit_adapter.py、facet_policy.py | 固定image原码及实际operate.patch；新109题四方案报告 |
| 测试冻结与指标 | evaluation/upgrade_dataset/internal-test-v1/、app/benchmark.py | freeze.json、retrieval_internal.json、逐题109报告 |
| 工程交付 | Dockerfile.upgrade、deploy/compose.upgrade.yml、.github/workflows/upgrade-checks.yml | ENGINEERING_TEST_REPORT.md、实际构建/23项部署核验 |

## 不可使用的表述

- “自主实现LightRAG底层向量/图算法”“首创截断前重排”“优于原生Reranker”：证据不支持。
- “112题全部通过”“RAG答案准确率98%”“引用正确率100%”：分别存在3题未评分、检索不等于答案、只验证部分语义与引用编号。
- “真实企业落地”“用户查找效率提升XX%”“20并发模型吞吐”：没有真实参与者，性能供应商是替身。
- “支持任意格式解析、真正流式输出、分布式高可用”：当前未实现。
- 历史39/45→44/45只属于20道开发题，不把它叫新的独立测试。

来源核查与实验保存采用脚本及自动辅助分析；没有外部真人盲评。模型别名可能变化，不能宣称锁定不可变模型权重。发布前以实际提交ID、测试日志和README为准。
