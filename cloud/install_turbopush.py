"""Install official Linux artifacts with pinned SHA256; no login material."""
import hashlib
import io
import os
import tarfile
import urllib.request
from pathlib import Path

artifacts={
    'desktop':('https://release.turbopush.top/latest/Turbo.Push_latest_amd64.deb',
        '267d93c43c97933e4dae68ea8b84513d58da380d9088aed9d17c0a02d6b7071c'),
    'mcp':('https://github.com/xueyc1f/turbopush-mcp/releases/download/v1.1.3/turbo-push-mcp-x86_64-unknown-linux-gnu',
        'dc70ed561a0b663de273298739156fb1292ca08880b0b9b7f14650baab2952b1')}
target=Path('/opt/turbopush');target.mkdir(parents=True,exist_ok=True)
for name,(url,expected) in artifacts.items():
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request,timeout=180) as response:data=response.read(150*1024*1024)
    if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Official artifact changed; review and update its pinned hash')
    if name=='mcp':(target/'turbo-push-mcp').write_bytes(data)
    else:
        offset=8
        if data[:8]!=b'!<arch>\n':raise RuntimeError('Invalid Debian archive')
        while offset<len(data):
            entry=data[offset:offset+16].decode().strip().rstrip('/')
            size=int(data[offset+48:offset+58]);content=data[offset+60:offset+60+size]
            offset+=60+size+(size%2)
            if entry.startswith('data.tar'):
                with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                    for member in archive:
                        if member.name in ('usr/bin/turbopush','usr/bin/turbo_push_server','usr/bin/turbo_push_kb'):
                            (target/Path(member.name).name).write_bytes(archive.extractfile(member).read())
for binary in target.iterdir():binary.chmod(0o755)
