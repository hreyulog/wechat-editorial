import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {editorialTurnTimeoutMs,forkEditorialThread,recoverEditorialSession} from './runtime-recovery.mjs';

test('long turns have a separate four-hour deadline from RPC timeout',()=>{
 assert.equal(editorialTurnTimeoutMs({requestTimeoutMs:600000}),14400000);
 assert.equal(editorialTurnTimeoutMs({turnTimeoutMs:25}),25);
 assert.equal(editorialTurnTimeoutMs({turnTimeoutMs:28800000}),14400000);
 assert.throws(()=>editorialTurnTimeoutMs({turnTimeoutMs:NaN}),/Invalid/);
});
test('recovery forks history without starting or replaying a task',async()=>{
 const calls=[],runner={activeTurns:new Map(),runtimeInfoByThread:new Map(),
  ensureConnected:async()=>{},request:async(method,params)=>{calls.push({method,params});return {thread:{id:'fork'}};}};
 assert.deepEqual(await forkEditorialThread(runner,'original','/studio'),{threadId:'fork',recoveredFrom:'original'});
 assert.equal(calls.length,1);assert.equal(calls[0].method,'thread/fork');
 assert(runner.runtimeInfoByThread.has('fork'));
 runner.activeTurns.set('original','running');
 await assert.rejects(()=>forkEditorialThread(runner,'original','/studio'),/active turn/);
});
test('only a checked idle session can switch to a successful recovery fork',async()=>{
 let session={threadId:'original',workspace:'/studio'},busy=false,writes=0;
 const store={getSession:()=>session,setSessionThread:(_id,threadId)=>{writes++;session={...session,threadId};}};
 const manager={isSessionResponding:()=>busy,storeFor:()=>store,runnerFor:()=>({forkEditorialThread:async()=>({threadId:'fork',recoveredFrom:'original'})})};
 busy=true;await assert.rejects(()=>recoverEditorialSession(manager,'account','session','original'),/responding/);
 busy=false;await assert.rejects(()=>recoverEditorialSession(manager,'account','session','wrong'),/changed/);
 assert.equal(writes,0);
 assert.equal((await recoverEditorialSession(manager,'account','session','original')).threadId,'fork');
 assert.equal(writes,1);assert.equal(session.threadId,'fork');
});
test('failed or concurrently changed recovery never replaces the binding',async()=>{
 let session={threadId:'original',workspace:'/studio'},writes=0;
 const store={getSession:()=>session,setSessionThread:()=>{writes++;}};
 const manager={isSessionResponding:()=>false,storeFor:()=>store,
  runnerFor:()=>({forkEditorialThread:async()=>{throw Error('fork failed');}})};
 await assert.rejects(()=>recoverEditorialSession(manager,'account','session','original'),/fork failed/);
 manager.runnerFor=()=>({forkEditorialThread:async()=>{session.threadId='changed';return {threadId:'fork'};}});
 await assert.rejects(()=>recoverEditorialSession(manager,'account','session','original'),/changed/);
 assert.equal(writes,0);
});

test('optional adapter installs once and separates the runtime turn deadline',async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'editorial-recovery-'));
 try{
  fs.mkdirSync(path.join(temp,'dist/codex'),{recursive:true});fs.mkdirSync(path.join(temp,'dist/server'),{recursive:true});
  fs.writeFileSync(path.join(temp,'package.json'),'{"type":"module"}');
  fs.writeFileSync(path.join(temp,'dist/codex/app-server-runner.js'),`export class AppServerCodexRunner {
    options={requestTimeoutMs:600000};
    async stop(threadId) {}
    deadline(){const timeoutMs = this.options.requestTimeoutMs ?? 600_000;return timeoutMs;}
}`);
  fs.writeFileSync(path.join(temp,'dist/codex/runner.js'),'export class Hybrid {\n    async stop(threadId) {}\n}');
  fs.writeFileSync(path.join(temp,'dist/server/account-manager.js'),'export class Manager {\n    async continueSession() {}\n}');
  fs.writeFileSync(path.join(temp,'dist/server/http-server.js'),'async function route(){\n    if (method === "POST" && sessionAction?.action === "messages") {}\n}');
  const script=fileURLToPath(new URL('../../scripts/patch-codex-weixin-recovery.mjs',import.meta.url));
  const helper=fileURLToPath(new URL('./runtime-recovery.mjs',import.meta.url));
  const install=()=>spawnSync(process.execPath,[script,temp,helper],{encoding:'utf8'});
  assert.equal(install().status,0);
  const second=install();assert.equal(second.status,0);assert.equal(JSON.parse(second.stdout).files_updated,0);
  for(const file of ['dist/codex/app-server-runner.js','dist/codex/runner.js','dist/server/account-manager.js','dist/server/http-server.js']){
   const check=spawnSync(process.execPath,['--check',path.join(temp,file)],{encoding:'utf8'});
   assert.equal(check.status,0,check.stderr);
  }
  const {AppServerCodexRunner}=await import(pathToFileURL(path.join(temp,'dist/codex/app-server-runner.js')).href);
  assert.equal(new AppServerCodexRunner().deadline(),14400000);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
});
