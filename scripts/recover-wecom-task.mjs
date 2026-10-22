// Operator-only recovery of one reconciled task, never a startup/backlog replay.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const args=Object.fromEntries(process.argv.slice(2).reduce((pairs,value,i,all)=>i%2?pairs:[...pairs,[value,all[i+1]]],[]));
const root=path.resolve(args['--root']||''),msgid=args['--message'],notePath=args['--note-file'];
if(!msgid||!notePath||!args['--root'])throw Error('Pass --root, --message, --note-file');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
const state=path.join(root,'state'),studio=path.resolve(root,'../wechat-content-studio');
if(read(path.join(state,'production.json')).phase!=='waiting_for_group_task')throw Error('Bot is not idle');
for(const [directory,statuses] of [[path.join(state,'inbox'),['queued','running','replying','control_pending']],[path.join(studio,'outbox'),['queued','sending']]])
 for(const name of fs.readdirSync(directory).filter(n=>n.endsWith('.json')))
  if(statuses.includes(read(path.join(directory,name)).status))throw Error('Live work detected');
const inboxPath=path.join(state,'inbox',crypto.createHash('sha256').update(msgid).digest('hex')+'.json');
const value=read(inboxPath);
if(value.msgid!==msgid||value.status!=='outcome_unknown'||value.reply_ack_at)throw Error('Only the specified unresolved task can be recovered');
const note=fs.readFileSync(path.resolve(notePath),'utf8').trim();
if(!note)throw Error('Reconcile actual side effects and supply a recovery note');
value.attempts=[...(value.attempts||[]),{started_at:value.started_at,error:value.error,status:value.status,reconciled_at:new Date().toISOString()}];
value.recovery_note=note;value.status='queued';value.recovery_count=(value.recovery_count||0)+1;
delete value.error;delete value.finished_at;delete value.started_at;
const temporary=inboxPath+'.'+crypto.randomUUID()+'.tmp';fs.writeFileSync(temporary,JSON.stringify(value,null,2));fs.renameSync(temporary,inboxPath);
console.log(JSON.stringify({queued:true,messageId:msgid,recovery_count:value.recovery_count}));
