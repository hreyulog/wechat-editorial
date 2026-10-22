import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {handleContentMessage} from '../wechat-content-studio/router.mjs';
import {reviewMedia} from './review-media.mjs';

const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const now=()=>new Date().toISOString();
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
export function write(p,v){const t=p+'.'+crypto.randomUUID()+'.tmp';fs.writeFileSync(t,JSON.stringify(v,null,2));fs.renameSync(t,p);}
export function authorized(body,binding,botId){
 return binding.enabled===true && (!body.aibotid||body.aibotid===botId) && body.chattype==='group'
  && body.chatid===binding.chatid && !!body.from?.userid
  && (binding.group_members==='all'||binding.user_ids?.includes(body.from.userid)) && !!body.msgid;
}
export function taskText(content){return String(content||'').trim().replace(/^(?:<@[^>]+>|@\S+)[\s\u2005]+/,'').trim();}
export function eligible(item,binding){return item.status==='queued' && item.destination?.provider==='wecom'
 && item.destination.chatid===binding.chatid && Date.parse(item.created_at)>=Date.parse(binding.activated_at);}
export function validateFiles(item,studio){
 if(!/^C\d{4,}$/.test(item.job_id)||!Number.isInteger(item.version)||item.version<1)throw Error('Invalid outbox job');
 const folder=fs.realpathSync(path.join(studio,'jobs',item.job_id,'v'+item.version));
 const manifest=read(path.join(folder,'manifest.json'));
 for(const [name,sha] of Object.entries({...manifest.sources,...manifest.outputs})){
  const p=fs.realpathSync(path.join(folder,name));const rel=path.relative(folder,p);
  if(rel.startsWith('..')||path.isAbsolute(rel)||digest(fs.readFileSync(p))!==sha)throw Error('Built artifact changed');
 }
 return item.files.map(f=>{
  const p=fs.realpathSync(f.path);const rel=path.relative(folder,p);
  if(rel.startsWith('..')||path.isAbsolute(rel)||path.basename(p)!=='review.mp4')throw Error('Unexpected delivery file');
  const bytes=fs.readFileSync(p);
  if(bytes.length>50*1024*1024)throw Error('Video exceeds official upload limit; produce a smaller review copy');
  if(digest(bytes)!==f.sha256||manifest.outputs['review.mp4']!==f.sha256)throw Error('Delivery hash mismatch');
  return {bytes,path:p,filename:item.job_id+'-v'+item.version+'.mp4'};
 });
}
function ack(result){if(result?.errcode!==0)throw Error('Official send acknowledgment failed');}
export function errorDetails(error){return {code:error?.errcode??error?.code??null,message:String(error?.errmsg??error?.message??'Unspecified error').slice(0,700)};}

export function startProduction({client,botId,root,onError,runTask}){
 const stateDir=path.join(root,'state'),bindingPath=path.join(stateDir,'binding.json');
 if(!fs.existsSync(bindingPath))return {handle:async()=>false};
 const binding=read(bindingPath),studio=path.resolve(root,'../wechat-content-studio');
 if(binding.bot_id_sha256!==digest(botId))throw Error('Bot credentials do not match approved binding');
 const inbox=path.join(stateDir,'inbox');fs.mkdirSync(inbox,{recursive:true});
 const statusPath=path.join(stateDir,'production.json');
 const status={phase:'waiting_for_group_task',started_at:now(),historical_backlog_enabled:false};
 const save=()=>write(statusPath,{...status,updated_at:now()});save();
 // In-flight work after a crash has an unknown outcome: never execute or send it twice.
 for(const name of fs.readdirSync(inbox).filter(n=>n.endsWith('.json'))){const p=path.join(inbox,name),v=read(p);
  if(['running','replying'].includes(v.status)){v.status='outcome_unknown';write(p,v);}}
 const outbox=path.join(studio,'outbox');
 for(const name of fs.readdirSync(outbox).filter(n=>n.endsWith('.json'))){const p=path.join(outbox,name),v=read(p);
  if(v.destination?.provider==='wecom'&&v.destination.chatid===binding.chatid&&v.status==='sending'){
   v.status='delivery_unknown';v.error='Service restarted during send; manual reconciliation required';write(p,v);}}
 const push=async content=>{if(!client.isConnected)throw Error('WeCom disconnected');
  let clipped='';for(const char of String(content)){if(Buffer.byteLength(clipped+char,'utf8')>3800)break;clipped+=char;}
  ack(await client.sendMessage(binding.chatid,{msgtype:'markdown',markdown:{content:clipped}}));};
 let handling=false,sending=false;
 async function processInbox(){
  if(handling||!client.isConnected)return;handling=true;
  try{
   const names=fs.readdirSync(inbox).filter(n=>n.endsWith('.json')).sort((a,b)=>String(read(path.join(inbox,a)).received_at).localeCompare(String(read(path.join(inbox,b)).received_at)));
   for(const name of names){const p=path.join(inbox,name),v=read(p);if(v.status!=='queued')continue;
    v.status='running';v.started_at=now();write(p,v);status.phase='processing';status.active_message=v.msgid;save();
    try{
     const direct=await handleContentMessage({reply:async(_sender,text)=>{v.reply=text;write(p,v);}},
       {text:v.text,id:'wecom:'+v.msgid,senderId:v.user_id});
     if(!direct){
      const prompt='来自已授权企业微信群成员 @ 机器人的用户任务。消息凭据 wecom:'+v.msgid+'；发起人 '+v.user_id+'。本群全体成员均已获准发起制作及修改任务。先读工作区 AGENTS.md。关键阶段使用简短 commentary 给群成员说明正在处理什么；这些内容会实时转发。需要用户选方向、音色或试听确认时，先给真实小样或关键问题，在最终回复中明确等待选择后停止，收到下一条回复再继续，不要擅自全部做完才问。成品用 studio.py deliver 入队到已绑定企业微信群，禁止发到旧微信群或自动公开发布。只处理本条新任务，不补发历史稿件。\n\n'+v.text;
      if(!runTask)throw Error('Codex runner is not configured');
      const result=await runTask(prompt,{onProgress:async text=>{
       v.progress=v.progress||[];const prior=v.progress.find(s=>s.text===text);if(prior)return prior.status==='sent';
       const progress={text,status:'sending',at:now()};v.progress.push(progress);write(p,v);
       try{await push(text);progress.status='sent';progress.sent_at=now();}catch(error){progress.status='delivery_unknown';onError(error,'progress_delivery');}
       write(p,v);return progress.status==='sent';
      }});
      v.reply=result.text||'任务已处理，请查看送审内容或发送“任务列表”。';
      v.codex_thread_id=result.threadId;
      if(result.progressFinalAttempted){
       if(!result.progressFinalDelivered)throw Error('Final reply delivery is unknown; do not resend automatically');
       v.skip_final_reply=true;
      }
     }
     v.status='replying';v.finished_at=now();write(p,v);
     if(!v.skip_final_reply)await push(v.reply);v.status='completed';v.reply_ack_at=now();write(p,v);
    }catch(error){v.status='outcome_unknown';v.error=errorDetails(error);write(p,v);onError(error,'production_task');}
    status.phase='waiting_for_group_task';delete status.active_message;save();
   }
  }catch(error){onError(error,'production_inbox');}finally{handling=false;}
 }
 async function processOutbox(){
  if(sending||!client.isConnected)return;sending=true;
  try{for(const name of fs.readdirSync(outbox).filter(n=>n.endsWith('.json')).sort()){
   const p=path.join(outbox,name),v=read(p);if(!eligible(v,binding))continue;
   let files;try{files=validateFiles(v,studio);}catch(error){v.status='failed';v.error=error.message;write(p,v);continue;}
   v.status='sending';v.steps=v.steps||[];write(p,v);
   try{
    if(!v.steps.some(s=>s.step==='text'&&s.errcode===0)){
     await push(v.text);v.steps.push({step:'text',errcode:0,at:now()});write(p,v);
    }
    for(let i=0;i<files.length;i++){
     if(v.steps.some(s=>s.step==='file:'+i&&s.errcode===0))continue;
     v.stage='preparing_media';write(p,v);
     const media=await reviewMedia(files[i],process.env.FFMPEG_BINARY||read(path.join(studio,'config.json')).ffmpeg);
     v.delivery_media={path:media.path,sha256:digest(media.bytes),bytes:media.bytes.length};write(p,v);
     v.stage='uploading';v.active_file=i;write(p,v);
     const upload=await client.uploadMedia(media.bytes,{type:'video',filename:media.filename});
     if(!upload.media_id)throw Error('Video upload returned no media ID');
     v.steps.push({step:'upload:'+i,media_id:upload.media_id,at:now()});write(p,v);
     v.stage='sending_video';write(p,v);
     ack(await client.sendMediaMessage(binding.chatid,'video',upload.media_id,{title:v.job_id+'-v'+v.version+' 审片',description:'请在本群 @ 机器人提出修改意见。'}));
     v.steps.push({step:'file:'+i,errcode:0,at:now()});write(p,v);
    }
    v.status='sent';v.stage='completed';v.sent_at=now();v.recipient_confirmation='pending';write(p,v);
   }catch(error){v.status=['uploading','preparing_media'].includes(v.stage)?'upload_failed':'delivery_unknown';v.error=errorDetails(error);v.failed_at=now();write(p,v);onError(error,'production_delivery');}
  }}finally{sending=false;}
 }
 const timer=setInterval(()=>{void processInbox();void processOutbox().catch(e=>onError(e,'outbox'));},3000);
 return {stop:()=>clearInterval(timer),isBusy:()=>handling||sending,handle:async frame=>{
  const body=frame.body||{};if(!authorized(body,binding,botId))return false;
  const text=taskText(body.text?.content);if(!text)return true;
  const p=path.join(inbox,digest(body.msgid)+'.json');if(fs.existsSync(p))return true;
  write(p,{msgid:body.msgid,user_id:body.from.userid,chatid:body.chatid,text,received_at:now(),status:'queued'});
  // Only acknowledge a new real user task, never on startup or configuration changes.
  try{ack(await client.replyStream(frame,'task_'+crypto.randomUUID(),'收到，处理中',true));}catch(e){onError(e,'task_ack');}
  if(/^(?:进度\s+C\d{4,}|任务列表)\s*$/.test(text)){
   const record=read(p);record.status='direct_command';write(p,record);
   try{
    await handleContentMessage({reply:async(_sender,reply)=>{
     if(status.active_message){const active=read(path.join(inbox,digest(status.active_message)+'.json'));const latest=active.progress?.at(-1);reply+='\n\n当前正在处理：'+active.text+(latest?'\n最近进度：'+latest.text:'');}
     await push(reply);
    }},{text,id:'wecom:'+body.msgid,senderId:body.from.userid});
    record.status='completed';record.reply_ack_at=now();write(p,record);
   }catch(error){record.status='outcome_unknown';record.error=errorDetails(error);write(p,record);onError(error,'status_reply');}
   return true;
  }
  void processInbox();return true;
 }};
}
