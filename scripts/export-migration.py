"""Archive the committed source tree only; never walk runtime directories."""
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args])
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'dist');args=parser.parse_args()
    if git('status','--porcelain').strip():raise SystemExit('Commit source changes before exporting a migration package')
    commit=git('rev-parse','HEAD').decode().strip()
    archive=git('archive','--format=tar','HEAD')
    files=[]
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source.getmembers():
            if member.isfile():
                data=source.extractfile(member).read()
                files.append({'path':member.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    manifest={'repository':'https://github.com/hreyulog/wechat-editorial','commit':commit,
              'created_at':datetime.now(timezone.utc).isoformat(),'linux_runtime_validation':'not_run_per_user_request',
              'contains_credentials':False,'contains_runtime_state':False,'contains_dependencies':False,'files':files}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d');stem=f'wechat-editorial-linux-{stamp}-{commit[:8]}'
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    prefix='wechat-editorial/';manifest_bytes=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    tarpath=output/(stem+'.tar.gz');zippath=output/(stem+'.zip')
    with tarfile.open(fileobj=io.BytesIO(archive)) as source,tarfile.open(tarpath,'w:gz') as target,zipfile.ZipFile(zippath,'w',zipfile.ZIP_DEFLATED) as zipped:
        for member in source.getmembers():
            if not member.isfile():continue
            data=source.extractfile(member).read();member.name=prefix+member.name
            target.addfile(member,io.BytesIO(data))
            info=zipfile.ZipInfo(member.name);info.external_attr=(member.mode&0o777)<<16
            info.compress_type=zipfile.ZIP_DEFLATED;zipped.writestr(info,data)
        info=tarfile.TarInfo(prefix+'MIGRATION-MANIFEST.json');info.size=len(manifest_bytes);info.mode=0o644
        target.addfile(info,io.BytesIO(manifest_bytes));zipped.writestr(prefix+'MIGRATION-MANIFEST.json',manifest_bytes)
    for p in (tarpath,zippath):
        (output/(p.name+'.sha256')).write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n',encoding='utf-8')
    (output/(stem+'-manifest.json')).write_bytes(manifest_bytes)
    print(json.dumps({'commit':commit,'files':len(files),'tar_gz':str(tarpath),'zip':str(zippath),'linux_runtime_validation':'not_run'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
