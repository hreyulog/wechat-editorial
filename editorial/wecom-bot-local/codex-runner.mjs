import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {write} from './production.mjs';

export function createCodexRunner({studio,stateDir,repository}){
 const stateFile=path.join(stateDir,'codex-thread.json');
 return prompt=>new Promise((resolve,reject)=>{
  let threadId=fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')).threadId:undefined;
  let text='',buffer='',lastError='',settled=false;
  const args=['exec','--json','--sandbox','workspace-write','-c','approval_policy="never"',
    '-c','sandbox_workspace_write.network_access=true','--skip-git-repo-check','-C',studio,'--add-dir',repository];
  if(process.env.CODEX_MODEL)args.push('--model',process.env.CODEX_MODEL);
  if(threadId)args.push('resume',threadId,'-');else args.push('-');
  const child=spawn(process.env.CODEX_BIN||'codex',args,{cwd:studio,windowsHide:true,stdio:['pipe','pipe','pipe'],env:process.env});
  const fail=e=>{if(!settled){settled=true;clearTimeout(timeout);reject(e);}};
  const timeout=setTimeout(()=>{child.kill('SIGTERM');fail(Error('Codex task exceeded timeout; inspect local task before retrying'));},Number(process.env.CODEX_TIMEOUT_SECONDS||14400)*1000);
  const consume=line=>{
   let event;try{event=JSON.parse(line);}catch{return;}
   if(event.type==='thread.started'&&event.thread_id){threadId=event.thread_id;write(stateFile,{threadId,updated_at:new Date().toISOString()});}
   if(event.type==='item.completed'&&event.item?.type==='agent_message')text=event.item.text||text;
   if(event.type==='turn.failed'||event.type==='error')lastError=String(event.error?.message||event.message||'Codex reported an error').slice(0,400);
  };
  child.stdout.on('data',chunk=>{buffer+=chunk.toString();let end;while((end=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,end));buffer=buffer.slice(end+1);}});
  child.stderr.on('data',()=>{}); // Never forward CLI diagnostics containing credentials or user config.
  child.on('error',()=>fail(Error('Unable to start Codex CLI; check CODEX_BIN and local login')));
  child.on('close',code=>{
   if(buffer.trim())consume(buffer);if(settled)return;clearTimeout(timeout);
   if(code!==0||lastError||!text)return fail(Error(lastError||'Codex returned no completed answer; inspect local session'));
   settled=true;resolve({text,threadId});
  });
  child.stdin.on('error',()=>{});child.stdin.end(prompt);
 });
}
