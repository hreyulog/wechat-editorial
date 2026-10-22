import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const run=(exe,args)=>new Promise((resolve,reject)=>{
 const p=spawn(exe,args,{windowsHide:true,stdio:['ignore','ignore','pipe']});let log='';
 p.stderr.on('data',b=>{log=(log+b).slice(-12000);});p.on('error',reject);p.on('close',code=>code===0?resolve(log):reject(Error('Review video conversion failed: '+log.slice(-1200))));
});
export async function reviewMedia(file,ffmpeg){
 if(file.bytes.length<9.5*1024*1024)return file;
 const sourceHash=hash(file.bytes),folder=path.join(path.dirname(file.path),'delivery',sourceHash.slice(0,16));
 fs.mkdirSync(folder,{recursive:true});const output=path.join(folder,'review-wecom.mp4'),receipt=path.join(folder,'transport.json');
 if(fs.existsSync(receipt)&&fs.existsSync(output)){
  const previous=read(receipt),bytes=fs.readFileSync(output);
  if(previous.source_sha256===sourceHash&&previous.output_sha256===hash(bytes)&&previous.full_decode&&bytes.length<9.5*1024*1024)return {...file,bytes,path:output};
 }
 const qa=read(path.join(path.dirname(file.path),'qa.json')),duration=Number(qa.video?.duration_seconds);
 if(!(duration>0)||hash(fs.readFileSync(file.path))!==sourceHash)throw Error('Validated source duration/hash required for review conversion');
 const bitrate=Math.floor(8800000*8/duration-80000);
 if(bitrate<80000)throw Error('Video too long for readable native review; use a file attachment');
 const temporary=path.join(folder,'encoding-'+crypto.randomUUID()+'.mp4');
 try{
  await run(ffmpeg,['-y','-hide_banner','-i',file.path,'-map','0:v:0','-map','0:a?','-vf','scale=-2:1280','-c:v','libx264','-preset','fast','-threads','2','-b:v',String(bitrate),'-maxrate',String(Math.ceil(bitrate*1.5)),'-bufsize',String(bitrate*3),'-pix_fmt','yuv420p','-c:a','aac','-b:a','64k','-movflags','+faststart',temporary]);
  const bytes=fs.readFileSync(temporary);if(bytes.length>=9.5*1024*1024)throw Error('Encoded review remains above native-video budget');
  await run(ffmpeg,['-hide_banner','-v','error','-i',temporary,'-map','0:v:0','-map','0:a?','-f','null','-']);
  fs.renameSync(temporary,output);
  for(const second of [0,Math.floor(duration/2),Math.max(0,Math.floor(duration)-1)])await run(ffmpeg,['-y','-hide_banner','-loglevel','error','-ss',String(second),'-i',output,'-frames:v','1',path.join(folder,'frame-'+second+'.png')]);
  fs.writeFileSync(receipt,JSON.stringify({source_sha256:sourceHash,output_sha256:hash(bytes),bytes:bytes.length,duration_seconds:duration,full_decode:true,conversion:'720x1280 H264, complete duration, AAC 64k',created_at:new Date().toISOString()},null,2));
  return {...file,bytes,path:output};
 }finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
}
