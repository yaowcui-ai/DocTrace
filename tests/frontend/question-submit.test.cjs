// Native Node tests: real controller source, fake UI and network, zero model calls.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const RESULT = {response:'测试答案', references:[], llm_generated:true,
  request_id:'79060ce7-f617-4db9-a3e3-804e7f3b012a'};
const ok = () => ({ok:true, status:200, json:async () => RESULT});

async function boot(handler = ok, options = {}) {
  const filename = path.join(__dirname, '../../app/web/question.js');
  assert.ok(fs.existsSync(filename), 'Create app/web/question.js first');
  const listeners = {};
  const input = {value:''};
  const modeInput = {value:options.mode ?? 'naive'};
  const calls = [];
  let operation = options.pending ?? null;
  let sequence = 0;
  const ui = {busy:[], waiting:0, answers:[], errors:[], refreshed:[], pending:[]};
  const context = vm.createContext({
    document:{getElementById(id) {
      if (id === 'question') return input;
      if (id === 'retrieval-mode') return modeInput;
      if (id === 'question-form') return {addEventListener(type, fn) {listeners[type] = fn;}};
      if (id === 'retry-pending') return {addEventListener(type, fn) {listeners.retry = fn;}};
      if (id === 'discard-pending') return {addEventListener(type, fn) {listeners.discard = fn;}};
      throw new Error('Unexpected controller DOM access: ' + id);
    }},
    fetch:async (url, options) => {calls.push({url, options}); return handler();},
  });
  const identity = {user:options.anonymous ? null : {user_id:'00000000-0000-4000-8000-000000000001'}, revision:1};
  const exports = {
    './auth-state.js':{
      getIdentity:() => identity,
      isCurrent:() => true,
      onIdentityChange:() => {},
      privateFetch:async (url, options) => {calls.push({url, options}); return handler();},
    },
    './history.js':{loadHistory:async offset => {ui.refreshed.push(offset);}},
    './pending-operation.js':{
      readPendingOperation:() => {
        if (options.readFailure) throw new Error('storage read failed');
        return operation;
      },
      createPendingOperation:(question, owner, mode) => {
        if (options.writeFailure) throw new Error('storage write failed');
        operation = {key:`00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}`, question, mode};
        return operation;
      },
      clearPendingOperation:key => {
        if (options.clearFailure) throw new Error('storage clear failed');
        if (operation?.key === key) operation = null;
      },
    },
    './question-view.js':{
      setQuestionBusy:value => ui.busy.push(value),
      showQuestionWaiting:() => {ui.waiting += 1;},
      showSubmittedAnswer:(...args) => ui.answers.push(args),
      showQuestionFailure:(...args) => ui.errors.push(args),
      showPendingOperation:value => ui.pending.push(value),
    },
  };
  const module = new vm.SourceTextModule(fs.readFileSync(filename, 'utf8'), {context});
  await module.link(async name => {
    const values = exports[name];
    assert.ok(values, 'Unexpected import: ' + name);
    return new vm.SyntheticModule(Object.keys(values), function () {
      for (const [key, value] of Object.entries(values)) this.setExport(key, value);
    }, {context});
  });
  await module.evaluate();
  assert.equal(typeof listeners.submit, 'function', 'Register the form submit handler');
  let prevented = 0;
  return {calls, ui, async submit(value) {
    input.value = value;
    return listeners.submit({preventDefault() {prevented += 1;}});
  }, prevented:() => prevented, pending:() => operation,
    async retry() {
      assert.equal(typeof listeners.retry, 'function', 'Register retry-pending click handler');
      return listeners.retry();
    },
    async discard() {
      assert.equal(typeof listeners.discard, 'function', 'Register discard-pending click handler');
      return listeners.discard();
    },
  };
}

test('page startup never automatically sends a paid question', async () => {
  const app = await boot();
  assert.equal(app.calls.length, 0);
  assert.equal(app.ui.busy.at(-1), false);
});

test('whitespace question is rejected without a request', async () => {
  const app = await boot();
  await app.submit('   ');
  assert.equal(app.calls.length, 0);
  assert.equal(app.ui.errors.length, 1);
  assert.equal(app.prevented(), 1);
});

test('overlong question is rejected without a request', async () => {
  const app = await boot();
  await app.submit('x'.repeat(2001));
  assert.equal(app.calls.length, 0);
  assert.equal(app.ui.errors.length, 1);
});

test('one POST sends trimmed JSON and displays the saved answer', async () => {
  const app = await boot();
  await app.submit('  中文问题  ');
  assert.equal(app.calls.length, 1);
  const call = app.calls[0];
  assert.equal(call.url, '/ask/optimized');
  assert.equal(call.options.method, 'POST');
  assert.equal(call.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(call.options.body), {question:'中文问题', mode:'naive'});
  assert.equal(app.ui.answers[0][0], RESULT);
  assert.equal(app.ui.answers[0][1], '中文问题');
  assert.deepEqual(app.ui.refreshed, [0]);
  assert.deepEqual(app.ui.busy, [false, true, false]);
});

test('a second submit while pending does not start another POST', async () => {
  let finish;
  const pending = new Promise(resolve => {finish = resolve;});
  const app = await boot(() => pending);
  const first = app.submit('第一次');
  await app.submit('第二次');
  assert.equal(app.calls.length, 1);
  finish(ok());
  await first;
  assert.equal(app.ui.answers.length, 1);
  assert.equal(app.ui.busy.at(-1), false);
});

test('explicit mix selection is sent and retained on retry', async () => {
  const app = await boot(() => ({ok:false, status:504, json:async () => ({detail:'timeout'})}), {mode:'mix'});
  await app.submit('Question');
  await app.retry();
  assert.equal(JSON.parse(app.calls[0].options.body).mode, 'mix');
  assert.equal(JSON.parse(app.calls[1].options.body).mode, 'mix');
  assert.equal(app.calls[0].options.headers['Idempotency-Key'], app.calls[1].options.headers['Idempotency-Key']);
});

test('retry uses saved mode instead of current selector', async () => {
  const app = await boot(ok, {mode:'naive', pending:{key:'1e533ba9-d7d6-490c-8945-c42e11836ea9', question:'Saved', mode:'mix'}});
  await app.retry();
  assert.equal(JSON.parse(app.calls[0].options.body).mode, 'mix');
});

test('HTTP failure keeps its ID, stage, status and never retries', async () => {
  const app = await boot(() => ({ok:false, status:504, json:async () => ({
    detail:{message:'等待回答超时', stage:'回答模型', request_id:RESULT.request_id},
  })}));
  await app.submit('测试');
  assert.equal(app.calls.length, 1);
  assert.equal(app.ui.answers.length, 0);
  assert.deepEqual(app.ui.errors[0], ['等待回答超时', RESULT.request_id, '回答模型', 504]);
  assert.equal(app.ui.busy.at(-1), false);
  assert.deepEqual(app.ui.refreshed, [0]);
});

test('network failure says outcome is uncertain and does not resend', async () => {
  const app = await boot(() => {throw new Error('offline');});
  await app.submit('测试');
  assert.equal(app.calls.length, 1);
  assert.match(app.ui.errors[0][0], /未能确认/);
  assert.equal(app.ui.answers.length, 0);
  assert.equal(app.ui.busy.at(-1), false);
});

test('invalid response JSON does not claim the model never ran', async () => {
  const app = await boot(() => ({ok:true, status:200, json:async () => {throw new SyntaxError('bad JSON');}}));
  await app.submit('测试');
  assert.equal(app.calls.length, 1);
  assert.match(app.ui.errors[0][0], /未能确认/);
  assert.equal(app.ui.busy.at(-1), false);
});

test('malformed 200 response is not displayed as a completed answer', async () => {
  const app = await boot(() => ({ok:true, status:200, json:async () => ({response:123})}));
  await app.submit('测试');
  assert.equal(app.calls.length, 1);
  assert.equal(app.ui.answers.length, 0);
  assert.equal(app.ui.errors.length, 1);
  assert.equal(app.ui.busy.at(-1), false);
});

test('successful submit sends a saved key and then clears pending operation', async () => {
  const app = await boot();
  await app.submit('新问题');
  assert.match(app.calls[0].options.headers['Idempotency-Key'], /^[0-9a-f-]{36}$/);
  assert.equal(app.pending(), null);
});

test('manual network retry preserves original key and question', async () => {
  let attempt = 0;
  const app = await boot(() => {if (++attempt === 1) throw new Error('offline'); return ok();});
  await app.submit('原问题');
  assert.equal(app.pending()?.question, '原问题');
  await app.retry();
  assert.equal(app.calls.length, 2);
  assert.equal(app.calls[0].options.headers['Idempotency-Key'], app.calls[1].options.headers['Idempotency-Key']);
  assert.equal(app.calls[0].options.body, app.calls[1].options.body);
  assert.equal(app.pending(), null);
});

test('reload restores an operation but never automatically sends it', async () => {
  const pending = {key:'1e533ba9-d7d6-490c-8945-c42e11836ea9', question:'保存的原问题'};
  const app = await boot(ok, {pending});
  assert.equal(app.calls.length, 0);
  assert.equal(app.ui.pending.at(-1), pending);
  await app.retry();
  assert.equal(app.calls[0].options.headers['Idempotency-Key'], pending.key);
  assert.equal(JSON.parse(app.calls[0].options.body).question, pending.question);
});

test('editing and submitting cannot silently replace an unresolved operation', async () => {
  const pending = {key:'1e533ba9-d7d6-490c-8945-c42e11836ea9', question:'原问题'};
  const app = await boot(ok, {pending});
  await app.submit('编辑后的新问题');
  assert.equal(app.calls.length, 0);
  assert.equal(app.pending(), pending);
  assert.equal(app.ui.errors.length, 1);
  await app.retry();
  assert.equal(JSON.parse(app.calls[0].options.body).question, '原问题');
});

test('ending tracking sends nothing and allows an explicitly new operation', async () => {
  const pending = {key:'1e533ba9-d7d6-490c-8945-c42e11836ea9', question:'原问题'};
  const app = await boot(ok, {pending});
  await app.discard();
  assert.equal(app.calls.length, 0);
  assert.equal(app.pending(), null);
  await app.submit('原问题');
  assert.notEqual(app.calls[0].options.headers['Idempotency-Key'], pending.key);
});

test('repeated retry clicks while busy send only once', async () => {
  let finish;
  const pendingResponse = new Promise(resolve => {finish = resolve;});
  const app = await boot(() => pendingResponse, {pending:{key:'1e533ba9-d7d6-490c-8945-c42e11836ea9', question:'原问题'}});
  const first = app.retry();
  await app.retry();
  assert.equal(app.calls.length, 1);
  finish(ok());
  await first;
});

test('storage write failure stops before network request', async () => {
  const app = await boot(ok, {writeFailure:true});
  await app.submit('问题');
  assert.equal(app.calls.length, 0);
  assert.equal(app.ui.errors.length, 1);
});

test('storage read failure blocks submission instead of replacing the key', async () => {
  const app = await boot(ok, {readFailure:true});
  await app.submit('问题');
  assert.equal(app.calls.length, 0);
  assert.ok(app.ui.errors.length >= 1);
});

test('cleanup failure after success preserves the confirmed answer', async () => {
  const app = await boot(ok, {clearFailure:true});
  await app.submit('问题');
  assert.equal(app.ui.answers.length, 1);
  assert.ok(app.pending());
  assert.match(app.ui.errors.at(-1)[0], /答案已保存/);
  assert.doesNotMatch(app.ui.errors.at(-1)[0], /未能确认/);
});

test('malformed success retains original operation for explicit retry', async () => {
  const app = await boot(() => ({ok:true, status:200, json:async () => ({response:123})}));
  await app.submit('问题');
  assert.equal(app.pending()?.question, '问题');
  assert.equal(app.calls.length, 1);
});

test('HTTP failure retains the key without an automatic retry', async () => {
  const app = await boot(() => ({ok:false, status:409, json:async () => ({detail:{message:'尚未完成', stage:'请求状态', request_id:RESULT.request_id}})}));
  await app.submit('问题');
  assert.ok(app.pending());
  assert.equal(app.calls.length, 1);
  await app.retry();
  assert.equal(app.calls.length, 2);
  assert.equal(app.calls[0].options.headers['Idempotency-Key'], app.calls[1].options.headers['Idempotency-Key']);
});

test('ending tracking is blocked while a request is in flight', async () => {
  let finish;
  const response = new Promise(resolve => {finish = resolve;});
  const app = await boot(() => response);
  const submission = app.submit('问题');
  const original = app.pending();
  assert.ok(original);
  await app.discard();
  assert.equal(app.pending(), original);
  finish(ok());
  await submission;
});

test('anonymous user cannot send a question', async () => {
  const app = await boot(ok, {anonymous:true});
  await app.submit('private question');
  assert.equal(app.calls.length,0);
});
