import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
export function previewQrParent(item,studio){
 if(typeof item.parent_outbox!=='string'||path.basename(item.parent_outbox)!==item.parent_outbox||!item.parent_outbox.endsWith('.json'))throw Error('Invalid review QR parent');
 const parent=read(path.join(studio,'outbox',item.parent_outbox));
 if(parent.job_id!==item.job_id||parent.version!==item.version||parent.source_message_id!==item.source_message_id
  ||JSON.stringify(parent.destination)!==JSON.stringify(item.destination)||parent.kind==='article_preview_qr')throw Error('Preview QR differs from original review delivery');
 return parent;
}
export function validatePreviewQr(item,studio,source){
 const parent=previewQrParent(item,studio);
 if(parent.status!=='sent')throw Error('Preview link has not been delivered');
 if(item.purpose!=='article_preview'||!/^C\d{4,}$/.test(item.job_id)||!Number.isInteger(item.version)||item.version<1)throw Error('Invalid article preview QR');
 if(!source||source.msgid!==item.source_message_id||item.destination?.chatid!==(source.chattype==='single'?source.user_id:source.chatid))throw Error('Preview QR source conversation mismatch');
 const folder=fs.realpathSync(path.join(studio,'jobs',item.job_id,'v'+item.version));
 if(sha(fs.readFileSync(path.join(folder,'manifest.json')))!==item.manifest_sha256)throw Error('Preview QR version changed');
 const preview=read(path.join(folder,'official-preview.json'));
 if(preview.valid===false)throw Error('The bound official draft preview is no longer valid');
 const url=preview.url,parsed=new URL(url);
 if(parsed.protocol!=='https:'||parsed.host!=='mp.weixin.qq.com'||!(parsed.pathname==='/s'||parsed.pathname.startsWith('/s/'))||sha(url)!==item.preview_url_sha256)throw Error('Preview QR URL changed or is not official');
 if(item.files?.length!==1)throw Error('Expected one preview PNG');
 const file=item.files[0],target=fs.realpathSync(file.path),rel=path.relative(path.join(folder,'review-qr'),target);
 if(rel.startsWith('..')||path.isAbsolute(rel)||path.extname(target)!=='.png')throw Error('Unexpected preview QR file');
 const bytes=fs.readFileSync(target);
 if(bytes.length>2*1024*1024||!bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))||sha(bytes)!==file.sha256)throw Error('Preview QR image changed');
 return [{path:target,bytes,media_type:'image',filename:item.job_id+'-v'+item.version+'-preview.png'}];
}
