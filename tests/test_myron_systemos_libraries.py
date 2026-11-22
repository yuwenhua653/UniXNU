"""Execute the production library mount helper against VFS failure cases."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device', type=Path, required=True)
parser.add_argument('--cc', nargs='+', default=['clang'])
args = parser.parse_args()
helper = (args.device / 'package/MyronSystemOSLibraries.h').read_text()
runtime = (args.device / 'root_runtime.py').read_text()
assert "'if (map_page_size < 0xa00" in runtime
assert runtime.index('int startup_error = myron_dyld_startup_prepare') < runtime.index('int libraries_error = myron_systemos_libraries_prepare')
assert 'if (libraries_error) panic(' in runtime
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define dev_t test_dev_t
#define user_addr_t test_user_addr_t
typedef int dev_t;
typedef int proc_t;
typedef uintptr_t user_addr_t;
#define EAUTH 80
#define EALREADY 37
#define NODEV -1
#define NULLVP NULL
#define MNT_RDONLY 1
#define MNT_UNION 32
#define CONFIG_UNION_MOUNTS 1
enum vtype { VDIR, VREG };
struct fsstat { const char *f_fstypename, *f_mntfromname; };
struct mounted { int flags; struct fsstat stat; };
typedef struct mounted *mount_t;
struct node { enum vtype type; mount_t mounted; };
typedef struct node *vnode_t;
struct vnode_attr { uint64_t va_fileid, va_data_size; int supported; };
#define VATTR_INIT(v) memset(v, 0, sizeof(*(v)))
#define VATTR_WANTED(v, field) ((void)(v))
#define VATTR_IS_SUPPORTED(v, field) ((v)->supported)
struct mount_args { user_addr_t type, path; int flags; user_addr_t data; };
static int view, fail_view;
static const char *const points[] = {"/usr/lib", "/System/Library/PrivateFrameworks"};
static const char *const dirs[] = {"/private/preboot/usr/lib", "/private/preboot/System/Library/PrivateFrameworks"};
static const char *const clients[] = {"/usr/lib/dyld", "/usr/libexec/pkd"};
static const char *const sources[] = {"/private/preboot/usr/lib/libobjc-trampolines.dylib",
 "/private/preboot/System/Library/PrivateFrameworks/PlugInKitDaemon.framework/PlugInKitDaemon"};
static const char *const targets[] = {"/usr/lib/libobjc-trampolines.dylib",
 "/System/Library/PrivateFrameworks/PlugInKitDaemon.framework/PlugInKitDaemon"};
static const unsigned sizes[] = {68176, 306400};
static int selected_fault;
#define fault (view == fail_view ? selected_fault : 0)
static int references, lookups, attrs, copies, mounts, volumes, auths;
static int native_bindfs_boot_mount;
static unsigned myron_dyld_startup_state;
static int myron_dyld_startup_status, native_owner_root_accepted, native_owner_cache_status;
static dev_t rootdev, native_owner_cache_mounted_device;
static struct mounted mounted;
static struct node root, loader, source, visible, other;
static vnode_t rootvnode;
static int vfs_context_current(void) { return 0; }
static enum vtype vnode_vtype(vnode_t v) { return v->type; }
static mount_t vnode_mount(vnode_t v) { return v->mounted; }
static struct fsstat *vfs_statfs(mount_t m) { return &m->stat; }
static int vfs_flags(mount_t m) { return m->flags; }
static void vnode_put(vnode_t v) { assert(v); assert(--references >= 0); }
static int native_verified_block_root_authorized(dev_t device) {
    if (auths == 4) {
        assert(!references && mounts == 1 && view == 0);
        view = 1;
        lookups = attrs = copies = volumes = auths = 0;
    }
    ++auths;
    assert(device == 11 || device == 22);
    return fault != 10 && !(fault == 40 && auths > 2);
}
static int myron_startup_volume(const char *path, dev_t device, int ro, enum vtype type) {
    ++volumes;
    if (volumes == 1) assert(!strcmp(path, points[view]) && device == 11 && type == VDIR);
    if (volumes == 2 || volumes == 5) assert(!strcmp(path, clients[view]) && device == 11 && type == VREG);
    if (volumes == 3) assert(!strcmp(path, dirs[view]) && device == 22 && type == VDIR);
    if (volumes == 4 || volumes == 6) assert(!strcmp(path, sources[view]) && device == 22 && type == VREG);
    assert(ro == 1 && (device == 11 || device == 22));
    assert(path[0] == '/' && (type == VDIR || type == VREG));
    return !((fault >= 11 && fault <= 14 && volumes == fault - 10) ||
             (fault == 38 && volumes == 5) || (fault == 39 && volumes == 6));
}
static int vnode_lookup(const char *path, int flags, vnode_t *out, int ctx) {
    (void)ctx;
    assert(flags == 0);
    ++lookups;
    if ((fault == 15 && lookups == 1) || (fault == 16 && lookups == 2) ||
        (fault == 24 && lookups == 3) || (fault == 33 && lookups == 4)) return 2;
    if (lookups == 1 || lookups == 4) {
        assert(!strcmp(path, clients[view]));
        *out = fault == 34 && lookups == 4 ? &other : &loader;
    } else if (lookups == 2) {
        assert(!strcmp(path, sources[view]));
        *out = &source;
    } else {
        assert(lookups == 3 && !strcmp(path, targets[view]));
        *out = &visible;
    }
    ++references;
    return 0;
}
static int vnode_getattr(vnode_t v, struct vnode_attr *a, int ctx) {
    (void)ctx;
    ++attrs;
    assert(v == (attrs == 1 ? &source : &visible));
    if ((fault == 17 && attrs == 1) || (fault == 29 && attrs == 2)) return 5;
    a->supported = !((fault == 18 && attrs == 1) || (fault == 30 && attrs == 2));
    a->va_fileid = (fault == 31 && attrs == 2) ? 456 : 123;
    a->va_data_size = ((fault == 19 && attrs == 1) || (fault == 32 && attrs == 2)) ? 123 : sizes[view];
    return 0;
}
static int copyout(const void *data, user_addr_t to, size_t length) {
    ++copies;
    if (fault >= 20 && fault <= 22 && copies == fault - 19) return 14;
    memcpy((void *)to, data, length);
    return 0;
}
static int mount(proc_t p, struct mount_args *request, int32_t *result) {
    (void)p; (void)result;
    ++mounts;
    assert(native_bindfs_boot_mount == 1);
    assert(request->flags == (MNT_RDONLY | MNT_UNION));
    assert(!strcmp((char *)request->type, "bindfs"));
    assert(!strcmp((char *)request->path, points[view]));
    assert(!strcmp((char *)request->data, dirs[view]));
    mounted.stat.f_mntfromname = dirs[view];
    if (fault == 23) return 5;
    if (fault == 25) visible.type = VDIR;
    if (fault == 26) mounted.stat.f_fstypename = "apfs";
    if (fault == 27) mounted.stat.f_mntfromname = "/private/var/usr/lib";
    if (fault == 28) mounted.flags = MNT_UNION;
    if (fault == 35) rootvnode = &other;
    if (fault == 36) rootdev = 99;
    if (fault == 37) native_owner_cache_mounted_device = 99;
    return 0;
}
/* PRODUCTION */
static void reset(int number) {
    view = 0; selected_fault = number;
    references = lookups = attrs = copies = mounts = volumes = auths = 0;
    mounted = (struct mounted){MNT_RDONLY | MNT_UNION, {"bindfs", "/private/preboot/usr/lib"}};
    root = (struct node){VDIR, &mounted};
    loader = source = visible = other = (struct node){VREG, &mounted};
    rootvnode = &root;
    rootdev = 11;
    native_owner_cache_mounted_device = 22;
    myron_dyld_startup_state = 2;
    myron_dyld_startup_status = native_owner_cache_status = native_bindfs_boot_mount = 0;
    native_owner_root_accepted = 1;
    myron_systemos_libraries_state = 0;
    myron_systemos_libraries_status = -1;
    switch(number) {
    case 1: myron_dyld_startup_state = 3; break;
    case 2: myron_dyld_startup_status = 5; break;
    case 3: native_bindfs_boot_mount = 1; break;
    case 4: rootvnode = NULLVP; break;
    case 5: rootdev = NODEV; break;
    case 6: native_owner_cache_mounted_device = NODEV; break;
    case 7: native_owner_cache_mounted_device = rootdev; break;
    case 8: native_owner_root_accepted = 0; break;
    case 9: native_owner_cache_status = 5; break;
    }
}
int main(void) {
    unsigned char scratch[4096];
    for (fail_view = 0; fail_view < 2; ++fail_view)
    for (int i = fail_view ? 10 : 0; i <= 40; ++i) {
        reset(i);
        memset(scratch, 0xa5, sizeof(scratch));
        int error = myron_systemos_libraries_prepare(1, (user_addr_t)scratch);
        assert((error == 0) == (i == 0));
        assert(references == 0 && mounts <= 2);
        assert(native_bindfs_boot_mount == (i == 3));
        assert(myron_systemos_libraries_status == error);
        if (!error) assert(view == 1 && mounts == 2);
        assert((myron_systemos_libraries_state == 3) == (i == 0));
        for (int j = 0; j < 0x800; ++j) assert(scratch[j] == 0xa5);
        int before = mounts;
        assert(myron_systemos_libraries_prepare(1, (user_addr_t)scratch) == EALREADY);
        assert(mounts == before);
    }
    fail_view = 0;
    reset(0);
    myron_dyld_startup_state = 0;
    assert(myron_systemos_libraries_prepare(1, (user_addr_t)scratch) == 0);
    assert(!mounts && !lookups && !myron_systemos_libraries_state);
    puts("PASS: original dyld and pkd, both authenticated SystemOS views, mount failures, retry and scratch isolation");
    return 0;
}
'''.replace('/* PRODUCTION */', helper)
# Production declares a volatile external variable supplied by upstream bindfs.
fixture = fixture.replace('static int native_bindfs_boot_mount;', 'volatile int native_bindfs_boot_mount;')
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    source = directory / 'systemos-libraries.c'
    binary = directory / 'systemos-libraries.exe'
    source.write_text(fixture)
    subprocess.run([*args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
