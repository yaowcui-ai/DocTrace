// Real, isolated Edge page. Only the known completed-key POST is allowed.
// playwright-core lives in a temporary tools folder, not project dependencies.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const {chromium} = require(path.join(os.tmpdir(), 'doctrace-browser-check/node_modules/playwright-core'));

const root = path.resolve(__dirname, '..');
const source = path.resolve(root, process.argv[2]);
const fixture = JSON.parse(fs.readFileSync(source, 'utf8'));
if (fixture.status !== 'passed' || fixture.kind !== 'integration_smoke_not_model_evaluation') {
  throw new Error('A passed, explicitly synthetic MySQL fixture is required');
}
const probe = fixture.probes.find(item => item.name === 'completed_first');
if (!probe || probe.body.llm_generated !== false) throw new Error('Synthetic saved answer required');
const expectedAnswer = probe.body.response;
const question = '【幂等集成测试，非政策提问】读取预先保存的测试答案。';
const base = 'http://127.0.0.1:8001';
const runId = new Date().toISOString().replace(/[-:.]/g, '') + '_' + randomUUID().slice(0, 8);
const prefix = path.join(root, 'evaluation/runs', runId + '_browser_idempotency');
const report = {kind:'browser_integration_not_model_evaluation', source, request_id:fixture.request_id,
  idempotency_key:fixture.idempotency_key, status:'started', posts:[], blocked_requests:[], page_errors:[]};
let browser;

function requireCheck(condition, label) {
  if (!condition) throw new Error(label);
}

function databaseCounts() {
  const python = [
    'import json,sys',
    'from sqlalchemy import text',
    'from app.database import create_db_engine',
    'from app.database_config import load_database_settings',
    'engine=create_db_engine(load_database_settings())',
    'with engine.connect() as conn:',
    '    total=conn.execute(text("SELECT COUNT(*) FROM qa_records")).scalar_one()',
    '    count=conn.execute(text("SELECT COUNT(*) FROM qa_records WHERE idempotency_key=:key"),{"key":sys.argv[1]}).scalar_one()',
    'print(json.dumps({"total":total,"rows_for_key":count}))',
    'engine.dispose()',
  ].join('\n');
  return JSON.parse(execFileSync(path.join(root, '.venv/Scripts/python.exe'), ['-c', python, fixture.idempotency_key],
    {cwd:root, encoding:'utf8', windowsHide:true, env:{...process.env, PYTHONIOENCODING:'utf-8'}}));
}

(async () => {
  try {
    report.database_before = databaseCounts();
    requireCheck(report.database_before.rows_for_key === 1, 'Expected one existing fixture');
    browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
    const context = await browser.newContext({viewport:{width:1280, height:900}});
    await context.route('**/*', async route => {
      const request = route.request();
      let allowed = new URL(request.url()).origin === base;
      if (request.method() === 'POST') {
        let payload;
        try {payload = request.postDataJSON();} catch {}
        allowed = allowed && new URL(request.url()).pathname === '/ask/optimized'
          && request.headers()['idempotency-key'] === fixture.idempotency_key
          && payload?.question === question;
      } else {
        allowed = allowed && ['GET', 'HEAD'].includes(request.method());
      }
      if (!allowed) {
        report.blocked_requests.push({url:request.url(), method:request.method()});
        return route.abort();
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', error => report.page_errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST') report.posts.push({url:request.url(), key:request.headers()['idempotency-key'], body:request.postData()});
    });
    await page.goto(base + '/', {waitUntil:'networkidle'});
    requireCheck(report.posts.length === 0, 'Page startup sent a POST');
    await page.evaluate(operation => sessionStorage.setItem('doctrace.pending-question.v1', JSON.stringify(operation)),
      {key:fixture.idempotency_key, question});
    await page.reload({waitUntil:'networkidle'});
    await page.locator('#pending-operation').waitFor({state:'visible'});
    requireCheck(await page.locator('#pending-question').textContent() === question, 'Original question not restored');
    requireCheck(report.posts.length === 0, 'Reload automatically sent a POST');
    report.restored_without_post = true;
    await page.screenshot({path:prefix+'_before.png', fullPage:true});

    const resultPromise = page.waitForResponse(response => new URL(response.url()).pathname === '/ask/optimized' && response.request().method() === 'POST');
    await page.locator('#retry-pending').click();
    const result = await resultPromise;
    report.http_status = result.status();
    report.response = await result.json();
    requireCheck(result.status() === 200, 'Replay did not return 200');
    requireCheck(report.response.request_id === fixture.request_id, 'Replay created another identity');
    requireCheck(report.response.response === expectedAnswer && report.response.llm_generated === false, 'Replay did not use the saved fixture');
    await page.locator('#pending-operation').waitFor({state:'hidden'});
    await page.waitForFunction(() => sessionStorage.getItem('doctrace.pending-question.v1') === null);
    requireCheck((await page.locator('#answer-content').textContent()).trim() === expectedAnswer, 'Saved answer not displayed');
    requireCheck((await page.locator('#record-info').textContent()).includes(fixture.request_id), 'Saved record identity not displayed');
    requireCheck(report.posts.length === 1 && report.blocked_requests.length === 0, 'Unexpected request count');
    requireCheck(report.page_errors.length === 0, 'Browser execution error');
    report.pending_cleared = true;
    await page.screenshot({path:prefix+'_after.png', fullPage:true});

    report.database_after = databaseCounts();
    requireCheck(JSON.stringify(report.database_after) === JSON.stringify(report.database_before), 'Database row counts changed');
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = String(error.message).slice(0, 1500);
  } finally {
    if (browser) await browser.close();
    fs.writeFileSync(prefix+'.json', JSON.stringify(report, null, 2), 'utf8');
  }
  console.log('Status:', report.status);
  console.log('Restored without POST:', report.restored_without_post);
  console.log('POST count:', report.posts.length);
  console.log('Pending cleared:', report.pending_cleared);
  console.log('Report:', prefix+'.json');
  process.exitCode = report.status === 'passed' ? 0 : 1;
})();
