import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {startProduction,validateVideoReview,write} from './production.mjs';
import {controlIntent} from './interrupt.mjs';

const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function fixture(){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'video-review-'));
 const root=path.join(temp,'wecom-bot-local'),studio=path.join(temp,'wechat-content-studio');
 const folder=path.join(studio,'jobs/C0001/v1');
 for(const dir of [path.join(root,'state'),path.join(studio,'outbox'),folder])fs.mkdirSync(dir,{recursive:true});
 const video=path.join(folder,'review.mp4'),metadata=path.join(folder,'video-metadata.json');
 fs.writeFileSync(video,'video fixture');
 const content={title:'真实标题',description:'完整简介',account:{id:7,name:'目标账号'}};
 write(metadata,content);
 write(path.join(folder,'manifest.json'),{sources:{'video-metadata.json':hash(fs.readFileSync(metadata))},outputs:{'review.mp4':hash(fs.readFileSync(video))}});
 const item={job_id:'C0001',version:1,created_at:new Date().toISOString(),status:'queued',
  destination:{provider:'wecom',chatid:'review-group'},text:'视频名：真实标题\n视频简介：完整简介\n目标视频号：目标账号',
  video_metadata:content,video_metadata_sha256:hash(fs.readFileSync(metadata)),review_video_sha256:hash(fs.readFileSync(video)),
  files:[{path:video,sha256:hash(fs.readFileSync(video))}]};
 return {temp,root,studio,folder,metadata,item};
}

test('video review binds title, description, account and version',()=>{
 const f=fixture();
 try{
  assert.doesNotThrow(()=>validateVideoReview(f.item,f.studio));
  assert.throws(()=>validateVideoReview({...f.item,review_video_sha256:'wrong'},f.studio),/does not match/);
  write(f.metadata,{...f.item.video_metadata,account:{id:8,name:'changed'}});
  assert.throws(()=>validateVideoReview(f.item,f.studio),/changed/);
 }finally{fs.rmSync(f.temp,{recursive:true,force:true});}
});

test('review sends metadata and actual MP4 as a file without a QR prerequisite',async()=>{
 const f=fixture();let worker;
 try{
  write(path.join(f.root,'state/binding.json'),{enabled:true,chatid:'review-group',group_members:'all',
   activated_at:'2000-01-01T00:00:00Z',bot_id_sha256:hash('fixture-bot')});
  write(path.join(f.studio,'config.json'),{});
  f.item.text+='\n完整长简介：'+'长'.repeat(2000);
  const queue=path.join(f.studio,'outbox/video-review.json');write(queue,f.item);
  const calls=[],errors=[];
  const client={isConnected:true,
   sendMessage:async(chat,body)=>{calls.push(['text',chat,body.markdown.content]);return {errcode:0};},
   uploadMedia:async(_bytes,options)=>{calls.push(['upload',options.type,options.filename]);return {media_id:options.type};},
   sendMediaMessage:async(chat,type)=>{calls.push(['media',chat,type]);return {errcode:0};}};
  worker=startProduction({client,botId:'fixture-bot',root:f.root,onError:e=>errors.push(e.message)});
  for(let i=0;i<100&&JSON.parse(fs.readFileSync(queue,'utf8')).status!=='sent';i++)await new Promise(r=>setTimeout(r,50));
  assert.deepEqual(errors,[]);
  const result=JSON.parse(fs.readFileSync(queue,'utf8'));
  assert.equal(result.status,'sent');assert(result.steps.some(s=>s.step==='file:0'&&s.errcode===0));
  const messages=calls.filter(c=>c[0]==='text');
  assert(messages.length>1);
  assert(messages.every(c=>c[1]==='review-group'&&Buffer.byteLength(c[2],'utf8')<=3800));
  assert.equal(messages.map(c=>c[2]).join(''),f.item.text);
  assert.deepEqual(calls.filter(c=>c[0]!=='text'),[['upload','file','C0001-v1.mp4'],['media','review-group','file']]);
 }finally{worker?.stop();while(worker?.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(f.temp,{recursive:true,force:true});}
});

test('draft confirmations queue instead of steering the current production task',()=>{
 for(const text of ['OK','OK C0001-v1','确认上传 C0001-v1','上传草稿 C0001-v1','通过 C0001-v1'])
  assert.equal(controlIntent(text).action,'queue');
});
