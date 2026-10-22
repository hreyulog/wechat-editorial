"""Manage only local TurboPush content. Never call browser publishing endpoints."""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path
from studio import ROOT, checked_manifest, get_job, now, read, sha, write


def request_local(endpoint, body=None):
    if endpoint not in ('/article/video', '/article/list?simple=true') and not re.fullmatch(r'/article/(get|update)/[1-9]\d*',endpoint):
        raise ValueError('Only local content storage endpoints are allowed')
    cfg = json.loads((Path.home()/'.TurboPush/mcp.json').read_text(encoding='utf-8-sig'))
    port = int(cfg['port'])
    if not 1 <= port <= 65535: raise ValueError('Invalid TurboPush port')
    headers = {'Authorization':str(cfg['auth'])}
    payload = None
    if body is not None:
        headers['Content-Type']='application/json';payload=json.dumps(body,ensure_ascii=False).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+endpoint,data=payload,headers=headers)
    with urllib.request.urlopen(req,timeout=40) as response: result=json.loads(response.read())
    if result.get('code')!=200: raise RuntimeError('TurboPush local content operation failed')
    return result.get('data')


def import_video(job_id,version=None):
    job=get_job(job_id);folder,manifest=checked_manifest(job,version)
    if manifest.get('qa',{}).get('video',{}).get('passed') is not True: raise ValueError('Validated video required')
    visual=read(folder/'visual-review.json')
    if visual.get('checked') is not True: raise ValueError('Actual video visual review required')
    video=folder/'review.mp4';digest=sha(video);receipt_path=folder/'turbopush-local.json'
    if receipt_path.exists():
        saved=read(receipt_path)
        if saved.get('video_sha256')!=digest: raise ValueError('Saved local draft belongs to another video')
        if not saved.get('id'): raise ValueError('Previous local import outcome unknown; inspect TurboPush before retrying')
        return verify_local(saved,receipt_path,video)
    number=int(folder.name[1:]);title=f'{job_id}-v{number}｜{job["topic"]}'
    payload={'title':title,'desc':job.get('summary') or job['topic'],
             'files':[str(video)],'thumb':[str(folder/'cover.png')],'autoThumb':False,'syncDraft':True}
    saved={'job_id':job_id,'version':number,'video_sha256':digest,'state':'creating_local_content','at':now(),
           'video_channel_uploaded':False,'published':False}
    write(receipt_path,saved)
    created=request_local('/article/video',payload)
    if not isinstance(created,dict) or not created.get('id'): raise ValueError('No local content ID returned')
    saved.update(id=created['id'],title=title,state='stored_locally',at=now());write(receipt_path,saved)
    return verify_local(saved,receipt_path,video)


def verify_local(saved,receipt_path,video):
    endpoint='/article/get/'+str(saved['id']);detail=request_local(endpoint)
    payload=detail.get('publish_data',{}) if isinstance(detail,dict) else {}
    if payload.get('title')!=saved['title'] or str(video) not in payload.get('files',[]) or detail.get('status')!=1:
        raise ValueError('Local draft readback did not match the imported video')
    if payload.get('syncDraft') is not True:
        payload['syncDraft']=True;request_local('/article/update/'+str(saved['id']),payload)
        if request_local(endpoint).get('publish_data',{}).get('syncDraft') is not True: raise ValueError('Local draft mode was not retained')
    saved.update(local_readback_verified=True,local_syncDraft=True);write(receipt_path,saved)
    return saved


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('id');parser.add_argument('--version',type=int);args=parser.parse_args()
    try:print(json.dumps(import_video(args.id,args.version),ensure_ascii=False,indent=2))
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__,'message':'Local content import failed; check the saved receipt before retrying'},ensure_ascii=False));sys.exit(1)
