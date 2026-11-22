#!/usr/bin/env python3
"""Apply reviewed board runtime integration after the immutable base overlays."""
from pathlib import Path
import shutil
import sys

def replace(path, old, new):
    text=path.read_text()
    if text.count(old)!=1:raise ValueError(f'Runtime boundary changed: {path.name}: {old[:65]}')
    path.write_text(text.replace(old,new))

def apply(root):
    d=root/'device/myron27'; u=root/'device/sm8850/drivers/NativeUfs'
    here=Path(__file__).resolve().parent
    for name in ('MyronDataWindow.h','MyronDataStore.h'):shutil.copyfile(here/name,u/name)
    shutil.copyfile(here/'ui_seed.py',d/'ui_seed.py')
    replace(d/'prepare_data_volume.py','    set_render_preferences(target)',
        '    import ui_seed\n    ui_seed.clear(target)\n    set_render_preferences(target)')
    replace(d/'build_ufs_dormant.py', '            from ram_data import stage as stage_ram_data',
        "            keep += ('_myron_data_store_open','_myron_data_store_read','_myron_data_store_write','_myron_data_store_sync')\n            from ram_data import stage as stage_ram_data")
    # Keep the original symbol registrations and all signed root/seed checks.
    replace(d/'ram_data.py',"source = source.replace(old, 'unsigned mode = 0; // myron: volatile Data only')",
        "source = source.replace(old, 'unsigned mode = myron_data_store_mode();')\n"
        "    source = source.replace('native_ufs_store_', 'myron_data_store_')\n"
        "    source = source.replace('bool ready=available();', 'bool ready=available() && storeAttached && direct && !directFailed;')\n"
        "    source = source.replace('if (!online) { IOLockUnlock(gate); return kIOReturnNotReady; }',\n"
        "        'if (!online || (storeAttached && !direct) || (buffer->getDirection()==kIODirectionOut && (!direct || directFailed))) { IOLockUnlock(gate); return kIOReturnNotReady; }')\n"
        "    source = source.replace('overlay.open(ops, pages, seedHash, mode == 1, overlayBits, discardRequested())',\n"
        "        'overlay.open(ops, pages, seedHash, false, overlayBits, blankStore(ops))')\n"
        "    source = source.replace('  void attachStore() {', '''  bool blankStore(StoreOps &ops) {\n"
        "    uint8_t header[4096];\n"
        "    return ops.read(0,1,header) && myronDataMayInitialize(header);\n"
        "  }\n"
        "  void attachStore() {''')\n"
        "    source = source.replace('if (!online) return kIOReturnNotReady;',\n"
        "        'if (!gate) return kIOReturnNotReady;\\n    IOLockLock(gate); if(!online || !direct || directFailed) { IOLockUnlock(gate); return kIOReturnNotReady; } bool ok=myron_data_store_sync(); if(!ok)directFailed=true; IOLockUnlock(gate); if(!ok)return kIOReturnIOError;')")
    replace(d/'ram_data.py', "    old = 'if(!ramPackedLayout(memory,bytes,&logical))return false;'",
        "    source = source.replace('        native_data_persist_present = overlay.present;', '        if (direct && !myronDataCommitInitialization()) { directFailed=true; native_data_persist_state=4; }\\n        native_data_persist_present = overlay.present;')\n"
        "    old = 'if(!ramPackedLayout(memory,bytes,&logical))return false;'")
    replace(d/'ram_data.py', '    return source', "    source = source.replace('kept, Data runs from the seed: ', 'kept, writable Data refused: ').replace('use Install and boot to start it over', 'retain the matching seed; no automatic reset')\n    return source")
    replace(d/'ram_data.py','persistent_store_enabled=False,','persistent_store_enabled=True,')
    replace(d/'MyronRamData.h','#include "ram-data/NativeRamBlock.cpp"',
        '#include "MyronDataStore.h"\n#include "ram-data/NativeRamBlock.cpp"')
    replace(d/'MyronRamData.h','// Keep the successful service owned for this boot. No persistent\n            // callbacks are opened by the staged RamBlock implementation.',
        '// Keep this service owned; seed selection attaches the bounded Data store.')
    # The two writers open non-overlapping windows under the same transport lock.
    replace(u/'MyronBootLog.h','storeMode() || logMode() || gStoreOpen || gLogOpen ||',
        'storeMode() || logMode() || gLogOpen ||')
    replace(u/'MyronBootLog.h','if(!hostLogOpen(first,MyLogBlocks))',
        'IOLockLock(gHost.lock);\n bool opened=hostLogOpen(first,MyLogBlocks);\n IOLockUnlock(gHost.lock);\n if(!opened)')
    # Qualify the intentionally changed persistent mode, retaining upstream IO tests.
    p=d/'tests/test_ram_data.py'
    replace(p,"self.assertFalse(report['persistent_store_enabled'])","self.assertTrue(report['persistent_store_enabled'])")
    replace(p,"self.assertIn('unsigned mode = 0;', text)","self.assertIn('unsigned mode = myron_data_store_mode();', text)")
    replace(p,".replace('#include \"ram-data/NativeRamBlock.cpp\"', '')",
        ".replace('#include \"ram-data/NativeRamBlock.cpp\"', '').replace('#include \"MyronDataStore.h\"', '')")
    # @3x phone presentation on the actual 1200x2608 GOP; no cropped canvas or
    # coordinate rescaling, and no change to the N104 kernel/security donor.
    p=d/'board.toml'
    for old,new in [('"display-scale" = 2','"display-scale" = 3'),('artwork-scale-factor = 2','artwork-scale-factor = 3'),
                    ('artwork-device-subtype = 1792','artwork-device-subtype = 2556'),
                    ('compatible-device-fallback = "iPhone11,8"','compatible-device-fallback = "iPhone15,2"')]:replace(p,old,new)

if __name__=='__main__':apply(Path(sys.argv[1]))
