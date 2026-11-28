"""Bind one signed addon to the actual native/final kernel before packaging it."""
import hashlib,json,struct,tempfile
from pathlib import Path
from prepare_metal_sidecars import prepare,modules,ORIGINAL_MODULES,verify_owner_policy
from earlyboot_launch_policy import verify_kernel_policy
from audit_userspace_artifact import require,sha
from myron_continuous_contract import kernel_definitions

def final_contract(kernel,contract):
    raw=Path(kernel).read_bytes();symbols=kernel_definitions(raw)
    wanted={'_myron_gpu_addon_contract','_native_ram_block_gpu_addon','_myron_gpu_addon_available',
        '_myron_gpu_publish_metal','_myron_gpu_ready','_myron_metal_registered','__ZTV14AGXAccelerator'}
    require(wanted<=symbols.keys(),'Actual kernel missing GPU installer/publication bindings')
    va=symbols['_myron_gpu_addon_contract'];at=32;locations=[]
    for _ in range(struct.unpack_from('<I',raw,16)[0]):
        command,n=struct.unpack_from('<II',raw,at)
        require(n>=8 and at+n<=len(raw),'Final fileset command bounds')
        if command==0x19:
            base,span,offset,count=struct.unpack_from('<4Q',raw,at+24)
            if base<=va and va+32<=base+count:locations.append(offset+va-base)
        at+=n
    require(len(locations)==1,'GPU addon contract is not uniquely file backed')
    require(raw[locations[0]:locations[0]+32]==bytes.fromhex(contract['outputs']['gpuaddon.bin']['sha256']),
        'Final compiled addon identity differs')
    launch_policy=verify_kernel_policy(raw)
    return dict(kernel_sha256=sha(raw),earlyboot_launch_policy=launch_policy,symbols={n:hex(symbols[n]) for n in sorted(wanted)},
        addon_contract_offset=locations[0],compiled_addon_sha256=raw[locations[0]:locations[0]+32].hex())

def stage(archive,original,out,kernel,root_report):
    here=Path(__file__).resolve().parent
    contract=json.loads((here/'metal-addon-contract.json').read_text())
    native=json.loads(Path(root_report).read_text());gpu=native.get('gpu_build',{})
    require(gpu.get('native_objects_compiled') is True and gpu.get('accelerator_contract',{}).get('donor_checked') is True,
        'Metal sidecars require audited iPhone accelerator objects')
    require(native.get('gpu_accelerator_link') and native.get('gpu_firmware_link'),
        'Metal sidecars require linked accelerator and firmware audits')
    final=final_contract(kernel,contract)
    with tempfile.TemporaryDirectory(prefix='myron-metal-') as tmp:
        path=Path(tmp)/'original.trust';path.write_bytes(original)
        report=prepare(Path(archive),path,Path(out))
    for key in contract:require(report[key]==contract[key],'Metal component contract differs: '+key)
    trust=(Path(out)/'kernel.macho.trustcache').read_bytes()
    verify_owner_policy(trust,contract['owner_cdhashes'])
    require(modules(trust)[1:]==modules(original) and tuple(map(sha,modules(original)))==ORIGINAL_MODULES,
        'Original Apple trust modules changed')
    return dict(addon_bytes=report['outputs']['gpuaddon.bin']['bytes'],
        addon_sha256=report['outputs']['gpuaddon.bin']['sha256'],
        trust_sha256=sha(trust),component=report['component'],final_kernel=final,
        contract_sha256=sha((here/'metal-addon-contract.json').read_bytes()),
        original_modules_unchanged=True,data_seed_modified=False,runtime_installed=False,hardware_tested=False)
