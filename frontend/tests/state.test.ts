import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OwnerScope, loadPending, savePending, clearPending, createPending, ApiError, apiRequest } from '../src/state.ts';

function storage() {
  const data = new Map<string, string>();
  return {getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => {data.set(key, value);}, removeItem: (key: string) => {data.delete(key);}};
}
const owner = '11111111-1111-4111-8111-111111111111';
const other = '22222222-2222-4222-8222-222222222222';
test('account changes invalidate old requests, including switching back to the original account', () => {
  const scope = new OwnerScope();
  scope.setOwner(owner);
  const stamp = scope.stamp();
  scope.setOwner(other);
  assert.equal(scope.current(stamp), false);
  scope.setOwner(owner);
  assert.equal(scope.current(stamp), false);
  assert.equal(scope.current(scope.stamp()), true);
});
test('pending operation restores the same key and mode only for its owner; old completion cannot delete newer work', () => {
  const store = storage();
  const first = createPending(owner, 'conversation-a', '培训需要审批吗？', 'mix');
  savePending(store, first);
  assert.deepEqual(loadPending(store, owner), first);
  assert.equal(loadPending(store, other), null);
  const second = createPending(owner, 'conversation-a', '还需要材料吗？', 'naive');
  savePending(store, second);
  clearPending(store, owner, first.key);
  assert.deepEqual(loadPending(store, owner), second);
  clearPending(store, owner, second.key);
  assert.equal(loadPending(store, owner), null);
});
test('tampered pending operation is discarded instead of replaying another owner or invalid mode', () => {
  const store = storage();
  const value = createPending(owner, 'conversation-a', '问题', 'naive');
  savePending(store, value);
  const wrapped = {getItem: () => JSON.stringify({...value, owner: other}), setItem() {}, removeItem() {}};
  assert.equal(loadPending(wrapped, owner), null);
});
test('pending recovery retains its knowledge base instead of following the current UI selection', () => {
  const store = storage();
  const pending = createPending(owner, 'conversation-a', '管理员上传了哪些政策？', 'naive', 'managed');
  savePending(store, pending);
  assert.equal(loadPending(store, owner)?.knowledgeBase, 'managed');
});
test('legacy pending operations default to frozen while malformed knowledge base is rejected', () => {
  const value = createPending(owner, 'conversation-a', '问题', 'mix');
  const raw: Record<string, unknown> = {...value};
  delete raw.knowledgeBase;
  const legacy = {getItem: () => JSON.stringify(raw), setItem() {}, removeItem() {}};
  assert.equal(loadPending(legacy, owner)?.knowledgeBase, 'frozen');
  const invalid = {getItem: () => JSON.stringify({...value, knowledgeBase: 'other-tenant'}), setItem() {}, removeItem() {}};
  assert.equal(loadPending(invalid, owner), null);
});
test('API sends same-origin credentials, owner and stable idempotency key', async () => {
  let init: RequestInit | undefined;
  const result = await apiRequest('/api/v1/test', {owner, method: 'POST', key: 'same-key', body: {question: 'hello'}, fetcher: async (_url, options) => {init = options; return new Response(JSON.stringify({data: {ok: true}}), {status: 200});}});
  assert.deepEqual(result, {ok: true});
  assert.equal(init?.credentials, 'same-origin');
  assert.equal(init?.cache, 'no-store');
  assert.equal(new Headers(init?.headers).get('X-DocTrace-User-ID'), owner);
  assert.equal(new Headers(init?.headers).get('Idempotency-Key'), 'same-key');
});
test('401 is distinguished from network failure so the app can clear private state', async () => {
  await assert.rejects(apiRequest('/api/v1/me', {fetcher: async () => new Response(JSON.stringify({detail: 'Not authenticated'}), {status: 401})}), error => error instanceof ApiError && error.status === 401);
});
