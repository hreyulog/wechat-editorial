import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {validatePublicationQr} from './publication-qr.mjs';
import {startProduction,write} from './production.mjs';
import {EDITORIAL_EXECUTION_POLICY} from './editorial-policy.mjs';
import {validatePreviewQr,previewQrParent} from './article-preview-qr.mjs';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function fixture(){
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'editorial-qr-')),studio=path.join(base,'wechat-content-studio'),root=path.join(base,'bot');
 const folder=path.join(studio,'jobs/C0001/v1'),image=path.join(folder,'publication/confirm.png');
 for(const p of [path.dirname(image),path.join(studio,'outbox'),path.join(root,'state/inbox')])fs.mkdirSync(p,{recursive:true});
 const bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf1sAAAAASUVORK5CYII=','base64');
 fs.writeFileSync(image,bytes);write(path.join(folder,'manifest.json'),{sources:{},outputs:{}});
 const source={msgid:'real-callback-fixture',user_id:'member',chattype:'single',text:'本篇发表，二维码发我',status:'completed'};
 const item={kind:'publication_qr',job_id:'C0001',version:1,status:'queued',created_at:new Date().toISOString(),
  source_message_id:source.msgid,destination:{provider:'wecom',chatid:source.user_id},
  publisher:'turbo_push',purpose:'publication_confirmation',publication_attempt_id:'attempt-fixture',
  captured_at:new Date().toISOString(),expires_at:new Date(Date.now()+120000).toISOString(),
  manifest_sha256:sha(fs.readFileSync(path.join(folder,'manifest.json'))),text:'请扫码确认',files:[{path:image,sha256:sha(bytes)}]};
 return {base,studio,root,folder,source,item};
}
test('a stale, changed or cross-conversation QR cannot be delivered',()=>{
 const f=fixture();try{
  assert.equal(validatePublicationQr(f.item,f.studio,f.source)[0].media_type,'image');
  for(const changed of [{destination:{provider:'wecom',chatid:'other'}},{expires_at:new Date(Date.now()-1000).toISOString()},
    {manifest_sha256:'different'},{source_message_id:'different'},{purpose:'promotional'}])
   assert.throws(()=>validatePublicationQr({...f.item,...changed},f.studio,f.source));
  fs.appendFileSync(f.item.files[0].path,'modified');assert.throws(()=>validatePublicationQr(f.item,f.studio,f.source),/changed/);
 }finally{fs.rmSync(f.base,{recursive:true,force:true});}
});
test('QR outbox uses image upload and same private recipient; expired images stay unsent',async()=>{
 const f=fixture(),sent=[];let worker;
 try{
  write(path.join(f.root,'state/binding.json'),{enabled:true,chatid:'group',group_members:'all',private_messages:'known_members',private_user_ids:['member'],
   bot_id_sha256:sha('bot'),activated_at:'2026-01-01T00:00:00Z'});
  write(path.join(f.root,'state/inbox',sha(f.source.msgid)+'.json'),f.source);
  write(path.join(f.studio,'outbox/fresh.json'),f.item);
  write(path.join(f.studio,'outbox/expired.json'),{...f.item,expires_at:new Date(Date.now()-1000).toISOString()});
  const client={isConnected:true,sendMessage:async target=>{assert.equal(target,'member');return {errcode:0};},
   uploadMedia:async(_bytes,options)=>{sent.push(options.type);return {media_id:'image-id'};},
   sendMediaMessage:async(target,type,id)=>{assert.equal(target,'member');assert.equal(id,'image-id');sent.push(type);return {errcode:0};}};
  worker=startProduction({client,botId:'bot',root:f.root,onError:error=>{throw error;},runTask:async()=>{throw Error('No production task should start');}});
  for(let i=0;i<70;i++){if(JSON.parse(fs.readFileSync(path.join(f.studio,'outbox/fresh.json'))).status==='sent')break;await new Promise(r=>setTimeout(r,100));}
  assert.deepEqual(sent,['image','image']);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.studio,'outbox/expired.json'))).status,'expired');
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.studio,'outbox/fresh.json'))).status,'sent');
 }finally{worker?.stop();while(worker?.isBusy())await new Promise(r=>setTimeout(r,10));fs.rmSync(f.base,{recursive:true,force:true});}
});
test('runtime instruction selects TurboPush and does not claim an unavailable QR capture tool',()=>{
 assert(EDITORIAL_EXECUTION_POLICY.includes('不能擅自改走 freepublish/submit'));
 assert(EDITORIAL_EXECUTION_POLICY.includes('新版本不能沿用旧版本'));
 assert(EDITORIAL_EXECUTION_POLICY.includes('当前 MCP 没有独立二维码截图工具'));
});
test('article preview QR follows a sent review and rejects a superseded preview URL',()=>{
 const f=fixture();try{
  const url='https://mp.weixin.qq.com/s?tempkey=test-only',image=path.join(f.folder,'review-qr/code.png');
  fs.mkdirSync(path.dirname(image));fs.copyFileSync(f.item.files[0].path,image);
  write(path.join(f.folder,'official-preview.json'),{url});
  write(path.join(f.studio,'outbox/parent.json'),{job_id:'C0001',version:1,source_message_id:f.source.msgid,destination:f.item.destination,status:'queued'});
  const item={...f.item,kind:'article_preview_qr',purpose:'article_preview',parent_outbox:'parent.json',preview_url_sha256:sha(url),files:[{path:image,sha256:sha(fs.readFileSync(image))}]};
  assert.equal(previewQrParent(item,f.studio).status,'queued');
  assert.throws(()=>validatePreviewQr(item,f.studio,f.source),/not been delivered/);
  const parent=JSON.parse(fs.readFileSync(path.join(f.studio,'outbox/parent.json')));parent.status='sent';write(path.join(f.studio,'outbox/parent.json'),parent);
  assert.equal(validatePreviewQr(item,f.studio,f.source)[0].media_type,'image');
  write(path.join(f.folder,'official-preview.json'),{url:url+'-new'});
  assert.throws(()=>validatePreviewQr(item,f.studio,f.source),/URL changed/);
  assert.throws(()=>previewQrParent({...item,parent_outbox:'../elsewhere.json'},f.studio),/Invalid/);
 }finally{fs.rmSync(f.base,{recursive:true,force:true});}
});
