"""Add the reviewed GPU addon installer to the original Data mount lifecycle."""
from pathlib import Path
import shutil

def apply(device,replace):
    here=Path(__file__).resolve().parent
    for name in ('gpu_addon.py','MyronGpuAddonWrite.h','MyronGpuAddonPrepare.h'):
        shutil.copyfile(here/name,device/name)
    shutil.copyfile(here.parent/'myron-gpu/metal-addon-contract.json',device/'metal-addon-contract.json')
    p=device/'root_runtime.py'
    replace(p,'import hashlib','import hashlib\nimport os')
    replace(p,"        replace(addon, staged_apps.source(addon,Path(__file__).with_name('myron-apps-plan.json')))",
        "        import gpu_addon\n"
        "        replace(addon, gpu_addon.source(addon,Path(__file__).with_name('metal-addon-contract.json'))+\n"
        "                staged_apps.source(addon,Path(__file__).with_name('myron-apps-plan.json')))")
    replace(p,"        replace('\\tif (!error) native_gpu_addon_prepare(p, scratch);\\n', '')",
        "        replace('\\tif (!error) native_gpu_addon_prepare(p, scratch);\\n',\n"
        "                '\\tif (!error) myron_gpu_addon_prepare(p);\\n')")
    replace(p,"        require('_myron_data_prepare' in info['defined'] and",
        "        require(os.environ.get('MYRON_GPU_NATIVE')!='1' or ('_myron_gpu_addon_contract' in info['defined'] and\n"
        "                {'_native_ram_block_gpu_addon','_myron_gpu_addon_available'} <= info['undefined']),\n"
        "                'GPU addon lost its payload handoff or publication dependency')\n"
        "        require('_myron_data_prepare' in info['defined'] and")
    replace(device/'build_ufs_dormant.py',"keep += ('_myron_data_store_open',",
        "keep += (('_native_ram_block_gpu_addon','_myron_gpu_addon_contract') if os.environ.get('MYRON_GPU_NATIVE')=='1' else ())\n            keep += ('_myron_data_store_open',")
    # Existing Data-mount harness substitutes both optional helpers; their real
    # implementations are exercised independently with failure-injection peers.
    p=device/'tests/test_root_runtime.py'
    replace(p,"        apps_start=block.index('/* The deletable system apps')",
        "        apps_start=block.index('static void myron_gpu_addon_prepare(proc_t p)') if 'static void myron_gpu_addon_prepare(proc_t p)' in block else block.index('/* Boot-time read-only union views of owner-provided GPU addon content')")
    replace(p,"+'static unsigned appCalls; static void myron_staged_apps_prepare",
        "+'static void myron_gpu_addon_prepare(proc_t p){(void)p;} static unsigned appCalls; static void myron_staged_apps_prepare")
