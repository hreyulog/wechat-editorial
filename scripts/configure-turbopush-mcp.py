"""Opt in one installed MCP binary; no tokens, browser actions, or API requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--studio',type=Path,default=Path(__file__).resolve().parents[1]/'editorial/wechat-content-studio')
parser.add_argument('--binary',type=Path,required=True)
args=parser.parse_args()
binary=args.binary.resolve(strict=True)
if not binary.is_file():raise SystemExit('An installed official TurboPush MCP executable is required')
studio=args.studio.resolve(strict=True)
if not (studio/'studio.py').is_file():raise SystemExit('Pass the content studio directory')
target=studio/'state/turbopush-mcp.json';target.parent.mkdir(exist_ok=True)
config={'enabled':True,'command':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'scope':'full-mcp-surface','enabled_tool_count':21,
        'credentials_source':'TurboPush MCP reads this machine\'s ~/.TurboPush/mcp.json; no credentials copied'}
temp=target.with_suffix('.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
os.replace(temp,target)
print(json.dumps({'configured':str(target),'scope':config['scope'],'enabled_tool_count':config['enabled_tool_count']},ensure_ascii=False))
