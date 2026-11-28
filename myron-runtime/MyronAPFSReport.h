// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
/* Best-effort bounded diagnostics, after the transaction has finished. This
 * never changes its outcome or permits another resize. Keep the directory
 * descriptor anchored; refuse links, shared files and non-owner files. */
static int myronAPFSReport(const void *data,size_t bytes) {
    if(!data || !bytes || bytes>4096)return 0;
    int directory=open("/private/var/root",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0)return 0;
    int fd=openat(directory,"myron-apfs-grow-v2.json",O_WRONLY|O_CREAT|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK,0600);
    if(fd<0){close(directory);return 0;}
    struct stat st={0};
    int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() && st.st_nlink==1 &&
        (st.st_mode&0777)==0600 && st.st_size>=0 && st.st_size<=4096 &&
        pwrite(fd,data,bytes,0)==(ssize_t)bytes && !ftruncate(fd,(off_t)bytes) && !fsync(fd);
    if(close(fd))ok=0;
    if(ok && fsync(directory))ok=0;
    if(close(directory))ok=0;
    return ok;
}
