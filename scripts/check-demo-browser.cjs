// Checks static replay under an actual HTTP origin; never touches a database/model.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process');
let playwright;
try {playwright=require('playwright-core');}
catch {playwright=require(path.join(os.tmpdir(),'doctrace-browser-check/node_modules/playwright-core'));}
const root=path.resolve(__dirname,'..'),delay=ms=>new Promise(r=>setTimeout(r,ms));
const report={kind:'public_static_replay_browser',status:'started',checks:[],provider_requests:0};
const check=(ok,label)=>{if(!ok)throw new Error(label);report.checks.push(label);};
let child,browser;
(async()=>{
 try {
  let base=process.argv[2];
  if(!base){
   const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
   base=`http://127.0.0.1:${port}/`;
   child=spawn('python',['scripts/serve-demo.py','--port',String(port)],{cwd:root,windowsHide:true,stdio:'ignore'});
   let ready=false;for(let i=0;i<60;i++){try{if((await fetch(base)).ok){ready=true;break;}}catch{}await delay(100);}
   check(ready,'local static server ready');
  }
  browser=await playwright.chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL||(process.platform==='win32'?'msedge':'chromium'),headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[],forbidden=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',message=>{if(message.type()==='error')console.log('Browser:',message.text());});
  page.on('request',r=>{requests.push(r.url());if(r.method()!=='GET'||/\/(ask|auth|records|query)(\/|\?|$)/.test(new URL(r.url()).pathname))forbidden.push(r.url());});
  await page.goto(base);
  try {await page.waitForSelector('.chat-turn[data-request-id="mode-naive"]',{timeout:10000});}
  catch(error){console.log('Page errors:',errors);console.log('Page status:',await page.locator('#request-status').textContent());throw error;}
  check(await page.locator('body').innerText().then(t=>t.includes('公开演示 · 真实结果回放')),'replay disclosure visible in page');
  check(await page.locator('#login-form').count()===0,'no fake login or credentials requested');
  check(await page.locator('#public-examples-list button').count()===10,'ten reviewed public examples available');
  check(await page.locator('#question').getAttribute('readonly')!==null,'arbitrary live questions cannot be submitted');
  check(await page.locator('#record-info').textContent().then(t=>t.includes('（naive）')),'default result carries saved naive provenance');
  await page.selectOption('#retrieval-mode','mix');
  await page.waitForSelector('.chat-turn[data-request-id="mode-mix"]');
  check(await page.locator('#record-info').textContent().then(t=>t.includes('（mix）')),'mode switch loads actual saved mix result');
  check(await page.locator('.chat-turn[data-request-id]').count()===2,'both saved mode results retained as separate turns');
  await page.locator('.chat-turn[data-request-id="mode-mix"] .citation-button').first().click();
  check(await page.locator('.chat-turn[data-request-id="mode-mix"] .chat-evidence details[open]').count()>0,'citation opens matching turn evidence');
  await page.locator('#public-examples-list button').first().click();
  await page.waitForSelector('.chat-turn[data-request-id="public-01"]');
  check(await page.locator('.chat-turn[data-request-id]').count()===3,'public example loads into conversation');
  for(let i=0;i<6&&await page.locator('#history-list button[data-request-id="mode-naive"]').count()===0;i++)await page.click('#history-next');
  await page.locator('#history-list button[data-request-id="mode-naive"]').click();
  check(await page.locator('.chat-turn[aria-current="true"]').getAttribute('data-request-id')==='mode-naive','history locates matching prior turn');
  check(await page.locator('#retrieval-mode').inputValue()==='naive','mode selector follows a selected saved-mode history turn');
  check(await page.locator('.chat-turn[data-request-id]').count()===3,'history selection does not duplicate messages');
  await page.waitForTimeout(300);
  const assets=path.join(root,'docs/images');fs.mkdirSync(assets,{recursive:true});
  await page.locator('.chat-workspace').screenshot({path:path.join(assets,'conversation-demo.png')});
  await page.setViewportSize({width:390,height:844});
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile layout fits viewport');
  await page.reload();await page.waitForSelector('.chat-turn[data-request-id="mode-naive"]');
  check(await page.locator('#public-examples-list button').count()===10,'reload restores replay without login');
  check(forbidden.length===0,'only static GET requests; no auth, QA or provider requests');
  check(requests.every(url=>new URL(url).origin===new URL(base).origin),'no external CDN or third-party API dependency');
  check(errors.length===0,'no JavaScript errors');
  report.status='passed';
 }catch(error){report.status='failed';report.error=error.stack;process.exitCode=1;}
 finally{
  if(browser)await browser.close();if(child)child.kill();
  const dir=path.join(root,'verification');fs.mkdirSync(dir,{recursive:true});
  const file=path.join(dir,process.argv[2]?'public-demo-browser.json':'local-demo-browser.json');
  fs.writeFileSync(file,JSON.stringify(report,null,2));
  console.log('Status:',report.status,'Checks:',report.checks.length,'Report:',file);if(report.error)console.log(report.error);
 }
})();
