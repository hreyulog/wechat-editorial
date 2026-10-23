import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {openBrowser, renderMedia, renderStill, selectComposition} from '@remotion/renderer';
const root=path.dirname(fileURLToPath(import.meta.url));
const config=JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8'));
config.ffmpeg=process.env.FFMPEG_BINARY||config.ffmpeg;
config.chrome=process.env.CHROME_BINARY||config.chrome;
const folder=path.resolve(process.argv[2]); const kind=process.argv[3];
if(!folder.startsWith(path.join(root,'jobs')+path.sep)) throw new Error('Job must be inside studio/jobs');
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
let qa={article:'not_requested',video:'not_requested',visual_review:'not_run',audio_review:'not_run'};
if(kind!=='video'){
  const article=JSON.parse(fs.readFileSync(path.join(folder,'article.json'),'utf8'));
  if(!article.title || !Array.isArray(article.sections) || !article.sections.length || article.fact_check?.checked!==true) throw new Error('Article content and fact_check required');
  if(!Array.isArray(article.sources)) throw new Error('Record sources or explicitly mark elementary derivation');
  const content=article.sections.map(s=>`<section><h2>${esc(s.heading)}</h2>${s.paragraphs.map(p=>`<p>${esc(p)}</p>`).join('')}</section>`).join('');
  const sources=article.sources.map(s=>`<li>${esc(s.title)}${s.url?`：<a href="${esc(s.url)}">来源</a>`:''}</li>`).join('');
  const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(article.title)}</title><style>body{max-width:720px;margin:40px auto;padding:0 24px;color:#24352e;background:#fbfaf6;font:18px/1.85 "Noto Sans CJK SC","Noto Sans SC",sans-serif}h1{font-size:32px;line-height:1.4}h2{font-size:23px;margin-top:32px}p{margin:16px 0}small{color:#62756a}a{color:#26745a}</style><h1>${esc(article.title)}</h1><small>${esc(article.subtitle||'待审核草稿')}</small>${content}<h2>来源与核对说明</h2><ul>${sources}</ul><p>${esc(article.fact_check.notes||'')}</p></html>`;
  fs.writeFileSync(path.join(folder,'article.html'),html);
  fs.writeFileSync(path.join(folder,'article.md'),`# ${article.title}\n\n${article.subtitle||''}\n\n`+article.sections.map(s=>`## ${s.heading}\n\n${s.paragraphs.join('\n\n')}`).join('\n\n')+'\n\n来源：\n'+article.sources.map(s=>`${s.title} ${s.url||''}`).join('\n'));
  const formatter=path.join(config.article_skills,'skills/aws-wechat-article-formatting/scripts/format.py');
  const formatted=spawnSync(config.article_python,['-X','utf8',formatter,path.join(folder,'article.md'),'--theme','亲和','--scheme','松绿','-o',path.join(folder,'wechat.html')],{cwd:config.article_skills,windowsHide:true,encoding:'utf8'});
  fs.writeFileSync(path.join(folder,'format.log'),(formatted.stdout||'')+(formatted.stderr||''));
  if(formatted.status!==0)throw new Error('WeChat inline formatting failed; see format.log');
  if(article.channel_video){
    const inserted=spawnSync(config.article_python,['-X','utf8',path.join(root,'channel_video.py'),'render',folder],{cwd:root,windowsHide:true,encoding:'utf8'});
    if(inserted.status!==0)throw new Error('Channels card insertion failed: '+inserted.stdout);
  }
  const require=createRequire(import.meta.url); const sharp=require('sharp');
  const wrap=(text,size)=>{let rows=[''],units=0;for(const ch of text){const u=/[\u0000-\u007f]/.test(ch)?0.55:1;if(units+u>size){rows.push('');units=0;}rows[rows.length-1]+=ch;units+=u;}return rows;};
  let y=100; const lines=[];
  const add=(text,size,color='#263c31')=>{for(const line of wrap(text,Math.floor(740/size))){lines.push(`<text x="50" y="${y}" font-size="${size}" fill="${color}">${esc(line)}</text>`);y+=size*1.65;}y+=20;};
  add(article.title,40);add(article.subtitle||'审核草稿',22,'#667a6b');for(const s of article.sections){add(s.heading,29);for(const p of s.paragraphs)add(p,25);}add('来源与核对说明',29);for(const s of article.sources)add(`${s.title}${s.url?' '+s.url:''}`,20);add(article.fact_check.notes||'',20);
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="840" height="${Math.ceil(y+35)}"><rect width="100%" height="100%" fill="#fbfaf6"/><g font-family="Noto Sans CJK SC, Noto Sans SC, sans-serif, sans-serif">${lines.join('')}</g></svg>`;
  await sharp(Buffer.from(svg)).png().toFile(path.join(folder,'article-preview.png'));
  const title=wrap(article.title,16).map((s,i)=>`<text x="70" y="${170+i*70}" font-size="54">${esc(s)}</text>`).join('');
  await sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="608"><rect width="1080" height="608" fill="#e9efe6"/><g fill="#214c37" font-family="Noto Sans CJK SC, Noto Sans SC, sans-serif">${title}<text x="70" y="540" font-size="28">内容审稿 · ${esc(path.basename(path.dirname(folder))+'-'+path.basename(folder))}</text></g></svg>`)).png().toFile(path.join(folder,'cover.png'));
  if(article.cover_source){
    const cover=path.resolve(folder,article.cover_source);
    if(!cover.startsWith(path.join(folder,'src')+path.sep))throw new Error('Imported cover must be a version source');
    await sharp(cover).png().toFile(path.join(folder,'cover.png'));
  }
  qa.article={passed:true,section_count:article.sections.length,fact_check:article.fact_check,wechat_inline_html:true,official_draft_created:false};
}
const importedPath=path.join(folder,'src/video-import.json');
if(kind!=='article' && fs.existsSync(importedPath)){
  const imported=JSON.parse(fs.readFileSync(importedPath,'utf8'));
  const source=path.resolve(folder,imported.path);
  if(!source.startsWith(path.join(folder,'src')+path.sep) || hash(source)!==imported.sha256)throw new Error('Imported video source/hash mismatch');
  const output=path.join(folder,'review.mp4');
  fs.copyFileSync(source,output);
  fs.mkdirSync(path.join(folder,'qa'),{recursive:true});
  const decode=spawnSync(config.ffmpeg,['-hide_banner','-xerror','-i',output,'-map','0','-progress','pipe:1','-f','null','-'],{windowsHide:true,encoding:'utf8'});
  fs.writeFileSync(path.join(folder,'qa/full-decode.log'),decode.stderr||'');
  fs.writeFileSync(path.join(folder,'qa/decode-progress.log'),decode.stdout||'');
  const counted=[...decode.stdout.matchAll(/^frame=(\d+)/gm)].at(-1)?.[1];
  if(decode.status!==0 || Number(counted)!==imported.frames)throw new Error('Imported video full decode/frame count mismatch');
  if(!decode.stderr.includes(`${imported.width}x${imported.height}`) || !decode.stderr.includes(`${imported.fps} fps`) || !decode.stderr.includes('Video: h264') || !decode.stderr.includes('Audio: aac'))throw new Error('Imported video metadata mismatch');
  const frames=[0,Math.floor(imported.frames/2),imported.frames-1];
  for(const frame of frames){
    const r=spawnSync(config.ffmpeg,['-y','-v','error','-ss',String(frame/imported.fps),'-i',output,'-frames:v','1',path.join(folder,'qa',`frame-${frame}.png`)],{windowsHide:true,encoding:'utf8'});
    if(r.status!==0)throw new Error(r.stderr);
  }
  qa.video={passed:true,width:imported.width,height:imported.height,fps:imported.fps,duration_seconds:imported.frames/imported.fps,full_decode:true,decoded_frames:Number(counted),encoded_keyframes:frames,sha256:hash(output),delivery_mode:'existing_final_video_byte_preserved',audio_review:'not_run'};
}else if(kind!=='article'){
  const entry=path.join(folder,'src/index.tsx');if(!fs.existsSync(entry))throw new Error('Author this topic-specific Remotion source first');
  const serveUrl=await bundle({entryPoint:entry,outDir:path.join(folder,'build')});
  const browser=await openBrowser('chrome',{browserExecutable:config.chrome||undefined});
  try{
    const composition=await selectComposition({serveUrl,id:'ReviewVideo',puppeteerInstance:browser});
    const output=path.join(folder,'review.mp4');
    await renderMedia({serveUrl,composition,puppeteerInstance:browser,codec:'h264',pixelFormat:'yuv420p',crf:23,concurrency:2,outputLocation:output});
    fs.mkdirSync(path.join(folder,'qa'),{recursive:true});
    const frames=[0,Math.floor(composition.durationInFrames/2),composition.durationInFrames-1];
    // These are decoded from the actual encoded MP4, rather than source-only stills.
    for(const frame of frames){const out=path.join(folder,'qa',`frame-${frame}.png`);const r=spawnSync(config.ffmpeg,['-y','-v','error','-ss',String(frame/composition.fps),'-i',output,'-frames:v','1',out],{windowsHide:true,encoding:'utf8'});if(r.status!==0)throw new Error(r.stderr);}
    const motion=Math.floor(composition.durationInFrames/3);
    for(const suffix of ['a','b'])await renderStill({serveUrl,composition,puppeteerInstance:browser,frame:motion,imageFormat:'png',output:path.join(folder,'qa',`repeat-${suffix}.png`)});
    if(hash(path.join(folder,'qa/repeat-a.png'))!==hash(path.join(folder,'qa/repeat-b.png')))throw new Error('Nondeterministic frame');
    const decode=spawnSync(config.ffmpeg,['-v','error','-xerror','-i',output,'-f','null','-'],{windowsHide:true,encoding:'utf8'});
    fs.writeFileSync(path.join(folder,'qa/full-decode.log'),decode.stderr||'');
    if(decode.status!==0)throw new Error('Final MP4 full decode failed');
    qa.video={passed:true,width:composition.width,height:composition.height,fps:composition.fps,duration_seconds:composition.durationInFrames/composition.fps,full_decode:true,deterministic_motion_frame:true,encoded_keyframes:frames,sha256:hash(output)};
  }finally{await browser.close({silent:true});}
}
fs.writeFileSync(path.join(folder,'qa.json'),JSON.stringify(qa,null,2));
console.log(JSON.stringify(qa));
