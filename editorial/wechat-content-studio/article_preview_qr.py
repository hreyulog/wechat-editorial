"""Generate a review QR from the actual registered official preview URL."""
import argparse
import hashlib
import json
from pathlib import Path


def enqueue(root, folder, parent_path):
    from studio import read, write, sha, now, official_url, require_deliverable_video
    import qrcode
    root=Path(root).resolve();folder=Path(folder).resolve();parent_path=Path(parent_path).resolve()
    parent_path.relative_to(root/'outbox');folder.relative_to(root/'jobs')
    parent=read(parent_path)
    if parent.get('kind') in ('publication_qr','article_preview_qr') or parent.get('destination',{}).get('provider')!='wecom':
        return None
    if not parent.get('source_message_id'):raise ValueError('Preview QR requires the review task source receipt')
    job_id=folder.parent.name;version=int(folder.name[1:])
    if parent.get('job_id')!=job_id or parent.get('version')!=version:raise ValueError('Review version differs')
    article=read(folder/'article.json')
    require_deliverable_video(folder,article,sha(folder/'manifest.json'))
    url=official_url(read(folder/'official-preview.json')['url'])
    url_hash=hashlib.sha256(url.encode()).hexdigest()
    # Never overwrite a previously delivered PNG when a temporary preview is refreshed.
    images=folder/'review-qr';images.mkdir(exist_ok=True)
    image=images/(url_hash[:16]+'.png')
    if not image.exists():
        code=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=6,border=4)
        code.add_data(url);code.make(fit=True);code.make_image(fill_color='black',back_color='white').save(image)
    target=root/'outbox'/f'{job_id}-v{version}-preview-qr-{hashlib.sha256((parent_path.name+url_hash).encode()).hexdigest()[:16]}.json'
    if not target.exists():
        write(target,{'kind':'article_preview_qr','purpose':'article_preview','job_id':job_id,'version':version,
            'created_at':now(),'status':'queued','source_message_id':parent['source_message_id'],
            'destination':parent['destination'],'parent_outbox':parent_path.name,'preview_url_sha256':url_hash,
            'manifest_sha256':sha(folder/'manifest.json'),
            'text':f'公众号预览二维码｜{job_id}-v{version}\n{article["title"]}\n请用微信扫码审阅；预览链接失效时可让机器人刷新。',
            'files':[{'path':str(image),'sha256':sha(image),'media_type':'image'}]})
    return {'outbox':str(target),'status':read(target)['status'],'kind':'article_preview_qr','published':False}


if __name__=='__main__':
    from studio import ROOT,checked_manifest,get_job
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id');parser.add_argument('--version',type=int,required=True)
    parser.add_argument('--review-outbox',type=Path,required=True)
    args=parser.parse_args()
    folder,_=checked_manifest(get_job(args.job_id),args.version)
    print(json.dumps(enqueue(ROOT,folder,args.review_outbox),ensure_ascii=False))
