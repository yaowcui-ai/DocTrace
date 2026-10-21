import {renderRecord} from './assets/record-view.js';
import {focusRecord,recordTurn} from './assets/conversation.js';

// This entry point reads a public snapshot only. It has no authentication or model APIs.
const status=document.getElementById('request-status');
const mode=document.getElementById('retrieval-mode');
const history=document.getElementById('history-list');
let records=[],offset=0;
const pageSize=2;

function replay(record) {
  if (record.source_kind==='saved_mode_comparison') mode.value=record.retrieval.mode;
  if (!recordTurn(record.request_id)) renderRecord(record);
  else focusRecord(record.request_id);
  status.textContent=record.source_kind==='saved_mode_comparison'
    ? `已回放 ${record.retrieval.mode} 的真实保存结果；没有重新检索或调用模型。`
    : '已回放经过审核的公开示例；答案是当时的政策快照。';
  document.getElementById('error-message').hidden=true;
}

function renderHistory() {
  history.replaceChildren();
  const sorted=[...records].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
  for (const record of sorted.slice(offset,offset+pageSize)) {
    const item=document.createElement('li'),button=document.createElement('button');
    button.type='button';button.className='history-item';button.dataset.requestId=record.request_id;
    const title=document.createElement('span');title.className='history-item-title';title.textContent=record.question;
    const meta=document.createElement('span');meta.className='history-item-meta';
    meta.textContent=record.retrieval?.mode ? `真实同题结果 · ${record.retrieval.mode}` : '已审核公开示例';
    button.append(title,meta);button.addEventListener('click',()=>replay(record));item.append(button);history.append(item);
  }
  document.getElementById('history-page').textContent=`第 ${offset/pageSize+1} 页`;
  document.getElementById('history-prev').disabled=offset===0;
  document.getElementById('history-next').disabled=offset+pageSize>=records.length;
  document.getElementById('history-status').textContent=`共 ${records.length} 条公开演示记录`;
}

function replayMode() {replay(records.find(r=>r.request_id==='mode-'+mode.value));}

async function start() {
  try {
    const response=await fetch('./data/demo.json',{credentials:'omit'});
    if (!response.ok) throw new Error('snapshot_load_failed');
    const data=await response.json();records=data.records;
    if (data.kind!=='saved_results_replay_not_live_qa'||!Array.isArray(records)||!records.length) throw new Error('invalid_snapshot');
    document.getElementById('question').value=records.find(r=>r.request_id==='mode-naive').question;
    document.getElementById('question').disabled=false;
    mode.disabled=false;document.getElementById('submit-question').disabled=false;
    document.getElementById('refresh-history').disabled=false;
    document.getElementById('question-form').addEventListener('submit',event=>{event.preventDefault();replayMode();});
    mode.addEventListener('change',replayMode);
    document.getElementById('history-prev').addEventListener('click',()=>{offset=Math.max(0,offset-pageSize);renderHistory();});
    document.getElementById('history-next').addEventListener('click',()=>{offset+=pageSize;renderHistory();});
    document.getElementById('refresh-history').addEventListener('click',renderHistory);
    const examples=records.filter(r=>r.source_kind==='reviewed_public_example');
    const showExamples=()=>{
      const list=document.getElementById('public-examples-list');list.replaceChildren();
      for (const record of examples) {
        const item=document.createElement('li'),button=document.createElement('button');
        button.type='button';button.className='public-example-item';button.textContent=record.question;
        button.addEventListener('click',()=>replay(record));item.append(button);list.append(item);
      }
      document.getElementById('public-examples-status').textContent=`${examples.length} 条已审核快照，点击后在政策对话中回放。`;
    };
    showExamples();document.getElementById('refresh-examples').addEventListener('click',showExamples);
    renderHistory();replayMode();
  } catch {
    status.textContent='演示数据暂时无法加载，请刷新页面；也可以从 GitHub 下载源码本地查看。';
    document.getElementById('history-status').textContent='未加载演示记录';
  }
}
start();
