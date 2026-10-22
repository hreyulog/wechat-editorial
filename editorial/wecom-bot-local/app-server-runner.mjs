import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
import {write} from './production.mjs';

// One native Codex app-server owns the thread; new input can steer the active turn.
export function createCodexRunner({studio,stateDir,repository}){
 const stateFile=path.join(stateDir,'codex-thread.json');
 let child,ready,nextId=1,active,threadId=fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')).threadId:undefined;
 const pending=new Map(),loaded=new Set();
 const send=value=>{if(!child||child.exitCode!==null||child.stdin.destroyed)throw Error('Codex app-server is disconnected');child.stdin.write(JSON.stringify(value)+'\n');};
 const request=(method,params)=>new Promise((resolve,reject)=>{
  const id=nextId++,timer=setTimeout(()=>{pending.delete(id);reject(Error('Codex request timed out; outcome requires reconciliation'));},30000);
  pending.set(id,{resolve,reject,timer});try{send({id,method,params});}catch(e){clearTimeout(timer);pending.delete(id);reject(e);}
 });
 const fail=error=>{
  for(const p of pending.values()){clearTimeout(p.timer);p.reject(error);}pending.clear();
  if(active){clearTimeout(active.timer);active.reject(error);active=undefined;}ready=undefined;loaded.clear();
 };
 const finish=async target=>{
  if(!target.completion||!target.started)return;await target.chain;
  if(active!==target)return;active=undefined;clearTimeout(target.timer);
  const turn=target.completion;
  if(turn.status==='completed'){target.resolve({text:target.text||'本轮已完成。',threadId:target.threadId});return;}
  const error=Error(turn.status==='interrupted'?'Codex app-server turn was interrupted':turn.error?.message||'Codex turn failed');
  if(turn.status==='interrupted')error.code='CODEX_TURN_INTERRUPTED';target.reject(error);
 };
 const incoming=message=>{
  if(message.id!==undefined&&!message.method){
   const p=pending.get(message.id);if(!p)return;pending.delete(message.id);clearTimeout(p.timer);
   if(message.error)p.reject(Error(String(message.error.message||'Codex RPC failed')));else p.resolve(message.result);return;
  }
  if(message.method&&message.id!==undefined){
   const id=message.id;
   if(/requestApproval$/.test(message.method)){send({id,result:message.method==='item/permissions/requestApproval'?{permissions:{},scope:'turn'}:{decision:'decline'}});return;}
   if(message.method==='item/tool/requestUserInput'){send({id,result:{answers:{}}});return;}
   if(message.method==='currentTime/read'){send({id,result:{currentTimeAt:Math.floor(Date.now()/1000)}});return;}
   send({id,error:{code:-32601,message:'Unsupported interactive tool; ask the user in the visible final response.'}});return;
  }
  const target=active,p=message.params||{};if(!target||p.threadId!==target.threadId)return;
  if(message.method==='turn/started')target.turnId=p.turn?.id||target.turnId;
  if(message.method==='item/completed'&&p.item?.type==='agentMessage'){
   const text=p.item.text?.trim();if(!text)return;
   if(p.item.phase==='commentary')target.chain=target.chain.then(()=>target.onProgress?.(text));else target.text=text;
  }
  if(message.method==='turn/completed'){
   if(target.turnId&&p.turn?.id!==target.turnId)return;target.completion=p.turn;void finish(target).catch(fail);
  }
 };
 const connect=()=>{
  if(ready)return ready;
  ready=(async()=>{
   child=spawn(process.env.CODEX_BIN||'codex',['-c','approval_policy="never"','-c','sandbox_workspace_write.network_access=true','-c','sandbox_workspace_write.writable_roots='+JSON.stringify([repository]),'app-server','--stdio'],{cwd:studio,windowsHide:true,stdio:['pipe','pipe','pipe'],env:process.env});
   const processRef=child;readline.createInterface({input:child.stdout}).on('line',line=>{try{incoming(JSON.parse(line));}catch(e){fail(e);}});
   child.stderr.on('data',()=>{});child.stdin.on('error',()=>{});
   child.on('error',()=>fail(Error('Unable to start Codex app-server; check CODEX_BIN and login')));
   child.on('exit',()=>{if(child===processRef)fail(Error('Codex app-server exited; inspect the task before replaying it'));});
   await request('initialize',{clientInfo:{name:'wechat-editorial',title:'WeChat Editorial',version:'0.1.0'},capabilities:{experimentalApi:false}});
   send({method:'initialized',params:{}});
  })();return ready;
 };
 const run=async(prompt,{onProgress,messageId}={})=>{
  await connect();if(active)throw Error('A Codex turn is already active');
  if(!threadId||!loaded.has(threadId)){
   const result=await request(threadId?'thread/resume':'thread/start',{...(threadId?{threadId}:{}),cwd:studio,approvalPolicy:'never',sandbox:'workspace-write',...(process.env.CODEX_MODEL?{model:process.env.CODEX_MODEL}:{})});
   threadId=result.thread?.id||threadId;if(!threadId)throw Error('Codex returned no thread ID');loaded.add(threadId);write(stateFile,{threadId,updated_at:new Date().toISOString()});
  }
  return new Promise((resolve,reject)=>{
   const target={threadId,messageId,text:'',onProgress,chain:Promise.resolve(),resolve,reject,started:false};active=target;
   target.timer=setTimeout(()=>reject(Error('Codex task deadline exceeded; outcome is unknown')),Number(process.env.CODEX_TIMEOUT_SECONDS||14400)*1000);
   request('turn/start',{threadId,cwd:studio,approvalPolicy:'never',input:[{type:'text',text:prompt,text_elements:[]}]}).then(result=>{
    target.turnId=result.turn?.id||target.turnId;if(!target.turnId)throw Error('Codex returned no turn ID');target.started=true;return finish(target);
   }).catch(error=>{if(active===target)active=undefined;clearTimeout(target.timer);reject(error);});
  });
 };
 run.control=async({action,text,messageId,targetMessageId})=>{
  const target=active;if(!target?.turnId||(targetMessageId&&target.messageId!==targetMessageId))return {accepted:false,reason:'not_running'};
  if(action==='interrupt')await request('turn/interrupt',{threadId:target.threadId,turnId:target.turnId});
  else await request('turn/steer',{threadId:target.threadId,expectedTurnId:target.turnId,clientUserMessageId:messageId,input:[{type:'text',text,text_elements:[]}]});
  return {accepted:true,action,threadId:target.threadId,turnId:target.turnId};
 };
 run.close=()=>{child?.kill();};return run;
}
