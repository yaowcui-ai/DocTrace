// Runs a real FastAPI/SQLite app with only the upstream provider replaced by the
// explicitly offline fixture. No production database, credentials or model calls.
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, join, resolve, sep} from 'node:path';
import {createServer} from 'node:net';
import {fileURLToPath} from 'node:url';

const frontend = resolve(fileURLToPath(new URL('..', import.meta.url)));
const root = resolve(frontend, '..');
let server;
let temp;
let output = '';
let target = process.env.DOCTRACE_E2E_BASE_URL;
try {
  if (!target) {
    const fixture = join(root, 'tests', 'support', 'product_browser_server.py');
    if (!existsSync(fixture)) throw new Error(`Offline API fixture is missing: ${fixture}`);
    const python = process.env.DOCTRACE_E2E_PYTHON ?? join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    if (!existsSync(python)) throw new Error('Project Python environment is missing; set DOCTRACE_E2E_PYTHON.');
    const port = await new Promise((accept, reject) => {
      const socket = createServer();
      socket.on('error', reject);
      socket.listen(0, '127.0.0.1', () => {const address = socket.address(); socket.close(() => accept(address.port));});
    });
    temp = await mkdtemp(join(tmpdir(), 'doctrace-browser-'));
    target = `http://127.0.0.1:${port}`;
    server = spawn(python, ['-u', fixture, join(temp, 'browser.sqlite3'), String(port)], {cwd: root, env: {...process.env, PYTHONUNBUFFERED: '1', PYTHONPATH: root}, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
    const capture = data => {output = (output + data.toString()).slice(-20_000);};
    server.stdout.on('data', capture); server.stderr.on('data', capture);
    let ready = false;
    for (let attempt = 0; attempt < 120; attempt++) {
      if (server.exitCode !== null) throw new Error(`Offline fixture exited: ${output}`);
      try {const response = await fetch(`${target}/api/v1/me`); if (response.status === 401 || response.ok) {ready = true; break;}} catch {}
      await new Promise(accept => setTimeout(accept, 250));
    }
    if (!ready) throw new Error(`Offline fixture did not become ready: ${output}`);
  }
  console.log(`Running actual API browser acceptance against ${target}; upstream is the offline fixture.`);
  const child = spawn(process.execPath, [join(frontend, 'node_modules', '@playwright', 'test', 'cli.js'), 'test', '--reporter=list,json'], {cwd: frontend, env: {...process.env, DOCTRACE_E2E_BASE_URL: target, PLAYWRIGHT_JSON_OUTPUT_NAME: join(frontend, 'test-results', 'actual-api-results.json')}, stdio: 'inherit', windowsHide: true});
  const code = await new Promise((accept, reject) => {child.on('error', reject); child.on('exit', accept);});
  process.exitCode = typeof code === 'number' ? code : 1;
  if (process.exitCode) console.error(output);
} catch (error) {console.error(error.message); process.exitCode = 1;}
finally {
  if (server && server.exitCode === null) {server.kill(); await new Promise(accept => {server.once('exit', accept); setTimeout(accept, 3000);});}
  if (temp) {
    const targetPath = resolve(temp);
    if (!targetPath.startsWith(resolve(tmpdir()) + sep) || !basename(targetPath).startsWith('doctrace-browser-')) throw new Error('Refusing unexpected temporary cleanup target.');
    await rm(targetPath, {recursive: true, force: true, maxRetries: 5, retryDelay: 200});
  }
}
