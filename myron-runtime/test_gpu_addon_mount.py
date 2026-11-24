#!/usr/bin/env python3
"""Exercise the real read-only union and readiness gate with failing VFS peers."""
from pathlib import Path
import os,subprocess,tempfile
HERE=Path(__file__).resolve().parent
patch=(HERE.parent/'patches/xnu/zzy-native-gpu-addon-mount.patch').read_text()
block='\n'.join(s[1:] for s in patch.splitlines() if s.startswith('+') and not s.startswith('+++'))
mount=block[block.index('static void\nnative_gpu_addon_mount('):block.index('/* The GPU addon of')]
source=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
// Darwin's SDK already declares user_addr_t (which is not uintptr_t on
// arm64). Only supply the missing type on non-Darwin hosts.
#if !defined(__APPLE__)
typedef uint64_t user_addr_t;
#endif
#ifndef CAST_USER_ADDR_T
#define CAST_USER_ADDR_T(p) ((user_addr_t)(uintptr_t)(p))
#endif
#define NULLVP NULL
#define FREAD 1
#define O_NOFOLLOW 2
#define VDIR 1
#define VLNK 2
#define MNT_RDONLY 1
#define MNT_UNION 2
#define Z_WAITOK 1
#define UIO_SYSSPACE 1
#define UIO_READ 1
#define VNODE_READDIR_EXTENDED 1
#define VNODE_LOOKUP_NOFOLLOW 1
#define KERN_SUCCESS 0
#define VM_MAP_KERNEL_FLAGS_ANYWHERE() 0
typedef void *proc_t;typedef void *vfs_context_t;typedef void *vm_map_t;typedef uintptr_t mach_vm_address_t;
struct node{int type,mount;};typedef struct node *vnode_t;
static struct node root={VDIR,1},child={VDIR,1};
struct direntry{uint64_t d_ino;uint16_t d_reclen;char d_name[40];};
struct io{void *data;uint64_t remain;off_t offset;};typedef struct io *uio_t;
struct mount_args{user_addr_t type,path;unsigned flags;user_addr_t data;};
static int scenario,refs,handles,pools,uios,mounts,published,livevm;
volatile int native_bindfs_boot_mount,native_gpu_addon_stage,native_gpu_addon_status;
volatile int native_gpu_addon_files,native_gpu_addon_written,native_gpu_addon_same,native_gpu_addon_failed,native_gpu_addon_error;
static vfs_context_t vfs_context_current(void){return NULL;}
static int vnode_open(const char *p,int flags,int mode,int x,vnode_t *out,vfs_context_t ctx){
 (void)mode;(void)x;(void)ctx;assert(!strcmp(p,"/System/Library/Extensions")&&flags==(FREAD|O_NOFOLLOW));
 if(scenario==3)return EIO;*out=&root;handles++;return 0;}
static int vnode_close(vnode_t n,int flags,vfs_context_t c){(void)n;(void)flags;(void)c;assert(handles);handles--;return 0;}
static int vnode_lookup(const char *p,int flags,vnode_t *out,vfs_context_t ctx){
 (void)flags;(void)ctx;
 if((scenario==4&&strstr(p,"/private/var/")) || (scenario==7&&mounts&&!strstr(p,"NativeAdrenoMetal")) || (scenario==8&&strstr(p,"NativeAdrenoMetal")))return ENOENT;
 *out=&child;refs++;return 0;}
static void vnode_put(vnode_t n){(void)n;assert(refs);refs--;}
static int vnode_vtype(vnode_t n){return n==&child&&scenario==14?VLNK:n->type;}
static int vnode_mount(vnode_t n){return n==&child&&scenario==15?2:n->mount;}
static unsigned vfs_flags(int m){assert(m==1);return scenario==11?0:MNT_RDONLY;}
static void *kalloc_data(size_t n,int flags){(void)flags;pools++;return calloc(1,n);}
static void kfree_data(void *p,size_t n){(void)n;assert(p&&pools);pools--;free(p);}
static uio_t uio_create(int count,off_t offset,int space,int rw){(void)space;(void)rw;assert(count==1);uios++;uio_t u=calloc(1,sizeof *u);u->offset=offset;return u;}
static int uio_addiov(uio_t u,uintptr_t data,size_t size){u->data=(void*)data;u->remain=size;return 0;}
static uint64_t uio_resid(uio_t u){return u->remain;}
static off_t uio_offset(uio_t u){return u->offset;}
static void uio_free(uio_t u){assert(uios);uios--;free(u);}
static int vnode_readdir64(vnode_t dir,uio_t u,int flags,int *eof,int *count,vfs_context_t ctx){
 (void)dir;(void)flags;(void)ctx;struct direntry *e=u->data;e->d_ino=1;e->d_reclen=sizeof *e;strcpy(e->d_name,"AGXActual.bundle");
 *eof=1;*count=1;u->remain=4096-sizeof *e;u->offset+=sizeof *e;
 if(scenario==12)e->d_reclen=0;if(scenario==13)u->remain=4097;return 0;}
static int copyout(const void *p,user_addr_t to,size_t n){if(scenario==5)return EFAULT;memcpy((void*)to,p,n);return 0;}
static int mount(proc_t p,struct mount_args *r,int32_t *result){(void)p;(void)result;
 assert(native_bindfs_boot_mount==1 && r->flags==(MNT_RDONLY|MNT_UNION)&&!strcmp((char*)r->type,"bindfs")&&
 !strcmp((char*)r->path,"/System/Library/Extensions")&&!strcmp((char*)r->data,"/private/var/ngpu/addons"));mounts++;return scenario==6?EPERM:0;}
static int PE_parse_boot_argn(const char *s,void *p,size_t n){assert(!strcmp(s,"myron-gpu-metal")&&n==4);*(uint32_t*)p=scenario?1:0;return 1;}
static void native_gpu_addon_install(proc_t p,user_addr_t scratch){(void)p;assert(scratch);native_gpu_addon_files=6;native_gpu_addon_written=scenario==2?5:6;native_gpu_addon_error=scenario==1?EIO:0;}
static void myron_gpu_addon_available(void){assert(native_gpu_addon_stage==5&&!native_gpu_addon_status&&!native_bindfs_boot_mount);published++;}
static vm_map_t current_map(void){return NULL;}
static int mach_vm_allocate_kernel(vm_map_t map,mach_vm_address_t *out,size_t n,int flags){(void)map;(void)flags;assert(n==4096);if(scenario==10)return 1;*out=(uintptr_t)calloc(1,n);livevm++;return 0;}
static int mach_vm_deallocate(vm_map_t map,mach_vm_address_t addr,size_t n){(void)map;assert(n==4096&&livevm);livevm--;free((void*)addr);return 0;}
'''+mount+(HERE/'MyronGpuAddonPrepare.h').read_text()+r'''
int main(void){
 for(scenario=0;scenario<=15;scenario++){
  native_bindfs_boot_mount=native_gpu_addon_stage=native_gpu_addon_status=0;
  native_gpu_addon_files=native_gpu_addon_written=native_gpu_addon_same=native_gpu_addon_failed=native_gpu_addon_error=0;
  refs=handles=pools=uios=mounts=published=livevm=0;myron_gpu_addon_prepare(NULL);
  assert(!refs&&!handles&&!pools&&!uios&&!native_bindfs_boot_mount&&!livevm);
  if(scenario==9)assert(published==1&&mounts==1);
  else {assert(!published);if(scenario)assert(native_gpu_addon_status);}
 }
 puts("PASS: real addon mount/readiness, 15 failure/disabled paths, sealed-entry discovery, read-only union and scratch cleanup");return 0;}
'''
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'host.c';exe=Path(tmp)/'host';path.write_text(source)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=undefined',str(path),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1'))
