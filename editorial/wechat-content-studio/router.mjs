import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const config=fs.existsSync(path.join(root,'config.json'))?JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8')):{python:process.env.PYTHON||'python3'};
export async function handleContentMessage(service,message){
  const text=message.text.trim();let request;
  let match=/^(?:草稿链接|\/reviewlink)\s+(C\d{4,})-v([1-9]\d*)\s+(https:\/\/\S+)\s*$/.exec(text);
  if(match)request={action:'link',id:match[1],version:Number(match[2]),url:match[3],message_id:message.id};
  match=/^通过\s+(C\d{4,})-v([1-9]\d*)\s*$/.exec(text);
  if(match)request={action:'approve',id:match[1],version:Number(match[2]),message_id:message.id};
  match=/^(?:确认发布|发布|ok)\s+(C\d{4,})-v([1-9]\d*)[。！!\s]*$/i.exec(text);
  if(match)request={action:'confirm-video',id:match[1],version:Number(match[2]),message_id:message.id};
  if(/^(?:ok|确认发布|可以发布|发布吧)[。！!\s]*$/i.test(text))request={action:'confirm-video',message_id:message.id};
  match=/^(?:进度\s+(C\d{4,})|任务列表)\s*$/.exec(text);
  if(match)request={action:'status',id:match[1]};
  if(!request)return false;
  const result=await new Promise((resolve,reject)=>{
    const child=spawn(config.python,[path.join(root,'router.py')],{cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONUTF8:'1'}});
    let output='',error='';child.stdout.on('data',c=>output+=c);child.stderr.on('data',c=>error+=c);child.on('error',reject);
    child.on('close',code=>{try{if(code)throw new Error(error);resolve(JSON.parse(output));}catch(e){reject(e);}});child.stdin.end(JSON.stringify(request));
  });
  let reply;
  if(!result.ok)reply='内容工作室：'+result.error;
  else if(result.result.publish_request)reply=`已记录 ${result.result.job_id}-v${result.result.version} 的手机预览确认，进入视频发布处理。`;
  else if(result.result.status==='already_confirmed')reply='该版本已确认过，不会重复提交发布；请查询已有发布记录。';
  else if(request.action==='approve')reply=`已记录 ${request.id}-v${request.version} 审核通过。未发布。`;
  else if(request.action==='link')reply=`已登记 ${request.id}-v${request.version} 的用户提供官方预览链接，来源会话发送状态：${result.result.delivery||result.result.status}。`;
  else reply=result.result.length?result.result.map(j=>`${j.id}-v${j.version}｜${j.topic}\n制作：${j.status}\n送审：${j.deliveries.map(d=>`v${d.version} ${d.status}`).join('；')||'未入队'}`).join('\n\n'):'目前没有内容制作任务。';
  await service.reply(message.senderId,reply);return result.ok&&result.result.publish_request?{publish_request:result.result.publish_request}:true;
}
