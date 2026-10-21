// Browser operation persistence only; never sends an HTTP request.
import test, { beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const url = new URL('../../app/web/pending-operation.js', import.meta.url);
const OWNER = '00000000-0000-4000-8000-000000000001';
const OTHER = '00000000-0000-4000-8000-000000000002';
const STORAGE_KEY = 'doctrace.pending-question.v2:' + OWNER;
let values;
beforeEach(() => {
  values = new Map();
  globalThis.sessionStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
});
after(() => { delete globalThis.sessionStorage; });

async function module() {
  assert.ok(existsSync(fileURLToPath(url)), 'Create app/web/pending-operation.js first');
  return import(url.href);
}

test('no stored operation returns null', async () => {
  const m = await module();
  assert.equal(m.readPendingOperation(OWNER), null);
});

test('new operations default to naive and preserve explicit mix after reload', async () => {
  const m = await module();
  assert.equal(m.createPendingOperation('Question', OWNER).mode, 'naive');
  const original = m.createPendingOperation('Question', OWNER, 'mix');
  assert.equal(m.readPendingOperation(OWNER).mode, 'mix');
  assert.equal(m.readPendingOperation(OWNER).key, original.key);
});

test('legacy operation without mode restores original mix rather than new default', async () => {
  const m = await module();
  const legacy = {key:crypto.randomUUID(), question:'Old question'};
  values.set(STORAGE_KEY, JSON.stringify(legacy));
  assert.equal(m.readPendingOperation(OWNER).mode, 'mix');
  assert.equal(m.readPendingOperation(OWNER).key, legacy.key);
});

test('invalid modes cannot be stored or restored', async () => {
  const m = await module();
  assert.throws(() => m.createPendingOperation('Question', OWNER, 'auto'));
  values.set(STORAGE_KEY, JSON.stringify({key:crypto.randomUUID(), question:'Question', mode:'auto'}));
  assert.throws(() => m.readPendingOperation(OWNER));
});

test('new operation stores the original question and a UUID', async () => {
  const m = await module();
  const operation = m.createPendingOperation('测试问题', OWNER);
  assert.match(operation.key, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  assert.equal(operation.question, '测试问题');
  assert.deepEqual(JSON.parse(values.get(STORAGE_KEY)), operation);
});

test('reading after reload preserves the same operation key', async () => {
  const m = await module();
  const original = m.createPendingOperation('测试问题', OWNER);
  assert.deepEqual(m.readPendingOperation(OWNER), original);
  assert.deepEqual(m.readPendingOperation(OWNER), original);
});

test('intentional new operation has a new key even for the same question', async () => {
  const m = await module();
  const first = m.createPendingOperation('相同问题', OWNER);
  const second = m.createPendingOperation('相同问题', OWNER);
  assert.notEqual(first.key, second.key);
  assert.deepEqual(m.readPendingOperation(OWNER), second);
});

test('clearing an old key cannot erase a newer operation', async () => {
  const m = await module();
  const old = m.createPendingOperation('旧问题', OWNER);
  const current = m.createPendingOperation('新问题', OWNER);
  m.clearPendingOperation(old.key, OWNER);
  assert.deepEqual(m.readPendingOperation(OWNER), current);
});

test('confirmed current operation can be removed', async () => {
  const m = await module();
  const current = m.createPendingOperation('测试问题', OWNER);
  m.clearPendingOperation(current.key, OWNER);
  assert.equal(m.readPendingOperation(OWNER), null);
});

for (const raw of ['not-json', JSON.stringify({key:'not-a-uuid', question:'测试问题'})]) {
  test('corrupt stored operation is rejected, not silently replaced: '+raw, async () => {
    const m = await module();
    values.set(STORAGE_KEY, raw);
    assert.throws(() => m.readPendingOperation(OWNER));
    assert.equal(values.get(STORAGE_KEY), raw);
  });
}

test('storage failure propagates so caller can stop before sending', async () => {
  const m = await module();
  globalThis.sessionStorage.setItem = () => { throw new Error('storage blocked'); };
  assert.throws(() => m.createPendingOperation('测试问题', OWNER), /storage blocked/);
  assert.equal(values.size, 0);
});

test('another account cannot restore or clear this account operation', async () => {
  const m = await module();
  const original = m.createPendingOperation('private alice', OWNER);
  assert.equal(m.readPendingOperation(OTHER), null);
  m.clearOwnerOperations(OTHER);
  assert.deepEqual(m.readPendingOperation(OWNER), original);
  m.clearOwnerOperations(OWNER);
  assert.equal(m.readPendingOperation(OWNER), null);
});
test('unowned legacy pending data is never restored', async () => {
  const m = await module();
  values.set('doctrace.pending-question.v1', JSON.stringify({question:'old private'}));
  assert.equal(m.readPendingOperation(OWNER), null);
});
