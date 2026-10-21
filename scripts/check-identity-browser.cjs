// Exercises a real isolated Edge browser against a synthetic local fixture.
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require(path.join(os.tmpdir(),'doctrace-browser-check/node_modules/playwright-core'));
const root=path.resolve(__dirname,'..');
const report={kind:'isolated_browser_identity_not_model_evaluation',checks:[],provider_requests:0,status:'started'};
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'doctrace-identity-'));
let child,browser;
const check=(ok,label)=>{if(!ok)throw new Error(label);report.checks.push(label);};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 try {
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  const base=`http://127.0.0.1:${port}`;
  child=spawn(path.join(root,'.venv/Scripts/python.exe'),['tests/support/identity_browser_server.py',path.join(temp,'fixture.db'),String(port)],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root},stdio:'ignore'});
  let ready=false;
  for(let i=0;i<80;i++){try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{} await delay(150);}
  check(ready,'isolated fixture ready');
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext();
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.waitForSelector('#login-form:not([hidden])');
  check(await page.locator('#submit-question').isDisabled(),'anonymous composer disabled');
  check(await page.locator('#retrieval-mode').inputValue()==='naive','new page defaults to naive');
  const login=async name=>{
   await page.fill('#login-username',name);await page.fill('#login-password','Fake!123');
   await page.click('#login-button');
   await page.waitForFunction(n=>document.getElementById('auth-status').textContent.includes(`当前账户：${n}`),name);
   await page.waitForFunction(n=>document.getElementById('history-list').textContent.includes(`${n} synthetic private question`),name);
  };
  await login('alice');
  check(!(await page.evaluate(()=>document.cookie)).includes('doctrace_session'),'HttpOnly credential hidden from JavaScript');
  const alice=await page.evaluate(async()=>{const r=await fetch('/records');return (await r.json()).items[0];});
  await page.locator('#history-list button').first().click();
  await page.waitForFunction(()=>document.getElementById('answer-content').textContent.includes('alice synthetic private answer'));
  check(true,'own history answer and evidence load');
  const aliceId=await page.evaluate(async()=> (await (await fetch('/auth/me')).json()).user_id);
  await page.evaluate(owner=>sessionStorage.setItem('doctrace.pending-question.v2:'+owner,JSON.stringify({key:crypto.randomUUID(),question:'alice unresolved synthetic'})),aliceId);
  await page.reload();
  await page.waitForFunction(()=>!document.getElementById('pending-operation').hidden);
  check((await page.locator('#pending-question').innerText()).includes('alice unresolved'),'refresh restores only current account pending operation');
  check(await page.locator('#retrieval-mode').inputValue()==='mix','legacy unresolved request restores original mix');
  await page.click('#discard-pending');
  // Hold a legitimate Alice detail response until after switching accounts.
  // Completed turns now focus locally, so clear the transcript to exercise an uncached read.
  await page.evaluate(async()=>{const view=await import('/static/conversation.js');view.clearConversation();});
  let release,seen;
  const arrived=new Promise(r=>{seen=r;});
  const held=new Promise(r=>{release=r;});
  await page.route('**/records/'+alice.request_id,async route=>{const response=await route.fetch();seen();await held;await route.fulfill({response});});
  await page.locator('#history-list button').first().click();
  await arrived;
  await page.click('#logout-button');
  await page.waitForFunction(()=>document.getElementById('auth-status').textContent==='已退出登录。');
  check(!(await page.locator('#answer-content').innerText()).includes('alice'),'logout clears private answer view');
  await login('bob');
  release();await delay(250);
  check(!(await page.locator('#answer-content').innerText()).includes('alice'),'late prior-account response discarded');
  check((await page.evaluate(async id=>(await fetch('/records/'+id)).status,alice.request_id))===404,'foreign record denied by backend');
  check(await page.locator('#pending-operation').isHidden(),'other account pending not shown');
  await page.fill('#question','Synthetic browser question');await page.click('#submit-question');
  await page.waitForFunction(()=>document.getElementById('answer-content').textContent.includes('Synthetic new answer'));
  check(true,'authenticated question saved and rendered with synthetic provider');
  await page.locator('.chat-turn[aria-current="true"] .chat-record-details > summary').click();
  check((await page.locator('#record-info').innerText()).includes('naive'),'default naive mode displayed after submission');
  await page.waitForFunction(()=>!document.getElementById('submit-question').disabled);
  await page.selectOption('#retrieval-mode','mix');
  await page.fill('#question','Synthetic browser mix question');
  const mixResponse=page.waitForResponse(r=>r.url()===base+'/ask/optimized'&&r.request().method()==='POST');
  await page.click('#submit-question');
  check((await mixResponse).status()===200,'mix selected request succeeds with synthetic provider');
  await page.waitForFunction(()=>document.getElementById('record-info').textContent.includes('（mix）'));
  check(true,'actual mix mode displayed');
  await page.waitForFunction(()=>!document.getElementById('submit-question').disabled);
  await page.reload();
  await page.locator('#history-list button').first().waitFor();
  await page.locator('#history-list button').first().click();
  await page.waitForFunction(()=>document.getElementById('record-info').textContent.includes('（mix）'));
  check(true,'mode retained in history after refresh');
  await page.click('#logout-button');
  await page.waitForFunction(()=>document.getElementById('auth-status').textContent==='已退出登录。');
  check((await page.evaluate(async()=>(await fetch('/records')).status))===401,'logged out history denied');
  check(errors.length===0,'no browser JavaScript errors');
  report.status='passed';
 }catch(error){report.status='failed';report.error=error.message;process.exitCode=1;}
 finally{
  if(browser)await browser.close();
  if(child){child.kill();await new Promise(r=>{child.once('exit',r);setTimeout(r,3000);});}
  const target=path.join(root,'evaluation/runs',new Date().toISOString().replace(/[-:.]/g,'')+'_identity_browser.json');
  fs.writeFileSync(target,JSON.stringify(report,null,2));
  console.log('Status:',report.status,'Checks:',report.checks.length,'Report:',target);
  if(report.error)console.log('Error:',report.error);
 }
})();
