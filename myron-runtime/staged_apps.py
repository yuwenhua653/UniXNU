"""Provision original system-app bundles into existing Data with a bounded plan.

The source is the authenticated, read-only OS volume covered by the Data mount.
Never fabricate LaunchServices registrations or replace the persistent seed.
"""
import hashlib
import json
from pathlib import Path
import re

BUDGET=384*1024*1024
RESERVE=384*1024*1024

def plan(source, output):
    import prepare_data_volume as volume
    rows=[]
    for path in sorted(Path(source).iterdir()):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',path.name) or not path.is_dir() or path.is_symlink():
            continue
        usage=volume.tree_usage(path,measure_xattrs=True)
        files=list(path.rglob('*'))
        if any(p.is_symlink() or (not p.is_file() and not p.is_dir()) for p in files):
            rows.append(dict(name=path.name,selected=False,reason='unsupported file kind'));continue
        rows.append(dict(name=path.name,allocation=usage['allocation_estimate'],selected=False))
    # Prefer small, useful stock apps; never spend all writable Data on bundles.
    priority=('Calculator','MobileNotes','MobileCal','MobileTimer','Weather','MobileMail','MobileSafari','Maps')
    def order(row):
        return (next((i for i,n in enumerate(priority) if n.lower() in row['name'].lower()),len(priority)),row.get('allocation',1<<62),row['name'])
    used=0
    for row in sorted(rows,key=order):
        size=row.get('allocation')
        if size is not None and used+size<=BUDGET:
            used+=size;row['selected']=True
    selected=sorted(r['name'] for r in rows if r['selected'])
    if not selected:raise ValueError('No original system app fits the bounded Data migration')
    result=dict(build='24A446',selected=selected,allocation_bytes=used,budget_bytes=BUDGET,
                reserve_bytes=RESERVE,inventory=rows,all_selected=len(selected)==len(rows),
                phone_installed=False)
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
    return result

def source(addon, plan_path):
    import plistlib
    import prepare_data_volume as volume
    # The caller has already checked the SHA-256 of this entire upstream block.
    start=addon.index('/* The deletable system apps')
    text=addon[start:]
    if not text.rstrip().endswith('}'):raise ValueError('Unexpected staged apps boundary')
    path=Path(plan_path)
    policy=json.loads(path.read_text()) if path.exists() else dict(selected=[],allocation_bytes=0,build='24A446')
    names=policy['selected']
    if policy['build']!='24A446' or any(not re.fullmatch(r'[A-Za-z0-9_.-]+',n) for n in names):
        raise ValueError('Invalid system app policy')
    digest=hashlib.sha256(json.dumps(names).encode()).hexdigest()[:16]
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Staged app source boundary changed: '+old[:60])
        text=text.replace(old,new)
    # The pinned helper predates upstream's unprefixed boot arguments. Match
    # the actual myron payload; otherwise the helper exits before copying.
    replace('PE_parse_boot_argn("sheng-staged-apps",',
            'PE_parse_boot_argn("staged-apps",')
    replace('"/private/var/db/.sheng-staged-apps"',json.dumps('/private/var/db/.myron-staged-24A446-'+digest))
    # Traverse only complete app trees selected against actual source sizes.
    allow=' || '.join('!strcmp(name,'+json.dumps(n)+')' for n in names) or '0'
    replace("\t\t\tpath[base] = '/';", "\t\t\tif (base == sizeof(\"/private/var/staged_system_apps\")-1 && !("+allow+")) continue;\n\t\t\tpath[base] = '/';")
    replace('\twhile (pending.count) {','\twhile (pending.count && !native_staged_apps_failed) {')
    replace('\tfor (int eof = 0; !error && !eof;) {','\tfor (int eof = 0; !error && !eof && !native_staged_apps_failed;) {')
    replace('\t\tint length = (int)chunk - resid;', '\t\tint length = (int)chunk - resid;\n'
        f'\t\tif (length < 0 || native_staged_apps_bytes + (uint64_t)length > UINT64_C({BUDGET})) {{ error=ENOSPC; break; }}')
    replace('\tconst uint32_t chunk = 1024 * 1024;',
        '\t/* Leave room for APFS transactions and user settings; no partial disk fill. */\n'
        '\tconst struct vfsstatfs *space = vfs_statfs(data_mount);\n'
        f'\tif (!space || space->f_bsize <= 0 || space->f_bavail <= 0 || (uint64_t)space->f_bavail < (UINT64_C({policy["allocation_bytes"]+RESERVE}) + space->f_bsize-1)/space->f_bsize) {{\n'
        '\t\tnative_staged_apps_fail(ENOSPC); native_staged_apps_stage=-3; vnode_put(vp); return;\n\t}\n'
        '\tconst uint32_t chunk = 1024 * 1024;')
    # Only remove the exact synthetic migration-complete record we created.
    # Preserve any userland-modified record, all SetupDone state and all keys.
    expected=plistlib.dumps(volume.desktop_preferences()['com.apple.migration'],fmt=plistlib.FMT_BINARY)
    helper='''static int
myron_apps_request_migration(proc_t p, user_addr_t scratch, vfs_context_t ctx)
{
    static const uint8_t expected[] = {'''+','.join(str(x) for x in expected)+'''};
    const char *path="/private/var/mobile/Library/Preferences/com.apple.migration.plist";
    vnode_t vp=NULLVP;
    int error=vnode_lookup(path,VNODE_LOOKUP_NOFOLLOW,&vp,ctx);
    if(error==ENOENT)return 0;
    if(error)return error;
    uint8_t bytes[sizeof(expected)+1]; int resid=0;
    if(vnode_vtype(vp)!=VREG){vnode_put(vp);return EINVAL;}
    error=vn_rdwr(UIO_READ,vp,(caddr_t)bytes,sizeof(bytes),0,UIO_SYSSPACE,IO_NOAUTH,
        vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
    vnode_put(vp);
    if(error)return error;
    if(resid!=1 || memcmp(bytes,expected,sizeof expected))return 0;
    struct unlink_args request={.path=scratch+0xa00};int32_t result=0;
    error=copyout(path,request.path,strlen(path)+1);
    return error?error:unlink(p,&request,&result);
}
'''
    replace('static void\nnative_staged_apps_prepare(',helper+'static void\nnative_staged_apps_prepare(')
    replace('\t\tif (!native_staged_apps_failed) {',
        '\t\tif (!native_staged_apps_failed) {\n'
        '\t\t\terror=myron_apps_request_migration(p,scratch,ctx);\n'
        '\t\t\tif(error)native_staged_apps_fail(error);\n\t\t}\n'
        '\t\tif (!native_staged_apps_failed) {')
    replace('\t\t\terror = vnode_close(marker, FWRITE, ctx);',
        '\t\t\terror = VNOP_FSYNC(marker, MNT_WAIT, ctx);\n'
        '\t\t\tint close_error=vnode_close(marker,FWRITE,ctx);\n\t\t\tif(!error)error=close_error;')
    # The upstream helper writes a path at +0xa00; never reuse SystemOS env scratch.
    text+='''
static void
myron_staged_apps_prepare(proc_t p, mount_t data_mount)
{
    mach_vm_address_t scratch=0;
    vm_map_t map=current_map();
    if(mach_vm_allocate_kernel(map,&scratch,4096,VM_MAP_KERNEL_FLAGS_ANYWHERE())!=KERN_SUCCESS){
        native_staged_apps_stage=-2;native_staged_apps_fail(ENOMEM);return;
    }
    native_staged_apps_prepare(p,(user_addr_t)scratch,data_mount);
    (void)mach_vm_deallocate(map,scratch,4096);
    printf("myron-apps: stage=%d files=%d MiB=%d failed=%d error=%d\\n",native_staged_apps_stage,
        native_staged_apps_files,native_staged_apps_mib,native_staged_apps_failed,native_staged_apps_error);
}
'''
    return text
