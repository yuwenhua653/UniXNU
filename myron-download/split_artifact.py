#!/usr/bin/env python3
"""Stream the pinned original GitHub archive into verified 450 MiB parts."""
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from merge_parts import NAME,SIZE,SHA,PART_BYTES,COUNT,require

URL='https://api.github.com/repos/yuwenhua653/UniXNU/actions/artifacts/13922666696/zip'


def response():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):return None
    req=urllib.request.Request(URL,headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],
        'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    try:return urllib.request.build_opener(NoRedirect).open(req,timeout=90)
    except urllib.error.HTTPError as e:
        if e.code not in (301,302,303,307,308):raise RuntimeError('GitHub archive HTTP '+str(e.code)) from None
        target=e.headers['Location'];parsed=urllib.parse.urlsplit(target)
        require(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password,'Unsafe download redirect')
        # Fresh request: never forward Authorization to the signed asset host.
        return urllib.request.urlopen(target,timeout=90)


def split(stream,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    parts=[];full=hashlib.sha256();total=0
    for i in range(COUNT):
        name=NAME+f'.part{i:02d}';remaining=min(PART_BYTES,SIZE-total);size=0;part=hashlib.sha256()
        with (out/name).open('xb') as f:
            while remaining:
                data=stream.read(min(8*1024**2,remaining))
                require(data,'Truncated source archive')
                f.write(data);full.update(data);part.update(data)
                remaining-=len(data);total+=len(data);size+=len(data)
        parts.append(dict(file=name,bytes=size,sha256=part.hexdigest()))
        print(f'Part {i+1}/{COUNT} downloaded',flush=True)
    require(not stream.read(1) and total==SIZE and full.hexdigest()==SHA,'Original archive SHA256 differs')
    (out/'parts.json').write_text(json.dumps(dict(archive=NAME,bytes=SIZE,sha256=SHA,parts=parts),indent=2)+'\n')
    print('All parts verified against the original successful build ZIP.',flush=True)


if __name__=='__main__':
    with response() as stream:split(stream,Path('split-parts'))
