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
#include "MyronAPFSGrow.h"

// Public IOKit C ABI loaded dynamically: iPhone SDKs omit IOKitLib.h.
typedef mach_port_t IORef;
static CFMutableDictionaryRef (*bsdMatch)(mach_port_t,uint32_t,const char *);
static IORef (*service)(mach_port_t,CFDictionaryRef);
static kern_return_t (*parents)(IORef,const char *,IORef *);
static IORef (*next)(IORef);
static kern_return_t (*releaseIO)(IORef);
static boolean_t (*conforms)(IORef,const char *);
static CFTypeRef (*property)(IORef,CFStringRef,CFAllocatorRef,uint32_t);
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
static int fail(NSMutableDictionary *report,NSString *why) {
    report[@"status"]=@"refused";report[@"reason"]=why;return 2;
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
#undef LOAD
    struct statfs before={0};
    if(statfs("/private/var",&before) || strcmp(before.f_fstypename,"apfs") ||
       (strcmp(before.f_mntonname,"/private/var") && strcmp(before.f_mntonname,"/System/Volumes/Data")) ||
       strncmp(before.f_mntfromname,"/dev/",5))return fail(r,@"Data is not a separate mounted APFS volume");
    NSString *vol=[NSString stringWithUTF8String:before.f_mntfromname+5];
    if(!validBSD(vol))return fail(r,@"invalid Data BSD identity");
    IORef node=service(MACH_PORT_NULL,bsdMatch(MACH_PORT_NULL,0,vol.UTF8String));
    if(!node)return fail(r,@"Data IOMedia missing");
    NSString *uuid=string(node,CFSTR("UUID"));
    if(!conforms(node,"AppleAPFSVolume") || !uuid.length){releaseIO(node);return fail(r,@"Data volume class/UUID unavailable");}
    r[@"volume"]=vol;r[@"volume_uuid"]=uuid;
    // Apple bless's documented hierarchy, single-parent only: volume ->
    // container -> synthesized media -> container scheme -> physical store.
    const char *classes[]={"AppleAPFSContainer","IOMedia","AppleAPFSContainerScheme","IOMedia"};
    for(unsigned i=0;i<4;++i){IORef up=parent(node);releaseIO(node);node=up;
        if(!node || !conforms(node,classes[i])){if(node)releaseIO(node);return fail(r,@"unexpected APFS parent chain");}}
    NSString *physical=string(node,CFSTR("BSD Name"));uint64_t size=number(node,CFSTR("Size"));
    if(!validBSD(physical)){releaseIO(node);return fail(r,@"physical-store name unavailable");}
    r[@"physical_store"]=physical;r[@"physical_bytes"]=@(size);
    BOOL found=NO;uint64_t authorized=0;
    for(unsigned i=0;node && i<8;++i){
        if(conforms(node,"NativeRamBlock")){found=YES;authorized=number(node,CFSTR("myron-data-grown-bytes"));releaseIO(node);node=0;break;}
        IORef up=parent(node);releaseIO(node);node=up;
    }
    if(node)releaseIO(node);
    if(!found)return fail(r,@"physical store does not belong to NativeRamBlock");
    NSString *raw=[@"/dev/r" stringByAppendingString:physical];
    int fd=open(raw.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0)return fail(r,@"cannot inspect raw Data store");
    unsigned char nx[4096];uint64_t current=0,blocks=0;uint32_t sector=0;
    struct stat st={0};int ok=!fstat(fd,&st)&&S_ISCHR(st.st_mode)&&
        !ioctl(fd,_IOR('d',24,uint32_t),&sector)&&!ioctl(fd,_IOR('d',25,uint64_t),&blocks)&&
        sector && blocks<=UINT64_MAX/sector && blocks*sector==size &&
        pread(fd,nx,sizeof(nx),0)==(ssize_t)sizeof(nx) && myronAPFSNX(nx,sizeof(nx),&current);
    if(!ok){close(fd);return fail(r,@"Data geometry or APFS superblock check failed");}
    unsigned char identity[16];memcpy(identity,nx+72,16);
    r[@"container_bytes_before"]=@(current);r[@"authorized_bytes"]=@(authorized);
    r[@"free_bytes_before"]=@((uint64_t)before.f_bavail*before.f_bsize);
    void *apfs=dlopen("/System/Library/PrivateFrameworks/APFS.framework/APFS",RTLD_NOW|RTLD_LOCAL);
    int (*resize)(const char *,uint64_t)=apfs?dlsym(apfs,"APFSContainerResize"):NULL;
    int (*minimum)(const char *,intptr_t *)=apfs?dlsym(apfs,"APFSContainerGetMinimalSize"):NULL;
    r[@"resize_api_available"]=@(resize && minimum);
    const char *attempt="/private/var/root/myron-apfs-grow.attempt";
    int prior=lstat(attempt,&st)==0 || errno!=ENOENT;
    int decision=myronAPFSGrowthDecision(size,current,authorized,requested,resize&&minimum,prior);
    r[@"decision"]=@(decision);
    if(decision==MyronAPFSInspect || decision==MyronAPFSDone){close(fd);r[@"status"]=decision==MyronAPFSDone?@"already-expanded":@"inspected";return 0;}
    if(decision!=MyronAPFSGrow){close(fd);return fail(r,@"growth guards refused; no resize attempted");}
    intptr_t lower=0;int rc=minimum(physical.UTF8String,&lower);
    r[@"minimum_status"]=@(rc);r[@"minimum_bytes"]=@(lower);
    if(rc || lower<=0 || (uint64_t)lower>current){close(fd);return fail(r,@"APFS sizing API returned implausible limits");}
    // Record intent durably before the private mutation API; an unknown outcome
    // is never silently retried by launchd or a later boot.
    int journal=open(attempt,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(journal<0){close(fd);return fail(r,@"prior or unavailable operation journal");}
    const char intent[]="myron-apfs-grow-v1 target=17179869184\n";
    ok=write(journal,intent,sizeof(intent)-1)==(ssize_t)sizeof(intent)-1 && !fsync(journal);
    close(journal);int directory=open("/private/var/root",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0 || fsync(directory))ok=0;if(directory>=0)close(directory);
    if(!ok){close(fd);return fail(r,@"operation journal not durable");}
    rc=resize(physical.UTF8String,size);r[@"resize_status"]=@(rc);r[@"resize_called"]=@YES;
    struct statfs after={0};uint64_t actual=0;
    IORef volume=service(MACH_PORT_NULL,bsdMatch(MACH_PORT_NULL,0,vol.UTF8String));
    NSString *afterUUID=volume?string(volume,CFSTR("UUID")):nil;if(volume)releaseIO(volume);
    ok=!rc && !statfs("/private/var",&after) && !strcmp(before.f_mntfromname,after.f_mntfromname) &&
        [uuid isEqualToString:afterUUID] && pread(fd,nx,sizeof(nx),0)==(ssize_t)sizeof(nx) &&
        myronAPFSNX(nx,sizeof(nx),&actual) && actual==size && !memcmp(nx+72,identity,16) &&
        after.f_bsize && after.f_blocks<=UINT64_MAX/after.f_bsize &&
        (uint64_t)after.f_blocks*after.f_bsize>(UINT64_C(15)<<30) &&
        (uint64_t)after.f_blocks*after.f_bsize<=size && after.f_bavail>before.f_bavail;
    close(fd);r[@"container_bytes_after"]=@(actual);
    r[@"free_bytes_after"]=@((uint64_t)after.f_bavail*after.f_bsize);
    r[@"status"]=ok?@"expanded-and-verified":@"resize-outcome-unverified-no-auto-retry";
    return ok?0:3;
#endif
}
int main(int argc,char **argv) {
    @autoreleasepool {
        BOOL grow=argc==2&&!strcmp(argv[1],"--grow");
        if(argc>2 || (argc==2 && !grow && strcmp(argv[1],"--inspect")))return 64;
        NSMutableDictionary *r=[@{@"format":@1,@"resize_called":@NO,@"changes_gpt":@NO} mutableCopy];
        int rc=run(grow,r);r[@"exit_status"]=@(rc);
        NSData *json=[NSJSONSerialization dataWithJSONObject:r options:NSJSONWritingPrettyPrinted error:NULL];
        if(json){fwrite(json.bytes,1,json.length,stdout);fputc('\n',stdout);}
        return rc;
    }
}
