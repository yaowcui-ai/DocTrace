// End-to-end service liveness with a deliberately frozen console. No model calls.
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'doctrace-console-'));
const report={kind:'frozen_console_liveness_not_model_evaluation',status:'started',provider_requests:0,probes:[]};
let child;
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 try{
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  const base=`http://127.0.0.1:${port}`;
  child=spawn(path.join(root,'.venv/Scripts/python.exe'),['tests/support/blocked_console_server.py',String(port),directory],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:root},stdio:'ignore'});
  let ready=false;
  for(let i=0;i<80;i++){
   try{if((await fetch(base+'/health',{signal:AbortSignal.timeout(600)})).ok){ready=true;break;}}catch{}
   if(child.exitCode!==null)throw new Error('Fixture exited before readiness');
   await wait(100);
  }
  if(!ready)throw new Error('Service did not start while console was blocked');
  for(let i=0;i<10;i++){
   for(const endpoint of ['/health','/records']){
    const started=performance.now();
    const response=await fetch(base+endpoint,{signal:AbortSignal.timeout(2000)});
    const expected=endpoint==='/health'?200:401;
    if(response.status!==expected)throw new Error(endpoint+' unexpected status '+response.status);
    report.probes.push({endpoint,http_status:response.status,milliseconds:Math.round(performance.now()-started)});
   }
  }
  const lines=fs.readFileSync(path.join(directory,'doctrace-qa.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  if(!lines.some(row=>row.event==='http_completed'&&row.http_status===401))throw new Error('File logs stopped with console');
  report.file_logs_continued=true;
  report.status='passed';
 }catch(error){report.status='failed';report.error=error.message;process.exitCode=1;}
 finally{
  if(child){child.kill();if(child.exitCode===null)await new Promise(r=>{child.once('exit',r);setTimeout(r,3000);});}
  const output=path.join(root,'evaluation/runs',new Date().toISOString().replace(/[-:.]/g,'')+'_console_backpressure.json');
  fs.writeFileSync(output,JSON.stringify(report,null,2));
  console.log('Status:',report.status,'Probes:',report.probes.length,'Report:',output);
  if(report.error)console.log('Error:',report.error);
 }
})();
