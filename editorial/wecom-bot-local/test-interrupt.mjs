import {test} from 'node:test';
import assert from 'node:assert/strict';
import {controlIntent,applyIncomingControl} from './interrupt.mjs';

test('commands distinguish stopping, steering and unrelated new tasks',()=>{
 assert.deepEqual(controlIntent('停止'),{action:'interrupt',resume:false,text:''});
 assert.deepEqual(controlIntent('打断：换成女声'),{action:'interrupt',resume:true,text:'换成女声'});
 assert.equal(controlIntent('补充：不要配乐').action,'steer');
 assert.equal(controlIntent('新任务：做一篇马尔可夫文章').action,'queue');
});
test('followup uses native control instead of queuing a duplicate task',async()=>{
 const record={msgid:'followup',text:'不要配乐',user_id:'member',status:'queued'},target={msgid:'original'};let calls=0;
 const handled=await applyIncomingControl({record,target,persist:()=>{},persistTarget:()=>{},push:async()=>{},control:async p=>{calls++;assert.equal(p.action,'steer');return{accepted:true,turnId:'same-turn'};}});
 assert(handled);assert.equal(calls,1);assert.equal(record.status,'steered');assert.equal(record.target_msgid,'original');
});
test('interruption is recorded; changing direction resumes only after native acceptance',async()=>{
 const record={msgid:'change',text:'打断：换成女声',user_id:'member'},target={msgid:'original'};
 const handled=await applyIncomingControl({record,target,persist:()=>{},persistTarget:()=>{},push:async()=>{},control:async p=>{assert.equal(p.action,'interrupt');return{accepted:true,turnId:'same-turn'};}});
 assert.equal(handled,false);assert.equal(target.interrupt_requested_by,'change');assert.equal(record.status,'queued');assert(record.priority);
});
test('a lost control acknowledgment never becomes an automatically replayed task',async()=>{
 const record={msgid:'stop',text:'停止',user_id:'member'},target={msgid:'original'};
 await assert.rejects(()=>applyIncomingControl({record,target,persist:()=>{},persistTarget:()=>{},push:async()=>{},control:async()=>{throw Error('response lost');}}));
 assert.equal(record.status,'control_unknown');assert.notEqual(record.status,'queued');
});
