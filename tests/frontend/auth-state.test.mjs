import test from 'node:test';
import assert from 'node:assert/strict';
import {getIdentity, setIdentity, isCurrent, privateFetch} from '../../app/web/auth-state.js';

test('anonymous page cannot submit a private request', async () => {
  setIdentity(null);
  await assert.rejects(privateFetch('/ask/optimized'), /请先登录/);
});
test('identity changes invalidate outstanding results', () => {
  setIdentity({user_id:'alice',username:'alice'});
  const before = getIdentity();
  setIdentity({user_id:'bob',username:'bob'});
  assert.equal(isCurrent(before),false);
});
test('expired session clears the current identity', async () => {
  setIdentity({user_id:'alice',username:'alice'});
  globalThis.fetch = async () => new Response('{}',{status:401});
  await assert.rejects(privateFetch('/records'), /登录已失效/);
  assert.equal(getIdentity().user,null);
});
test('requests bind expected identity without exposing a credential', async () => {
  setIdentity({user_id:'alice',username:'alice'});
  globalThis.fetch = async (url, options) => {
    assert.equal(options.headers.get('X-DocTrace-User-ID'),'alice');
    assert.equal(options.credentials,'same-origin');
    assert.equal(options.headers.get('Authorization'),null);
    return new Response('{}');
  };
  assert.equal((await privateFetch('/records')).status,200);
});
test('late response from previous account is discarded', async () => {
  setIdentity({user_id:'alice',username:'alice'});
  let resolve;
  globalThis.fetch = () => new Promise(r => {resolve=r;});
  const pending = privateFetch('/records');
  setIdentity({user_id:'bob',username:'bob'});
  resolve(new Response('{}'));
  await assert.rejects(pending,/身份已改变/);
});
