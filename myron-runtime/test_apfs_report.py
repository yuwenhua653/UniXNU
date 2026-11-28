#!/usr/bin/env python3
"""Execute the real bounded report writer against disposable files only."""
from pathlib import Path
import subprocess,tempfile
source=Path(__file__).with_name('MyronAPFSReport.h').read_text().replace('#pragma once','')
with tempfile.TemporaryDirectory(prefix='myron-report-') as t:
    root=Path(t);source=source.replace('"/private/var/root"','"'+str(root/'data')+'"')
    (root/'data').mkdir()
    # Compile the actual writer. Syscall peers inject failures but otherwise
    # use real descriptors, file types, permissions and link counts.
    prelude=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static int fault,calls;
static int checkStat(int fd,struct stat *s){if(fault==1)return -1;int r=fstat(fd,s);if(fault==2)s->st_uid=geteuid()+1;return r;}
static ssize_t checkWrite(int fd,const void *p,size_t n,off_t at){if(fault==3)return -1;return pwrite(fd,p,fault==4?n-1:n,at);}
static int checkTruncate(int fd,off_t n){return fault==5?-1:ftruncate(fd,n);}
static int checkSync(int fd){calls++;return (fault==6&&calls==1)||(fault==7&&calls==2)?-1:fsync(fd);}
static int checkClose(int fd){int r=close(fd);return fault==8?-1:r;}
#define fstat checkStat
#define pwrite checkWrite
#define ftruncate checkTruncate
#define fsync checkSync
#define close checkClose
'''
    after=r'''
#undef close
int main(int argc,char **argv){assert(argc==2);assert(!chdir(argv[1]));
 const char *name="myron-apfs-grow-v2.json";
 assert(!myronAPFSReport(NULL,1)&&!myronAPFSReport("x",0)&&!myronAPFSReport("x",4097));
 for(fault=0;fault<=8;fault++){
  unlink(name);calls=0;assert(myronAPFSReport("{\"first\":true}",14)==!fault);
 }
 fault=0;unlink(name);assert(!mkfifo(name,0600));assert(!myronAPFSReport("{}",2));unlink(name);assert(myronAPFSReport("{\"first\":true}",14));
 assert(myronAPFSReport("{}",2));char buffer[32]={0};int fd=open(name,O_RDONLY);assert(fd>=0&&read(fd,buffer,sizeof buffer)==2&&!strcmp(buffer,"{}"));close(fd);
 unlink(name);fd=open("keep",O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0&&write(fd,"keep",4)==4);close(fd);
 assert(!symlink("keep",name));assert(!myronAPFSReport("{}",2));unlink(name);
 assert(!link("keep",name));assert(!myronAPFSReport("{}",2));unlink(name);
 assert(!mkdir(name,0700));assert(!myronAPFSReport("{}",2));assert(!rmdir(name));
 fd=open(name,O_CREAT|O_WRONLY,0644);assert(fd>=0);close(fd);assert(!myronAPFSReport("{}",2));unlink(name);
 fd=open("keep",O_RDONLY);assert(fd>=0&&read(fd,buffer,sizeof buffer)==4&&!memcmp(buffer,"keep",4));close(fd);
 puts("PASS: bounded real report I/O, 8 injected failures, shorter rewrite, invalid size, links, mode and directory refusal; no APFS called");
}
'''
    (root/'test.c').write_text(prelude+source+after)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined',root/'test.c','-o',root/'test'],check=True)
    subprocess.run([root/'test',root/'data'],check=True)
