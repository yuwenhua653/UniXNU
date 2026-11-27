"""Restore only the pinned, hash-bound Metal addon path on existing myron Data."""
import hashlib,json,os
from pathlib import Path

def source(addon, contract_path):
    if os.environ.get('MYRON_GPU_NATIVE')!='1':
        return ('static void myron_gpu_addon_prepare(proc_t p){(void)p;}\n'
                'size_t myron_data_helper_snapshot(char *out,size_t cap){(void)out;(void)cap;return 0;}\n')
    # root_runtime already SHA-pins the complete upstream block before calling us.
    contract=json.loads(Path(contract_path).read_text());entry=contract['outputs']['gpuaddon.bin']
    text=addon[:addon.index('/* The deletable system apps')]
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('GPU addon source boundary changed: '+old[:80])
        text=text.replace(old,new)
    start=text.index('/* The OS cryptex where iPadOS looks for it.')
    text=text[:start]+Path(__file__).with_name('MyronGpuAddonPrepare.h').read_text()+'\n'
    replace('extern volatile int native_bindfs_boot_mount;',
        'extern volatile int native_bindfs_boot_mount;\n'
        'extern void myron_gpu_addon_available(void);\n'
        'const uint8_t myron_gpu_addon_contract[32]={'+','.join(str(x) for x in bytes.fromhex(entry['sha256']))+'};')
    replace('if (bytes < 24 || memcmp(addon, "NGPUADD2", 8)) {',
        'uint8_t digest[32]; SHA256_CTX hash;\n'
        f'\tif(bytes!=UINT64_C({entry["bytes"]})){{native_gpu_addon_error=EINVAL;return;}}\n'
        '\tSHA256_Init(&hash);SHA256_Update(&hash,addon,bytes);SHA256_Final(digest,&hash);\n'
        '\tif (memcmp(digest,myron_gpu_addon_contract,32) || bytes < 24 || memcmp(addon, "NGPUADD2", 8)) {')
    replace('if (total != bytes || !count || count > 4096) {',
        f'if (total != bytes || count != {len(contract["addon_files"])} || memcmp(addon+12,"\\0\\0\\0\\0",4)) {{')
    replace('size_t bytes = (size_t)items * size + 16;',
        'if (size && (size_t)items > (SIZE_MAX-16)/size) return Z_NULL;\n\tsize_t bytes = (size_t)items * size + 16;')
    replace('uint8_t *block = (uint8_t *)address - 16;',
        'if (!address) return;\n\tuint8_t *block = (uint8_t *)address - 16;')
    # The complete pinned series already creates ngpu itself. Preserve that fix.
    if 'sizeof("/private/var/ngpu") - 1' not in text:raise ValueError('Missing upstream ngpu parent fix')
    replace('int equal = native_gpu_addon_equal(vp, data, size, mode, ctx);',
        'int equal = vnode_vtype(vp)==VREG && native_gpu_addon_equal(vp, data, size, mode, ctx);')
    start=text.index('static int\nnative_gpu_addon_write(')
    end=text.index('/* Creates the missing parent directories',start)
    text=text[:start]+Path(__file__).with_name('MyronGpuAddonWrite.h').read_text()+'\n'+text[end:]
    # The new writer keeps the old final file until a complete fsynced/read-back
    # temporary file can be renamed. Failed installation never mounts a mixed tree.
    text=text.replace('native_gpu_addon_write(path, data, size, mode, ctx)',
                      'native_gpu_addon_write(p, scratch, path, data, size, mode, ctx)')
    replace('\t\t\tnative_gpu_addon_error = error;\n\t\t} else {',
        '\t\t\tnative_gpu_addon_error = error;\n\t\t\tbreak;\n\t\t} else {')
    replace("\t\tparent[i] = '/';\n\t\tif (error && error != EEXIST) {",
        "\t\tif (!error || error==EEXIST) {\n"
        "\t\t\tvnode_t dir=NULLVP;error=vnode_lookup(parent,VNODE_LOOKUP_NOFOLLOW,&dir,vfs_context_current());\n"
        "\t\t\tif(!error){if(vnode_vtype(dir)!=VDIR)error=EINVAL;vnode_put(dir);}\n\t\t}\n"
        "\t\tparent[i] = '/';\n\t\tif (error) {")
    old='\t\t\terror = native_gpu_addon_write(p, scratch, path, data, size, mode, ctx);\n'
    old+='\t\t\tif (error == ENOENT && !(error = native_gpu_addon_parents(p, scratch, path))) {\n'
    old+='\t\t\t\terror = native_gpu_addon_write(p, scratch, path, data, size, mode, ctx);\n\t\t\t}'
    replace(old,'\t\t\terror=native_gpu_addon_parents(p,scratch,path);\n'
        '\t\t\tif(!error)error=native_gpu_addon_write(p,scratch,path,data,size,mode,ctx);')
    replace('extern int native_ram_block_gpu_addon(const uint8_t **, uint64_t *) __attribute__((weak_import));',
        'extern int native_ram_block_gpu_addon(const uint8_t **, uint64_t *);')
    replace('if (!native_ram_block_gpu_addon || !native_ram_block_gpu_addon(&addon, &bytes)) {',
        'if (!native_ram_block_gpu_addon(&addon, &bytes)) {')
    return text
