# DocTrace：企业 HR 政策 AI 全栈问答系统

[GitHub源码](https://github.com/yaowcui-ai/DocTrace) · [免登录结果回放](https://yaowcui-ai.github.io/DocTrace/)

React/TypeScript + FastAPI + LightRAG + BGE-M3/BGE Reranker + MySQL + Docker。基于现有项目增量升级，68份GitLab公开HR政策、318个片段；没有训练大模型。在线Pages演示仍是保存结果回放，不是实时React服务。真实React工作台需本地启动。

## 已交付的功能

- 登录、个人会话、问题内容搜索、分页历史、基础多轮上下文、刷新恢复及手动同键重试。
- naive / mix单链路选择，默认naive；原文引用卡片、本人引用快照、回答反馈及降级提示。
- 管理员上传UTF-8 .txt/.md、索引状态、版本更新及停用；固定独立可写知识库，不覆盖冻结实验库。仅processed版本进入回答。
- FastAPI版本化Pydantic契约、MySQL短事务、账号级请求幂等、Cookie会话、角色和记录归属、受限并发、阶段日志。
- 管理员只读实验报告、失败案例及真实请求聚合统计。普通用户看不到管理入口，后端也会拒绝其管理请求。
- React同源Docker交付；旧页面和接口保留。真正的模型流式输出尚未实现，页面明确等待完整答案。

这是一套可本机部署和复现的产品实践，不宣称已在真实企业上线、多租户隔离、分布式高可用或公网生产安全验收。

## 可核查结果

| 证据 | 实际结果与边界 |
|---|---|
| 历史开发20题/45组 | 关闭重排39/45；原生与自定义整句43/45；条件性融合44/45。保留退化案例，非新测试 |
| 新冻结内部测试112题 | 109题可评分、3题超时/中断未评分；证据组109/124→122/124。原生B1、自定义B2/B3本轮相同 |
| 生成12题、24次请求 | B0主结论8完整/2部分/2未答；B1/B2/B3为11完整/1部分。选取类型覆盖样本，不是全测试答案准确率 |
| 工程 | 1076项Python通过、3项真实MySQL集成通过、旧JS86项、React状态7项、Playwright真实API流程3项 |
| 部署 | 隔离Docker实际构建、24项登录/权限/报告只读检查；原库/快照哈希复核 |
| 性能/业务 | 保存1/5/10/20合成供应商并发测试；8项模拟查找任务双方均7/8完整。没有真人效率提升结论 |

**源码核查发现：固定版本LightRAG原生已经在top-k/token截断之前重排。** 项目增加的是源码挂钩、自定义策略、故障可观测性与业务工程，不把原生已有的顺序说成原创算法，也不声称本轮优于原生重排。

## 文档与代码阅读

- [升级审计与优先级](docs/UPGRADE_AUDIT.md)
- [实际架构与生命周期](docs/ARCHITECTURE.md)
- [冻结与实验设计](docs/EXPERIMENT_DESIGN.md)
- [实际实验数据及失败](docs/EVALUATION_REPORT.md)
- [工程、安全与性能验证](docs/ENGINEERING_TEST_REPORT.md)
- [模拟业务价值](docs/BUSINESS_VALUE.md)
- [简历与逐项证据](docs/RESUME_EVIDENCE.md)
- [部署、停止与恢复边界](docs/operations/upgrade-deployment.md)
- [旧版演示说明](guide/demo-guide.md)

关键目录：`frontend/`是React；`app/product/`是接口、服务及存储；`app/knowledge/`是文档状态机和worker；`app/managed_query.py`过滤生效版本；原问答及LightRAG策略继续使用`qa_pipeline.py`、`prelimit_adapter.py`、`facet_policy.py`和`deploy/build_hr_prelimit.py`。

## Windows 本地启动

需要Docker Desktop Linux引擎、Python3.11+；前端本地开发需要Node24。模型及Embedding可以复用已有服务，仓库不提供免费API额度，不会默认采购服务。

```powershell
Set-Location 'C:\Users\86139\Documents\ChatGPT\实习项目\doctrace'
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -r requirements-dev.txt
```

首次配置：复制`.env.example`到私有`.env`，填回答模型和重排配置。使用现有配置时不要覆盖。运行：

```powershell
.\.venv\Scripts\python.exe scripts/init_upgrade_config.py
```

新环境将`.lightrag.env.example`复制为私有`.lightrag.env`，填写LLM/Embedding配置，然后运行：

```powershell
.\.venv\Scripts\python.exe scripts/init_managed_config.py --source .lightrag.env
.\scripts\start_upgrade.ps1
```

当前已有环境可省去配置生成，直接运行启动脚本。生成器不覆盖已有私有文件。容器创建独立`doctrace_upgrade`数据库与3310端口；工作台8005，独立托管LightRAG9631。管理员`upgrade_admin`，密码只在`runtime/upgrade/.env`的`UPGRADE_ADMIN_PASSWORD`，不要提交或截图。

- React工作台：[http://127.0.0.1:8005/workspace/](http://127.0.0.1:8005/workspace/)
- 旧界面：[http://127.0.0.1:8005/](http://127.0.0.1:8005/)
- OpenAPI：[http://127.0.0.1:8005/docs](http://127.0.0.1:8005/docs)

首次克隆没有向量/图索引：可通过管理员上传政策，等待processed后选择“托管政策库”问答；索引会使用已配置模型。选择“冻结HR库”还需要按旧部署文档准备9624服务及68份政策索引；本仓库不附带密钥、数据库或完整向量/图运行目录。不能把空机器启动网页当成冻结知识库已复现。

新增普通账户：

```powershell
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml exec app python -m app.upgrade_setup --create-user example_user
```

关闭升级服务（保留数据库和索引，不影响其他项目）：

```powershell
.\scripts\stop_upgrade.ps1
```

不要执行`down --volumes`或删除runtime。`/health`仅表示应用存活；模型、数据库及索引是否可用需分阶段验证。worker仅处理管理员明确排队的任务，未知提交不自动重做。

## 测试与演示流程

```powershell
.\.venv\Scripts\python.exe -c "import tiktoken; tiktoken.encoding_for_model('gpt-4o-mini')"
.\.venv\Scripts\python.exe -m pytest -q
npm ci
npm run test:frontend
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
```

Playwright使用临时SQL数据库和真实FastAPI/Cookie接口，仅供应商替换为离线fixture，不连接真实个人历史或付费模型。真实MySQL集成需显式环境开关，见工程报告。GitHub Actions保留XML和浏览器截图，依赖安装需联网，测试无须模型密钥。

本地演示：登录→新建会话→选择库和naive→提问→展开引用→提交反馈→刷新/搜索历史→选择mix另问一次；管理员再演示文档上传→提交索引→processed→托管问答→只读实验报告。上传成功不等于索引完成。避免重复索引同文档或自动重试未知付费请求。

## 许可、数据与限制

公开政策是GitLab Handbook快照，来源URL、版本及许可见[第三方声明](THIRD_PARTY_NOTICES.md)。项目非GitLab官方产品，不提供个人工资、员工工时、预算余额或审批记录。证据不足应说明无法确认。

NanoVectorDB保存向量、NetworkX保存图、JSON保存LightRAG部分元数据；MySQL保存业务身份、问答和任务，未使用Milvus。API模型别名可能变化，不能保证权重版本不变。源码、脱敏摘要与原始尝试分别保存；不会把AI辅助核查写成外部真人盲评。
