import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {authorized,eligible,startProduction,write} from './production.mjs';
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
const binding={enabled:true,chatid:'group',group_members:'all',private_messages:'known_members',private_user_ids:['owner'],bot_id_sha256:sha('bot'),activated_at:'2026-01-01T00:00:00Z'};

test('explicit private access works before group binding and keeps each sender as the target',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-private-')),root=path.join(temp,'bot'),studio=path.join(temp,'wechat-content-studio');
 for(const folder of [path.join(root,'state'),path.join(studio,'state'),path.join(studio,'outbox')])fs.mkdirSync(folder,{recursive:true});
 write(path.join(studio,'config.json'),{});
 const mutable={...binding,chatid:null,private_messages:'all',private_user_ids:[]};
 const sends=[],runs=[];
 const worker=startProduction({root,botId:'bot',bindingOverride:mutable,onError:e=>{throw e;},
  client:{isConnected:true,replyStream:async()=>({errcode:0}),sendMessage:async(chat,body)=>{sends.push({chat,text:body.markdown.content});return {errcode:0};}},
  runTask:async(prompt,{messageId,onProgress})=>{runs.push(messageId);await onProgress('progress '+messageId);return{text:'done '+messageId};}});
 const frame=(chat,userid,id,bot='bot')=>({body:{chattype:chat,chatid:chat==='group'?'group':undefined,aibotid:bot,from:{userid},msgid:id,text:{content:'new task'}}});
 const wait=async n=>{for(let i=0;i<150;i++){if(sends.length>=n)return;await new Promise(r=>setTimeout(r,20));}assert.fail('Replies did not arrive');};
 try{
  assert.equal(await worker.handle(frame('group','owner','unbound')),false);
  assert.equal(await worker.handle(frame('single','first','wrong','another-bot')),false);
  assert.equal(await worker.handle(frame('single','first','one')),true);await wait(2);
  assert.equal(await worker.handle(frame('single','second','two')),true);await wait(4);
  Object.assign(mutable,{chatid:'group'});
  assert.equal(await worker.handle(frame('group','third','three')),true);await wait(6);
  assert.deepEqual(runs,['one','two','three']);
  assert.deepEqual(sends.map(s=>s.chat),['first','first','second','second','group','group']);
 }finally{worker.stop();while(worker.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(temp,{recursive:true,force:true});}
});

test('private delivery requires a known sender and the matching inbound receipt',()=>{
 const source={chattype:'single',user_id:'owner',msgid:'private1'};
 const item={status:'queued',created_at:'2027-01-01T00:00:00Z',destination:{provider:'wecom',chatid:'owner'},source_message_id:'private1'};
 assert(authorized({...source,from:{userid:'owner'}},binding,'bot'));
 assert(!authorized({...source,from:{userid:'stranger'}},binding,'bot'));
 assert(eligible(item,binding,source));
 assert(!eligible(item,binding));
 assert(!eligible({...item,source_message_id:'another'},binding,source));
 assert(!eligible({...item,destination:{provider:'wecom',chatid:'group'}},binding,source));
 assert(!eligible({...item,destination:{provider:'wecom',chatid:'stranger'}},binding,source));
});

test('private task queues separately and all its replies and MP4 stay in that private chat',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-conversation-')),root=path.join(temp,'bot'),studio=path.join(temp,'wechat-content-studio');
 for(const folder of [path.join(root,'state'),path.join(studio,'state'),path.join(studio,'outbox'),path.join(studio,'jobs/C0001/v1')])fs.mkdirSync(folder,{recursive:true});
 write(path.join(root,'state/binding.json'),binding);write(path.join(studio,'config.json'),{});
 const video=path.join(studio,'jobs/C0001/v1/review.mp4');fs.writeFileSync(video,'fixture');
 write(path.join(studio,'jobs/C0001/v1/manifest.json'),{sources:{},outputs:{'review.mp4':sha('fixture')}});
 const sends=[],runs=[];let unblock,controls=0;
 const waitFor=async condition=>{for(let i=0;i<150;i++){if(condition())return;await new Promise(r=>setTimeout(r,40));}assert.fail('Expected routing outcome did not arrive');};
 const client={isConnected:true,
  replyStream:async frame=>{sends.push({chat:frame.body.chattype==='single'?frame.body.from.userid:frame.body.chatid,text:'ack'});return{errcode:0};},
  sendMessage:async(chat,body)=>{sends.push({chat,text:body.markdown.content});return{errcode:0};},
  uploadMedia:async(bytes,options)=>{assert.equal(options.type,'file');assert.equal(options.filename,'C0001-v1.mp4');assert.equal(bytes.toString(),'fixture');return{media_id:'file-id'};},
  sendMediaMessage:async(chat,type,id)=>{sends.push({chat,type,id});return{errcode:0};}
 };
 const worker=startProduction({client,botId:'bot',root,onError:e=>{throw e;},controlTask:async()=>{controls++;return{accepted:true};},runTask:async(prompt,{messageId,onProgress})=>{
  runs.push(messageId);
  if(messageId==='group1'){await new Promise(resolve=>{unblock=resolve;});return{text:'group done'};}
  assert(prompt.includes('私聊'));
  const origin=JSON.parse(fs.readFileSync(path.join(studio,'state/active-wecom-task.json'),'utf8'));
  assert.equal(origin.chattype,'single');assert.equal(origin.reply_to,'owner');
  await onProgress('private progress');
  write(path.join(studio,'outbox/private.json'),{job_id:'C0001',version:1,status:'queued',created_at:'2027-01-01T00:00:00Z',destination:{provider:'wecom',chatid:origin.reply_to},source_message_id:origin.msgid,text:'private article link',files:[{path:video,sha256:sha('fixture')}],steps:[]});
  return{text:'private done'};
 }});
 const frame=(chattype,userid,msgid,content)=>({body:{chattype,chatid:chattype==='group'?'group':undefined,from:{userid},msgid,text:{content}}});
 try{
  assert.equal(await worker.handle(frame('single','stranger','denied','private topic')),false);
  assert.equal(sends.length,0);
  await worker.handle(frame('group','owner','group1','group topic'));await waitFor(()=>!!unblock);
  await worker.handle(frame('single','owner','private1','private topic'));
  assert.equal(controls,0);assert.deepEqual(runs,['group1']);
  unblock();await waitFor(()=>sends.some(s=>s.id==='file-id'));
  assert.deepEqual(runs,['group1','private1']);
  for(const text of ['private progress','private done','private article link'])assert.deepEqual(sends.filter(s=>s.text===text).map(s=>s.chat),['owner']);
  assert.deepEqual(sends.filter(s=>s.id==='file-id'),[{chat:'owner',type:'file',id:'file-id'}]);
  assert.deepEqual(sends.filter(s=>s.text==='group done').map(s=>s.chat),['group']);
  await worker.handle(frame('single','owner','private1','private topic'));assert.deepEqual(runs,['group1','private1']);
 }finally{unblock?.();worker.stop();while(worker.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(temp,{recursive:true,force:true});}
});
