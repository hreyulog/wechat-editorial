// Local UI regression. Temporary fixtures only; no bot, platform API, or real sends.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
const {chromium}=await import(process.env.WORKBENCH_PLAYWRIGHT_MODULE||'playwright');
const root=path.dirname(fileURLToPath(import.meta.url));
const temporary=await fs.mkdtemp(path.join(process.env.WORKBENCH_TEST_TMP||os.tmpdir(),'editorial-ui-'));
const write=async(name,data)=>{const target=path.join(temporary,name);await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,JSON.stringify(data));};
const fixture=[['C0001','both','awaiting_review','人物故事与数学传承'],['C0002','video','producing','下一期人物纪录片'],['C0003','article','awaiting_video_embed','视频卡片待核对'],['C0004','video','video_draft_uploaded','已确认的视频稿']];
for(const [id,kind,status,topic] of fixture){
 await write(`studio/jobs/${id}/job.json`,{id,kind,status,topic,version:1,updated_at:'2026-10-23T00:00:00Z'});
 await write(`studio/jobs/${id}/v1/article.json`,{title:topic,subtitle:'本地界面测试数据',sections:[{heading:'人物与研究',paragraphs:['这是一段用于测试界面的正文。']}],sources:[]});
 await write(`studio/jobs/${id}/v1/video-metadata.json`,{title:topic,description:'完整简介 <img src=x onerror="window.injected=true">',account:{name:'示例账号'}});
}
await write('studio/jobs/C0001/v1/official-preview.json',{url:'https://mp.weixin.qq.com/s?tempkey=local-ui-fixture'});
await write('studio/jobs/C0001/v2/article.json',{title:'历史版本示例',sections:[],sources:[]});
const python=process.env.WORKBENCH_PYTHON||(process.platform==='win32'?'python':'python3');
const server=spawn(python,['-X','utf8',path.join(root,'server.py'),'--port','0','--studio',path.join(temporary,'studio'),'--bot',path.join(temporary,'bot'),'--state-dir',path.join(temporary,'state')],{stdio:['ignore','pipe','pipe'],windowsHide:true});
let browser;
try{
 const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Local server startup timed out')),15000);server.stdout.on('data',data=>{text+=data.toString();const found=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(found){clearTimeout(timer);resolve(found[0]);}});server.once('error',e=>{clearTimeout(timer);reject(e);});server.once('exit',()=>{clearTimeout(timer);reject(Error('Local server stopped early'));});});
 browser=await chromium.launch({headless:true,...(process.env.CHROME_BINARY?{executablePath:process.env.CHROME_BINARY}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 // Fail if the application unexpectedly contacts an external host.
 const external=[];await context.route('**/*',route=>{if(new URL(route.request().url()).origin!==url){external.push(route.request().url());return route.abort();}return route.continue();});
 await page.goto(url);await page.getByText('人物故事与数学传承',{exact:true}).waitFor();
 await page.getByRole('link',{name:/内容看板/}).click();
 await page.getByRole('searchbox').fill('C0003');assert.equal(await page.locator('tbody tr').count(),1);
 await page.getByRole('searchbox').fill('');await page.getByRole('button',{name:'查看 →'}).first().click();
 await page.locator('#task-detail h2').waitFor();
 assert.equal(await page.locator('#task-detail .description img').count(),0);
 assert.equal(await page.evaluate(()=>window.injected),undefined);
 assert.equal(await page.getByRole('link',{name:'打开公众号官方预览 ↗'}).getAttribute('href'),'https://mp.weixin.qq.com/s?tempkey=local-ui-fixture');
 await page.getByLabel('查看版本').selectOption('2');
 assert.equal(await page.getByRole('button',{name:'复制确认上传指令',exact:true}).count(),0);
 await page.getByRole('button',{name:'关闭内容详情'}).click();
 await page.getByRole('button',{name:'新建选题'}).click();
 await page.getByLabel('选题名称').fill('UI 回归选题');await page.getByLabel('负责人').fill('测试编辑');
 await page.getByLabel('计划日期').fill('2026-10-24');await page.getByLabel('关联已有内容').selectOption('C0001');
 await page.getByRole('button',{name:'保存选题',exact:true}).click();await page.locator('#plan-dialog').waitFor({state:'hidden'});
 await page.getByRole('link',{name:'选题与排期'}).click();await page.getByRole('button',{name:/UI 回归选题/}).waitFor();
 await page.reload();await page.getByRole('button',{name:/UI 回归选题/}).click();
 assert.equal(await page.getByLabel('负责人').inputValue(),'测试编辑');
 await page.getByLabel('归档此选题').check();await page.getByRole('button',{name:'保存选题',exact:true}).click();
 await page.locator('#plan-dialog').waitFor({state:'hidden'});await page.getByText('已归档选题（1）').waitFor();
 for(const name of ['运营总览','内容看板','审核中心','选题与排期','账号与连接']){await page.getByRole('link',{name:new RegExp(name)}).click();await page.locator('#page-title').filter({hasText:name}).waitFor();}
 await page.getByRole('link',{name:'运营总览'}).click();
 if(process.env.WORKBENCH_SCREENSHOTS){await fs.mkdir(process.env.WORKBENCH_SCREENSHOTS,{recursive:true});await page.screenshot({path:path.join(process.env.WORKBENCH_SCREENSHOTS,'workbench-fixture-desktop.png'),fullPage:true});}
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 if(process.env.WORKBENCH_SCREENSHOTS)await page.screenshot({path:path.join(process.env.WORKBENCH_SCREENSHOTS,'workbench-fixture-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 console.log(JSON.stringify({browser:'passed',checks:['navigation','search','version-switch','literal-content','plan-save-reload-archive','mobile-overflow','no-external-requests'],real_messages_sent:false}));
 await context.close();
}finally{
 await browser?.close();if(server.pid&&server.exitCode===null){const stopped=new Promise(resolve=>server.once('close',resolve));server.kill();await stopped;}
 assert.equal(path.dirname(temporary),path.resolve(process.env.WORKBENCH_TEST_TMP||os.tmpdir()));
 await fs.rm(temporary,{recursive:true,force:true});
}
