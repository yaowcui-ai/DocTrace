// Offline DOM checks: no server, database, or model calls.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const dom = new JSDOM(readFileSync(new URL('../../app/web/index.html', import.meta.url), 'utf8'), {url:'http://127.0.0.1:8001/'});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
dom.window.HTMLElement.prototype.scrollIntoView = function () { this.dataset.scrolled = 'yes'; };
after(() => { dom.window.close(); delete globalThis.window; delete globalThis.document; });
const moduleUrl = new URL('../../app/web/citations.js', import.meta.url);

async function setup(html) {
  assert.ok(existsSync(fileURLToPath(moduleUrl)), 'Create app/web/citations.js first');
  const { linkCitations } = await import(moduleUrl.href);
  const answer = document.getElementById('answer-content');
  answer.innerHTML = html; // Test fixtures only; production receives sanitized DOM.
  const list = document.getElementById('reference-list');
  list.innerHTML = '<details><summary>leave.md</summary></details><details><summary>benefits.md</summary></details>';
  const [leave, benefits] = list.children;
  const targets = new Map([['2', leave], ['1', benefits]]);
  linkCitations(answer, targets);
  return {answer, leave, benefits, targets, linkCitations};
}

test('reference ID wins over array order; click opens, scrolls and focuses evidence', async () => {
  const {answer, leave, benefits} = await setup('<p>政策依据[1]。</p>');
  const button = answer.querySelector('button');
  assert.ok(button);
  assert.equal(button.type, 'button');
  assert.equal(button.textContent, '[1]');
  button.click();
  assert.equal(benefits.open, true);
  assert.equal(leave.open, false);
  assert.equal(benefits.dataset.scrolled, 'yes');
  assert.equal(document.activeElement, benefits);
});

test('unknown IDs stay plain text; multiple and repeated citations are linked', async () => {
  const {answer} = await setup('<p>[1][2] 与 [1]，缺失[99]</p>');
  assert.deepEqual([...answer.querySelectorAll('button')].map(x => x.textContent), ['[1]', '[2]', '[1]']);
  assert.equal(answer.textContent, '[1][2] 与 [1]，缺失[99]');
});

test('code, existing links and existing buttons are left unchanged', async () => {
  const {answer} = await setup('<pre>[1]</pre><code>[2]</code><a href="https://example.com">[1]</a><button>[2]</button><p>依据[1]</p>');
  assert.equal(answer.querySelectorAll('button.citation-button').length, 1);
  assert.equal(answer.querySelector('pre').textContent, '[1]');
  assert.equal(answer.querySelector('a button'), null);
});

test('repeated enhancement does not nest or duplicate buttons', async () => {
  const {answer, targets, linkCitations} = await setup('<strong>依据[1]</strong>');
  linkCitations(answer, targets);
  assert.equal(answer.querySelectorAll('button').length, 1);
  assert.equal(answer.querySelector('button button'), null);
});

test('only the most recently selected evidence is highlighted', async () => {
  const {answer, leave, benefits} = await setup('<p>[1][2]</p>');
  const buttons = answer.querySelectorAll('button');
  assert.equal(buttons.length, 2);
  buttons[0].click();
  buttons[1].click();
  assert.equal(benefits.classList.contains('evidence-selected'), false);
  assert.equal(leave.classList.contains('evidence-selected'), true);
});

test('record view connects citations to current evidence and replaces old targets', async () => {
  await setup('');
  const {renderRecord} = await import('../../app/web/record-view.js');
  const base = {request_id:'test', question:'问题', status:'completed', answer:'依据[1]', http_status:200,
    references:[{reference_id:'1', file_path:'old.md', content:['<b>原文</b>']}]};
  renderRecord(base);
  const old = document.querySelector('#reference-list details');
  assert.equal(document.querySelector('#reference-list pre b'), null);
  renderRecord({...base, references:[{reference_id:'1', file_path:'new.md', content:['新原文']}]});
  const button = document.querySelector('#answer-content button.citation-button');
  assert.ok(button);
  button.click();
  assert.equal(old.open, false);
  assert.equal(document.querySelector('#reference-list details').open, true);
  assert.match(document.querySelector('#reference-list summary').textContent, /new.md/);
});
