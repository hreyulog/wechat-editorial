import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {WSClient} from '@wecom/aibot-node-sdk';
import {startProduction,errorDetails,write,taskText} from './production.mjs';
import {createCodexRunner} from './codex-runner.mjs';

const root=path.dirname(fileURLToPath(import.meta.url)),repository=path.resolve(root,'../..');
if(fs.existsSync(path.join(repository,'.env')))process.loadEnvFile(path.join(repository,'.env'));
const stateDir=path.join(root,'state');fs.mkdirSync(stateDir,{recursive:true,mode:0o700});
const botId=process.env.WECOM_BOT_ID?.trim(),secret=process.env.WECOM_BOT_SECRET?.trim();
if(!botId?.startsWith('aib')||!secret)throw Error('Fill WECOM_BOT_ID and WECOM_BOT_SECRET in the local .env first');
const lock=path.join(stateDir,'listener.lock');
if(fs.existsSync(lock)){
 const owner=JSON.parse(fs.readFileSync(lock,'utf8'));
 try{process.kill(owner.pid,0);throw Error('A listener is already running for this installation');}
 catch(error){if(error.code!=='ESRCH')throw error;fs.unlinkSync(lock);}
}
fs.writeFileSync(lock,JSON.stringify({pid:process.pid,started_at:new Date().toISOString()}),{flag:'wx',mode:0o600});
process.on('exit',()=>{try{fs.unlinkSync(lock);}catch{}});
const state={pid:process.pid,authenticated:false,phase:'starting'};
const save=()=>write(path.join(stateDir,'connectivity.json'),{...state,updated_at:new Date().toISOString()});
const sanitize=s=>String(s).replaceAll(secret,'[REDACTED]').replaceAll(botId,'[BOT]');
const onError=(error,where)=>{const detail=errorDetails(error);state.last_error={where,code:detail.code,message:sanitize(detail.message),at:new Date().toISOString()};save();};
const logger={info:()=>{},warn:()=>{},error:()=>{},debug:message=>{
 const m=/^Uploaded chunk (\d+)\/(\d+) \((\d+) bytes\)$/.exec(String(message));
 if(m)write(path.join(stateDir,'upload-progress.json'),{chunk:+m[1],total:+m[2],bytes:+m[3],at:new Date().toISOString()});
}};
const client=new WSClient({botId,secret,logger,maxAuthFailureAttempts:1,maxReconnectAttempts:10,requestTimeout:30000});
const bind=process.argv.includes('--bind'),phrase=crypto.randomBytes(4).toString('hex'),studio=path.resolve(root,'../wechat-content-studio');
let worker,runner,closing=false;
if(bind){console.log('请在目标企业微信群 @ 此机器人，发送：绑定审核群 '+phrase);}
else{
 if(!fs.existsSync(path.join(stateDir,'binding.json')))throw Error('Run npm run bind to select a group before starting the bot');
 runner=createCodexRunner({studio,stateDir,repository});
 worker=startProduction({client,botId,root,onError,runTask:runner,controlTask:runner.control});
}
client.on('authenticated',()=>{state.authenticated=true;state.phase=bind?'waiting_for_binding':'waiting_for_group_task';save();console.log('Enterprise bot authenticated.');});
client.on('disconnected',()=>{state.authenticated=false;state.phase='disconnected';save();});
client.on('error',e=>onError(e,'sdk'));
client.on('message.text',frame=>{void (async()=>{
 if(closing)return;
 if(!bind){await worker.handle(frame);return;}
 const b=frame.body||{};
 if(b.chattype!=='group'||!b.chatid||!b.from?.userid||(b.aibotid&&b.aibotid!==botId)||taskText(b.text?.content)!=='绑定审核群 '+phrase)return;
 const binding={enabled:true,chatid:b.chatid,group_members:'all',bot_id_sha256:crypto.createHash('sha256').update(botId).digest('hex'),activated_at:new Date().toISOString(),historical_backlog_enabled:false};
 write(path.join(stateDir,'binding.json'),binding);
 const configPath=path.join(studio,'config.json'),config=JSON.parse(fs.readFileSync(configPath,'utf8'));
 config.review_destination={provider:'wecom',chatid:b.chatid,display_name:'企业微信审核群'};write(configPath,config);
 console.log('Group binding saved locally. No sample, historical artifact, or notification was sent.');client.disconnect();process.exit(0);
 })().catch(e=>onError(e,'message'));});
let timer;
const close=async()=>{
 if(closing)return;closing=true;worker?.stop();
 while(worker?.isBusy())await new Promise(r=>setTimeout(r,1000));
 clearInterval(timer);runner?.close();client.disconnect();state.phase='stopped';save();process.exit(0);
};
process.on('SIGTERM',()=>void close());process.on('SIGINT',()=>void close());
timer=setInterval(()=>{state.socket_connected=client.isConnected;save();},5000);
save();client.connect();
