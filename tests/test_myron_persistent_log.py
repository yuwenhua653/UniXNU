#!/usr/bin/env python3
"""Execute the actual disk commit/bounds code and reject interrupted/stale reads."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser();p.add_argument('--device',type=Path,required=True);p.add_argument('--cc',default='c++');p.add_argument('--upstream-reader',type=Path)
a=p.parse_args();a.device=a.device.resolve();sys.path.insert(0,str(a.device))
import myron_read_log as reader
ufs=a.device.parent/'sm8850/drivers/NativeUfs'
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    source=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "MyronBootLogCore.h"
static uint8_t disk[128*4096],msg[32*4096],previous[32*4096],slot[16*4096],header[4096];
static int calls,fail;
static std::vector<unsigned> writes;
static bool write(uint64_t rel,uint32_t n,const void *p) {
 ++calls;if(calls==fail)return false;
 assert(myronLogRange(rel,n));writes.push_back((unsigned)rel);
 memcpy(disk+rel*4096,p,n*4096);return true;
}
static bool sync(){return ++calls!=fail;}
static MyronLogHeader initial() {
 MyronLogHeader h={};memcpy(h.magic,"SHLOG001",8);h.version=5;h.header_bytes=sizeof h;
 h.boot_id=0x1234;h.first_lba=65664;h.window_blocks=128;
 h.msg_first=1;h.msg_blocks=32;h.slot_first=33;h.slot_blocks=16;h.slot_count=5;
 h.state=2;strcpy(h.tag,"myron-persist-v1");return h;
}
int main(int argc,char **argv) {
 assert(argc==2);
 MyronRootGeometry g={256,65791,66047,264241152ULL,3616768,1024};uint64_t first=0;
 assert(myronLogWindow(g,67108864ULL,g.first,g.last,&first)&&first==65664);
 auto bad=g;bad.carrierCapacity+=14*4096;assert(!myronLogWindow(bad,67108864ULL,g.first,g.last,&first));
 bad=g;bad.carrierOffset+=14*4096;assert(!myronLogWindow(bad,67108864ULL,g.first,g.last,&first));
 bad=g;bad.reserveBlocks=128;assert(!myronLogWindow(bad,67108864ULL,g.first,g.last,&first));
 assert(!myronLogWindow(g,UINT64_MAX,g.first,g.last,&first));
 assert(!myronLogWindow(g,67108864ULL,g.first+1,g.last,&first));
 assert(!myronLogRange(UINT64_MAX,1)&&!myronLogRange(127,2)&&!myronLogRange(0,0)&&myronLogRange(127,1));
 assert(myronLogCrc("123456789",9)==0xcbf43926);
 // Fail each message, slot, sync and header step. In-memory commit counters must not advance.
 strcpy((char*)msg,"kernel test\n");strcpy((char*)slot,"[myron] boot=1234 round=1 log_seconds=0\nreason\n");
 unsigned used=(unsigned)strlen((char*)slot)+1;
 for(fail=1;fail<=36;++fail) {
  auto h=initial();MyronLogCheck ck={};memcpy(ck.magic,"MYLGC001",8);
  calls=0;writes.clear();memset(disk,0,sizeof disk);
  assert(!myronLogCommit(h,ck,msg,previous,false,slot,used,header,write,sync));
  assert(h.rounds==0&&h.slots_written==0&&calls==fail);
  if(fail<=34)assert(writes.empty() || writes.back()!=0);
 }
 fail=0;calls=0;writes.clear();memset(disk,0,sizeof disk);
 auto h=initial();MyronLogCheck ck={};memcpy(ck.magic,"MYLGC001",8);
 h.msg_bytes=(uint32_t)strlen((char*)msg);
 assert(myronLogCommit(h,ck,msg,previous,false,slot,used,header,write,sync));
 assert(calls==36&&writes.back()==0);memcpy(previous,msg,sizeof msg);
 for(unsigned round=2;round<=7;++round) {
  memset(slot,0,sizeof slot);snprintf((char*)slot,sizeof slot,"[myron] boot=1234 round=%u log_seconds=0\nreason\n",round);
  calls=0;writes.clear();
  assert(myronLogCommit(h,ck,msg,previous,true,slot,(uint32_t)strlen((char*)slot)+1,header,write,sync));
  assert(calls==4&&writes.size()==2&&writes.back()==0); // no unchanged msg blocks written
 }
 FILE *f=fopen(argv[1],"wb");assert(f);assert(fwrite(disk,1,sizeof disk,f)==sizeof disk);fclose(f);
}
'''
    (tmp/'core.cpp').write_text(source)
    exe=tmp/'core'
    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0')
    subprocess.run([a.cc,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(ufs),str(tmp/'core.cpp'),'-o',str(exe)],check=True)
    fixture=tmp/'log.bin';subprocess.run([str(exe),str(fixture)],check=True,env=env)
    raw=fixture.read_bytes();h,msg,slots=reader.decode(raw,65664)
    assert h['complete_round'] and h['rounds']==7 and len(slots)==5 and 'round=3 ' in slots[0] and 'round=7 ' in slots[-1]
    assert msg=='kernel test\n'
    for bad,first in [(raw[:-1],65664),(raw+b'x',65664),(bytes(len(raw)),65664),(raw,1)]:
        try:reader.decode(bad,first)
        except ValueError:pass
        else:raise AssertionError('bad header accepted')
    bad=bytearray(raw);bad[100]^=1
    try:reader.decode(bad,65664)
    except ValueError:pass
    else:raise AssertionError('torn header accepted')
    bad=bytearray(raw);bad[4096]^=1
    assert not reader.decode(bad,65664)[0]['complete_round']
    bad=bytearray(raw);bad[33*4096]^=1
    assert not reader.decode(bad,65664)[0]['complete_round']
    # Simulated recovery: exact bounds only, preserve raw on no-writer/partial data.
    layout=dict(first=256,last=65791,diskLast=66047,partitionGuid='test',partition_bytes=268435456)
    dep=dict(device='myron',partition='unixnu',device_bound=True,layout=layout,
             geometry=dict(layout,carrierOffset=264241152,carrierCapacity=3616768,reserveBlocks=1024),
             files={'root-container.raw':{'bytes':67108864}})
    assert reader.window(dep)==65664
    import copy
    bad=copy.deepcopy(dep);bad['geometry']['carrierCapacity']+=14*4096
    try:reader.window(bad)
    except ValueError:pass
    else:raise AssertionError('carrier overlap accepted')
    class Fake:
        def __init__(self,data):self.data=data;self.calls=0;self.changed=False
        def layout(self):
            self.calls+=1
            return (dict(layout,first=1) if self.changed and self.calls>1 else layout),(b'header',)*4
        def read(self,first,n):assert (first,n)==(65664,128);return self.data
    archive,report=reader.capture(Fake(raw),dep,tmp/'valid')
    assert archive.is_file() and report['device_writes']==0 and report['header']['complete_round']
    _,report=reader.capture(Fake(bytes(len(raw))),dep,tmp/'empty')
    assert 'decode_error' in report and (tmp/'empty/log.bin').is_file()
    f=Fake(raw);f.changed=True
    try:reader.capture(f,dep,tmp/'changed')
    except ValueError:pass
    else:raise AssertionError('changed GPT accepted')
    # The real binary read emits only fixed dd input options; detects full-size failed reads.
    r=reader.Recovery.__new__(reader.Recovery);r.last=66047;r.serial='test';seen=[]
    r.invoke=lambda *args:seen.append(args) or raw
    assert r.read(65664,128)==raw
    assert seen[0][:3]==('-s','test','exec-out') and ' of=' not in seen[0][-1] and 'MYRON_READ_FAILED' in seen[0][-1]
    r.invoke=lambda *args:raw+b'MYRON_READ_FAILED'
    try:r.read(65664,128)
    except ValueError:pass
    else:raise AssertionError('failed dd accepted')
    # Validate compatibility against the official unmodified decoder when supplied.
    if a.upstream_reader:
        spec=importlib.util.spec_from_file_location('official_reader',a.upstream_reader)
        official=importlib.util.module_from_spec(spec);spec.loader.exec_module(official)
        out=official.decode(raw,tmp/'official')
        assert (out/'msgbuf.txt').read_text()==msg
        assert (out/'latest.txt').read_text()==slots[-1]
        print('PASS unmodified official decoder reads actual C++ v5 output')

    print('PASS geometry/overflow guards, 36 I/O fault points, ring rollover, CRC/torn/stale validation, recovery read-only capture')
