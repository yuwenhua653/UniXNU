// SPDX-License-Identifier: BSD-2-Clause-Patent
/* One-shot adapter for the hash-pinned donor's absent optional HorizonSetup
 * boot task. No APFS, Foundation, reboot, signal or raw-disk APIs here. The
 * boot task requires success: failure of the separate helper must not become
 * a nonzero exit of this adapter. Never retry or kill an in-flight resize. */
#include <errno.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static void checkpoint(const char *stage,int status) {
    char line[160];int n=snprintf(line,sizeof(line),
        "[myron-data-earlyboot] stage=%s status=%d\n",stage,status);
    int fd=open("/dev/console",O_WRONLY|O_NOCTTY|O_NONBLOCK|O_CLOEXEC);
    if(fd>=0){if(n>0 && (size_t)n<sizeof(line))(void)write(fd,line,(size_t)n);(void)close(fd);}
}
static int growthRequested(const char *args) {
    unsigned found=0;
    for(const char *p=args;*p;){
        while(*p==' ' || *p=='\t')++p;
        const char *end=p;while(*end && *end!=' ' && *end!='\t')++end;
        if((size_t)(end-p)>=16 && !memcmp(p,"myron-data-grow=",16)){
            if(end-p!=18 || memcmp(p,"myron-data-grow=16",18))return 0;
            ++found;
        }
        p=end;
    }
    return found==1;
}
int main(int argc,char **argv) {
    (void)argv;checkpoint("entered",0);
    char executable[1024]={0},bootargs[2048]={0};uint32_t executableBytes=sizeof(executable);
    size_t bootargsBytes=sizeof(bootargs);
    if(argc!=1 || getppid()!=1 || geteuid()!=0 ||
       _NSGetExecutablePath(executable,&executableBytes) ||
       !memchr(executable,0,sizeof(executable)) || strcmp(executable,"/usr/libexec/HorizonSetup") ||
       sysctlbyname("kern.bootargs",bootargs,&bootargsBytes,NULL,0) ||
       !bootargsBytes || bootargsBytes>sizeof(bootargs) ||
       !memchr(bootargs,0,bootargsBytes) || !growthRequested(bootargs)){
        checkpoint("context-refused",0);return 0;
    }
    posix_spawn_file_actions_t actions;posix_spawnattr_t attributes;
    int rc=posix_spawn_file_actions_init(&actions);
    if(rc){checkpoint("actions-failed",rc);return 0;}
    rc=posix_spawnattr_init(&attributes);
    if(rc){(void)posix_spawn_file_actions_destroy(&actions);checkpoint("attributes-failed",rc);return 0;}
    /* Do not inherit launchd's panic/reboot spawn attributes into the child. */
    rc=posix_spawnattr_setflags(&attributes,POSIX_SPAWN_CLOEXEC_DEFAULT);
    if(!rc)rc=posix_spawn_file_actions_addopen(&actions,1,"/dev/console",O_WRONLY|O_NOCTTY,0);
    if(!rc)rc=posix_spawn_file_actions_addopen(&actions,2,"/dev/console",O_WRONLY|O_NOCTTY,0);
    pid_t child=0;
    char *args[]={"/private/var/ngpu/addons/myron-data-grow","--grow",NULL};
    if(!rc)rc=posix_spawn(&child,args[0],&actions,&attributes,args,environ);
    (void)posix_spawnattr_destroy(&attributes);(void)posix_spawn_file_actions_destroy(&actions);
    if(rc){checkpoint("spawn-failed",rc);return 0;}
    checkpoint("helper-started",(int)child);
    int status=0;pid_t waited;
    do {waited=waitpid(child,&status,0);} while(waited<0 && errno==EINTR);
    if(waited!=child)checkpoint("wait-failed",errno);
    else if(WIFEXITED(status))checkpoint("helper-exited",WEXITSTATUS(status));
    else if(WIFSIGNALED(status))checkpoint("helper-signalled",WTERMSIG(status));
    else checkpoint("helper-unknown",status);
    return 0;
}
