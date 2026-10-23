"""Read the bound official draft by identity, never by a matching title."""
import hashlib
import json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mobile_playback_confirmed(folder,media_id,manifest_sha256,content):
    path=folder/'official/mobile-playback-confirmation.json'
    if not path.exists():return False
    proof=json.loads(path.read_text(encoding='utf-8-sig'))
    return (proof.get('user_confirmed') is True and bool(proof.get('confirmed_at'))
        and proof.get('media_id')==media_id and proof.get('manifest_sha256')==manifest_sha256
        and proof.get('content_sha256')==hashlib.sha256(content.encode('utf-8')).hexdigest())


def read_exact(client, media_id, title):
    if not isinstance(media_id,str) or not media_id:
        raise ValueError('Official draft media_id is missing; do not select a same-title substitute')
    detail=client.request('/draft/get',{'media_id':media_id})
    items=detail.get('news_item') or []
    if len(items)!=1 or items[0].get('title')!=title:
        raise ValueError('Bound official draft differs; do not select or overwrite another same-title draft')
    return detail


def invalidate(folder, receipt, error):
    from studio import write,now
    unavailable=getattr(error,'code',None)==40007
    receipt.update(state='draft_unavailable' if unavailable else 'readback_unconfirmed',
        ready_for_review=False,readback_error_code=getattr(error,'code',None),readback_checked_at=now())
    write(folder/'official/receipt.json',receipt)
    preview_path=folder/'official-preview.json'
    if preview_path.exists():
        preview=json.loads(preview_path.read_text(encoding='utf-8-sig'))
        preview.update(valid=False,state=receipt['state'],invalidated_at=now())
        write(preview_path,preview)


def check_local_binding(folder, receipt, manifest_sha256):
    preview=json.loads((folder/'official-preview.json').read_text(encoding='utf-8-sig'))
    if preview.get('valid') is False or receipt.get('state') in ('draft_unavailable','readback_unconfirmed'):
        raise ValueError('Official draft is unavailable or unconfirmed; refresh this exact media_id before delivery')
    if not receipt.get('media_id') or preview.get('media_id')!=receipt['media_id']:
        raise ValueError('Preview and receipt refer to different official drafts')
    if preview.get('manifest_sha256')!=manifest_sha256:
        raise ValueError('Official preview belongs to another content version')
    if receipt.get('manifest_sha256')!=manifest_sha256:
        raise ValueError('Official draft receipt belongs to another content version')
    if preview.get('readback_sha256')!=digest(folder/'official/readback.json'):
        raise ValueError('Official readback changed since this preview was registered')
    return preview


def refresh_native_readback(folder, article, receipt, manifest_sha256):
    """An authorized read-only check immediately before native-card delivery/review."""
    from official_api import OfficialClient
    from studio import write,now,official_url
    from video_embed_check import verify_video_component
    from urllib.parse import urlsplit,urlunsplit
    check_local_binding(folder,receipt,manifest_sha256)
    try:detail=read_exact(OfficialClient(),receipt['media_id'],article['title'])
    except Exception as error:
        invalidate(folder,receipt,error);raise ValueError('The bound draft could not be read; no same-title draft was substituted') from error
    previous=json.loads((folder/'official/readback.json').read_text(encoding='utf-8-sig'))
    if detail['news_item'][0].get('content','')!=previous['news_item'][0].get('content',''):
        invalidate(folder,receipt,ValueError('Draft edited since version readback'))
        raise ValueError('The bound draft was edited; adopt the real change in a new version before delivery')
    check=verify_video_component(folder,article,detail['news_item'][0].get('content',''))
    if not check['preserved']:
        invalidate(folder,receipt,ValueError('Native component removed'))
        raise ValueError('Fresh official readback lost the required native card; delivery stopped')
    raw_url=detail['news_item'][0].get('url','');parsed=urlsplit(raw_url)
    if parsed.scheme=='http' and parsed.hostname=='mp.weixin.qq.com':raw_url=urlunsplit(parsed._replace(scheme='https'))
    url=official_url(raw_url)
    # Keep the preview and readback in one identity-bound generation.
    write(folder/'official/readback.json',detail)
    proof=digest(folder/'official/readback.json')
    confirmed=mobile_playback_confirmed(folder,receipt['media_id'],manifest_sha256,detail['news_item'][0].get('content',''))
    receipt.update(readback_sha256=proof,readback_at=now(),video_component_check=check,
        verification_scope='official_draft_fields_and_user_mobile_playback' if confirmed else 'official_draft_fields_only',phone_playback_tested=confirmed)
    write(folder/'official/receipt.json',receipt)
    write(folder/'official-preview.json',{'url':url,'provenance':'official_api_draft_get','media_id':receipt['media_id'],
        'manifest_sha256':manifest_sha256,'readback_sha256':proof,'attached_at':now(),'valid':True})
    return check
