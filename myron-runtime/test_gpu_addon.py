#!/usr/bin/env python3
"""Compile/run real addon install and atomic-write functions with injected peers."""
import argparse,hashlib,json,os,subprocess,tempfile
from pathlib import Path
from gpu_addon import source
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
p=argparse.ArgumentParser();p.add_argument('--sidecars',type=Path,required=True);p.add_argument('--cc',default='cc');p.add_argument('--exec-source',type=Path,required=True);a=p.parse_args()
text=a.exec_source.read_text()
start=text.index('/* Boot-time read-only union views of owner-provided GPU addon content')
end=text.index('static int\nnative_owner_data_prepare',start)
addon=text[start:end]
assert hashlib.sha256(addon.encode()).hexdigest()=='ffe7c83e9bfc4a864a63ff5c062119c621f65c3c10f4bf5cee5326b0a7a7ab64'
os.environ['MYRON_GPU_NATIVE']='1'
real=source(addon,ROOT/'myron-gpu/metal-addon-contract.json')
assert 'weak_import' not in real and 'O_TRUNC' not in real
contract=json.loads((ROOT/'myron-gpu/metal-addon-contract.json').read_text())
prelude=r'''
#define _GNU_SOURCE
#define OPENSSL_SUPPRESS_DEPRECATED
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <openssl/sha.h>
#include <zlib.h>
#define __unused __attribute__((unused))
#define Z_WAITOK 1
#define Z_ZERO 2
typedef void *proc_t;typedef uintptr_t user_addr_t;typedef void *vfs_context_t;
static int allocations;
static void *kalloc_data(size_t n,int flags){void *p=malloc(n);assert(p);allocations++;if(flags&Z_ZERO)memset(p,0,n);return p;}
static void kfree_data(void *p,size_t n){(void)n;assert(p&&allocations>0);allocations--;free(p);}
static vfs_context_t vfs_context_current(void){return NULL;}
static uint8_t *payload;static uint64_t payload_size;static int present=1,calls,fail_at,equal_mode;
static int native_ram_block_gpu_addon(const uint8_t **p,uint64_t *n){*p=payload;*n=payload_size;return present;}
static int native_gpu_addon_parents(proc_t p,user_addr_t s,const char *path){(void)p;(void)s;assert(!strncmp(path,"/private/var/ngpu/addons/",24));return 0;}
'''
rows=[]
for name,r in sorted(contract['addon_files'].items()):
 rows.append('{'+json.dumps('/private/var/ngpu/'+name)+','+str(r['bytes'])+','+str(r['mode'])+',"'+r['sha256']+'"}')
prelude+='static const struct {const char *name;uint64_t size;uint32_t mode;const char *sha;} expected[]={'+','.join(rows)+'};\n'
prelude+=r'''
static int native_gpu_addon_write(proc_t p,user_addr_t scratch,const char *path,const uint8_t *data,uint64_t size,uint32_t mode,vfs_context_t ctx){
 (void)p;(void)scratch;(void)ctx;int i=calls++;assert(i<(int)(sizeof expected/sizeof expected[0])&&!strcmp(path,expected[i].name)&&size==expected[i].size&&mode==expected[i].mode);
 uint8_t hash[32];char text[65];SHA256(data,size,hash);for(unsigned j=0;j<32;j++)sprintf(text+2*j,"%02x",hash[j]);assert(!strcmp(text,expected[i].sha));
 return fail_at==calls?EIO:equal_mode?-1:0;
}
'''
# Keep actual inflater, counters and installer; VFS writer independently tested below.
part=real[real.index('/* The GPU addon of'):real.index('/* Discover an existing sealed')]
b=part.index('static int\nnative_gpu_addon_equal(');e=part.index('static void\nnative_gpu_addon_install(',b)
part=part[:b]+part[e:]
part=part.replace('extern int native_ram_block_gpu_addon(const uint8_t **, uint64_t *);','').replace('#include <libkern/zlib.h>','')
digest=bytes.fromhex(contract['outputs']['gpuaddon.bin']['sha256'])
prelude+='static const uint8_t myron_gpu_addon_contract[32]={'+','.join(map(str,digest))+'};\n'
main=r'''
static void reset(void){native_gpu_addon_files=-1;native_gpu_addon_written=native_gpu_addon_same=native_gpu_addon_failed=native_gpu_addon_error=calls=0;assert(!allocations);}
int main(int argc,char **argv){assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);payload_size=ftell(f);rewind(f);payload=malloc(payload_size);assert(payload&&fread(payload,1,payload_size,f)==payload_size);fclose(f);
 reset();native_gpu_addon_install(NULL,0);assert(calls==9&&native_gpu_addon_written==9&&!native_gpu_addon_error&&!allocations);
 equal_mode=1;reset();native_gpu_addon_install(NULL,0);assert(calls==9&&native_gpu_addon_same==9&&!native_gpu_addon_error&&!allocations);equal_mode=0;
 fail_at=2;reset();native_gpu_addon_install(NULL,0);assert(calls==2&&native_gpu_addon_failed==1&&native_gpu_addon_error==EIO&&!allocations);fail_at=0;
 for(unsigned at=0;at<96;at++){payload[at]^=1;reset();native_gpu_addon_install(NULL,0);assert(!calls&&native_gpu_addon_error==EINVAL&&!allocations);payload[at]^=1;}
 payload_size--;reset();native_gpu_addon_install(NULL,0);assert(!calls&&native_gpu_addon_error==EINVAL);payload_size++;
 present=0;reset();native_gpu_addon_install(NULL,0);assert(!calls&&native_gpu_addon_files==-1);free(payload);
 puts("PASS: real addon inflate/hash/file inventory, unchanged-file reuse, write failure, 96 corruptions, missing/truncated payload");return 0;}
'''
writer=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define rename mock_rename
#define unlink mock_unlink
#define NULLVP NULL
#define FREAD 1
#define FWRITE 2
#define O_NOFOLLOW 4
#define O_CREAT 8
#define O_EXCL 16
#define VREG 1
#define UIO_WRITE 1
#define UIO_SYSSPACE 1
#define IO_NOAUTH 1
#define IO_UNIT 2
#define MNT_WAIT 1
typedef void *proc_t;typedef uintptr_t user_addr_t;typedef void *vfs_context_t;
struct node{char bytes[32];int mode,size,exists;};typedef struct node *vnode_t;
static struct node final,temp;static int scenario,handles,renames,opens;
struct vnode_attr{unsigned va_mode;};
#define VATTR_INIT(p) memset(p,0,sizeof *(p))
#define VATTR_SET(p,k,v) ((p)->k=(v))
struct rename_args{user_addr_t from,to;};struct unlink_args{user_addr_t path;};
static int vnode_vtype(vnode_t p){(void)p;return VREG;}
static int vnode_open(const char *path,int flags,int mode,int x,vnode_t *out,vfs_context_t ctx){
 (void)x;(void)ctx;opens++;struct node *n=strstr(path,".myron-stage")?&temp:&final;
 if(scenario==1&&n==&final)return EACCES;
 if(scenario==2&&n==&temp)return EACCES;
 if(flags&O_CREAT){assert(flags&O_EXCL);if(n->exists)return EEXIST;*n=(struct node){.mode=mode,.exists=1};}
 else if(!n->exists)return ENOENT;
 if(scenario==7&&n==&temp&&flags== (FREAD|O_NOFOLLOW))return EIO;
 *out=n;handles++;return 0;
}
static int native_gpu_addon_equal(vnode_t n,const uint8_t *d,uint64_t size,uint32_t mode,vfs_context_t ctx){(void)ctx;return scenario!=8&&n->size==(int)size&&n->mode==(int)mode&&!memcmp(n->bytes,d,size);}
static int vnode_close(vnode_t n,int flags,vfs_context_t c){(void)n;(void)c;assert(handles>0);handles--;return scenario==6&&flags==FWRITE?EIO:0;}
static void *vfs_context_ucred(vfs_context_t c){return c;}static proc_t vfs_context_proc(vfs_context_t c){return c;}
static int vn_rdwr(int rw,vnode_t n,char *d,int len,int at,int seg,int flags,void *cred,int *resid,proc_t p){
 (void)at;(void)seg;(void)flags;(void)cred;(void)p;assert(rw==UIO_WRITE&&n==&temp&&len<32);
 memcpy(n->bytes,d,len);n->size=len;*resid=scenario==3?1:0;return 0;}
static int vnode_setattr(vnode_t n,struct vnode_attr *v,vfs_context_t c){(void)c;n->mode=v->va_mode;return scenario==4?EIO:0;}
static int VNOP_FSYNC(vnode_t n,int mode,vfs_context_t c){(void)n;(void)mode;(void)c;return scenario==5?EIO:0;}
static int copyout(const void *p,user_addr_t out,size_t n){if(scenario==9)return EFAULT;memcpy((void*)out,p,n);return 0;}
static int mock_rename(proc_t p,struct rename_args *r,int32_t *v){(void)p;(void)v;assert(strstr((char*)r->from,".myron-stage")&&!strstr((char*)r->to,".myron-stage"));if(scenario==10)return EIO;assert(temp.exists&&!handles);final=temp;temp.exists=0;renames++;return 0;}
static int mock_unlink(proc_t p,struct unlink_args *r,int32_t *v){(void)p;(void)v;assert(strstr((char*)r->path,".myron-stage"));temp.exists=0;return 0;}
'''+(HERE/'MyronGpuAddonWrite.h').read_text()+r'''
int main(void){uint8_t scratch[4096];const uint8_t data[]={1,2,3,4};
 for(scenario=0;scenario<=10;scenario++){
  final=(struct node){.bytes="old",.mode=0644,.size=3,.exists=1};temp=(struct node){0};handles=renames=opens=0;
  int error=native_gpu_addon_write(NULL,(user_addr_t)scratch,"/private/var/ngpu/addons/x",data,4,0755,NULL);
  assert(!handles);
  if(!scenario)assert(!error&&renames==1&&final.mode==0755&&!memcmp(final.bytes,data,4));
  else assert(error>0&&!renames&&final.size==3&&!memcmp(final.bytes,"old",3));
 }
 scenario=0;final=(struct node){.mode=0755,.size=4,.exists=1};memcpy(final.bytes,data,4);temp=(struct node){0};renames=opens=handles=0;
 assert(native_gpu_addon_write(NULL,(user_addr_t)scratch,"/private/var/ngpu/addons/x",data,4,0755,NULL)==-1&&opens==1&&!renames&&!handles);
 final.exists=0;temp.exists=1;assert(!native_gpu_addon_write(NULL,(user_addr_t)scratch,"/private/var/ngpu/addons/x",data,4,0755,NULL)&&renames==1&&!handles);
 puts("PASS: real atomic writer preserves final bytes through 10 faults, readback, stale temporary, unchanged-file reuse");return 0;}
'''
with tempfile.TemporaryDirectory() as directory:
 t=Path(directory)
 for name,code,libs,args in [('install',prelude+part+main,['-lz','-lcrypto'],[str(a.sidecars.resolve()/'gpuaddon.bin')]),('write',writer,[],[])]:
  c=t/(name+'.c');exe=t/name;c.write_text(code)
  subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=undefined',str(c),'-o',str(exe),*libs],check=True)
  subprocess.run([str(exe),*args],check=True,env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1'))
