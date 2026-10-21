import test, {beforeEach, after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';

const html=readFileSync(new URL('../../app/web/index.html',import.meta.url),'utf8');
const dom=new JSDOM(html,{url:'http://127.0.0.1:8001/'});
globalThis.window=dom.window;
globalThis.document=dom.window.document;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
const originalFetch=globalThis.fetch;
let sequence=0;
const sample={example_id:'00000000-0000-4000-8000-000000000001',question:'Synthetic public question',
  answer:'**Synthetic answer** [1]',corpus_id:'synthetic',published_at:'2026-10-17T00:00:00Z',
  references:[{reference_id:'1',file_path:'synthetic.md',content:['<script>evidence is text</script>']}]};
beforeEach(()=>{document.body.innerHTML=html.match(/<body>([\s\S]*)<\/body>/)[1];});
after(()=>{globalThis.fetch=originalFetch;dom.window.close();delete globalThis.window;delete globalThis.document;});
const view=()=>import('../../app/web/examples-view.js');

test('public section is independent from private history controls',()=>{
  const section=document.getElementById('public-examples-section');
  assert.ok(section);
  assert.equal(section.closest('#history-controls'),null);
  assert.ok(document.getElementById('public-examples-list'));
});
test('question text is not inserted as HTML',async()=>{
  const m=await view();
  let selected;
  m.renderPublicExamples([{...sample,question:'<img src=x onerror=alert(1)>'}],id=>{selected=id;});
  assert.equal(document.querySelector('#public-examples-list img'),null);
  document.querySelector('#public-examples-list button').click();
  assert.equal(selected,sample.example_id);
});
test('public detail uses safe Markdown, plain evidence, and public metadata',async()=>{
  const m=await view();
  m.renderPublicExample(sample);
  assert.equal(document.querySelector('#public-example-answer strong').textContent,'Synthetic answer');
  assert.equal(document.querySelector('#public-example-references pre').textContent,sample.references[0].content[0]);
  assert.equal(document.querySelector('#public-example-references script'),null);
  assert.ok(document.getElementById('public-example-meta').textContent.includes('synthetic'));
  assert.ok(!document.getElementById('public-example-meta').textContent.includes('原请求'));
});
test('public citation opens its own evidence',async()=>{
  const m=await view();m.renderPublicExample(sample);
  document.querySelector('#public-example-answer button').click();
  assert.equal(document.querySelector('#public-example-references details').open,true);
});

async function controller(handler){
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return handler(url,options);};
  const m=await import('../../app/web/examples.js?test='+String(++sequence));
  await m.initialLoad;
  return {m,calls};
}
test('anonymous page loads only public GET with cookies omitted',async()=>{
  const {calls}=await controller(()=>new Response(JSON.stringify({items:[sample],has_more:false}),{status:200}));
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/examples?limit=10&offset=0');
  assert.equal(calls[0].options.credentials,'omit');
  assert.equal(calls[0].options.cache,'no-store');
});
test('public selection fetches saved detail without asking the model',async()=>{
  const {m,calls}=await controller(url=>new Response(JSON.stringify(url.includes('?')?{items:[sample],has_more:false}:sample),{status:200}));
  await m.loadPublicExample(sample.example_id);
  assert.equal(calls.at(-1).url,'/examples/'+sample.example_id);
  assert.ok(calls.every(c=>c.url.startsWith('/examples')));
  assert.equal(document.getElementById('public-example-detail').hidden,false);
});
test('empty list displays an explicit empty state',async()=>{
  await controller(()=>new Response(JSON.stringify({items:[],has_more:false}),{status:200}));
  assert.ok(document.getElementById('public-examples-status').textContent.includes('暂无'));
});
test('failed list stays isolated from personal answer panel',async()=>{
  document.getElementById('answer-content').textContent='Existing private answer';
  await controller(()=>new Response('{}',{status:503}));
  assert.ok(document.getElementById('public-examples-status').textContent.includes('失败'));
  assert.equal(document.getElementById('answer-content').textContent,'Existing private answer');
});
test('withdrawn detail cannot leave previous public answer visible',async()=>{
  const {m}=await controller(url=>new Response(JSON.stringify(url.includes('?')?{items:[sample],has_more:false}:{}),{status:url.includes('?')?200:404}));
  const v=await view();v.renderPublicExample(sample);
  await m.loadPublicExample(sample.example_id);
  assert.equal(document.getElementById('public-example-detail').hidden,true);
  assert.ok(document.getElementById('public-example-status').textContent.includes('下架'));
});
test('late earlier detail response cannot replace the current selection',async()=>{
  let release;
  const earlier=new Promise(r=>{release=r;});
  const {m}=await controller(url=>url.includes('?')?new Response(JSON.stringify({items:[sample],has_more:false})):url.endsWith('/first')?earlier:new Response(JSON.stringify({...sample,question:'Second selection'})));
  const first=m.loadPublicExample('first');
  await m.loadPublicExample('second');
  release(new Response(JSON.stringify(sample)));await first;
  assert.equal(document.getElementById('public-example-question').textContent,'Second selection');
});
