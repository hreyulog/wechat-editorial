"""Official WeChat draft-only API; credentials and tokens are never logged."""
import os
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from studio import CONFIG, ROOT, now, write

API_BASE = 'https://api.weixin.qq.com/cgi-bin'
ALLOWED_PATHS = {'/token', '/draft/count', '/draft/get', '/draft/add',
                 '/material/add_material', '/media/uploadimg'}


class ApiError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'WeChat API {code}: {message}')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError('redirect_refused', 'Official API redirect was refused')


class OfficialClient:
    def __init__(self):
        self.appid = os.environ.get('WECHAT_APPID', '')
        self.secret = os.environ.get('WECHAT_APPSECRET', '')
        if not re.fullmatch(r'wx[0-9a-fA-F]{16}', self.appid): raise ValueError('WECHAT_APPID is missing or malformed')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', self.secret): raise ValueError('WECHAT_APPSECRET is missing or malformed')
        selected = CONFIG.get('official_appid')
        if selected and selected != self.appid: raise ValueError('Account differs from configured AppID')
        self.token = None
        self.opener = urllib.request.build_opener(NoRedirect)

    def sanitize(self, message):
        text = str(message)
        for secret in (self.secret, self.token):
            if secret: text = text.replace(secret, '[REDACTED]')
        return text

    def request(self, endpoint, body=None, *, authenticate=True, data=None, content_type=None, query=None):
        if endpoint not in ALLOWED_PATHS: raise ValueError('Endpoint is outside the draft-only allowlist')
        parameters = dict(query or {})
        if authenticate: parameters['access_token'] = self.get_token()
        url = API_BASE + endpoint
        if parameters: url += '?' + urllib.parse.urlencode(parameters)
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if content_type: headers['Content-Type'] = content_type
        try:
            with self.opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=40) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024: raise ApiError('response_too_large', 'API response exceeded limit')
                result = json.loads(payload)
        except urllib.error.HTTPError as error:
            raise ApiError(f'http_{error.code}', 'Official API HTTP failure; no automatic write retry') from None
        except (urllib.error.URLError, TimeoutError):
            raise ApiError('network', 'Official API network failure; write outcome may be unknown') from None
        if result.get('errcode') not in (None, 0):
            message = self.sanitize(result.get('errmsg', 'Unknown API error'))
            write(ROOT / 'state/official-api-error.json', {'at': now(), 'endpoint': endpoint, 'code': result['errcode'], 'message': message})
            # Keep any IP whitelist detail in the local receipt, rather than chat logs.
            public_message = re.sub(r'(?:\d{1,3}\.){3}\d{1,3}', '[IP in local receipt]', message)
            raise ApiError(result['errcode'], public_message[:500])
        return result

    def get_token(self):
        if self.token is None:
            result = self.request('/token', authenticate=False, query={
                'grant_type': 'client_credential', 'appid': self.appid, 'secret': self.secret})
            token = result.get('access_token')
            if not isinstance(token, str) or not token: raise ApiError('no_token', 'API did not return a token')
            self.token = token
        return self.token


def check():
    client = OfficialClient()
    client.get_token()
    result = client.request('/draft/count')
    receipt = {'checked_at': now(), 'appid': client.appid, 'credentials_accepted': True,
               'draft_count_readable': True, 'draft_count': result.get('total_count'),
               'draft_creation_tested': False, 'published': False}
    write(ROOT / 'state/official-api-check.json', receipt)
    return receipt


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['check']); parser.parse_args()
    try:
        print(json.dumps(check(), ensure_ascii=False, indent=2))
    except (ApiError, ValueError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False)); sys.exit(1)
