import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {turbopushCodexArgs,TURBOPUSH_TOOLS} from './turbopush-mcp.mjs';

test('explicit MCP connection exposes local tools without tokens or browser publishing',()=>{
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
  assert(!TURBOPUSH_TOOLS.some(name=>/^(publish_|delete_|close_browser)/.test(name)));
  assert(!args.some(s=>/AUTH|PORT|\.env/.test(s)));
  fs.writeFileSync(command,'unexpected replacement');
  assert.throws(()=>turbopushCodexArgs(config),/hash changed/);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
});
