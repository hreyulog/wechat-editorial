import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {authorized,eligible,taskText,validateFiles,startProduction,write,errorDetails} from './production.mjs';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const binding={enabled:true,chatid:'test-group',user_ids:['owner'],activated_at:'2026-10-22T16:00:00Z',bot_id_sha256:sha('test-bot')};
test('only approved user and group are authorized',()=>{
 const b={chattype:'group',chatid:'test-group',from:{userid:'owner'},msgid:'1',aibotid:'test-bot'};
 assert(authorized(b,binding,'test-bot'));
 for(const patch of [{chatid:'elsewhere'},{from:{userid:'other'}},{aibotid:'other'},{chattype:'single'}])assert(!authorized({...b,...patch},binding,'test-bot'));
 assert.equal(taskText('@机器人\u2005做一篇文章'),'做一篇文章');
});
test('old and legacy queues cannot be sent by enterprise worker',()=>{
 const q={status:'queued',created_at:'2026-10-22T16:01:00Z',destination:{provider:'wecom',chatid:'test-group'}};
 assert(eligible(q,binding));
 assert(!eligible({...q,created_at:'2026-10-22T15:59:00Z'},binding));
 assert(!eligible({...q,destination:undefined},binding));assert(!eligible({...q,status:'delivery_unknown'},binding));
});
test('all group members can trigger when owner authorizes group membership',()=>{
 const b={chattype:'group',chatid:'test-group',from:{userid:'another-member'},msgid:'2'};
 const all={...binding,group_members:'all'};
 assert(authorized(b,all,'test-bot'));
 assert(!authorized({...b,chatid:'another-group'},all,'test-bot'));
});
test('official structured upload errors retain code and message',()=>{
 assert.deepEqual(errorDetails({errcode:40011,errmsg:'invalid video size'}),{code:40011,message:'invalid video size'});
});
test('media must match built version and hash',()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-media-'));
 try{const folder=path.join(temp,'jobs/C0001/v1');fs.mkdirSync(folder,{recursive:true});const p=path.join(folder,'review.mp4');
  fs.writeFileSync(p,'fixture');const hash=sha('fixture');write(path.join(folder,'manifest.json'),{sources:{},outputs:{'review.mp4':hash}});
  const item={job_id:'C0001',version:1,files:[{path:p,sha256:hash}]};assert.equal(validateFiles(item,temp).length,1);
  fs.writeFileSync(p,'changed');assert.throws(()=>validateFiles(item,temp),/changed/);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
});
test('startup stays silent; one new callback executes once and replies to same group',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-route-')),root=path.join(temp,'bot'),studio=path.join(temp,'wechat-content-studio');
 for(const p of [path.join(root,'state'),path.join(studio,'state'),path.join(studio,'outbox')])fs.mkdirSync(p,{recursive:true});
 write(path.join(root,'state/binding.json'),binding);
 const sends=[];let continuations=0;
 const client={isConnected:true,replyStream:async()=>{sends.push('ack');return {errcode:0};},sendMessage:async(chat,body)=>{assert.equal(chat,binding.chatid);sends.push(body.markdown.content);return {errcode:0};}};
 const worker=startProduction({client,botId:'test-bot',root,onError:e=>{throw e;},runTask:async prompt=>{continuations++;assert(prompt.includes('new topic'));return{text:'mock completed'};}});
 try{
  assert.equal(sends.length,0);
  const frame={body:{chattype:'group',chatid:binding.chatid,from:{userid:'owner'},msgid:'new1',text:{content:'@机器人 new topic'}}};
  await worker.handle(frame);await worker.handle(frame);
  for(let n=0;n<30&&!sends.includes('mock completed');n++)await new Promise(r=>setTimeout(r,10));
  assert.equal(continuations,1);assert.deepEqual(sends,['ack','mock completed']);
 }finally{worker.stop();while(worker.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(temp,{recursive:true,force:true});}
});
test('failed upload can resume video without repeating acknowledged article',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-upload-')),root=path.join(temp,'bot'),studio=path.join(temp,'wechat-content-studio');
 const folder=path.join(studio,'jobs/C0001/v1');
 for(const p of [path.join(root,'state'),path.join(studio,'outbox'),folder])fs.mkdirSync(p,{recursive:true});
 write(path.join(root,'state/binding.json'),binding);write(path.join(studio,'config.json'),{});
 const video=path.join(folder,'review.mp4');fs.writeFileSync(video,'fixture');const hash=sha('fixture');
 write(path.join(folder,'manifest.json'),{sources:{},outputs:{'review.mp4':hash}});
 const q=path.join(studio,'outbox/test.json');write(q,{job_id:'C0001',version:1,status:'queued',destination:{provider:'wecom',chatid:binding.chatid},created_at:'2027-01-01T00:00:00Z',text:'article',steps:[{step:'text',errcode:0}],files:[{path:video,sha256:hash}]});
 let fail=true,textSends=0,videoSends=0;
 const client={isConnected:true,sendMessage:async()=>{textSends++;return{errcode:0};},uploadMedia:async()=>{if(fail)throw{errcode:40011,errmsg:'invalid video size'};return{media_id:'fixture'};},sendMediaMessage:async()=>{videoSends++;return{errcode:0};}};
 const worker=startProduction({client,botId:'test-bot',root,onError:()=>{}});
 const readQ=()=>JSON.parse(fs.readFileSync(q,'utf8'));
 const until=async state=>{for(let i=0;i<100;i++){if(readQ().status===state)return;await new Promise(r=>setTimeout(r,50));}assert.fail('Queue did not become '+state);};
 try{
  await until('upload_failed');assert.equal(readQ().error.code,40011);assert.equal(videoSends,0);
  fail=false;write(q,{...readQ(),status:'queued'});await until('sent');
  assert.equal(textSends,0);assert.equal(videoSends,1);
 }finally{worker.stop();while(worker.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(temp,{recursive:true,force:true});}
});

test('a stopped task reports failure once to its source and does not replay',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'wecom-failure-')),root=path.join(temp,'bot'),studio=path.join(temp,'wechat-content-studio');
 for(const p of [path.join(root,'state'),path.join(studio,'state'),path.join(studio,'outbox')])fs.mkdirSync(p,{recursive:true});
 write(path.join(root,'state/binding.json'),binding);
 const sends=[],errors=[];let attempts=0;
 const client={isConnected:true,replyStream:async()=>({errcode:0}),sendMessage:async(chat,body)=>{sends.push({chat,text:body.markdown.content});return {errcode:0};}};
 const worker=startProduction({client,botId:'test-bot',root,onError:e=>errors.push(e.message),runTask:async()=>{attempts++;throw Error('thread already has an active writer');}});
 const frame={body:{chattype:'group',chatid:binding.chatid,from:{userid:'owner'},msgid:'failure',text:{content:'继续制作'}}};
 try{
  await worker.handle(frame);
  for(let i=0;i<100&&worker.isBusy();i++)await new Promise(r=>setTimeout(r,10));
  await worker.handle(frame);
  const record=JSON.parse(fs.readFileSync(path.join(root,'state/inbox',sha('failure')+'.json'),'utf8'));
  assert.equal(attempts,1);assert.equal(record.status,'outcome_unknown');
  assert.equal(record.failure_notice.status,'sent');assert.equal(sends.length,1);
  assert.equal(sends[0].chat,binding.chatid);assert.match(sends[0].text,/会话被占用/);
  assert.equal(errors.length,1);
 }finally{worker.stop();while(worker.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(temp,{recursive:true,force:true});}
});
