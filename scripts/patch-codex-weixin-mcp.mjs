// codex-weixin 0.3.14: explicitly opt in the editorial MCP after global MCP isolation.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const runtime=path.resolve(process.argv[2]||''),helper=path.resolve(process.argv[3]||'');
if(!fs.statSync(helper).isFile())throw Error('Pass the editorial turbopush-mcp.mjs helper');
const edits=new Map();
function edit(relative,marker,before,after){
 const p=path.join(runtime,relative),original=edits.get(p)?.source??fs.readFileSync(p,'utf8'),source=edits.get(p)?.after??original;if(source.includes(marker))return;
 if(!source.includes(before))throw Error('Unsupported codex-weixin layout: '+relative);
 edits.set(p,{p,source:original,after:source.replace(before,after)});
}
edit('dist/codex/app-server-runner.js','turbopushCodexArgs',
 'import { spawn } from "node:child_process";',
 'import {turbopushCodexArgs} from '+JSON.stringify(pathToFileURL(helper).href)+';\nimport { spawn } from "node:child_process";');
edit('dist/codex/app-server-runner.js','...turbopushCodexArgs(',
 '[...command.argsPrefix, "app-server", "--stdio"]',
 '[...command.argsPrefix, ...turbopushCodexArgs(process.env.CODEX_EDITORIAL_MCP_CONFIG), "app-server", "--stdio"]');
edit('dist/codex/app-server-runner.js','async editorialMcpStatus(',
 '    async listSessions() {',
 `    async editorialMcpStatus(session) {
        await this.ensureConnected();
        if (!session.threadId) throw new Error("Content session has no Codex thread");
        if (!this.runtimeInfoByThread.has(session.threadId)) {
            const result = await this.request("thread/resume", {threadId:session.threadId,cwd:session.workspace,approvalPolicy:"never"});
            this.runtimeInfoByThread.set(session.threadId,runtimeInfoFromThreadResponse(result));
        }
        const status = await this.request("mcpServerStatus/list", {threadId:session.threadId,serverName:"turbo_push",detail:"toolsAndAuthOnly"});
        const server = status.data?.find(s=>s.name==="turbo_push");
        const tools = Object.keys(server?.tools||{});
        if (!tools.includes("list_logged_accounts")) return {connected:false,tools};
        const read = await this.request("mcpServer/tool/call", {threadId:session.threadId,server:"turbo_push",tool:"list_logged_accounts",arguments:{}});
        return {connected:!read.isError,tools,read_tool:"list_logged_accounts",read_ok:!read.isError,browser_publishing_enabled:false};
    }
    async listSessions() {`);
edit('dist/server/account-manager.js','async editorialMcpStatus(',
 '    async controlSession(',
 `    async editorialMcpStatus(accountId,sessionId) {
        const session=requireSession(this.storeFor(accountId),sessionId);
        if(this.respondingSessions.size)throw new Error("Wait for active Codex tasks to finish before integration diagnostics");
        return this.runnerFor().appServer.editorialMcpStatus(session);
    }
    async controlSession(`);
edit('dist/server/http-server.js','/api/editorial/mcp-status',
 '    if (method === "GET" && url.pathname === "/api/bootstrap") {',
 `    if (method === "POST" && url.pathname === "/api/editorial/mcp-status") {
        const body=bodySchema.parse(await readJsonBody(request));
        const result=await context.accountManager.editorialMcpStatus(requiredString(body.accountId,"accountId"),requiredString(body.sessionId,"sessionId"));
        sendJson(response,200,result);return;
    }
    if (method === "GET" && url.pathname === "/api/bootstrap") {`);
// All source anchors are checked before any file is changed.
for(const {p,source,after} of edits.values()){
 if(!fs.existsSync(p+'.before-editorial-mcp'))fs.writeFileSync(p+'.before-editorial-mcp',source);
 fs.writeFileSync(p,after);
}
console.log('Installed explicit editorial TurboPush MCP integration.');
