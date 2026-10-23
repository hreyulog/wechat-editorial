"""Write machine-local paths; does not authenticate, contact APIs, or start the bot."""
import json
import os
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
studio=ROOT/'editorial/wechat-content-studio'
for name in ('jobs','outbox','state'):(studio/name).mkdir(exist_ok=True)
(ROOT/'editorial/wecom-bot-local/state').mkdir(exist_ok=True,mode=0o700)
target=studio/'config.json'
old=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
config={**old,'group':'企业微信审核群','python':sys.executable,'article_python':sys.executable,
        'node':shutil.which('node') or 'node','ffmpeg':os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg') or 'ffmpeg',
        'chrome':os.environ.get('CHROME_BINARY',''),'article_skills':str(ROOT/'editorial/upstream/wechat-article-skills'),
        'article_delivery':'official_wechat_preview_only','turbopush_enabled':False,'publish_enabled':False}
target.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
env=ROOT/'.env'
if not env.exists() and not os.environ.get('EDITORIAL_CLOUD'):shutil.copyfile(ROOT/'.env.example',env);env.chmod(0o600)
print('Local paths configured. Fill .env and run codex login before binding the group.')
