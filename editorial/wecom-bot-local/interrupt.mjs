export function controlIntent(text){
 if(/^(?:新任务|另一个任务|排队任务)\s*[:：]/.test(text))return {action:'queue',text:text.replace(/^[^:：]+[:：]\s*/,'')};
 if(/^(?:停止|停下|暂停|取消|打断|别做了|先停下|stop)(?:[吧了]?|当前(?:任务|制作)?)?[。！!\s]*$/i.test(text))return {action:'interrupt',resume:false,text:''};
 if(/^(?:打断|中断并修改|停止并修改)\s*[:：,，]?\s*\S/.test(text))return {action:'interrupt',resume:true,text:text.replace(/^(?:打断|中断并修改|停止并修改)\s*[:：,，]?\s*/,'')};
 if(/^(?:(?:通过|确认上传|上传草稿|ok)\s+C\d+-v\d+|草稿链接\s+|\/reviewlink\s+)/i.test(text)||/^(?:ok|确认上传|可以上传|上传草稿)[。！!\s]*$/i.test(text))return {action:'queue',text};
 return {action:'steer',text};
}

// Incoming controls never go through the task queue while the target turn is active.
export async function applyIncomingControl({record,target,control,persist,persistTarget,push}){
 const intent=controlIntent(record.text);if(intent.action==='queue')return false;
 if(!target){
  if(intent.action!=='interrupt')return false;
  if(intent.resume){record.text=intent.text;return false;}
  record.status='completed';record.reply='当前没有正在执行的任务。';persist();await push(record.reply);return true;
 }
 const previousIntent=target.interrupt_requested_by;
 record.status='control_pending';record.target_msgid=target.msgid;persist();
 if(intent.action==='interrupt'){target.interrupt_requested_by=record.msgid;persistTarget();}
 try{
  const command={action:intent.action,text:'来自群成员 '+record.user_id+' 的即时补充，消息凭据 wecom:'+record.msgid+'：\n'+intent.text,messageId:'wecom:'+record.msgid};
  let result=await control(command);
  for(let attempt=0;result.reason==='starting'&&attempt<50;attempt++){
   await new Promise(resolve=>setTimeout(resolve,200));result=await control(command);
  }
  record.control=result;
  if(!result.accepted){
   if(intent.action==='interrupt'){target.interrupt_requested_by=previousIntent;persistTarget();}
   if(result.reason==='not_running'){
    record.status=intent.action==='interrupt'&&!intent.resume?'completed':'queued';
    if(intent.resume)record.text=intent.text;persist();
    if(record.status==='completed'){await push('当前这一轮已结束，没有继续执行的任务。');return true;}return false;
   }
   throw Error('Task control was not accepted');
  }
  record.status=intent.action==='steer'?'steered':intent.resume?'queued':'completed';
  if(intent.resume){record.text='前一轮已按本条指令中断；保留已经落盘的文件，先核对当前状态，再按新要求继续：'+intent.text;record.priority=true;}
  persist();
  await push(intent.action==='steer'?'已补充到当前任务。':intent.resume?'已收到打断，正在停止当前一轮，随后按新要求继续。':'已请求停止当前任务。已生成的文件会保留。');
  return record.status!=='queued';
 }catch(error){record.status='control_unknown';record.error=String(error.message);persist();throw error;}
}
