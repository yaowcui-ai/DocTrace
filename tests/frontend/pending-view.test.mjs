import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
import {setIdentity} from '../../app/web/auth-state.js';
setIdentity({user_id:'testuser',username:'testuser'});

const dom = new JSDOM(readFileSync(new URL('../../app/web/index.html', import.meta.url), 'utf8'), {url:'http://127.0.0.1:8001/'});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
after(() => {dom.window.close(); delete globalThis.window; delete globalThis.document;});

test('pending recovery panel is hidden initially and controls do not submit the form', () => {
  const panel = document.getElementById('pending-operation');
  assert.ok(panel);
  assert.equal(panel.hidden, true);
  for (const id of ['retry-pending', 'discard-pending']) {
    assert.equal(document.getElementById(id).type, 'button');
  }
});

test('pending question is shown as plain text and hides when cleared', async () => {
  const view = await import('../../app/web/question-view.js');
  view.showPendingOperation({key:'test', question:'<img src=x onerror=alert(1)>'});
  assert.equal(document.getElementById('pending-operation').hidden, false);
  assert.equal(document.getElementById('pending-question').textContent, '<img src=x onerror=alert(1)>\n原请求模式：mix');
  assert.equal(document.querySelector('#pending-question img'), null);
  view.showPendingOperation(null);
  assert.equal(document.getElementById('pending-operation').hidden, true);
});

test('busy state disables both retry and end-tracking controls', async () => {
  const view = await import('../../app/web/question-view.js');
  for (const busy of [true, false]) {
    view.setQuestionBusy(busy);
    assert.equal(document.getElementById('retry-pending').disabled, busy);
    assert.equal(document.getElementById('discard-pending').disabled, busy);
    assert.equal(document.getElementById('retrieval-mode').disabled, busy);
  }
});
