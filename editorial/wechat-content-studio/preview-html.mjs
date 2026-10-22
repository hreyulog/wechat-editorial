import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire(import.meta.url);
const {chromium}=require('playwright');
const root=path.dirname(fileURLToPath(import.meta.url));
const config=JSON.parse(fs.readFileSync(path.join(root,'config.json'),'utf8'));
config.chrome=process.env.CHROME_BINARY||config.chrome;
const source=path.resolve(process.argv[2]);
if(!source.startsWith(path.resolve(root)+path.sep))throw new Error('Only local content studio artifacts may be rendered');
const browser=await chromium.launch({...(config.chrome?{executablePath:config.chrome}:{}),headless:true});
try{
 const page=await browser.newPage({viewport:{width:420,height:880},deviceScaleFactor:1});
 await page.route('**/*',route=>route.abort());
 await page.setContent('<!doctype html><html><meta charset="utf-8"><body style="margin:0;background:white">'+fs.readFileSync(source,'utf8')+'</body></html>');
 await page.evaluate(()=>document.fonts.ready);
 const target=source.replace(/\.html$/,'.png');
 await page.screenshot({path:target,fullPage:true});console.log(target);
}finally{await browser.close();}
