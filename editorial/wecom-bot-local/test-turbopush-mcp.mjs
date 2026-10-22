import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {turbopushCodexArgs,TURBOPUSH_TOOLS} from './turbopush-mcp.mjs';

test('explicit MCP connection matches the workstation tools without copying credentials',()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'editorial-mcp-'));
 try{
  const command=path.join(temp,'installed-mcp'),config=path.join(temp,'config.json');
  assert.deepEqual(turbopushCodexArgs(config),[]);
  fs.writeFileSync(command,'fixture binary');
  fs.writeFileSync(config,JSON.stringify({enabled:true,command,sha256:crypto.createHash('sha256').update('fixture binary').digest('hex')}));
  const args=turbopushCodexArgs(config),fields=Object.fromEntries(args.filter((_,i)=>i%2===1).map(s=>{const eq=s.indexOf('=');return[s.slice(0,eq),JSON.parse(s.slice(eq+1))];}));
  assert.equal(fields['mcp_servers.turbo_push.command'],command);
  assert.deepEqual(fields['mcp_servers.turbo_push.enabled_tools'],[...TURBOPUSH_TOOLS]);
  assert(TURBOPUSH_TOOLS.includes('list_logged_accounts'));
  assert.equal(TURBOPUSH_TOOLS.length,21);
  assert.equal(new Set(TURBOPUSH_TOOLS).size,21);
  for(const tool of ['publish_video','publish_article','publish_graph_text','close_browser',
   'create_platform_setting','update_platform_setting','delete_platform_setting','delete_article']){
   assert(TURBOPUSH_TOOLS.includes(tool));
  }
  assert(!args.some(s=>/AUTH|PORT|\.env/.test(s)));
  fs.writeFileSync(config,JSON.stringify({enabled:false,command}));
  assert.deepEqual(turbopushCodexArgs(config),[]);
  fs.writeFileSync(config,JSON.stringify({enabled:true,command,sha256:crypto.createHash('sha256').update('fixture binary').digest('hex')}));
  fs.writeFileSync(command,'unexpected replacement');
  assert.throws(()=>turbopushCodexArgs(config),/hash changed/);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
});

test('legacy MCP patch installs once and upgrades an existing diagnostic',()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'editorial-mcp-patch-'));
 try{
  const helper=fileURLToPath(new URL('./turbopush-mcp.mjs',import.meta.url));
  const patch=fileURLToPath(new URL('../../scripts/patch-codex-weixin-mcp.mjs',import.meta.url));
  const fixtures={
   'dist/codex/app-server-runner.js':'import { spawn } from "node:child_process";\nclass Runner {\n    async listSessions() {\n        const args=[...command.argsPrefix, "app-server", "--stdio"];\n    }\n}\n',
   'dist/server/account-manager.js':'class Manager {\n    async controlSession() {}\n}\n',
   'dist/server/http-server.js':'async function handle() {\n    if (method === "GET" && url.pathname === "/api/bootstrap") {}\n}\n'
  };
  for(const [relative,source] of Object.entries(fixtures)){
   const target=path.join(temp,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,source);
  }
  const run=()=>{
   const result=spawnSync(process.execPath,[patch,temp,helper],{encoding:'utf8',windowsHide:true});
   assert.equal(result.status,0,result.stderr);
  };
  run();
  const runnerPath=path.join(temp,'dist/codex/app-server-runner.js');
  const installed=fs.readFileSync(runnerPath,'utf8');
  assert(installed.includes('...turbopushCodexArgs('));
  assert(installed.includes('browser_publishing_enabled:tools.includes('));
  assert.equal(fs.readFileSync(runnerPath+'.before-editorial-mcp','utf8'),fixtures['dist/codex/app-server-runner.js']);
  run();assert.equal(fs.readFileSync(runnerPath,'utf8'),installed);
  fs.writeFileSync(runnerPath,installed.replace('browser_publishing_enabled:tools.includes("publish_video")||tools.includes("publish_article")||tools.includes("publish_graph_text")','browser_publishing_enabled:false'));
  run();assert.equal(fs.readFileSync(runnerPath,'utf8'),installed);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
});
