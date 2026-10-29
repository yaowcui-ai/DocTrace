# DocTrace React 工作台

React / TypeScript / Vite，生产资源前缀固定为 `/workspace/`。沿用深绿、灰白的原工作台视觉；原版入口为 `/`。

```powershell
npm ci
npm test
npm run build
npm run test:e2e
```

`npm run build` 先执行 TypeScript 检查，再生成 `dist/`。FastAPI 挂载这个构建目录。开发时 `npm run dev` 将 `/auth`、`/api` 代理到本机 8001；认证 Origin 必须与实际访问地址匹配。

`npm test` 使用 Node 内置测试器验证身份切换、待处理操作和 HTTP 契约。`npm run test:e2e` 启动 `tests/support/product_browser_server.py`，创建临时 SQLite，运行真正的登录 Cookie、SQL 仓储与 API；仅模型供应商由明确的离线 fixture 替代。测试不连接实际供应商、不启动索引 worker、不写生产数据库。浏览器测试包括生成响应丢失后的同键恢复、刷新不自动重发、引用归属、反馈、个人历史、管理员权限与文档排队。浏览器截图在 `frontend/test-results/`。

需 Node 24+ 和 Playwright Chromium（缺失时运行 `npx playwright install chromium`）。可用 `DOCTRACE_E2E_PYTHON` 指定项目 Python，或 `DOCTRACE_E2E_BASE_URL` 指向已启动的同类离线测试服务器。

产品请求均为同源 Cookie 加 `X-DocTrace-User-ID`，问答另带固定 UUID `Idempotency-Key`。待处理问题保存在当前浏览器 tab 的 `sessionStorage`，按已确认用户隔离；刷新只恢复信息，用户手动点击才重新提交原操作。账户变更和 401 清除页面私有数据并丢弃旧响应。服务端仍负责最终认证、归属和幂等约束。

每次提问可选择冻结 HR 库或管理员上传的托管政策库。知识库随操作保存，恢复原操作时不会跟随界面当前选择切换；旧版本待处理操作默认恢复到冻结库。托管库仅使用已索引政策，空库或缺少依据时应明确返回没有依据。

当前回答与引用按纯文本显示。文档管理只接收 UTF-8 `.txt` / `.md`、1 MiB 以内的文件，保存文档与排队索引分开操作，页面不会把上传成功显示成索引完成；任务由独立 worker 处理。管理报告只读。此版本尚未实现真实模型流式输出，等待状态显示完整请求处理过程。
