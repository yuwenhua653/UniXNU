/* Discover an existing sealed directory entry, instead of assuming an iPad GPU
 * bundle name on the iPhone donor. Its lookup must survive the union mount. */
static int
myron_gpu_sealed_entry(char *path,size_t cap)
{
    vfs_context_t ctx=vfs_context_current();vnode_t dir=NULLVP;
    const char *base="/System/Library/Extensions";
    int error=vnode_open(base,FREAD|O_NOFOLLOW,0,0,&dir,ctx);if(error)return error;
    uint8_t *entries=kalloc_data(4096,Z_WAITOK);
    if(!entries){vnode_close(dir,FREAD,ctx);return ENOMEM;}
    if(vnode_vtype(dir)!=VDIR || !(vfs_flags(vnode_mount(dir))&MNT_RDONLY))error=EINVAL;
    off_t offset=0;int found=0;
    for(unsigned page=0;!error && !found && page<32;page++){
        uio_t uio=uio_create(1,offset,UIO_SYSSPACE,UIO_READ);if(!uio){error=ENOMEM;break;}
        error=uio_addiov(uio,CAST_USER_ADDR_T(entries),4096);
        int eof=0,count=0;if(!error)error=vnode_readdir64(dir,uio,VNODE_READDIR_EXTENDED,&eof,&count,ctx);
        uint64_t remaining=uio_resid(uio);off_t next=uio_offset(uio);uio_free(uio);
        if(error)break;
        if(remaining>4096){error=EINVAL;break;}
        uint32_t filled=4096-(uint32_t)remaining;
        for(uint32_t at=0;!found && at<filled;){
            size_t head=offsetof(struct direntry,d_name);
            if(filled-at<=head){error=EINVAL;break;}
            struct direntry *entry=(struct direntry *)(entries+at);uint32_t length=entry->d_reclen;
            if(length<=head || length>filled-at){error=EINVAL;break;}
            const char *name=entry->d_name;size_t n=strnlen(name,length-head);
            if(n==length-head){error=EINVAL;break;}
            at+=length;
            if(!entry->d_ino || !n || !strcmp(name,".") || !strcmp(name,"..") ||
               !strncmp(name,"NativeAdrenoMetal",17) || strchr(name,'/'))continue;
            if(snprintf(path,cap,"%s/%s",base,name)>=(int)cap)continue;
            vnode_t child=NULLVP;error=vnode_lookup(path,VNODE_LOOKUP_NOFOLLOW,&child,ctx);
            if(!error){
                found=(vnode_mount(child)==vnode_mount(dir) && vnode_vtype(child)!=VLNK);
                vnode_put(child);
            }
        }
        if(error || found || eof || !filled)break;
        if(next<=offset){error=EINVAL;break;}offset=next;
    }
    kfree_data(entries,4096);int close_error=vnode_close(dir,FREAD,ctx);
    return error?error:close_error?close_error:found?0:ENOENT;
}
static void
native_gpu_addon_prepare(proc_t p,user_addr_t scratch)
{
    uint32_t enabled=0;
    if(!PE_parse_boot_argn("myron-gpu-metal",&enabled,sizeof enabled) || enabled!=1)return;
    native_gpu_addon_install(p,scratch);
    if(native_gpu_addon_error || native_gpu_addon_failed || native_gpu_addon_files!=6 ||
       native_gpu_addon_written+native_gpu_addon_same!=native_gpu_addon_files){
        native_gpu_addon_status=native_gpu_addon_error?native_gpu_addon_error:EIO;return;
    }
    char lower[512];int error=myron_gpu_sealed_entry(lower,sizeof lower);
    if(error){native_gpu_addon_status=error;return;}
    static const char source[]="/private/var/ngpu/addons",point[]="/System/Library/Extensions";
    native_gpu_addon_mount(p,scratch,0x400,source,sizeof source,point,sizeof point,lower,
        "/System/Library/Extensions/NativeAdrenoMetal.bundle/Info.plist",
        &native_gpu_addon_stage,&native_gpu_addon_status);
    if(!native_gpu_addon_status && native_gpu_addon_stage==5)myron_gpu_addon_available();
}
static void
myron_gpu_addon_prepare(proc_t p)
{
    uint32_t enabled=0;
    if(!PE_parse_boot_argn("myron-gpu-metal",&enabled,sizeof enabled) || enabled!=1)return;
    mach_vm_address_t scratch=0;vm_map_t map=current_map();
    if(mach_vm_allocate_kernel(map,&scratch,4096,VM_MAP_KERNEL_FLAGS_ANYWHERE())!=KERN_SUCCESS){
        native_gpu_addon_status=ENOMEM;return;
    }
    native_gpu_addon_prepare(p,(user_addr_t)scratch);
    (void)mach_vm_deallocate(map,scratch,4096);
    printf("myron-gpu-addon: stage=%d status=%d files=%d written=%d same=%d failed=%d error=%d\n",
        native_gpu_addon_stage,native_gpu_addon_status,native_gpu_addon_files,native_gpu_addon_written,
        native_gpu_addon_same,native_gpu_addon_failed,native_gpu_addon_error);
}
