import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {handleContentMessage} from '../wechat-content-studio/router.mjs';
import {reviewMedia} from './review-media.mjs';
import {applyIncomingControl} from './interrupt.mjs';

const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const now=()=>new Date().toISOString();
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
export function write(p,v){const t=p+'.'+crypto.randomUUID()+'.tmp';fs.writeFileSync(t,JSON.stringify(v,null,2));fs.renameSync(t,p);}
export function authorized(body,binding,botId,knownMembers=new Set()){
 if(binding.enabled!==true||(body.aibotid&&body.aibotid!==botId)||!body.from?.userid||!body.msgid)return false;
 if(body.chattype==='single')return binding.private_messages==='known_members'
  && (binding.private_user_ids?.includes(body.from.userid)||knownMembers.has(body.from.userid));
 return body.chattype==='group' && body.chatid===binding.chatid
  && (binding.group_members==='all'||binding.user_ids?.includes(body.from.userid));
}
export const replyTarget=(record,binding)=>record.chattype==='single'?record.user_id:binding.chatid;
export function taskText(content){return String(content||'').trim().replace(/^(?:<@[^>]+>|@\S+)[\s\u2005]+/,'').trim();}
export function eligible(item,binding,source,knownMembers=new Set()){
 if(item.status!=='queued'||item.destination?.provider!=='wecom'||!(Date.parse(item.created_at)>=Date.parse(binding.activated_at)))return false;
 if(source?.chattype==='single')return source.msgid===item.source_message_id
  && item.destination.chatid===source.user_id
  && authorized({...source,from:{userid:source.user_id}},binding,undefined,knownMembers);
 return item.destination.chatid===binding.chatid;
}
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
export function validateVideoReview(item,studio){
 if(!item.video_metadata_sha256)return;
 const folder=fs.realpathSync(path.join(studio,'jobs',item.job_id,'v'+item.version));
 const metadataPath=path.join(folder,'video-metadata.json');
 if(digest(fs.readFileSync(metadataPath))!==item.video_metadata_sha256)throw Error('Reviewed video title or description changed');
 const metadata=read(metadataPath),manifest=read(path.join(folder,'manifest.json'));
 if(metadata.title.trim()!==item.video_metadata?.title||metadata.description.trim()!==item.video_metadata?.description
  ||manifest.outputs['review.mp4']!==item.review_video_sha256)throw Error('Video review metadata does not match its version');
}
export function errorDetails(error){return {code:error?.errcode??error?.code??null,message:String(error?.errmsg??error?.message??'Unspecified error').slice(0,700)};}

export function startProduction({client,botId,root,onError,runTask,controlTask}){
 const stateDir=path.join(root,'state'),bindingPath=path.join(stateDir,'binding.json');
 if(!fs.existsSync(bindingPath))return {handle:async()=>false};
 const binding=read(bindingPath),studio=path.resolve(root,'../wechat-content-studio');
 if(binding.bot_id_sha256!==digest(botId))throw Error('Bot credentials do not match approved binding');
 const inbox=path.join(stateDir,'inbox');fs.mkdirSync(inbox,{recursive:true});
 const knownMembers=new Set();
 for(const name of fs.readdirSync(inbox).filter(n=>n.endsWith('.json'))){const v=read(path.join(inbox,name));
  if(v.chatid===binding.chatid&&v.chattype!=='single'&&v.user_id
   && (binding.group_members==='all'||binding.user_ids?.includes(v.user_id)))knownMembers.add(v.user_id);}
 const statusPath=path.join(stateDir,'production.json');
 const status={phase:'waiting_for_group_task',started_at:now(),historical_backlog_enabled:false};
 const save=()=>write(statusPath,{...status,updated_at:now()});save();
 // In-flight work after a crash has an unknown outcome: never execute or send it twice.
 for(const name of fs.readdirSync(inbox).filter(n=>n.endsWith('.json'))){const p=path.join(inbox,name),v=read(p);
  if(['running','replying'].includes(v.status)){v.status='outcome_unknown';write(p,v);}}
 const outbox=path.join(studio,'outbox');
 const sourceOf=item=>{if(!item.source_message_id)return undefined;const p=path.join(inbox,digest(item.source_message_id)+'.json');return fs.existsSync(p)?read(p):undefined;};
 for(const name of fs.readdirSync(outbox).filter(n=>n.endsWith('.json'))){const p=path.join(outbox,name),v=read(p);
  if(v.status==='sending'&&eligible({...v,status:'queued'},binding,sourceOf(v),knownMembers)){
   v.status='delivery_unknown';v.error='Service restarted during send; manual reconciliation required';write(p,v);}}
 const push=async(content,target=binding.chatid)=>{if(!client.isConnected)throw Error('WeCom disconnected');
  let chunk='';for(const char of String(content)){
   if(Buffer.byteLength(chunk+char,'utf8')>3800){ack(await client.sendMessage(target,{msgtype:'markdown',markdown:{content:chunk}}));chunk='';}
   chunk+=char;
  }
  if(chunk)ack(await client.sendMessage(target,{msgtype:'markdown',markdown:{content:chunk}}));};
 let handling=false,sending=false,activeRecord;
 async function processInbox(){
  if(handling||!client.isConnected)return;handling=true;
  try{
   const names=fs.readdirSync(inbox).filter(n=>n.endsWith('.json')).sort((a,b)=>Number(!!read(path.join(inbox,b)).priority)-Number(!!read(path.join(inbox,a)).priority)||String(read(path.join(inbox,a)).received_at).localeCompare(String(read(path.join(inbox,b)).received_at)));
   for(const name of names){const p=path.join(inbox,name),v=read(p);if(v.status!=='queued')continue;
    v.status='running';v.started_at=now();write(p,v);activeRecord={p,v};write(path.join(studio,'state/active-wecom-task.json'),{msgid:v.msgid,user_id:v.user_id,chattype:v.chattype||'group',reply_to:replyTarget(v,binding),started_at:v.started_at});status.phase='processing';status.active_message=v.msgid;save();
    try{
     const direct=await handleContentMessage({reply:async(_sender,text)=>{v.reply=text;write(p,v);}},
       {text:v.text,id:'wecom:'+v.msgid,senderId:v.user_id});
     const draftInstruction='\n\n最新送审要求：先把 MP4 文件和实际视频名、完整简介、目标账号发回来源会话，等用户看完回复 OK 后才上传视频号草稿箱。不再要求手机预览二维码；本流程不授权公开发布。上传必须显式 syncDraft:true，并使用已审核的同一版本、标题、简介和目标账号。完成后向来源会话列出视频名、视频简介、文件名、版本、目标账号、草稿上传实际结果和记录号；不能只发完成通知或把本地入库说成草稿成功。'+(direct?.draft_request?'\n本条真实用户已确认收到的视频文件；只处理以下草稿上传请求。先核对 video-draft-approval.json、manifest 与 video-metadata.json；旧记录或结果不明时先查记录，不重复执行。仅在工具策略允许时保存草稿，不公开发布。\n'+JSON.stringify(direct.draft_request):'');
     if(!direct||direct.draft_request){
      const prompt=(v.chattype==='single'?'来自已确认群成员的企业微信私聊任务。':'来自已授权企业微信群成员 @ 机器人的用户任务。')+'消息凭据 wecom:'+v.msgid+'；发起人 '+v.user_id+'。先读工作区 AGENTS.md。进度、最终答复、文章链接和视频附件全部回到本条消息的来源会话；私聊回本人，群消息回原群，不跨会话发送。关键阶段使用简短 commentary 给用户说明正在处理什么；这些内容会实时转发到来源会话。需要用户选方向、音色或试听确认时，先给真实小样或关键问题，在最终回复中明确等待选择后停止，收到下一条回复再继续，不要擅自全部做完才问。成品用 studio.py deliver，出站目的地由当前入站消息决定，禁止手动改成审核群、旧微信群或自动公开发布。只处理本条新任务，不补发历史稿件。\n\n'+v.text+(v.recovery_note?'\n\n本次人工恢复说明（保留原始用户任务）：'+v.recovery_note:'');
      if(!runTask)throw Error('Codex runner is not configured');
      const result=await runTask(prompt+draftInstruction,{messageId:v.msgid,onProgress:async text=>{
       v.progress=v.progress||[];const prior=v.progress.find(s=>s.text===text);if(prior)return prior.status==='sent';
       const progress={text,status:'sending',at:now()};v.progress.push(progress);write(p,v);
       try{await push(text,replyTarget(v,binding));progress.status='sent';progress.sent_at=now();}catch(error){progress.status='delivery_unknown';onError(error,'progress_delivery');}
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
     if(!v.skip_final_reply&&!v.interrupt_requested_by)await push(v.reply,replyTarget(v,binding));v.status='completed';v.reply_ack_at=now();write(p,v);
    }catch(error){
     if(v.interrupt_requested_by&&(/interrupt/i.test(error.message)||error.code==='CODEX_TURN_INTERRUPTED')){
      v.status='interrupted';v.interrupted_at=now();write(p,v);
      const cp=path.join(inbox,digest(v.interrupt_requested_by)+'.json');
      if(fs.existsSync(cp)){const c=read(cp);c.stop_confirmed_at=now();if(c.status!=='queued')c.status='completed';write(cp,c);}
     }else{v.status='outcome_unknown';v.error=errorDetails(error);write(p,v);onError(error,'production_task');
      const notice=/active writer/.test(String(error?.message))?'执行会话被占用，本次任务已停止，现有文件和回执已保留，需要恢复执行。':/timed out|deadline|timeout/i.test(String(error?.message))?'本次任务超时停止，现有文件和回执已保留，未自动重跑。':'本次任务处理异常，记录已保留，未自动重跑；请查询进度或联系维护。';
      v.failure_notice={text:notice,status:'sending',at:now()};write(p,v);
      try{await push(notice,replyTarget(v,binding));v.failure_notice.status='sent';}catch(noticeError){v.failure_notice.status='delivery_unknown';onError(noticeError,'failure_notice');}write(p,v);
     }
    }
    activeRecord=undefined;
    const activePath=path.join(studio,'state/active-wecom-task.json');
    if(fs.existsSync(activePath)&&read(activePath).msgid===v.msgid)fs.unlinkSync(activePath);
    status.phase='waiting_for_group_task';delete status.active_message;save();
   }
  }catch(error){onError(error,'production_inbox');}finally{handling=false;}
 }
 async function processOutbox(){
  if(sending||!client.isConnected)return;sending=true;
  try{for(const name of fs.readdirSync(outbox).filter(n=>n.endsWith('.json')).sort()){
   const p=path.join(outbox,name),v=read(p);if(!eligible(v,binding,sourceOf(v),knownMembers))continue;
   let files;try{files=validateFiles(v,studio);validateVideoReview(v,studio);}catch(error){v.status='failed';v.error=error.message;write(p,v);continue;}
   const cancelled=()=>{if(!v.source_message_id)return false;const source=path.join(inbox,digest(v.source_message_id)+'.json');return fs.existsSync(source)&&!!read(source).interrupt_requested_by;};
   if(cancelled()){v.status='cancelled';write(p,v);continue;}
   v.status='sending';v.steps=v.steps||[];write(p,v);
   try{
    if(!v.steps.some(s=>s.step==='text'&&s.errcode===0)){
     await push(v.text,v.destination.chatid);v.steps.push({step:'text',errcode:0,at:now()});write(p,v);
    }
    for(let i=0;i<files.length;i++){
     if(v.steps.some(s=>s.step==='file:'+i&&s.errcode===0))continue;
     v.stage='preparing_media';write(p,v);
     const media=await reviewMedia(files[i],process.env.FFMPEG_BINARY||read(path.join(studio,'config.json')).ffmpeg);
     v.delivery_media={path:media.path,sha256:digest(media.bytes),bytes:media.bytes.length,media_type:'file',filename:media.filename};write(p,v);
     v.stage='uploading';v.active_file=i;write(p,v);
     const upload=await client.uploadMedia(media.bytes,{type:'file',filename:media.filename});
     if(!upload.media_id)throw Error('File upload returned no media ID');
     v.steps.push({step:'upload:'+i,media_id:upload.media_id,media_type:'file',at:now()});write(p,v);
     if(cancelled()){const e=new Error('Delivery cancelled by user interruption');e.code='DELIVERY_CANCELLED';throw e;}
     v.stage='sending_file';write(p,v);
     ack(await client.sendMediaMessage(v.destination.chatid,'file',upload.media_id));
     v.steps.push({step:'file:'+i,media_type:'file',filename:media.filename,errcode:0,at:now()});write(p,v);
    }
    v.status='sent';v.stage='completed';v.sent_at=now();v.recipient_confirmation='pending';write(p,v);
   }catch(error){v.status=error.code==='DELIVERY_CANCELLED'?'cancelled':['uploading','preparing_media'].includes(v.stage)?'upload_failed':'delivery_unknown';v.error=errorDetails(error);v.failed_at=now();write(p,v);onError(error,'production_delivery');}
  }}finally{sending=false;}
 }
 const timer=setInterval(()=>{void processInbox();void processOutbox().catch(e=>onError(e,'outbox'));},3000);
 return {stop:()=>clearInterval(timer),isBusy:()=>handling||sending,handle:async frame=>{
  const body=frame.body||{};if(!authorized(body,binding,botId,knownMembers))return false;
  if(body.chattype==='group')knownMembers.add(body.from.userid);
  const text=taskText(body.text?.content);if(!text)return true;
  const p=path.join(inbox,digest(body.msgid)+'.json');if(fs.existsSync(p))return true;
  write(p,{msgid:body.msgid,user_id:body.from.userid,chatid:body.chatid,chattype:body.chattype,text,received_at:now(),status:'queued'});
  // Only acknowledge a new real user task, never on startup or configuration changes.
  try{ack(await client.replyStream(frame,'task_'+crypto.randomUUID(),'收到，处理中',true));}catch(e){onError(e,'task_ack');}
  if(/^(?:进度\s+C\d{4,}|任务列表)\s*$/.test(text)){
   const record=read(p);record.status='direct_command';write(p,record);
   try{
    await handleContentMessage({reply:async(_sender,reply)=>{
     if(status.active_message){const active=read(path.join(inbox,digest(status.active_message)+'.json'));if(replyTarget(active,binding)===replyTarget(record,binding)){const latest=active.progress?.at(-1);reply+='\n\n当前正在处理：'+active.text+(latest?'\n最近进度：'+latest.text:'');}}
     await push(reply,replyTarget(record,binding));
    }},{text,id:'wecom:'+body.msgid,senderId:body.from.userid});
    record.status='completed';record.reply_ack_at=now();write(p,record);
   }catch(error){record.status='outcome_unknown';record.error=errorDetails(error);write(p,record);onError(error,'status_reply');}
   return true;
  }
  const record=read(p),targetRecord=activeRecord&&replyTarget(activeRecord.v,binding)===replyTarget(record,binding)?activeRecord:undefined;
  try{
   const handled=await applyIncomingControl({record,target:targetRecord?.v,
    control:options=>{if(!controlTask)throw Error('Native task control is unavailable');return controlTask({...options,targetMessageId:targetRecord?.v.msgid});},
    persist:()=>write(p,record),persistTarget:()=>{if(targetRecord)write(targetRecord.p,targetRecord.v);},push:text=>push(text,replyTarget(record,binding))});
   if(handled)return true;
  }catch(error){onError(error,'task_control');await push('当前控制请求的结果不明，已保留记录，不会自动重复执行。',replyTarget(record,binding));return true;}
  void processInbox();return true;
 }};
}
