# 从源码运行 DocTrace

公开演示见 <https://yaowcui-ai.github.io/DocTrace/>。下面说明实际后端的本地配置；演示回放本身不需要这些服务。

## 1. 环境和依赖

需要 Python 3.11、Node.js 24、MySQL 8.0 和 Docker。操作示例以项目根目录的 PowerShell 为例：

```powershell
git clone https://github.com/yaowcui-ai/DocTrace.git
Set-Location DocTrace
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
npm ci
```

## 2. 数据库

在 MySQL Workbench 的管理员连接中建立空库和运行账号，将示例占位密码替换成自己的密码：

```sql
CREATE DATABASE doctrace CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'doctrace_app'@'127.0.0.1' IDENTIFIED BY '<choose-a-private-database-password>';
GRANT SELECT, INSERT, UPDATE ON doctrace.* TO 'doctrace_app'@'127.0.0.1';
```

然后依次执行 `sql/001_create_qa_records.sql` 至 `sql/007_add_request_mode.sql`，每个文件只执行一次。它们是有顺序的结构迁移，不是可以反复批量执行的数据导入文件。数据库中不会自动创建演示用户、历史记录或会话。

```powershell
Copy-Item .env.example .env
```

在 `.env` 中填写自己的 `MYSQL_*` 配置。账号数据库密码和网页用户密码用途不同。

## 3. LightRAG 与模型配置

```powershell
Copy-Item .lightrag.env.example .lightrag.env
docker pull ghcr.io/hkuds/lightrag@sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e
```

编辑 `.lightrag.env`，填入：

- `LIGHTRAG_API_KEY`：自己生成的本机服务保护密钥，与 DocTrace `.env` 中的同名项保持一致。
- `LLM_BINDING_API_KEY` / `LLM_BINDING_HOST` / `LLM_MODEL`：支持 OpenAI 兼容协议的生成服务。`openai` 表示协议适配，不表示必须调用 OpenAI。
- `EMBEDDING_BINDING_API_KEY` / `EMBEDDING_BINDING_HOST` / `EMBEDDING_MODEL`：Embedding 服务；示例使用 BGE-M3、1024 维。更换向量生成方式后需重新建立兼容索引。

编辑 DocTrace `.env` 中的 `RERANK_*` 和 `ANSWER_*`，使用自己账号中可用的模型名称及供应商端点。两份配置的模型和服务鉴权用途不同。模板中的模型名不代表账号一定已开通该模型。

```powershell
.\.venv\Scripts\python.exe deploy/build_hr_prelimit.py
.\.venv\Scripts\python.exe deploy/prepare_hr_prelimit_env.py
docker compose -f deploy/compose.public.yml up -d
```

该配置只将知识库映射到本机 `127.0.0.1:9624`，使用空的 `runtime/gitlab_hr_v3` 持久化目录。等待服务初始化后访问 <http://127.0.0.1:9624/webui/>，用自己配置的服务密钥进入。

## 4. 建立自己的索引

`data/gitlab_hr/v3/sources.json` 列出冻结的 68 份来源；对应 `cleaned/` 文件保留 GitLab 链接和 CC BY-SA 4.0 转换说明。通过 LightRAG 管理页上传这 68 份 Markdown，配置固定切分 1200 token、重叠 100，等待每份文档达到 processed。

上传已接收不等于索引完成。入库会进行文本向量化、实体关系抽取和索引保存，因而会产生供应商调用费用。仓库没有分发已建立的向量/图索引，也不会在安装或测试时自动替你入库。

本仓库的 `app.ingest_hr_v2` 是早期 v2 的固定批次实验工具，不能用于直接建立 v3。复现旧实验时须按原文件说明使用，不要把其端口或数据目录误认为当前库。

## 5. 创建账户并启动业务服务

确认 `.env` 的 `HR_LIGHTRAG_URL` 为 `http://127.0.0.1:9624`，`HR_CORPUS_ID=gitlab_hr_v3`；旧 `/ask` 的 `LIGHTRAG_URL` 也可明确指向自己的实例。

```powershell
.\.venv\Scripts\python.exe -m app.create_user --username alice
# 按提示交互输入网页密码，不在命令行参数中写密码。
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

访问 <http://127.0.0.1:8001/>，登录后选择 naive 或 mix 提问。`AUTH_ALLOWED_ORIGIN` 应与访问地址一致；配置为 `127.0.0.1` 时不要换用 `localhost`。`/health` 只证明业务进程存活，不能证明模型和索引均可用。

## 6. 离线验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
npm run test:frontend
```

只看本地静态演示：

```powershell
py scripts/serve-demo.py --port 8080
```

打开 <http://127.0.0.1:8080/>。浏览器必须通过 HTTP 读取演示数据，不能直接双击 HTML 后用 `file://` 打开。

## 配置与数据范围

`.env.example` 和 `.lightrag.env.example` 只有配置项，没有实际密钥。`.env`、`.lightrag.env`、运行时目录、日志、数据库备份和私人记录被 Git 忽略。当前应用为学习与本地演示实践，未宣称完成公网生产的容量、限流或故障恢复保障。
