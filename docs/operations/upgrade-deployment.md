# 隔离升级环境

本环境的 Compose 项目固定为 `doctrace-upgrade`，数据库为 `doctrace_upgrade`，数据库端口只绑定 `127.0.0.1:3310`，网页端口为 `127.0.0.1:8005`。数据库和日志使用该项目独立命名卷。旧 `doctrace` 数据库、原生 3306 服务、8001 应用及其他 Compose 项目不参与初始化。

在 `doctrace` 目录运行；配置生成器只复制提供商密钥、URL 和模型名称，另行生成升级数据库、root、管理员及管理知识库服务密钥。它不会显示密钥或覆盖已有配置。私有文件位于已被父仓库忽略的 `runtime/upgrade/.env`，不得提交或复制到报告。首次登录账号为 `upgrade_admin`；密码在该私有文件的 `UPGRADE_ADMIN_PASSWORD` 中，可通过本机编辑器查看。

```powershell
.\.venv\Scripts\python.exe scripts/init_upgrade_config.py
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml config --quiet
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml up -d --build
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml ps
```

容器启动先等待独立 MySQL 账户可查询，显式执行 `python -m app.upgrade_setup --initialize --admin upgrade_admin`，再启动 Uvicorn。初始化仅允许 `doctrace_upgrade` 搭配宿主 loopback:3310 或容器 `mysql:3306`，其他初始化目标在连接前拒绝。建表幂等，不覆盖已有密码。指定的管理员若已是普通用户，必须人工增加 `--grant-existing-admin`；不会暗中提升已有用户。

React 页面为 `http://127.0.0.1:8005/workspace/`，原版界面为 `http://127.0.0.1:8005/`。`/health` 仅检查应用存活；不调用模型，也不证明提供商或完整问答链路可用。数据库健康检查只执行 `SELECT 1`。本地 HTTP 仅供本机使用，不属于公网生产部署。

升级配置使用 `DOCTRACE_SESSION_COOKIE=doctrace_upgrade_session`，与原版登录 Cookie 区分。升级数据库的会话不能用于另一个环境读取数据；原版 Cookie 不会被升级登录覆盖。

升级问答通过容器宿主网关只查询已有 v3 HR 实例 9624，不导入或修改冻结知识库。文档管理使用独立目标 9631，必须由管理客户端验证专属标题和工作空间。`MANAGED_LIGHTRAG_API_KEY` 是新生成的专属服务密钥，须与 9631 实例一致；未配置该专属实例时，管理任务会失败关闭，不能切换到 9624 入库。

工作器可通过managed-worker profile常驻顺序处理，仅处理管理员明确排队的任务；不会自动发现或上传文件。也可以manual-worker执行一次。索引可能消耗已有服务额度，提交未知不自动重复入库。

```powershell
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml --profile manual-worker run --rm worker --once
```

需要创建普通账户时，通过隐藏输入或临时 `UPGRADE_USER_PASSWORD` 环境变量，执行独立库中的创建命令。普通账户不会获得管理员角色；已有账户密码和角色不会被此命令更改。

```powershell
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml exec app python -m app.upgrade_setup --create-user example_user
```

宿主机直接初始化可使用 `--env-file runtime/upgrade/.env`；生成文件中数据库连接即 loopback:3310。高级 `--tables-only --confirm-database <精确库名>` 模式只增加产品和管理知识库表，不创建旧表、不创建或提升账户。本次交付不在旧数据库执行该模式。

停止环境使用同一明确项目命令，不增加 `--volumes`：

```powershell
docker compose --env-file runtime/upgrade/.env -f deploy/compose.upgrade.yml down
```

停写后保存独立 MySQL 数据卷与管理知识库的独立索引目录；恢复到另一个明确的隔离目标后，再检查用户、问答、引用 UTF-8、角色、会话和任务状态。首次部署结果以实际构建、健康和登录验证记录为准，单元测试通过不代表容器已运行。


## 一键入口与实际验收

`./scripts/start_upgrade.ps1`先核对引擎/私有配置，启动专属9631及8005/MySQL/worker；`-NoBuild`复用已经构建的应用。`./scripts/stop_upgrade.ps1`只停止两个明确升级Compose项目，不删除卷。新克隆需先按README配置供应商；冻结9624索引并不附在仓库，管理上传库可独立使用。

2026-10-29最新代码已实际构建并启动，真实MySQL3项集成、浏览器3条流程及24项部署核验通过；详细命令/失败与限制见ENGINEERING_TEST_REPORT。常规验收只读已有记录，不重复调用模型。运行账户仍拥有隔离升级库DDL权限，公网部署前应另拆迁移账户与最小权限运行账户。
