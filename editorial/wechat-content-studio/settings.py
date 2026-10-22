"""Resolve a fresh deployment without importing workstation state."""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]


def load_env():
    source = REPOSITORY / '.env'
    if source.exists():
        for line in source.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line: continue
            key, value = line.split('=', 1)
            key = key.removeprefix('export ').strip()
            if value[:1] in ('"', "'") and value[-1:] == value[:1]: value = value[1:-1]
            os.environ.setdefault(key, value)


def load_config():
    load_env()
    source = ROOT / 'config.json'
    config = json.loads(source.read_text(encoding='utf-8')) if source.exists() else {}
    defaults = {'group': '企业微信审核群', 'python': sys.executable,
                'article_python': sys.executable, 'node': shutil.which('node') or 'node',
                'ffmpeg': os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg') or 'ffmpeg',
                'chrome': os.environ.get('CHROME_BINARY', ''),
                'article_skills': str(REPOSITORY / 'editorial/upstream/wechat-article-skills'),
                'article_delivery': 'official_wechat_preview_only', 'turbopush_enabled': False,
                'publish_enabled': False}
    result = {**defaults, **config}
    if os.environ.get('FFMPEG_BINARY'): result['ffmpeg'] = os.environ['FFMPEG_BINARY']
    if os.environ.get('CHROME_BINARY'): result['chrome'] = os.environ['CHROME_BINARY']
    return result
