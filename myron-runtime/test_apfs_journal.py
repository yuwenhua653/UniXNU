#!/usr/bin/env python3
"""Exercise the actual helper's journal adapter against a disposable directory."""
import os,subprocess,tempfile
from pathlib import Path
here=Path(__file__).resolve().parent
source=(here/'myron-data-grow.m').read_text()
start=source.index('static int journal(');end=source.index('static int resize(',start)
body=source[start:end]
assert body.count('"/private/var/root"')==1
body=body.replace('"/private/var/root"','testDirectory')
harness=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include "MyronAPFSTransaction.h"
static char *testDirectory;
static int fault, syncCalls, closeCalls;
static int testOpen(const char *p,int flags){if(fault==1){errno=EACCES;return -1;}return open(p,flags);}
static int testOpenAt(int d,const char *p,int flags,mode_t mode){if(fault==2){errno=ENOSPC;return -1;}return openat(d,p,flags,mode);}
static ssize_t testWrite(int f,const void *p,size_t n){if(fault==3){errno=ENOSPC;return -1;}return write(f,p,fault==4?n-1:n);}
static int testSync(int f){++syncCalls;if(fault==4+syncCalls){errno=EIO;return -1;}return fsync(f);}
static ssize_t testRead(int f,void *p,size_t n,off_t offset){
 if(fault==7){errno=EIO;return -1;}
 ssize_t r=pread(f,p,fault==8?n-1:n,offset);if(fault==9 && r>0)((char*)p)[0]^=1;return r;
}
static int testClose(int f){int rc=close(f);++closeCalls;if(fault==9+closeCalls){errno=EIO;return -1;}return rc;}
#define open testOpen
#define openat testOpenAt
#define write testWrite
#define fsync testSync
#define pread testRead
#define close testClose
'''+body+r'''
#undef open
#undef openat
#undef write
#undef fsync
#undef pread
#undef close
int main(int argc,char **argv){
 assert(argc==2);testDirectory=argv[1];MyronGrowSnapshot s={0};s.physical=UINT64_C(16)<<30;
 strcpy(s.volume,"disk3s1");strcpy(s.media,"disk3");strcpy(s.store,"disk1");
 strcpy(s.volumeUUID,"12345678-1234-1234-1234-123456789abc");
 int d=open(testDirectory,O_RDONLY|O_DIRECTORY);assert(d>=0);
 for(fault=0;fault<=11;++fault){
  syncCalls=closeCalls=0;assert(journal(NULL,&s)==(fault!=0));
  int f=openat(d,"myron-apfs-grow.attempt",O_RDONLY|O_NOFOLLOW);
  if(fault<=2 && fault){assert(f<0 && errno==ENOENT);continue;}
  assert(f>=0);struct stat st;assert(!fstat(f,&st) && S_ISREG(st.st_mode) && (st.st_mode&0777)==0600);
  char saved[384],again[384];ssize_t n=read(f,saved,sizeof(saved));assert(n>=0);close(f);
  /* A pre-existing intent, including partial/error records, is never replaced. */
  int previous=fault;fault=0;assert(journal(NULL,&s));fault=previous;
  f=openat(d,"myron-apfs-grow.attempt",O_RDONLY);assert(f>=0);
  assert(read(f,again,sizeof(again))==n && !memcmp(saved,again,(size_t)n));close(f);
  assert(!unlinkat(d,"myron-apfs-grow.attempt",0));
 }
 assert(!symlinkat("other-file",d,"myron-apfs-grow.attempt"));fault=0;assert(journal(NULL,&s));
 assert(!unlinkat(d,"myron-apfs-grow.attempt",0));
 assert(!mkdirat(d,"myron-apfs-grow.attempt",0700));assert(journal(NULL,&s));
 assert(!unlinkat(d,"myron-apfs-grow.attempt",AT_REMOVEDIR));close(d);
 puts("PASS: real journal adapter: 12 I/O cases, retained attempts, symlink and directory refusal");
}
'''
with tempfile.TemporaryDirectory(prefix='myron-journal-check-') as temp:
    p=Path(temp);(p/'journal.c').write_text(harness);(p/'store').mkdir()
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',
        '-I',str(here),str(p/'journal.c'),'-o',str(p/'check')],check=True)
    subprocess.run([str(p/'check'),str(p/'store')],check=True)
