// Optional codex-weixin 0.3.14 maintenance adapter. Does not execute any tasks.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const runtime=path.resolve(process.argv[2]||'');
const helper=path.resolve(process.argv[3]||'editorial/wecom-bot-local/runtime-recovery.mjs');
if(!fs.existsSync(helper))throw Error('Pass the installed runtime-recovery.mjs helper');
const edits=[];
function replace(source,before,after){
 if(!source.includes(before))throw Error('Unsupported codex-weixin source layout');
 return source.replace(before,after);
}
function edit(relative,marker,mutate){
 const p=path.join(runtime,relative),before=fs.readFileSync(p,'utf8');
 if(before.includes(marker))return;
 edits.push({p,before,after:mutate(before)});
}
const url=JSON.stringify(pathToFileURL(helper).href);
edit('dist/codex/app-server-runner.js','// editorial long-turn recovery',source=>{
 source='import {editorialTurnTimeoutMs,forkEditorialThread} from '+url+'; // editorial long-turn recovery\n'+source;
 source=replace(source,'    async stop(threadId) {','    async forkEditorialThread(threadId,cwd) { return forkEditorialThread(this,threadId,cwd); }\n    async stop(threadId) {');
 return replace(source,'const timeoutMs = this.options.requestTimeoutMs ?? 600_000;','const timeoutMs = editorialTurnTimeoutMs(this.options);');
});
edit('dist/codex/runner.js','async forkEditorialThread(',source=>replace(source,'    async stop(threadId) {',
 '    async forkEditorialThread(threadId,cwd) { return this.appServer.forkEditorialThread(threadId,cwd); }\n    async stop(threadId) {'));
edit('dist/server/account-manager.js','async recoverEditorialSession(',source=>{
 source='import {recoverEditorialSession} from '+url+';\n'+source;
 return replace(source,'    async continueSession(', '    async recoverEditorialSession(accountId,sessionId,expectedThreadId) { return recoverEditorialSession(this,accountId,sessionId,expectedThreadId); }\n    async continueSession(');
});
edit('dist/server/http-server.js','sessionAction?.action === "recover"',source=>replace(source,
 '    if (method === "POST" && sessionAction?.action === "messages") {',
 `    if (method === "POST" && sessionAction?.action === "recover") {
        const body = bodySchema.parse(await readJsonBody(request));
        if (body.confirmIdle !== true) throw new Error("Recovery needs an explicit idle check");
        const result = await context.accountManager.recoverEditorialSession(sessionAction.accountId,sessionAction.sessionId,
            requiredString(body.expectedThreadId,"expectedThreadId"));
        sendJson(response,200,result); return;
    }
    if (method === "POST" && sessionAction?.action === "messages") {`));
// Validate every anchor before changing the installation. Retain local backups.
for(const {p,before,after} of edits){
 if(!fs.existsSync(p+'.before-editorial-recovery'))fs.writeFileSync(p+'.before-editorial-recovery',before);
 fs.writeFileSync(p,after);
}
console.log(JSON.stringify({recovery_adapter_installed:true,files_updated:edits.length}));
