"""Integrate bounded lossless kernel transport after the immutable overlays."""
from pathlib import Path
import shutil

def apply(device, replace):
    here=Path(__file__).resolve().parent.parent/'myron-gpu/transport'
    shutil.copyfile(here/'MyronPackedKernel.h',device/'loader/MyronPackedKernel.h')
    shutil.copyfile(here/'transport.py',device/'kernel_transport.py')
    replace(device/'loader/KernelStream.h','  *FileSize = (UINTN)Info->FileSize;',
        '  *FileSize = (UINTN)Info->FileSize;\n'
        '  Status = MkOpen (&File, FileSize);\n'
        '  if (EFI_ERROR (Status)) { goto Done; }')
    p=device/'prepare_loader.py'
    replace(p,"'#include \"KernelStream.h\"\\n#include \"Handoff.h\"'",
        "'#include \"MyronPackedKernel.h\"\\n#include \"KernelStream.h\"\\n#include \"Handoff.h\"'")
    replace(p,"headers = ['KernelStream.h', 'MyronMemory.h', 'Handoff.h', 'Handoff.S']",
        "headers = ['KernelStream.h', 'MyronMemory.h', 'Handoff.h', 'Handoff.S', 'MyronPackedKernel.h']")
    replace(device/'tests/kernel_stream_host.c','#include "KernelStream.h"',
        '#include "MyronPackedKernel.h"\n#include "KernelStream.h"')
    p=device/'build_payload.py'
    replace(p,"kernel, reference = a.kernel.read_bytes(), a.reference_adt.read_bytes()",
        "kernel, reference = a.kernel.read_bytes(), a.reference_adt.read_bytes()\n"
        "from kernel_transport import pack, unpack\n"
        "kernel_file=pack(kernel) if a.root_bundle and os.environ.get('MYRON_PACKED_KERNEL')=='1' else kernel\n"
        "assert unpack(kernel_file)==kernel")
    replace(p,'startup_probe=a.dyld_startup_probe)',
        'startup_probe=a.dyld_startup_probe,kernel_transport_bytes=len(kernel_file))')
    replace(p,"(dest / 'kernel.macho').write_bytes(kernel)","(dest / 'kernel.macho').write_bytes(kernel_file)")
    replace(p,'kernel_bytes=len(kernel), kernel_sha256=sha(kernel),',
        "kernel_bytes=len(kernel), kernel_sha256=sha(kernel),\n"
        "              kernel_transport_bytes=len(kernel_file), kernel_transport_sha256=sha(kernel_file),\n"
        "              kernel_transport='MYRKERN1' if kernel_file[:8]==b'MYRKERN1' else 'plain',")
    p=device/'boot_assets.py'
    replace(p,'def capacity(kernel, data_bytes, trust_bytes):','def capacity(kernel, data_bytes, trust_bytes, kernel_transport_bytes=None, addon_bytes=0):')
    replace(p,'    used=align(align(align(span,16384)+4096+MAX_ADT,4096)+align(data_bytes,4096)+trust_bytes,16384)',
        '    used=align(align(align(span,16384)+4096+MAX_ADT,4096)+align(data_bytes,4096)+trust_bytes,16384)\n'
        '    require(0<=addon_bytes<=64*1024*1024,"GPU addon outside loader bounds")\n'
        '    used=align(used+addon_bytes,16384)')
    replace(p,'    staged=kernel.stat().st_size+data_bytes+trust_bytes+MAX_ADT+4096',
        '    stored=kernel.stat().st_size if kernel_transport_bytes is None else kernel_transport_bytes\n'
        '    require(32<=stored<=128*1024*1024,"Kernel transport outside loader bounds")\n'
        '    staged=stored+data_bytes+trust_bytes+addon_bytes+MAX_ADT+4096')
    replace(p,'startup_probe=False):','startup_probe=False,kernel_transport_bytes=None):')
    replace(p,"budget=capacity(kernel,seed['transport_bytes'],len(trust))",
        "budget=capacity(kernel,seed['transport_bytes'],len(trust),kernel_transport_bytes)")
    # Physical files are always checked separately, while reports retain logical kernel identity.
    for name in ('build_root_firmware.py','package_root_image.py','tests/check_root_handoff.py'):
        space='' if name.startswith('tests/') else ' '
        replace(device/name,"'kernel.macho':"+space+"proof['kernel_sha256']",
            "'kernel.macho': proof.get('kernel_transport_sha256',proof['kernel_sha256'])")
    replace(device/'tests/check_boot_payload.py',"assert len(read('Payloads/kernel.macho'))==a.kernel.stat().st_size",
        "from kernel_transport import unpack\n"
        "assert unpack(read('Payloads/kernel.macho'))==a.kernel.read_bytes()\n"
        "assert hashlib.sha256(read('Payloads/kernel.macho')).hexdigest()==report['kernel_transport_sha256']")
    p=device/'tests/test_loader_boot.py'
    replace(p,'kernel_sha = hashlib.sha256(a.kernel.read_bytes()).hexdigest() if a.kernel else None',
        "sys.path.insert(0,str(Path(__file__).resolve().parents[1]))\n"
        "from kernel_transport import unpack\n"
        "kernel_raw=unpack(a.kernel.read_bytes()) if a.kernel else None\n"
        "kernel_sha = hashlib.sha256(kernel_raw).hexdigest() if kernel_raw else None")
    replace(p,"if a.relocate_host_window: environment['MYRON_TEST_RELOCATE_WINDOW']='1'",
        "if a.relocate_host_window: environment['MYRON_TEST_RELOCATE_WINDOW']='1'\n"
        "if kernel_raw is not None:\n"
        "    raw_path=a.out/'expected-kernel.raw';raw_path.write_bytes(kernel_raw)\n"
        "    environment['MYRON_EXPECTED_KERNEL']=str(raw_path.resolve())")
    replace(p,'kernel_sha256=kernel_sha, edk2_headers_pin=core_pin,',
        'kernel_sha256=kernel_sha, kernel_transport_sha256=hashlib.sha256(a.kernel.read_bytes()).hexdigest(), edk2_headers_pin=core_pin,')
    p=device/'tests/loader_boot_host.c'
    replace(p,'static FILE_MOCK root_file, kernel_file, tree_file, trust_file;',
        'static FILE_MOCK root_file, kernel_file, tree_file, trust_file, logical_kernel;')
    replace(p,'kernel_file.data+s->FileOffset','logical_kernel.data+s->FileOffset')
    replace(p,'assert(ParseKernelHeader(kernel_file.data,32+U32(kernel_file.data+20),kernel_file.size,&expected_kernel)==EFI_SUCCESS);',
        'const char *logical=getenv("MYRON_EXPECTED_KERNEL");assert(logical);load(&logical_kernel,logical);\n'
        ' assert(ParseKernelHeader(logical_kernel.data,32+U32(logical_kernel.data+20),logical_kernel.size,&expected_kernel)==EFI_SUCCESS);')
    replace(p,'assert(live==1&&owned&&max_read==65536);','assert(live==1&&owned&&max_read>0&&max_read<=65536);')
    replace(p,'free(kernel_file.data);','free(logical_kernel.data);free(kernel_file.data);')
    # Fileset member headers can occupy distinct LZ4 blocks. Bound metadata I/O
    # by the kernel extent instead of the old uncompressed 256 KiB assumption.
    replace(p,'assert(header_bytes>=32&&header_bytes<256*1024);',
        'assert(header_bytes>=32&&header_bytes<4*kernel_file.size);')
