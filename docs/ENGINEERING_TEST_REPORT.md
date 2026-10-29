# 工程测试与安全验证

截至2026年10月29日，北京时间。所有结论对应实际命令及保存输出；不把模拟供应商测试当真实模型性能。

## 验证结果

| 检查 | 实际结果 | 证据 |
|---|---|---|
| Python完整测试 | 1076 passed，3 skipped（MySQL需显式启用） | `evaluation/upgrade/20261029T011051Z_160732eb/` |
| 真实MySQL集成 | 3 passed；独立随机测试库，结束删除该测试库 | `evaluation/upgrade/20261029T011102Z_52f95c52/` |
| 旧JS / React状态 | 86 / 7项通过 | `evaluation/upgrade/20261029T011313Z_b78ea652/`、`20261029T011345Z_b83af7f9/` |
| React生产构建、TypeScript | 退出0 | `evaluation/upgrade/20261029T005927Z_b2da1523/` |
| Playwright真实API浏览器 | 3 passed；供应商替身，其余真实FastAPI/Cookie/SQL | `evaluation/upgrade/20261029T011021Z_01bdd7c0/` |
| Docker最新应用/worker构建启动 | 退出0，应用健康，独立MySQL健康 | `evaluation/upgrade/20261029T011042Z_3538da25/` |
| 实际部署只读验收 | 24项通过；真实登录/退出/权限/报告/静态页面/SQL，0模型调用 | `evaluation/upgrade/20261029T012607Z_deployment_f21bcf19/report.json` |
| 旧知识库及源码补丁保留 | 68份来源哈希、固定原码、生成补丁、部署补丁一致 | `evaluation/upgrade/20261029T011337Z_audit_a45831f1/` |
| 新测试冻结 | 数据集及7个算法文件哈希一致 | `evaluation/upgrade_dataset/internal-test-v1/freeze.json` |
| 原生选择器宿主/容器等价 | 109题×4方案的选中ID及渲染token相同 | `evaluation/upgrade/reports/selector_equivalence.json` |

原始日志中保留预期失败与执行错误：首次pytest误收集backups造成98个错误；新增边界测试先失败再修复；浏览器首次复跑误用旧dist，构建后通过；部署核验脚本把正确204退出误写成200，按既有契约修正后通过。没有覆盖旧失败日志。

## 实际覆盖的安全及故障边界

- 账号隔离：Cookie身份、X-DocTrace预期账号、他人会话/问答/引用不可读；普通成员的文档及评测管理请求403。客户端隐藏按钮不能替代服务端权限。
- 幂等：账号级唯一键；同键改问题、会话、模式、知识库409；实际MySQL八并发同键只执行一次供应商替身。刷新不自动重发，手动恢复沿用原键。
- 历史关联：并发导入不能抢占正在处理的消息；旧问答保留原corpus与实际记录的模式，不把旧未知模式伪装成naive。
- 上传：仅管理员、UTF-8 .txt/.md、1MiB，拒绝PDF/Word、异常编码、NUL、危险路径、空文件及超限请求。未实现PDF/Word解析；不能宣传支持任意文件。
- 索引任务：重复hash/重复排队去重，专属9631服务标题/工作空间校验；提交超时记submission_unknown，不自动重入库。已processed新版本才切换，撤销版本先从回答白名单排除。
- 版本竞争：提问绑定生效版本指纹，检索前、生成前、生成后复核。处理期间版本改变返回409，避免把新内容标成旧快照。不能保证校验后永不再次更新，保存记录表示当时快照。
- 失败：Mock验证模型超时、检索/重排失败、MySQL写入失败、无证据；重排降级显式标记，生成未确认不能声称模型已成功。
- 前端：真实API测试登录、旧记录导入、搜索、naive/mix、引用、反馈刷新回显、同账号草稿、丢响应同键恢复、迟到响应跨账号清除、过期会话清除、管理员上传排队、窄屏及102个会话分页。证据纯文本渲染，不执行文档指令/HTML。
- 日志与报告：错误固定安全消息；报告ID白名单；无原始数据库错误、Cookie或密钥回传。请求统计只返回聚合值，排除合成负载。
- 真实模型注入烟测3次；一次词面规则误报保留，范围仅固定证据，不承诺防御所有提示词注入。

## 真实性与待补充项

真实小文档已在9631完成解析/向量/实体关系索引，一次实际托管回答已保存。脚本在保存报告时遇到日期序列化错误，后用只读恢复取回同一结果，未重复提问。真实版本更新/撤销的整轮供应商验收尚未执行；相应状态机由Mock/API/SQL测试覆盖。

并发1/5/10/20是实际HTTP+MySQL和模拟0.1秒供应商，每档20次；单账号准入上限1，高并发主要返回429。保存吞吐、成功/失败、P50/P95及末尾资源快照，未采集全过程资源峰值。没有以本实验推算真实模型并发、冷启动速度或生产SLA。

工作器持久化全局锁在硬崩溃后可能需要人工核对；不自动清锁，以免重复已经计费的入库。并发/登录限流为单进程版本；未交付分布式限流、跨节点可用性或公网TLS。运行账户初始化拥有独立升级库DDL权限，尚未拆成迁移账户和最小运行账户，不能声称生产最小权限部署。

## 重现命令

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -c "import tiktoken; tiktoken.encoding_for_model('gpt-4o-mini')"
.\.venv\Scripts\python.exe scripts/upgrade_check.py --label backend -- .\.venv\Scripts\python.exe -m pytest -q
npm ci
npm run test:frontend
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
```

MySQL集成读取已忽略的`runtime/upgrade/.env`，仅连接明确的3310独立升级实例。设置`DOCTRACE_MYSQL_INTEGRATION=1`后运行`tests/integration/test_mysql_upgrade.py`，结束移除该环境变量。不要对旧3306执行初始化或清库。真实模型脚本均要求显式`--execute`，常规测试不调用模型。

实际一键启动脚本曾因PowerShell单字符串展开报错，现已强制使用字符串数组并实际运行通过，失败与修复日志保留。

GitHub Actions配置为`.github/workflows/upgrade-checks.yml`，执行离线供应商测试、旧JS、React构建和真实API浏览器，并保存XML/截图。运行依赖安装和公开tokenizer词表下载需要网络；测试不需要模型密钥。远端状态应以该分支实际Actions结果为准。

发布副本在不提供私有.env的条件下另跑1076项Python和3条Playwright流程通过；修正了一个将仓库名写死的旧测试。副本证据：`evaluation/upgrade/20261029T012544Z_d64878e7/`、`20261029T012555Z_fdd74058/`。
