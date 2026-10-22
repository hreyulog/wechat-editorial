import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {startProduction,validatePhonePreviewImages,write} from './production.mjs';

const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function fixture(){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'phone-review-'));
 const root=path.join(temp,'wecom-bot-local'),studio=path.join(temp,'wechat-content-studio');
 const folder=path.join(studio,'jobs/C0001/v1');
 for(const dir of [path.join(root,'state'),path.join(studio,'outbox'),path.join(folder,'src')])fs.mkdirSync(dir,{recursive:true});
 const video=path.join(folder,'review.mp4'),image=path.join(folder,'src/phone-preview.png');
 fs.writeFileSync(video,'video fixture');fs.writeFileSync(image,Buffer.from([137,80,78,71,13,10,26,10,1,2]));
 const manifest=path.join(folder,'manifest.json');
 write(manifest,{sources:{},outputs:{'review.mp4':hash(fs.readFileSync(video))}});
 const preview=path.join(folder,'phone-preview.json');
 const draft=path.join(folder,'turbopush-remote.json');write(draft,{status:'fixture draft upload receipt'});
 write(preview,{provenance:'video_channel_phone_preview',manifest_sha256:hash(fs.readFileSync(manifest)),
  draft_receipt:{path:'turbopush-remote.json',sha256:hash(fs.readFileSync(draft))},
  image:{path:'src/phone-preview.png',sha256:hash(fs.readFileSync(image))}});
 const item={job_id:'C0001',version:1,created_at:new Date().toISOString(),status:'queued',
  destination:{provider:'wecom',chatid:'review-group'},text:'phone preview fixture',
  phone_preview_sha256:hash(fs.readFileSync(preview)),
  files:[{path:video,sha256:hash(fs.readFileSync(video))}],images:[{path:image,sha256:hash(fs.readFileSync(image))}]};
 return {temp,root,studio,folder,image,item};
}

test('phone preview image stays bound to its version, manifest and bytes',()=>{
 const f=fixture();
 try{
  assert.equal(validatePhonePreviewImages(f.item,f.studio).length,1);
  assert.throws(()=>validatePhonePreviewImages({...f.item,phone_preview_sha256:undefined},f.studio),/bound phone preview/);
  fs.appendFileSync(f.image,'changed');
  assert.throws(()=>validatePhonePreviewImages(f.item,f.studio),/changed/);
 }finally{fs.rmSync(f.temp,{recursive:true,force:true});}
});

test('review queue sends the native preview QR as an image and the MP4 as a file',async()=>{
 const f=fixture();let worker;
 try{
  write(path.join(f.root,'state/binding.json'),{enabled:true,chatid:'review-group',group_members:'all',
   activated_at:'2000-01-01T00:00:00Z',bot_id_sha256:hash('fixture-bot')});
  write(path.join(f.studio,'config.json'),{});
  const queue=path.join(f.studio,'outbox/phone-review.json');write(queue,f.item);
  const calls=[],errors=[];
  const client={isConnected:true,
   sendMessage:async(chat,body)=>{calls.push(['text',chat,body.markdown.content]);return {errcode:0};},
   uploadMedia:async(_bytes,options)=>{calls.push(['upload',options.type]);return {media_id:options.type};},
   sendMediaMessage:async(chat,type)=>{calls.push(['media',chat,type]);return {errcode:0};}};
  worker=startProduction({client,botId:'fixture-bot',root:f.root,onError:e=>errors.push(e.message)});
  for(let i=0;i<100&&JSON.parse(fs.readFileSync(queue,'utf8')).status!=='sent';i++)await new Promise(r=>setTimeout(r,50));
  assert.deepEqual(errors,[]);
  assert.equal(JSON.parse(fs.readFileSync(queue,'utf8')).status,'sent');
  assert(JSON.parse(fs.readFileSync(queue,'utf8')).phone_preview_sent_at);
  assert.deepEqual(calls,[['text','review-group','phone preview fixture'],['upload','image'],
   ['media','review-group','image'],['upload','file'],['media','review-group','file']]);
 }finally{worker?.stop();while(worker?.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(f.temp,{recursive:true,force:true});}
});
