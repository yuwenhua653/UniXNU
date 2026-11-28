// SPDX-License-Identifier: BSD-2-Clause-Patent
// Narrow iOS helper: discover the mounted Data store; never accept a disk path.
#import <Foundation/Foundation.h>
#include <TargetConditionals.h>
#include <mach/mach.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include "MyronAPFSTransaction.h"

// Public IOKit C ABI loaded dynamically: iPhone SDKs omit IOKitLib.h.
typedef mach_port_t IORef;
static CFMutableDictionaryRef (*bsdMatch)(mach_port_t,uint32_t,const char *);
static IORef (*service)(mach_port_t,CFDictionaryRef);
static kern_return_t (*parents)(IORef,const char *,IORef *);
static IORef (*next)(IORef);
static kern_return_t (*releaseIO)(IORef);
static boolean_t (*conforms)(IORef,const char *);
static CFTypeRef (*property)(IORef,CFStringRef,CFAllocatorRef,uint32_t);
static kern_return_t (*registryID)(IORef,uint64_t *);
static int (*resizeAPI)(const char *,uint64_t);
static int (*minimumAPI)(const char *,intptr_t *);
static int (*spaceAPI)(const char *,uint64_t *,uint64_t *);
typedef struct { int stage,status; } SnapshotContext;
static uint64_t number(IORef node,CFStringRef key) {
    CFTypeRef p=property(node,key,kCFAllocatorDefault,0);int64_t n=0;
    if(p){if(CFGetTypeID(p)==CFNumberGetTypeID())CFNumberGetValue(p,kCFNumberSInt64Type,&n);CFRelease(p);}
    return n>0?(uint64_t)n:0;
}
static NSString *string(IORef node,CFStringRef key) {
    CFTypeRef p=property(node,key,kCFAllocatorDefault,0);NSString *s=nil;
    if(p){if(CFGetTypeID(p)==CFStringGetTypeID())s=[(__bridge NSString *)p copy];CFRelease(p);}return s;
}
static IORef parent(IORef node) {
    IORef iterator=0;if(parents(node,"IOService",&iterator)!=KERN_SUCCESS)return 0;
    IORef first=next(iterator),second=next(iterator);releaseIO(iterator);
    if(second){releaseIO(second);if(first)releaseIO(first);return 0;}return first;
}
static int validBSD(NSString *name) {
    const char *p=name.UTF8String;if(!p || strncmp(p,"disk",4) || strlen(p)>24)return 0;
    p+=4;if(*p<'0'||*p>'9')return 0;while(*p>='0'&&*p<='9')++p;
    while(*p=='s'){++p;if(*p<'0'||*p>'9')return 0;while(*p>='0'&&*p<='9')++p;}return !*p;
}
static const char *attempt="/private/var/root/myron-apfs-grow.attempt";
static void event(void *ctx,const char *stage) {
    (void)ctx;
    char line[192];int n=snprintf(line,sizeof(line),"[myron-apfs-grow] pid=%d stage=%s\n",getpid(),stage);
    int fd=open("/dev/console",O_WRONLY|O_NOCTTY|O_NONBLOCK|O_CLOEXEC);
    if(fd>=0){if(n>0 && (size_t)n<sizeof(line))(void)write(fd,line,(size_t)n);close(fd);}
}
static int bytes(uint64_t blocks,uint64_t unit,uint64_t *out) {
    if(!unit || blocks>UINT64_MAX/unit)return 0;
    *out=blocks*unit;return 1;
}
static int copyName(char *dest,size_t cap,NSString *value) {
    if(!value.length || !value.UTF8String || strlen(value.UTF8String)>=cap)return 0;
    memcpy(dest,value.UTF8String,strlen(value.UTF8String)+1);return 1;
}
/* Every observation rediscovers the chain from the current Data mount. The
 * bootstrap NX copy supplies only a checksummed container identity, never live
 * capacity. 24A446 APFSContainerGetSpaceInfo accepts synthesized media, while
 * Resize/Minimum also permit physical stores; use the synthesized identity for
 * all three, after verifying its unique physical NativeRamBlock ancestry. */
static int snapshot(void *ctx,MyronGrowSnapshot *s) {
    SnapshotContext *observation=ctx;observation->stage=1;observation->status=1;
    memset(s,0,sizeof(*s));
    struct statfs fs={0};
    if(statfs("/private/var",&fs) || strcmp(fs.f_fstypename,"apfs") ||
       (fs.f_flags&MNT_RDONLY) ||
       (strcmp(fs.f_mntonname,"/private/var") && strcmp(fs.f_mntonname,"/System/Volumes/Data")) ||
       strncmp(fs.f_mntfromname,"/dev/",5) ||
       !bytes(fs.f_blocks,fs.f_bsize,&s->volumeBytes) ||
       !bytes(fs.f_bavail,fs.f_bsize,&s->freeBytes))return 1;
    memcpy(s->fsid,&fs.f_fsid,sizeof(s->fsid));
    observation->stage=2;
    NSString *vol=[NSString stringWithUTF8String:fs.f_mntfromname+5];
    if(!validBSD(vol) || !copyName(s->volume,sizeof(s->volume),vol))return 1;
    IORef node=service(MACH_PORT_NULL,bsdMatch(MACH_PORT_NULL,0,s->volume));
    if(!node)return 1;
    NSString *uuid=string(node,CFSTR("UUID"));
    if(!conforms(node,"AppleAPFSVolume") || registryID(node,&s->volumeID) ||
       ![[NSUUID alloc] initWithUUIDString:uuid] || !copyName(s->volumeUUID,sizeof(s->volumeUUID),uuid)){
        releaseIO(node);return 1;
    }
    const char *classes[]={"AppleAPFSContainer","AppleAPFSMedia","AppleAPFSContainerScheme","IOMedia"};
    for(unsigned i=0;i<4;++i){
        observation->stage=3+(int)i;
        IORef up=parent(node);releaseIO(node);node=up;
        if(!node || !conforms(node,classes[i])){if(node)releaseIO(node);return 1;}
        if(i==1){
            NSString *media=string(node,CFSTR("BSD Name"));
            if(registryID(node,&s->mediaID) || !validBSD(media) || !copyName(s->media,sizeof(s->media),media)){
                releaseIO(node);return 1;
            }
        }
    }
    NSString *physical=string(node,CFSTR("BSD Name"));s->physical=number(node,CFSTR("Size"));
    observation->stage=7;
    if(registryID(node,&s->storeID) || !validBSD(physical) || !copyName(s->store,sizeof(s->store),physical)){
        releaseIO(node);return 1;
    }
    BOOL found=NO;
    observation->stage=8;
    for(unsigned i=0;node && i<8;++i){
        if(conforms(node,"NativeRamBlock")){
            found=registryID(node,&s->providerID)==KERN_SUCCESS;
            s->authorized=number(node,CFSTR("myron-data-grown-bytes"));releaseIO(node);node=0;break;
        }
        IORef up=parent(node);releaseIO(node);node=up;
    }
    if(node)releaseIO(node);
    if(!found)return 1;
    NSString *raw=[@"/dev/r" stringByAppendingString:physical];
    observation->stage=9;
    int fd=open(raw.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0)return 1;
    unsigned char nx[4096];uint64_t bootstrap=0,blocks=0;uint32_t sector=0;struct stat st={0};
    int ok=!fstat(fd,&st) && S_ISCHR(st.st_mode) &&
        !ioctl(fd,_IOR('d',24,uint32_t),&sector) && !ioctl(fd,_IOR('d',25,uint64_t),&blocks) &&
        sector && blocks<=UINT64_MAX/sector && blocks*sector==s->physical &&
        pread(fd,nx,sizeof(nx),0)==(ssize_t)sizeof(nx) && myronAPFSNX(nx,sizeof(nx),&bootstrap) &&
        bootstrap>=UINT64_C(1073741824) && bootstrap<=s->physical;
    close(fd);if(!ok)return 1;
    s->rawDevice=(uint64_t)st.st_rdev;memcpy(s->nxUUID,nx+72,sizeof(s->nxUUID));
    /* This API's physical-store fallback is DISABLED in the exact donor. */
    observation->stage=10;
    observation->status=spaceAPI(s->media,&s->container,&s->containerFree);
    return observation->status;
}
static int prior(void *ctx) {
    (void)ctx;struct stat st;return lstat(attempt,&st)==0 || errno!=ENOENT;
}
static int minimum(void *ctx,const MyronGrowSnapshot *s,uint64_t *size) {
    (void)ctx;intptr_t limit=0;int rc=minimumAPI(s->media,&limit);
    *size=limit>0?(uint64_t)limit:0;return rc;
}
static int journal(void *ctx,const MyronGrowSnapshot *s) {
    (void)ctx;
    int directory=open("/private/var/root",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0)return 1;
    int fd=openat(directory,"myron-apfs-grow.attempt",O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0){close(directory);return 1;}
    char intent[384],check[384];int n=snprintf(intent,sizeof(intent),
        "myron-apfs-grow-v2 target=%llu volume=%s media=%s store=%s uuid=%s\n",
        (unsigned long long)s->physical,s->volume,s->media,s->store,s->volumeUUID);
    int ok=n>0 && (size_t)n<sizeof(intent) && write(fd,intent,(size_t)n)==n && !fsync(fd) &&
        pread(fd,check,(size_t)n,0)==n && !memcmp(check,intent,(size_t)n) && !fsync(directory);
    if(close(fd))ok=0;
    if(close(directory))ok=0;
    return !ok;
}
static int resize(void *ctx,const MyronGrowSnapshot *s) {
    (void)ctx;return resizeAPI(s->media,s->physical);
}
static int fail(NSMutableDictionary *r,NSString *reason) {
    r[@"status"]=@"refused";r[@"reason"]=reason;return 2;
}
static int run(BOOL requested,NSMutableDictionary *r) {
#if TARGET_OS_OSX || TARGET_OS_SIMULATOR
    (void)requested;return fail(r,@"iOS physical-device execution only");
#else
    if(geteuid()!=0)return fail(r,@"root required");
    void *io=dlopen("/System/Library/Frameworks/IOKit.framework/IOKit",RTLD_NOW|RTLD_LOCAL);
    if(!io)return fail(r,@"IOKit unavailable");
#define LOAD(field,name) field=dlsym(io,name);if(!field)return fail(r,@name " unavailable")
    LOAD(bsdMatch,"IOBSDNameMatching");LOAD(service,"IOServiceGetMatchingService");
    LOAD(parents,"IORegistryEntryGetParentIterator");LOAD(next,"IOIteratorNext");
    LOAD(releaseIO,"IOObjectRelease");LOAD(conforms,"IOObjectConformsTo");LOAD(property,"IORegistryEntryCreateCFProperty");
    LOAD(registryID,"IORegistryEntryGetRegistryEntryID");
#undef LOAD
    void *apfs=dlopen("/System/Library/PrivateFrameworks/APFS.framework/APFS",RTLD_NOW|RTLD_LOCAL);
    resizeAPI=apfs?dlsym(apfs,"APFSContainerResize"):NULL;
    minimumAPI=apfs?dlsym(apfs,"APFSContainerGetMinimalSize"):NULL;
    spaceAPI=apfs?dlsym(apfs,"APFSContainerGetSpaceInfo"):NULL;
    r[@"resize_api_available"]=@(resizeAPI && minimumAPI && spaceAPI);
    if(!resizeAPI || !minimumAPI || !spaceAPI)return fail(r,@"APFS live-space or resize API unavailable");
    MyronGrowOps ops={snapshot,prior,minimum,journal,resize,event};MyronGrowResult result;
    SnapshotContext observation={0};
    int rc=myronGrowTransaction(&observation,&ops,requested,&result);
    r[@"observation_stage"]=@(observation.stage);r[@"observation_status"]=@(observation.status);
    r[@"status"]=[NSString stringWithUTF8String:result.status];
    if(result.reason)r[@"reason"]=[NSString stringWithUTF8String:result.reason];
    if(result.before.volume[0])r[@"volume"]=[NSString stringWithUTF8String:result.before.volume];
    if(result.before.media[0])r[@"container_media"]=[NSString stringWithUTF8String:result.before.media];
    if(result.before.store[0])r[@"physical_store"]=[NSString stringWithUTF8String:result.before.store];
    if(result.before.volumeUUID[0])r[@"volume_uuid"]=[NSString stringWithUTF8String:result.before.volumeUUID];
    r[@"physical_bytes"]=@(result.before.physical);r[@"authorized_bytes"]=@(result.before.authorized);
    r[@"container_bytes_before"]=@(result.before.container);r[@"free_bytes_before"]=@(result.before.freeBytes);
    r[@"decision"]=@(result.decision);r[@"minimum_status"]=@(result.minimumStatus);
    r[@"minimum_bytes"]=@(result.minimumBytes);r[@"resize_called"]=@(result.resizeCalled!=0);
    if(result.resizeCalled){
        r[@"resize_status"]=@(result.resizeStatus);r[@"container_bytes_after"]=@(result.after.container);
        r[@"free_bytes_after"]=@(result.after.freeBytes);
    }
    return rc;
#endif
}
int main(int argc,char **argv) {
    @autoreleasepool {
        event(NULL,"started");
        BOOL grow=argc==2&&!strcmp(argv[1],"--grow");
        if(argc>2 || (argc==2 && !grow && strcmp(argv[1],"--inspect")))return 64;
        NSMutableDictionary *r=[@{@"format":@1,@"resize_called":@NO,@"changes_gpt":@NO} mutableCopy];
        int rc=run(grow,r);r[@"exit_status"]=@(rc);
        event(NULL,[r[@"status"] UTF8String]);
        NSData *json=[NSJSONSerialization dataWithJSONObject:r options:NSJSONWritingPrettyPrinted error:NULL];
        if(json){fwrite(json.bytes,1,json.length,stdout);fputc('\n',stdout);}
        return rc;
    }
}
