"""Queue a freshly observed TurboPush publication-confirmation PNG to its source.

This does not create a code or start publishing. Capture the actual confirmation
modal with an allowed tool first; homepage/promotional QR images are not valid.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from studio import ROOT, read, write, checked_manifest, get_job, sha, now


def enqueue(job_id, version, image, evidence):
    folder,_=checked_manifest(get_job(job_id),version)
    image=image.resolve();image.relative_to((folder/'publication').resolve())
    if image.suffix.lower()!='.png' or not 8<=image.stat().st_size<=2*1024*1024 or image.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':
        raise ValueError('A real bounded PNG capture is required')
    capture=read(evidence)
    source=read(ROOT/'state/active-wecom-task.json')
    required={'publisher':'turbo_push','purpose':'publication_confirmation','job_id':job_id,'version':version,
        'source_message_id':source['msgid'],'image_sha256':sha(image)}
    if any(capture.get(key)!=value for key,value in required.items()) or not capture.get('publication_attempt_id'):
        raise ValueError('Capture evidence differs from this publication and source message')
    stamp=datetime.fromisoformat(capture['captured_at'].replace('Z','+00:00'))
    clock=datetime.now(timezone.utc)
    if not -5<=(clock-stamp).total_seconds()<120:
        raise ValueError('The code must be observed within the past two minutes')
    target=source['reply_to']
    if not target:raise ValueError('No originating conversation')
    key=hashlib.sha256((source['msgid']+sha(image)).encode()).hexdigest()[:16]
    destination=ROOT/'outbox'/f'{job_id}-v{version}-qr-{key}.json'
    if destination.exists():
        return {'queued':False,'status':read(destination)['status'],'replayed':False}
    item={'kind':'publication_qr','job_id':job_id,'version':version,'status':'queued','created_at':now(),
        'source_message_id':source['msgid'],'destination':{'provider':'wecom','chatid':target},
        'publisher':'turbo_push','purpose':'publication_confirmation',
        'publication_attempt_id':capture['publication_attempt_id'],
        'captured_at':capture['captured_at'],'expires_at':(stamp+timedelta(seconds=120)).isoformat(),
        'manifest_sha256':sha(folder/'manifest.json'),
        'text':f'{job_id}-v{version} 发布确认二维码。请使用对应账号的管理员微信扫码；如已失效请获取新码。扫码结果及发表状态将另行核对。',
        'files':[{'path':str(image),'sha256':sha(image),'media_type':'image'}]}
    write(destination,item)
    return {'queued':True,'published':False,'media_type':'image','outbox':str(destination)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id');parser.add_argument('--version',type=int,required=True)
    parser.add_argument('--image',type=Path,required=True);parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(enqueue(args.job_id,args.version,args.image,args.evidence),ensure_ascii=False))
    except (ValueError,KeyError,OSError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));raise SystemExit(1)
