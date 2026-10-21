// Real parser/sanitizer and DOM. This suite never contacts an API or database.
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const html = readFileSync(new URL('../../app/web/index.html', import.meta.url), 'utf8');
const dom = new JSDOM(html, {url:'http://127.0.0.1:8001/'});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
after(() => {dom.window.close(); delete globalThis.window; delete globalThis.document;});

const moduleUrl = new URL('../../app/web/markdown.js', import.meta.url);
async function render(source) {
  assert.ok(existsSync(fileURLToPath(moduleUrl)), 'Create app/web/markdown.js first');
  const { renderMarkdown } = await import(moduleUrl.href);
  assert.equal(typeof renderMarkdown, 'function');
  const target = document.getElementById('answer-content');
  renderMarkdown(target, source);
  return target;
}

test('headings, emphasis and lists become formatted elements', async () => {
  const target = await render('## 资格条件\n\n必须**同时满足**：\n\n- 任职未中断\n- 已通过原试用期');
  assert.equal(target.querySelector('h2').textContent, '资格条件');
  assert.equal(target.querySelector('strong').textContent, '同时满足');
  assert.equal(target.querySelectorAll('ul > li').length, 2);
  assert.equal(target.classList.contains('markdown-answer'), true);
});

test('code remains literal and tables retain their rows', async () => {
  const target = await render('```html\n<img src=x onerror=alert(1)>\n```\n\n| 条件 | 要求 |\n| --- | --- |\n| 试用期 | 已通过 |');
  assert.match(target.querySelector('pre code').textContent, /<img/);
  assert.equal(target.querySelector('pre code img'), null);
  assert.equal(target.querySelectorAll('table tbody tr').length, 1);
});

test('scripts, event handlers and styles are removed', async () => {
  const target = await render('<script>window.pwned=1</script>\n\n<p onclick="alert(1)" style="position:fixed">安全文字</p>');
  assert.equal(target.querySelector('script'), null);
  assert.equal(target.querySelector('[onclick],[style]'), null);
  assert.match(target.textContent, /安全文字/);
});

test('images, frames, forms and SVG are not introduced into the answer', async () => {
  const target = await render('<img src="https://example.com/tracker" onerror="alert(1)"><iframe src="https://example.com"></iframe><form><input></form><svg onload="alert(1)"></svg>');
  assert.equal(target.querySelector('img,iframe,form,input,svg'), null);
});

for (const href of ['javascript:alert(1)', 'java&#x0a;script:alert(1)', 'data:text/html,test',
                    'mailto:test@example.com', '/records', '//example.com/path']) {
  test('non-HTTP link is inert: ' + href, async () => {
    const target = await render(`<a href="${href}">链接文字</a>`);
    assert.equal(target.querySelector('a[href]'), null);
    assert.match(target.textContent, /链接文字/);
  });
}

test('HTTP, HTTPS and local fragment links remain usable', async () => {
  const target = await render('[HTTP](http://example.com) [政策](https://handbook.gitlab.com) [依据](#reference-1)');
  assert.deepEqual([...target.querySelectorAll('a')].map(a => a.getAttribute('href')),
    ['http://example.com', 'https://handbook.gitlab.com', '#reference-1']);
});

test('re-render replaces the previous answer instead of appending', async () => {
  await render('**旧答案**');
  const target = await render('## 新答案');
  assert.equal(target.querySelector('strong'), null);
  assert.equal(target.textContent.trim(), '新答案');
});

test('record view renders the answer but preserves source evidence as text', async () => {
  await render(''); // Confirm the user renderer exists before importing the integration.
  const { renderRecord } = await import(new URL('../../app/web/record-view.js', import.meta.url).href);
  const record = {
    request_id:'79060ce7-f617-4db9-a3e3-804e7f3b012a', question:'问题', corpus_id:'test',
    status:'completed', answer:'**答案**', http_status:200, error_stage:null,
    llm_generated:true, retrieval:null,
    references:[{reference_id:'1',file_path:'policy.md',content:['<b>原文</b>']}],
  };
  renderRecord(record);
  assert.equal(document.querySelector('#answer-content strong').textContent, '答案');
  const evidence = document.querySelector('#reference-list pre');
  assert.equal(evidence.textContent, '<b>原文</b>');
  assert.equal(evidence.querySelector('b'), null);
  assert.equal(record.answer, '**答案**');
});

test('switching to a failed record clears Markdown style and old evidence', async () => {
  await render('**旧答案**');
  const { renderRecord } = await import(new URL('../../app/web/record-view.js', import.meta.url).href);
  renderRecord({request_id:'test', question:'失败问题', corpus_id:'test',status:'failed',
    answer:null, error_message:'<b>错误说明</b>', error_stage:'回答模型', http_status:504,
    llm_generated:null, retrieval:null, references:null});
  const target = document.getElementById('answer-content');
  assert.equal(target.classList.contains('markdown-answer'), false);
  assert.equal(target.querySelector('b'), null);
  assert.match(target.textContent, /<b>错误说明<\/b>/);
  assert.equal(document.getElementById('evidence-panel').hidden, true);
});
