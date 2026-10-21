import test, {after, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {JSDOM} from 'jsdom';

const html = readFileSync(new URL('../../app/web/index.html', import.meta.url), 'utf8');
const dom = new JSDOM(html, {url:'http://127.0.0.1:8001/'});
const originalBody = dom.window.document.body.innerHTML;
globalThis.window = dom.window;
globalThis.document = dom.window.document;
dom.window.HTMLElement.prototype.scrollIntoView = function() {this.dataset.scrolled = 'yes';};
beforeEach(() => {
  document.body.innerHTML = originalBody;
});
after(() => {dom.window.close(); delete globalThis.window; delete globalThis.document;});

const record = (id, question, at='2026-10-21T01:00:00Z') => ({
  request_id:id, question, answer:`${question} 的答案 [1]`, status:'completed',
  created_at:at, corpus_id:'fixture', http_status:200, llm_generated:true,
  references:[{reference_id:'1',file_path:`${id}.md`,content:[`原文 ${id}`]}],
});
async function view() {return import('../../app/web/record-view.js');}
async function conversation() {
  const url = new URL('../../app/web/conversation.js', import.meta.url);
  assert.ok(existsSync(url), 'Create the conversation view module');
  return import(url.href);
}

test('chat transcript precedes the composer and has an accessible label', () => {
  const log = document.getElementById('conversation-log');
  assert.ok(log, 'The page needs a conversation transcript');
  assert.equal(log.getAttribute('role'),'log');
  assert.ok(log.compareDocumentPosition(document.getElementById('question-form')) & window.Node.DOCUMENT_POSITION_FOLLOWING);
});

test('loading another record keeps both question and answer pairs in chronological order', async () => {
  const {renderRecord} = await view();
  renderRecord(record('new','新问题','2026-10-21T02:00:00Z'));
  renderRecord(record('old','旧问题'));
  const turns = [...document.querySelectorAll('.chat-turn[data-request-id]')];
  assert.equal(turns.length,2);
  assert.deepEqual(turns.map(t=>t.dataset.requestId),['old','new']);
  assert.match(turns[0].textContent,/旧问题 的答案/);
  assert.match(turns[1].textContent,/新问题 的答案/);
});

test('rereading the same record updates one existing pair instead of duplicating it', async () => {
  const {renderRecord} = await view();
  renderRecord(record('same','问题'));
  renderRecord({...record('same','问题'),answer:'更新后的答案 [1]'});
  const turns = document.querySelectorAll('.chat-turn[data-request-id]');
  assert.equal(turns.length,1);
  assert.match(turns[0].textContent,/更新后的答案/);
});

test('each turn citation opens its own evidence even when all references are numbered one', async () => {
  const {renderRecord} = await view();
  renderRecord(record('one','第一个问题'));
  renderRecord(record('two','第二个问题'));
  const turns = document.querySelectorAll('.chat-turn[data-request-id]');
  assert.equal(turns.length,2);
  turns[0].querySelector('.citation-button').click();
  assert.equal(turns[0].querySelector('.chat-evidence details').open,true);
  assert.equal(turns[1].querySelector('.chat-evidence details').open,false);
  assert.match(turns[0].querySelector('.chat-evidence details').textContent,/one.md/);
});

test('history selection scrolls and focuses the matching existing pair without duplication', async () => {
  const {renderRecord} = await view();
  renderRecord(record('one','一'));
  renderRecord(record('two','二'));
  const {focusRecord} = await conversation();
  assert.equal(focusRecord('one'),true);
  const first = [...document.querySelectorAll('.chat-turn')].find(t=>t.dataset.requestId==='one');
  assert.equal(first.dataset.scrolled,'yes');
  assert.equal(document.activeElement,first);
  assert.equal(first.getAttribute('aria-current'),'true');
  assert.equal(document.querySelectorAll('.chat-turn[data-request-id]').length,2);
});

test('pending question resolves in place and repeat responses never add another pair', async () => {
  const {beginPendingTurn} = await conversation();
  const {renderRecord} = await view();
  const pending=beginPendingTurn('新问题','operation-1');
  assert.match(pending.textContent,/正在/);
  renderRecord(record('saved','新问题'), {operationKey:'operation-1'});
  renderRecord(record('saved','新问题'), {operationKey:'operation-1'});
  assert.equal(document.querySelectorAll('.chat-turn[data-request-id]').length,1);
  assert.equal(document.querySelectorAll('.chat-turn[data-operation-key]').length,0);
  assert.match(pending.textContent,/新问题 的答案/);
});

test('clearing a private conversation removes all old user content and restores the empty state', async () => {
  const {renderRecord}=await view();
  renderRecord(record('alice-private','alice 私人问题'));
  const {clearConversation}=await conversation();
  clearConversation();
  assert.equal(document.querySelectorAll('.chat-turn[data-request-id]').length,0);
  assert.doesNotMatch(document.getElementById('answer-panel').textContent,/alice 私人问题/);
  assert.equal(document.getElementById('answer-empty').hidden,false);
  assert.ok(document.getElementById('answer-content'));
});

test('a late processing snapshot cannot replace a completed answer already on the page', async () => {
  const {renderRecord}=await view();
  renderRecord(record('one','问题'));
  renderRecord({...record('one','问题'),status:'processing',answer:null},{focus:false});
  assert.match(document.getElementById('answer-panel').textContent,/问题 的答案/);
});

test('an uncertain POST response cannot erase an answer already read from saved history', async () => {
  const {beginPendingTurn,showPendingFailure}=await conversation();
  const pending=beginPendingTurn('问题','key');
  const {renderRecord}=await view();
  renderRecord(record('confirmed','问题'),{focus:false});
  showPendingFailure(pending,'网络连接中断','confirmed');
  const saved=document.querySelector('.chat-turn[data-request-id="confirmed"]');
  assert.equal(saved.dataset.status,'completed');
  assert.match(saved.textContent,/问题 的答案/);
  assert.equal(document.querySelectorAll('.chat-turn:not([hidden])').length,1);
});

test('current-record DOM aliases remain unique across several turns', async () => {
  const {renderRecord}=await view();
  for (const id of ['one','two','three']) renderRecord(record(id,id));
  const ids=[...document.querySelectorAll('[id]')].map(el=>el.id);
  assert.equal(new Set(ids).size,ids.length);
});
