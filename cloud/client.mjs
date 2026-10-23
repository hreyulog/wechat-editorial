import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const helper=fileURLToPath(new URL('./client.py',import.meta.url));
export function cloudCall(operation,values={}){
 if(!process.env.EDITORIAL_CLOUD)return;
 const result=spawnSync(process.env.PYTHON_BIN||'python3',[helper],{
  input:JSON.stringify({operation,...values}),encoding:'utf8',windowsHide:true,timeout:610000,maxBuffer:1024*1024});
 if(result.status!==0)throw Error('Cloud persistence unavailable; operation stopped before local commit');
 return JSON.parse(result.stdout);
}
