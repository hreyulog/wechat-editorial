"""Restore UTF-8 resource filenames after the platform's ZIP handoff."""
import base64
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
bundle=root/'cloud/unicode-sources.json'
if bundle.exists():
    for name,value in json.loads(bundle.read_text(encoding='utf-8')).items():
        path=(root/name).resolve();path.relative_to(root)
        if not name.startswith('editorial/upstream/'):
            raise ValueError('Unexpected unicode resource path')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(base64.b64decode(value,validate=True))
    bundle.unlink()
