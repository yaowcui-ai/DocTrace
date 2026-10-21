// Real Edge + isolated SQLite and synthetic answers. Never uses production records/models.
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require(path.join(os.tmpdir(),'doctrace-browser-check/node_modules/playwright-core'));
const root=path.resolve(__dirname,'..');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'doctrace-chat-'));
const report={kind:'isolated_conversation_browser_not_model_evaluation',checks:[],provider_requests:0,status:'started'};
const check=(ok,label)=>{if(!ok)throw new Error(label);report.checks.push(label);};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let child,browser,page;
(async()=>{
 try {
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  const base=`http://127.0.0.1:${port}`;
  child=spawn(path.join(root,'.venv/Scripts/python.exe'),['tests/support/identity_browser_server.py',path.join(temp,'fixture.db'),String(port)],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root},stdio:'ignore'});
  let ready=false;
  for(let i=0;i<80;i++){try{if((await fetch(base+'/health')).ok){ready=true;break;}}catch{}await delay(150);}
  check(ready,'temporary fixture ready');
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  page=await context.newPage();
  const errors=[],posts=[],keys=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/ask/optimized')){posts.push(r.postDataJSON());keys.push(r.headers()['idempotency-key']);}});
  // Public list fixture is separate from private chat and the production database.
  await page.route('**/examples?*',r=>r.fulfill({json:{items:[],has_more:false,next_offset:null,limit:10,offset:0}}));
  await page.goto(base);
  await page.waitForSelector('#login-form:not([hidden])');
  check(await page.locator('#submit-question').isDisabled(),'anonymous composer remains protected');
  check(await page.locator('#public-examples-section').isVisible(),'public examples section preserved');
  const count=()=>page.locator('.chat-turn[data-request-id]').count();
  const login=async name=>{
   await page.fill('#login-username',name);await page.fill('#login-password','Fake!123');await page.click('#login-button');
   await page.waitForFunction(n=>document.querySelector('#auth-status').textContent.includes(`当前账户：${n}`),name);
   await page.waitForFunction(n=>document.querySelector('#conversation-log').textContent.includes(`${n} synthetic private answer`),name);
   await page.waitForFunction(()=>!document.querySelector('#refresh-history').disabled);
  };
  await login('alice');
  check(await count()===1,'login automatically reads saved question and answer into chat');
  check(posts.length===0,'history loading never generates answers');
  const aliceId=await page.locator('.chat-turn[data-request-id]').getAttribute('data-request-id');
  await page.locator('.citation-button').click();
  check(await page.locator('.chat-evidence details').evaluate(el=>el.open),'citation opens evidence inside its own turn');
  const submit=async(question,mode)=>{
   await page.waitForFunction(()=>!document.querySelector('#submit-question').disabled);
   await page.selectOption('#retrieval-mode',mode);await page.fill('#question',question);
   const response=page.waitForResponse(r=>r.url()===base+'/ask/optimized'&&r.request().method()==='POST');
   await page.click('#submit-question');
   check((await response).ok(),`synthetic ${mode} question succeeds`);
   await page.waitForFunction(()=>!document.querySelector('#submit-question').disabled&&!document.querySelector('#refresh-history').disabled);
  };
  await submit('First synthetic chat question','naive');
  await submit('Second synthetic chat question','mix');
  check(await count()===3,'successive submissions append turns and retain old history');
  check(posts[0].mode==='naive'&&posts[1].mode==='mix','existing mode selection preserved');
  check(await page.locator('.chat-turn[data-operation-key]').count()===0,'pending bubbles resolved without duplicates');
  await page.click('#history-next');
  await page.waitForFunction(()=>document.querySelector('#history-page').textContent.includes('2')&&!document.querySelector('#refresh-history').disabled);
  await page.locator('#history-list button').first().click();
  check(await page.locator('.chat-turn[aria-current="true"]').getAttribute('data-request-id')===aliceId,'clicking older personal history focuses its matching chat turn');
  check(await count()===3,'reselecting history never duplicates a turn');
  await page.reload();
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn[data-request-id]').length===2&&!document.querySelector('#refresh-history').disabled);
  check(posts.length===2,'refresh restores latest history using read-only requests');
  await page.click('#history-next');
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn[data-request-id]').length===3&&!document.querySelector('#refresh-history').disabled);
  await page.locator('#history-list button').first().click();
  check(await page.locator('.chat-turn[aria-current="true"]').getAttribute('data-request-id')===aliceId,'unloaded older history is inserted then focused');
  await page.waitForFunction(()=>{
   const turn=document.querySelector('.chat-turn[aria-current="true"]');
   const log=document.querySelector('#conversation-log');
   const t=turn.getBoundingClientRect(),l=log.getBoundingClientRect();
   return t.top>=l.top-2&&t.top<l.bottom&&document.activeElement===turn;
  });
  check(true,'history selection scrolls its bubble into the transcript viewport');
  const chronological=await page.locator('.chat-turn[data-request-id]').evaluateAll(rows=>rows.map(r=>Number(r.dataset.orderTime)).every((t,i,a)=>i===0||a[i-1]<=t));
  check(chronological,'chat ordered from oldest to newest');
  // Abort before sending: explicit retry must reuse the operation and bubble.
  await page.route('**/ask/optimized',r=>r.abort('failed'),{times:1});
  await page.fill('#question','Synthetic retry question');await page.click('#submit-question');
  await page.waitForFunction(()=>!document.querySelector('#error-message').hidden&&!document.querySelector('#retry-pending').disabled);
  check(await page.locator('.chat-turn[data-operation-key]').count()===1,'network failure preserves one uncertain bubble');
  const failedKey=keys.at(-1);
  await page.click('#retry-pending');
  await page.waitForFunction(()=>document.querySelectorAll('.chat-turn[data-request-id]').length===4&&!document.querySelector('#refresh-history').disabled);
  check(await page.locator('.chat-turn[data-operation-key]').count()===0,'manual retry resolves the same bubble');
  check(Boolean(failedKey)&&keys.at(-1)===failedKey,'manual retry preserves the original idempotency key');
  const ids=await page.locator('.chat-turn[data-request-id]').evaluateAll(rows=>rows.map(r=>r.dataset.requestId));
  check(new Set(ids).size===4,'all rendered saved turns are unique');
  await page.locator('.chat-turn').last().evaluate(el=>el.scrollIntoView());
  const output=path.join(root,'backups/chat_view_20261021');fs.mkdirSync(output,{recursive:true});
  await page.locator('#conversation-log').evaluate(el=>{el.scrollTop=0;});
  await page.evaluate(()=>document.activeElement?.blur());
  await page.screenshot({path:path.join(output,'desktop-chat.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile layout has no horizontal overflow');
  await page.screenshot({path:path.join(output,'mobile-chat.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  // Hold an uncached legitimate read across logout/account switch.
  await page.evaluate(async()=>{const m=await import('/static/conversation.js');m.clearConversation();});
  let release,seen;
  const arrived=new Promise(r=>seen=r),held=new Promise(r=>release=r);
  await page.route('**/records/'+aliceId,async r=>{const response=await r.fetch();seen();await held;await r.fulfill({response});});
  // Current page can vary after submit, so invoke the same history selection controller.
  await page.evaluate(id=>{import('/static/record-detail.js').then(m=>m.loadRecord(id));},aliceId);
  await Promise.race([arrived,delay(5000).then(()=>{throw new Error('held detail did not start');})]);
  await page.click('#logout-button');
  await page.waitForSelector('#login-form:not([hidden])');
  check(await count()===0,'logout removes every private turn');
  await login('bob');release();await delay(250);
  check(!(await page.locator('#conversation-log').innerText()).includes('alice'),'late prior-account response cannot enter current chat');
  check(await count()===1,'other account sees only its own saved conversation');
  check(errors.length===0,'no browser JavaScript errors');
  report.status='passed';
 }catch(error){report.status='failed';report.error=error.stack;process.exitCode=1;if(page)await page.screenshot({path:path.join(temp,'failure.png'),fullPage:true}).catch(()=>{});report.debug_directory=temp;}
 finally{
  if(browser)await browser.close();
  if(child){child.kill();await new Promise(r=>{child.once('exit',r);setTimeout(r,2000);});}
  const target=path.join(root,'evaluation/runs',new Date().toISOString().replace(/[-:.]/g,'')+'_conversation_browser.json');
  fs.writeFileSync(target,JSON.stringify(report,null,2));
  console.log('Status:',report.status,'Checks:',report.checks.length,'Report:',target);
  if(report.error)console.log(report.error);
 }
})();
