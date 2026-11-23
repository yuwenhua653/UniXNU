/* Execute the generated migration request against a deterministic vnode peer. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
typedef void *test_proc_t;
typedef uintptr_t test_user_addr_t;
typedef void *test_vfs_context_t;
typedef void *test_vnode_t;
struct test_unlink_args {test_user_addr_t path;};
enum {VREG=1, VNODE_LOOKUP_NOFOLLOW=1, UIO_READ=0, UIO_SYSSPACE=0, IO_NOAUTH=0};
#define NULLVP ((test_vnode_t)0)
static unsigned char record[4096];
static size_t record_size;
static int lookup_error,read_error,unlink_error,type=VREG,puts_count,unlinks;
static int vnode_lookup(const char *path,int flags,test_vnode_t *vp,test_vfs_context_t ctx){
    (void)ctx;assert(flags==VNODE_LOOKUP_NOFOLLOW);
    assert(!strcmp(path,"/private/var/mobile/Library/Preferences/com.apple.migration.plist"));
    if(lookup_error)return lookup_error;
    *vp=record;return 0;
}
static int vnode_vtype(test_vnode_t vp){assert(vp==record);return type;}
static void vnode_put(test_vnode_t vp){assert(vp==record);++puts_count;}
static void *vfs_context_ucred(test_vfs_context_t ctx){return ctx;}
static void *vfs_context_proc(test_vfs_context_t ctx){return ctx;}
static int vn_rdwr(int op,test_vnode_t vp,char *out,size_t len,int off,int space,int flags,
                   void *cred,int *resid,void *proc){
    (void)space;(void)flags;(void)cred;(void)proc;
    assert(op==UIO_READ && vp==record && off==0);
    size_t n=record_size<len?record_size:len;memcpy(out,record,n);*resid=(int)(len-n);return read_error;
}
static int copyout(const char *src,test_user_addr_t dest,size_t bytes){memcpy((void *)dest,src,bytes);return 0;}
static int test_unlink(test_proc_t p,struct test_unlink_args *request,int32_t *result){
    (void)p;(void)result;
    assert(!strcmp((char *)request->path,"/private/var/mobile/Library/Preferences/com.apple.migration.plist"));
    ++unlinks;return unlink_error;
}
/* GENERATED_FUNCTION */
int main(void){
    unsigned char scratch[4096];
    const unsigned char expected[]={EXPECTED_BYTES};
    memcpy(record,expected,sizeof expected);record_size=sizeof expected;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==0 && unlinks==1 && puts_count==1);
    unlinks=0;record[0]^=1;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==0 && !unlinks);
    record[0]^=1;record_size--;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==0 && !unlinks);
    record_size=sizeof expected+1;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==0 && !unlinks);
    record_size=sizeof expected;read_error=EIO;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==EIO && !unlinks);
    read_error=0;lookup_error=ENOENT;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==0 && !unlinks);
    lookup_error=EACCES;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==EACCES && !unlinks);
    lookup_error=0;type=0;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==EINVAL && !unlinks);
    type=VREG;unlink_error=EROFS;
    assert(myron_apps_request_migration(0,(uintptr_t)scratch,0)==EROFS && unlinks==1);
    return 0;
}
