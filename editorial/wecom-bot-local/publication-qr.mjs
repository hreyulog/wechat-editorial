import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
export function validatePublicationQr(item,studio,source,clock=Date.now()){
 if(item.kind!=='publication_qr'||!/^C\d{4,}$/.test(item.job_id)||!Number.isInteger(item.version)||item.version<1)throw Error('Invalid publication QR item');
 if(!source||source.msgid!==item.source_message_id||!source.user_id)throw Error('QR has no genuine source message');
 if(item.destination?.chatid!==(source.chattype==='single'?source.user_id:source.chatid))throw Error('QR destination differs from its originating conversation');
 const captured=Date.parse(item.captured_at),expires=Date.parse(item.expires_at);
 if(!Number.isFinite(captured)||!Number.isFinite(expires)||captured>clock+5000||expires>captured+300000||expires<=captured||expires<=clock){
  const error=Error('Publication QR is expired or has invalid capture time; obtain a fresh real code');error.code='QR_EXPIRED';throw error;
 }
 const version=fs.realpathSync(path.join(studio,'jobs',item.job_id,'v'+item.version));
 if(digest(fs.readFileSync(path.join(version,'manifest.json')))!==item.manifest_sha256)throw Error('QR belongs to a different content version');
 if(item.publisher!=='turbo_push'||item.purpose!=='publication_confirmation'||!item.publication_attempt_id)throw Error('QR is not bound to a TurboPush publication attempt');
 if(item.files?.length!==1)throw Error('Expected exactly one publication QR image');
 const file=item.files[0],target=fs.realpathSync(file.path),relative=path.relative(path.join(version,'publication'),target);
 if(relative.startsWith('..')||path.isAbsolute(relative)||path.extname(target).toLowerCase()!=='.png')throw Error('QR image is outside its publication folder');
 const bytes=fs.readFileSync(target);
 if(bytes.length<8||bytes.length>2*1024*1024||!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))||digest(bytes)!==file.sha256)throw Error('QR PNG changed or exceeds image transport budget');
 return [{bytes,path:target,filename:item.job_id+'-v'+item.version+'-publish-confirm.png',media_type:'image'}];
}
