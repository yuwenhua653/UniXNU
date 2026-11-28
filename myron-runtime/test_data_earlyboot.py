#!/usr/bin/env python3
"""Compile the actual adapter; substitute process/sysctl calls, never spawn APFS."""
from pathlib import Path
import subprocess,tempfile
source=Path(__file__).with_name('myron-data-earlyboot.c').read_text()
prefix=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#ifndef POSIX_SPAWN_CLOEXEC_DEFAULT
#define POSIX_SPAWN_CLOEXEC_DEFAULT 0x4000
#endif
static int fault,spawns,waits,actions,attributes,opens,exits;
static const char *bootargs="serial=3 myron-data-grow=16 log=1";
static char last[180];
static int fakeOpen(const char *path,int flags){assert(!strcmp(path,"/dev/console")&&(flags&O_NONBLOCK));return 33;}
static ssize_t fakeWrite(int fd,const void *data,size_t n){assert(fd==33&&n<sizeof(last));memcpy(last,data,n);last[n]=0;return (ssize_t)n;}
static int fakeClose(int fd){assert(fd==33);return 0;}
static pid_t fakeParent(void){return fault==1?2:1;}
static uid_t fakeUID(void){return fault==2?501:0;}
static int fakePath(char *path,uint32_t *n){assert(*n==1024);strcpy(path,fault==3?"/tmp/HorizonSetup":"/usr/libexec/HorizonSetup");return fault==4;}
static int fakeSysctl(const char *name,void *out,size_t *n,void *input,size_t inputn){
 assert(!strcmp(name,"kern.bootargs")&&!input&&!inputn&&*n==2048);
 if(fault==5)return -1;
 if(fault==6){memset(out,'x',*n);return 0;}
 strcpy(out,bootargs);*n=fault==7?2049:strlen(bootargs)+1;return 0;
}
static int fakeActionsInit(posix_spawn_file_actions_t *a){(void)a;if(fault==8)return ENOMEM;actions++;return 0;}
static int fakeAttrInit(posix_spawnattr_t *a){(void)a;if(fault==9)return ENOMEM;attributes++;return 0;}
static int fakeFlags(posix_spawnattr_t *a,short flags){(void)a;assert(flags==POSIX_SPAWN_CLOEXEC_DEFAULT);return fault==10?EINVAL:0;}
static int fakeAddOpen(posix_spawn_file_actions_t *a,int fd,const char *p,int f,mode_t m){
 (void)a;opens++;assert(fd==opens&&!strcmp(p,"/dev/console")&&f==(O_WRONLY|O_NOCTTY)&&m==0);return fault==10+opens?EACCES:0;
}
static int fakeActionsDestroy(posix_spawn_file_actions_t *a){(void)a;assert(actions==1);actions--;return 0;}
static int fakeAttrDestroy(posix_spawnattr_t *a){(void)a;assert(attributes==1);attributes--;return 0;}
static int fakeSpawn(pid_t *pid,const char *path,const posix_spawn_file_actions_t *a,const posix_spawnattr_t *b,char *const argv[],char *const env[]){
 (void)a;(void)b;assert(actions&&attributes&&opens==2&&!spawns);
 assert(!strcmp(path,"/private/var/ngpu/addons/myron-data-grow")&&!strcmp(argv[0],path)&&!strcmp(argv[1],"--grow")&&!argv[2]&&env);
 ++spawns;*pid=123;return fault==13?ENOEXEC:0;
}
static pid_t fakeWait(pid_t pid,int *status,int flags){
 assert(pid==123&&!flags&&spawns==1);waits++;
 if(fault==14){errno=ECHILD;return -1;}
 if(fault==15&&waits==1){errno=EINTR;return -1;}
 *status=fault==16?SIGSEGV:exits<<8;return pid;
}
#define open fakeOpen
#define write fakeWrite
#define close fakeClose
#define getppid fakeParent
#define geteuid fakeUID
#define _NSGetExecutablePath fakePath
#define sysctlbyname fakeSysctl
#define posix_spawn_file_actions_init fakeActionsInit
#define posix_spawnattr_init fakeAttrInit
#define posix_spawnattr_setflags fakeFlags
#define posix_spawn_file_actions_addopen fakeAddOpen
#define posix_spawn_file_actions_destroy fakeActionsDestroy
#define posix_spawnattr_destroy fakeAttrDestroy
#define posix_spawn fakeSpawn
#define waitpid fakeWait
#define main adapterMain
'''
suffix=r'''
#undef main
static void run(int argc){spawns=waits=actions=attributes=opens=0;assert(adapterMain(argc,NULL)==0);assert(!actions&&!attributes);}
int main(void){
 unsigned cases=0;
 for(fault=0;fault<=16;++fault)for(exits=0;exits<=3;++exits){
  run(1);assert(spawns==(fault==0||fault>=13));
  assert(waits==(fault==15?2:(fault==0||fault>=14)?1:0));
  if(fault==0)assert(strstr(last,"helper-exited"));
  if(fault==16)assert(strstr(last,"helper-signalled"));++cases;
 }
 fault=0;run(2);assert(!spawns);++cases;
 const char *bad[]={"","myron-data-grow=1","myron-data-grow=160","myron-data-grow=16x",
  "xmyron-data-grow=16","myron-data-grow=16 myron-data-grow=16","myron-data-grow=16 myron-data-grow=0",
  "myron-data-grow=0 myron-data-grow=16"};
 for(unsigned i=0;i<sizeof bad/sizeof *bad;++i){bootargs=bad[i];run(1);assert(!spawns);++cases;}
 bootargs="\tmyron-data-grow=16\t";run(1);assert(spawns==1);++cases;
 printf("PASS: %u actual early-boot adapter cases; helper failure/signal never returns boot-task failure; no real child executed\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='myron-earlyboot-check-') as t:
    p=Path(t)
    for name in ('mach-o/dyld.h','sys/sysctl.h'):
        f=p/name;f.parent.mkdir(exist_ok=True);f.write_text('/* adapters supplied by the host peer */\n')
    (p/'test.c').write_text(prefix+source+suffix)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=undefined','-I',str(p),str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
