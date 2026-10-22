// Shared by the optional codex-weixin adapter; no credentials or network clients.
export const DEFAULT_TURN_TIMEOUT_MS=4*60*60*1000;
export function editorialTurnTimeoutMs(options={}){
 const timeout=options.turnTimeoutMs??DEFAULT_TURN_TIMEOUT_MS;
 if(!Number.isSafeInteger(timeout)||timeout<=0)throw Error('Invalid editorial turn timeout');
 return Math.min(timeout,DEFAULT_TURN_TIMEOUT_MS);
}
export async function forkEditorialThread(runner,threadId,cwd){
 if(!threadId||!cwd)throw Error('Recovery requires the original thread and workspace');
 if(runner.activeTurns.has(threadId))throw Error('Cannot recover an active turn');
 await runner.ensureConnected();
 const result=await runner.request('thread/fork',{threadId,cwd,approvalPolicy:'never'});
 const id=result.thread?.id;
 if(!id||id===threadId)throw Error('Recovery did not return a distinct thread');
 runner.runtimeInfoByThread.set(id,{});
 return {threadId:id,recoveredFrom:threadId};
}
export async function recoverEditorialSession(manager,accountId,sessionId,expectedThreadId){
 if(manager.isSessionResponding(accountId,sessionId))throw Error('Cannot recover a responding session');
 const store=manager.storeFor(accountId),session=store.getSession(sessionId);
 if(!session||!expectedThreadId||session.threadId!==expectedThreadId)throw Error('Recovery session changed');
 const result=await manager.runnerFor().forkEditorialThread(session.threadId,session.workspace);
 // The native fork does no user work or publishing. Only switch after success.
 if(manager.isSessionResponding(accountId,sessionId)||store.getSession(sessionId).threadId!==expectedThreadId)
  throw Error('Recovery session changed during fork; original binding retained');
 store.setSessionThread(sessionId,result.threadId);
 return result;
}
