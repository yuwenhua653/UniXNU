/* Included by gpu_addon.py inside the pinned kern_exec.c Data support block. */
static int
native_gpu_addon_write(proc_t p, user_addr_t scratch, const char *path,
    const uint8_t *data, uint64_t size, uint32_t mode, vfs_context_t ctx)
{
    vnode_t vp=NULLVP;
    int error=vnode_open(path,FREAD|O_NOFOLLOW,0,0,&vp,ctx);
    if(!error){
        int equal=vnode_vtype(vp)==VREG && native_gpu_addon_equal(vp,data,size,mode,ctx);
        int close_error=vnode_close(vp,FREAD,ctx);
        if(close_error)return close_error;
        if(equal)return -1;
    }else if(error!=ENOENT)return error;
    char temporary[224];
    if(snprintf(temporary,sizeof temporary,"%s.myron-stage",path)>=(int)sizeof temporary)return ENAMETOOLONG;
    // Create a new inode; an interrupted prior temporary file is unlinked first.
    error=vnode_open(temporary,O_CREAT|O_EXCL|FWRITE|O_NOFOLLOW,mode,0,&vp,ctx);
    if(error==EEXIST){
        struct unlink_args request={.path=scratch+0xa00};int32_t result=0;
        error=copyout(temporary,request.path,strlen(temporary)+1);
        if(!error)error=unlink(p,&request,&result);
        if(!error)error=vnode_open(temporary,O_CREAT|O_EXCL|FWRITE|O_NOFOLLOW,mode,0,&vp,ctx);
    }
    if(error)return error;
    if(vnode_vtype(vp)!=VREG)error=EINVAL;
    int resid=0;
    if(!error)error=vn_rdwr(UIO_WRITE,vp,(caddr_t)(uintptr_t)data,(int)size,0,
        UIO_SYSSPACE,IO_NOAUTH|IO_UNIT,vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
    if(!error && resid)error=EIO;
    if(!error){struct vnode_attr va;VATTR_INIT(&va);VATTR_SET(&va,va_mode,mode);error=vnode_setattr(vp,&va,ctx);}
    if(!error)error=VNOP_FSYNC(vp,MNT_WAIT,ctx);
    int close_error=vnode_close(vp,FWRITE,ctx);if(!error)error=close_error;
    // Check bytes and mode through a new read handle before committing the name.
    if(!error){
        error=vnode_open(temporary,FREAD|O_NOFOLLOW,0,0,&vp,ctx);
        if(!error){
            if(vnode_vtype(vp)!=VREG || !native_gpu_addon_equal(vp,data,size,mode,ctx))error=EIO;
            close_error=vnode_close(vp,FREAD,ctx);if(!error)error=close_error;
        }
    }
    if(!error){
        struct rename_args request={.from=scratch+0xa00,.to=scratch+0xb00};int32_t result=0;
        error=copyout(temporary,request.from,strlen(temporary)+1);
        if(!error)error=copyout(path,request.to,strlen(path)+1);
        if(!error)error=rename(p,&request,&result);
    }
    if(error){
        struct unlink_args request={.path=scratch+0xa00};int32_t result=0;
        if(!copyout(temporary,request.path,strlen(temporary)+1))(void)unlink(p,&request,&result);
    }
    return error;
}
