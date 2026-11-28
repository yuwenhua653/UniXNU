#!/usr/bin/env python3
"""Execute the real addon publication path with bounded VFS fault injection."""
from pathlib import Path
import subprocess,tempfile
source=Path(__file__).with_name('MyronGpuAddonPrepare.h').read_text()
source=source.replace('#include <sys/dirent.h>','')
# The allocation wrapper is unchanged and separately compiled by XNU CI.
source=source[:source.index('static void\nmyron_gpu_addon_prepare(proc_t p)')]
prelude=r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
#define FREAD 1
#define O_NOFOLLOW 2
#define VDIR 1
#define VLNK 2
#define MNT_RDONLY 1
#define Z_WAITOK 1
#define UIO_SYSSPACE 1
#define UIO_READ 1
#define VNODE_READDIR_EXTENDED 1
#define VNODE_LOOKUP_NOFOLLOW 1
#define NULLVP NULL
#ifndef CAST_USER_ADDR_T
#define CAST_USER_ADDR_T(p) ((user_addr_t)(uintptr_t)(p))
#endif
typedef void *proc_t;typedef void *vfs_context_t;
#if !defined(__APPLE__)
typedef uintptr_t user_addr_t;
#endif
struct node {int mount,kind;};typedef struct node *vnode_t;
struct direntry {uint64_t d_ino;uint16_t d_reclen;char d_name[64];};
struct io {void *buffer;uint64_t left;off_t offset;};typedef struct io *uio_t;
static struct node directory={1,VDIR},child={1,3};
static int fault,handles,allocations,scan,mountCalls,published,enabled;
static int native_gpu_addon_error,native_gpu_addon_failed,native_gpu_addon_files,native_gpu_addon_written,native_gpu_addon_same;
static int native_gpu_addon_stage,native_gpu_addon_status,native_gpu_addon2_stage,native_gpu_addon2_status;
static int native_gpu_addon3_stage,native_gpu_addon3_status;
static vfs_context_t vfs_context_current(void){return NULL;}
static int vnode_open(const char *path,int flags,int mode,int x,vnode_t *out,vfs_context_t ctx){
 (void)mode;(void)x;(void)ctx;assert(flags==(FREAD|O_NOFOLLOW));
 scan=!strcmp(path,"/System/Library/xpc")?3:!strcmp(path,"/System/Library/LaunchDaemons")?2:1;
 assert(scan!=1||!strcmp(path,"/System/Library/Extensions"));
 if((scan<3&&fault==scan+4)||(scan==3&&fault==19))return EACCES;*out=&directory;handles++;return 0;
}
static int vnode_close(vnode_t n,int flags,vfs_context_t c){(void)n;(void)flags;(void)c;handles--;return 0;}
static int vnode_vtype(vnode_t n){return n==&directory&&fault==7?VLNK:n->kind;}
static int vnode_mount(vnode_t n){return n->mount;}
static int vfs_flags(int m){(void)m;return fault==8?0:MNT_RDONLY;}
static void *kalloc_data(size_t n,int flags){(void)flags;if(fault==9)return NULL;allocations++;return calloc(1,n);}
static void kfree_data(void *p,size_t n){(void)n;free(p);allocations--;}
static uio_t uio_create(int n,off_t off,int space,int rw){(void)n;(void)space;(void)rw;if(fault==10)return NULL;uio_t u=calloc(1,sizeof *u);u->offset=off;allocations++;return u;}
static int uio_addiov(uio_t u,uintptr_t p,int n){u->buffer=(void*)p;u->left=n;return 0;}
static int vnode_readdir64(vnode_t n,uio_t u,int flags,int *eof,int *count,vfs_context_t c){
 (void)n;(void)flags;(void)c;*eof=1;*count=1;
 if(fault==11)return EIO;
 struct direntry *d=u->buffer;d->d_ino=1;d->d_reclen=sizeof *d;
 strcpy(d->d_name,scan==1?"AppleExisting.bundle":scan==3?"launchd.plist":"com.apple.existing.plist");
 if(fault==12)d->d_reclen=1;if(fault==13)memset(d->d_name,'x',sizeof *d - offsetof(struct direntry,d_name));
 if(fault==14)strcpy(d->d_name,".");
 u->left-=sizeof *d;u->offset+=sizeof *d;return 0;
}
static uint64_t uio_resid(uio_t u){return u->left;}
static off_t uio_offset(uio_t u){return u->offset;}
static void uio_free(uio_t u){free(u);allocations--;}
static int vnode_lookup(const char *p,int flags,vnode_t *out,vfs_context_t c){(void)p;(void)flags;(void)c;if(fault==15)return ENOENT;*out=&child;handles++;return 0;}
static void vnode_put(vnode_t n){(void)n;handles--;}
static int PE_parse_boot_argn(const char *name,void *out,int n){assert(!strcmp(name,"myron-gpu-metal")&&n==4);*(uint32_t*)out=enabled;return enabled!=0;}
static void native_gpu_addon_install(proc_t p,user_addr_t s){(void)p;(void)s;native_gpu_addon_files=fault==1?8:9;native_gpu_addon_error=fault==2?EIO:0;native_gpu_addon_failed=fault==3?1:0;native_gpu_addon_written=fault==4?8:9;}
static void myron_gpu_addon_available(void){published++;}
static void native_gpu_addon_mount(proc_t p,user_addr_t scratch,user_addr_t offset,const char *src,size_t sn,const char *point,size_t pn,const char *lower,const char *own,int *stage,int *status){
 (void)p;(void)scratch;mountCalls++;
 assert(sn==strlen(src)+1&&pn==strlen(point)+1&&!strncmp(lower,point,strlen(point)));
 if(mountCalls==1){assert(offset==0x400&&!strcmp(point,"/System/Library/Extensions"));assert(strstr(own,"NativeAdrenoMetal.bundle/Info.plist"));}
 else if(mountCalls==2){assert(offset==0x600);assert(!strcmp(src,"/private/var/ngpu/addons/myron-data-daemons"));assert(!strcmp(point,"/System/Library/LaunchDaemons"));assert(!strcmp(own,"/System/Library/LaunchDaemons/org.unixnu.myron.data-grow.plist"));}
 else{assert(mountCalls==3&&offset==0x800);assert(!strcmp(src,"/private/var/ngpu/addons/myron-data-xpc"));assert(!strcmp(point,"/System/Library/xpc"));assert(!strcmp(own,"/System/Library/xpc/launchd.plist"));}
 *status=fault==mountCalls+15?EIO:0;*stage=*status?2:5;
}
'''
main=r'''
int main(void){
 for(enabled=0;enabled<=2;enabled++)for(fault=0;fault<=19;fault++){
  handles=allocations=scan=mountCalls=published=0;
  native_gpu_addon_stage=native_gpu_addon2_stage=0;native_gpu_addon_status=native_gpu_addon2_status=-1;
  native_gpu_addon3_stage=0;native_gpu_addon3_status=-1;
  native_gpu_addon_prepare(NULL,0);assert(!handles&&!allocations);
  if(enabled!=1){assert(!mountCalls&&!published);continue;}
  if(!fault){assert(mountCalls==3&&published==1&&native_gpu_addon2_stage==5&&!native_gpu_addon2_status&&native_gpu_addon3_stage==5&&!native_gpu_addon3_status);continue;}
  if(fault==6){assert(mountCalls==1&&published==1&&native_gpu_addon2_status==EACCES);continue;}
  if(fault==16){assert(mountCalls==1&&!published&&native_gpu_addon_status==EIO);continue;}
  if(fault==17){assert(mountCalls==2&&published==1&&native_gpu_addon2_status==EIO);continue;}
  if(fault==18){assert(mountCalls==3&&published==1&&native_gpu_addon3_status==EIO);continue;}
  if(fault==19){assert(mountCalls==2&&published==1&&native_gpu_addon3_status==EACCES);continue;}
  assert(!mountCalls&&!published);
 }
 native_gpu_addon2_stage=5;native_gpu_addon2_status=0;
 char full[256];size_t length=myron_data_helper_snapshot(full,sizeof full);
 assert(length==strlen(full)&&strstr(full,"daemon_stage=5 daemon_status=0"));
 assert(!myron_data_helper_snapshot(NULL,256));
 for(size_t cap=0;cap<=sizeof full;cap++){
  char buffer[258];memset(buffer,0x5a,sizeof buffer);
  size_t n=myron_data_helper_snapshot(buffer+1,cap);
  assert(buffer[0]==0x5a&&buffer[cap+1]==0x5a);
  if(cap)assert(n<cap&&buffer[1+n]==0);else assert(!n&&buffer[1]==0x5a);
 }
 puts("PASS: actual helper/GPU/cache publication, sealed scan, 19 faults and bounded persistent snapshot");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)/'launch.c';p.write_text(prelude+source+main);binary=p.with_suffix('')
 subprocess.run(['cc','-std=c11','-D_DEFAULT_SOURCE','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=undefined',str(p),'-o',str(binary)],check=True)
 subprocess.run([str(binary)],check=True)
