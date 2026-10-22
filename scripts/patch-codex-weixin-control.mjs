// Optional adapter for codex-weixin 0.3.14. No credentials and no network calls.
import fs from 'node:fs';
import path from 'node:path';
const runtime=path.resolve(process.argv[2]||'');
if(!fs.existsSync(path.join(runtime,'dist/server/account-manager.js')))throw Error('Pass the codex-weixin package directory');
const edits=[];
function edit(relative,marker,mutate){const p=path.join(runtime,relative),before=fs.readFileSync(p,'utf8');if(before.includes(marker))return;edits.push({p,before,after:mutate(before)});}
function replace(source,before,after){if(!source.includes(before))throw Error('Unsupported codex-weixin source layout');return source.replace(before,after);}
edit('dist/codex/app-server-runner.js','async controlTurn(',s=>{
 s=replace(s,'    async stop(threadId) {',`    async controlTurn(threadId, action, text, messageId) {
        const turnId = this.activeTurns.get(threadId);
        if (!turnId) return { accepted: false, reason: "not_running" };
        if (action === "interrupt") await this.request("turn/interrupt", { threadId, turnId });
        else await this.request("turn/steer", { threadId, expectedTurnId: turnId,
            input: [{ type: "text", text, text_elements: [] }], ...(messageId ? { clientUserMessageId: messageId } : {}) });
        return { accepted: true, threadId, turnId, action };
    }
    async stop(threadId) {`);
 s=replace(s,'            reject(new Error("Codex app-server turn was interrupted"));','            const error = new Error("Codex app-server turn was interrupted"); error.code = "CODEX_TURN_INTERRUPTED"; reject(error);');
 // Reuse the thread already loaded by this same app-server process, rather than opening a second writer.
 s=replace(s,'const threadResponse = await this.request(input.threadId ? "thread/resume" : "thread/start", compactObject({','const threadResponse = input.threadId && this.runtimeInfoByThread.has(input.threadId) ? { thread: { id: input.threadId } } : await this.request(input.threadId ? "thread/resume" : "thread/start", compactObject({');
 return s;
});
edit('dist/codex/runner.js','async controlTurn(',s=>{
 s=replace(s,'        catch (error) {','        catch (error) {\n            if (error?.code === "CODEX_TURN_INTERRUPTED") throw error;');
 return replace(s,'    async stop(threadId) {','    async controlTurn(threadId, action, text, messageId) {\n        return this.appServer.controlTurn(threadId, action, text, messageId);\n    }\n    async stop(threadId) {');
});
edit('dist/server/account-manager.js','async controlSession(',s=>replace(s,'    async continueSession(accountId, sessionId, text, uploads = [], onProgress) {',`    async controlSession(accountId, sessionId, action, text, messageId) {
        const session = requireSession(this.storeFor(accountId), sessionId);
        if (!session.threadId || !this.isSessionResponding(accountId, sessionId)) return { accepted: false, reason: "not_running" };
        this.controlRequests ??= new Map();
        if (this.controlRequests.has(messageId)) return this.controlRequests.get(messageId);
        const result = this.runnerFor().controlTurn(session.threadId, action, text, messageId);
        this.controlRequests.set(messageId, result);
        if (this.controlRequests.size > 1000) this.controlRequests.delete(this.controlRequests.keys().next().value);
        return result;
    }
    async continueSession(accountId, sessionId, text, uploads = [], onProgress) {`));
edit('dist/server/http-server.js','sessionAction?.action === "control"',s=>replace(s,'    if (method === "POST" && sessionAction?.action === "messages") {',`    if (method === "POST" && sessionAction?.action === "control") {
        const body = bodySchema.parse(await readJsonBody(request));
        if (!["steer", "interrupt"].includes(body.action)) throw new Error("Invalid control action");
        const result = await context.accountManager.controlSession(sessionAction.accountId, sessionAction.sessionId,
            body.action, body.action === "steer" ? requiredString(body.text, "text") : "",
            requiredString(body.messageId, "messageId"));
        sendJson(response, 200, result); return;
    }
    if (method === "POST" && sessionAction?.action === "messages") {`));
// All anchors were checked before any runtime file is changed. Backups are local and ignored.
for(const {p,before,after} of edits){if(!fs.existsSync(p+'.before-editorial-control'))fs.writeFileSync(p+'.before-editorial-control',before);fs.writeFileSync(p,after);}
// Scope a control to its originating WeCom request, even if the active turn changes during transit.
const managerPath=path.join(runtime,'dist/server/account-manager.js');
let manager=fs.readFileSync(managerPath,'utf8');
if(!manager.includes('this.editorialRequestIds')){
 manager=replace(manager,'async controlSession(accountId, sessionId, action, text, messageId) {','async controlSession(accountId, sessionId, action, text, messageId, expectedMessageId) {');
 manager=replace(manager,'        this.controlRequests ??= new Map();','        if (expectedMessageId && this.editorialRequestIds?.get(accountId + ":" + sessionId) !== expectedMessageId) return { accepted: false, reason: "not_running" };\n        this.controlRequests ??= new Map();');
 manager=replace(manager,'async continueSession(accountId, sessionId, text, uploads = [], onProgress) {','async continueSession(accountId, sessionId, text, uploads = [], onProgress, sourceMessageId) {');
 manager=replace(manager,'        this.setSessionResponding(accountId, session.id, true);','        this.setSessionResponding(accountId, session.id, true);\n        this.editorialRequestIds ??= new Map();\n        this.editorialRequestIds.set(accountId + ":" + session.id, sourceMessageId);');
 manager=replace(manager,'            this.setSessionResponding(accountId, session.id, false);','            this.setSessionResponding(accountId, session.id, false);\n            if (this.editorialRequestIds.get(accountId + ":" + session.id) === sourceMessageId) this.editorialRequestIds.delete(accountId + ":" + session.id);');
 fs.writeFileSync(managerPath,manager);
}
const serverPath=path.join(runtime,'dist/server/http-server.js');
let server=fs.readFileSync(serverPath,'utf8');
if(!server.includes('x-editorial-request-id')){
 server=replace(server,'requiredString(body.messageId, "messageId"));','requiredString(body.messageId, "messageId"), optionalString(body.targetMessageId));');
 server=replace(server,'body.uploads, async (message) => writeNdjson(response, { type: "progress", message }));','body.uploads, async (message) => writeNdjson(response, { type: "progress", message }), request.headers["x-editorial-request-id"]);');
 server=replace(server,'body.text, body.uploads)\n','body.text, body.uploads, undefined, request.headers["x-editorial-request-id"])\n');
 fs.writeFileSync(serverPath,server);
}
const runnerPath=path.join(runtime,'dist/codex/app-server-runner.js');
let runner=fs.readFileSync(runnerPath,'utf8');
if(!runner.includes('editorial loaded-thread reset')){
 runner=replace(runner,'        this.child = child;\n        this.stderr = "";','        this.child = child;\n        this.runtimeInfoByThread.clear(); // editorial loaded-thread reset\n        this.stderr = "";');
 fs.writeFileSync(runnerPath,runner);
}
manager=fs.readFileSync(managerPath,'utf8');
if(!manager.includes('editorial control startup')){
 manager=replace(manager,'if (!session.threadId || !this.isSessionResponding(accountId, sessionId)) return { accepted: false, reason: "not_running" };','if (!this.isSessionResponding(accountId, sessionId)) return { accepted: false, reason: "not_running" };\n        if (!session.threadId) return { accepted: false, reason: "starting" }; // editorial control startup');
 manager=replace(manager,'        return result;\n    }\n    async continueSession','        const reply = await result;\n        if (!reply.accepted) { this.controlRequests.delete(messageId); if (reply.reason === "not_running" && this.isSessionResponding(accountId, sessionId)) return { accepted: false, reason: "starting" }; }\n        return reply;\n    }\n    async continueSession');
 fs.writeFileSync(managerPath,manager);
}
console.log(JSON.stringify({control_adapter_installed:true,files_updated:edits.length}));
