import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

// Local content operations and reads only. Browser publishing is not enabled here.
export const TURBOPUSH_TOOLS=Object.freeze([
 'list_platforms','list_accounts','list_logged_accounts','list_platform_settings',
 'list_articles','get_article','create_article','create_graph_text','create_video','update_article',
 'list_records','get_record_info','get_platform_setting_schema'
]);
export function turbopushCodexArgs(configPath){
 if(!configPath||!fs.existsSync(configPath))return [];
 const config=JSON.parse(fs.readFileSync(configPath,'utf8').replace(/^\uFEFF/,''));
 if(config.enabled!==true)return [];
 if(!path.isAbsolute(config.command)||!fs.statSync(config.command).isFile())throw Error('TurboPush MCP executable is missing');
 if(!config.sha256||crypto.createHash('sha256').update(fs.readFileSync(config.command)).digest('hex')!==config.sha256)throw Error('TurboPush MCP binary hash changed; reconfigure the integration');
 const fields={command:config.command,args:[],enabled:true,enabled_tools:TURBOPUSH_TOOLS,startup_timeout_sec:30,tool_timeout_sec:90};
 return Object.entries(fields).flatMap(([key,value])=>['-c','mcp_servers.turbo_push.'+key+'='+JSON.stringify(value)]);
}
