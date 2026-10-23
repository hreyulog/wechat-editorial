// Standard MCP stdio transport to the explicitly configured native TurboPush.
// Never prints credentials, server stderr, raw publication HTML or account cookies.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import readline from 'node:readline';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

export async function withTurbo(configPath, operation){
 const config=JSON.parse(fs.readFileSync(configPath,'utf8').replace(/^\uFEFF/,''));
 if(config.enabled!==true||!path.isAbsolute(config.command)||crypto.createHash('sha256').update(fs.readFileSync(config.command)).digest('hex')!==config.sha256)throw Error('TurboPush executable is not configured or changed');
 const child=spawn(config.command,[],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:process.env});
 let next=1;const pending=new Map();
 child.stderr.on('data',()=>{});
 const fail=()=>{for(const item of pending.values()){clearTimeout(item.timer);item.reject(Error('TurboPush MCP disconnected; reconcile before retrying'));}pending.clear();};
 child.on('error',fail);child.on('exit',fail);
 readline.createInterface({input:child.stdout}).on('line',line=>{
  let value;try{value=JSON.parse(line);}catch{return;}
  const item=pending.get(value.id);if(!item)return;pending.delete(value.id);clearTimeout(item.timer);
  if(value.error)item.reject(Error('TurboPush MCP protocol error: '+value.error.code));else item.resolve(value.result);
 });
 const rpc=(method,params,timeout=90000)=>new Promise((resolve,reject)=>{
  const id=next++,timer=setTimeout(()=>{pending.delete(id);reject(Error('TurboPush MCP timeout; outcome requires reconciliation'));},timeout);
  pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
 });
 try{
  await rpc('initialize',{protocolVersion:'2024-11-05',clientInfo:{name:'wechat-editorial',version:'0.2.0'},capabilities:{}});
  child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized',params:{}})+'\n');
  return await operation({list:()=>rpc('tools/list',{}),call:(name,args)=>rpc('tools/call',{name,arguments:args})});
 }finally{child.stdin.end();child.kill();fail();}
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const root=path.dirname(fileURLToPath(import.meta.url));
 const [tool,args='{}',output]=process.argv.slice(2);
 try{
  const result=await withTurbo(path.join(root,'state/turbopush-mcp.json'),m=>tool==='tools/list'?m.list():m.call(tool,JSON.parse(args)));
  if(output)fs.writeFileSync(output,JSON.stringify(result,null,2),{mode:0o600});
  console.log(JSON.stringify({ok:!result.isError,tools:result.tools?.map(t=>({name:t.name,inputSchema:t.inputSchema})),
   output_saved:!!output,result_keys:Object.keys(result),error:result.isError?result.content?.filter(c=>c.type==='text').map(c=>c.text).join('\n'):undefined}));
 }catch(error){console.log(JSON.stringify({ok:false,error:String(error.message)}));process.exitCode=1;}
}
