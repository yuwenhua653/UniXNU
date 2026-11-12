#!/usr/bin/env python3
"""Build from an explicitly supplied private input archive; never accept private keys."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
import zipfile

FILES={'history/storage-report-r65s.json','history/verification.json','history/installation.json',
       'reference.img','anchor.bin','policies/public.pem','policies/OS/manifest.bin',
       'policies/SystemOS/manifest.bin'}

def unpack(archive, output, expected):
    if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('Invalid archive digest')
    with Path(archive).open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:raise ValueError('Archive digest differs')
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh input directory')
    with zipfile.ZipFile(archive) as z:
        rows=z.infolist()
        if len(rows)!=len(FILES) or {r.filename for r in rows}!=FILES:raise ValueError('Unexpected archive files')
        if sum(r.file_size for r in rows)>230*1024**2:raise ValueError('Oversized inputs')
        if any(stat.S_ISLNK(r.external_attr>>16) or r.flag_bits&1 for r in rows):raise ValueError('Unsupported archive entry')
        output.mkdir(mode=0o700)
        try:
            for row in rows:
                target=output/row.filename;target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(row) as source,target.open('xb') as dest:shutil.copyfileobj(source,dest)
                target.chmod(0o600)
        except Exception:
            shutil.rmtree(output);raise
    return output


def open_input(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.hostname!='api.github.com':
        return urllib.request.urlopen(url,timeout=90)
    import re
    if parsed.scheme!='https' or parsed.netloc!='api.github.com' or parsed.query or parsed.fragment or not re.fullmatch(
            r'/repos/yuwenhua653/UniXNU/releases/assets/[0-9]+',parsed.path):
        raise ValueError('Unapproved authenticated asset endpoint')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):return None
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
        'Accept':'application/octet-stream','X-GitHub-Api-Version':'2022-11-28'})
    try:
        return urllib.request.build_opener(NoRedirect).open(request,timeout=90)
    except urllib.error.HTTPError as error:
        if error.code not in (301,302,303,307,308):raise
        destination=error.headers['Location']
        target=urllib.parse.urlsplit(destination)
        if target.scheme!='https' or not target.hostname or target.username or target.password:
            raise ValueError('Unsafe asset redirect')
        # Never forward the repository token to the signed asset host.
        return urllib.request.urlopen(destination,timeout=90)


def main():
    import re
    here=Path(__file__).resolve().parent;temp=Path(os.environ['RUNNER_TEMP']).resolve()
    url=os.environ.pop('MYRON_INPUT_URL');expected=os.environ.pop('MYRON_INPUT_SHA256')
    # A temporary HTTPS download is supplied explicitly at dispatch time.
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Require an HTTPS input download')
    archive=temp/'device-inputs.zip'
    try:
        with open_input(url) as source,archive.open('xb') as dest:
            total=0
            while chunk:=source.read(1024*1024):
                total+=len(chunk)
                if total>230*1024**2:raise ValueError('Oversized archive')
                dest.write(chunk)
    except Exception:
        raise RuntimeError('Private input download failed; no URL is logged') from None
    inputs=unpack(archive,temp/'myron-private-inputs',expected)
    archive.unlink()
    subprocess.run([sys.executable,str(here/'myron27-build.py'),'--source-only'],check=True)
    sys.path.insert(0,str(temp/'myron-iphone27/device/myron27'))
    from device_inputs import inspect,run_session
    result=inspect(here/'myron27-build.py',inputs/'history',inputs/'reference.img',
                   anchor=inputs/'anchor.bin',owner_policies=inputs/'policies')
    session=temp/'myron-device-session.json'
    with open(session,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
        json.dump(result,stream,indent=2)
    run_session(session,temp/'myron-private-native')

if __name__=='__main__':main()
