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
    shutil.copyfile(here/'constant-marker.patch',d/'patches/xnuprelink/zzzzz-constant-marker.patch')
    from display_fence import apply as apply_display_fence
    apply_display_fence(d,replace)
    from display_performance import apply as apply_display_performance
    apply_display_performance(d,replace)
    from accelerator import apply as apply_accelerator
    apply_accelerator(d,replace)
    shutil.copyfile(here/'platform-power.patch',d/'platform-power.patch')
    replace(d/'install_upstream.py', "prelink=u/'kits/XnuPrelink'", """platform=u/'drivers/ArmDTPlatform'
revision=subprocess.check_output(['git','-C',str(platform),'rev-parse','HEAD'],text=True).strip()
if revision!='417ff95d6a6e8607ddea9309ec45c3bfd4a67c60':raise SystemExit('Unexpected platform power source')
power_patch=here/'platform-power.patch'
if subprocess.run(['git','-C',str(platform),'apply','--reverse','--check',str(power_patch)],capture_output=True).returncode:
 subprocess.run(['git','-C',str(platform),'apply','--check',str(power_patch)],check=True)
 subprocess.run(['git','-C',str(platform),'apply',str(power_patch)],check=True)
prelink=u/'kits/XnuPrelink'""")
    for name in ('MyronDataWindow.h','MyronDataStore.h'):shutil.copyfile(here/name,u/name)
    shutil.copyfile(here/'ui_seed.py',d/'ui_seed.py')
    shutil.copyfile(here/'reuse_data_seed.py',d/'reuse_data_seed.py')
    shutil.copyfile(here/'staged_apps.py',d/'staged_apps.py')
    replace(d/'prepare_userland.py',"            checkpoint('original-data-copy-plan',plan)",
        "            checkpoint('original-data-copy-plan',plan)\n"
        "            import staged_apps\n"
        "            apps=staged_apps.plan(var/'staged_system_apps',Path(__file__).with_name('myron-apps-plan.json'))\n"
        "            checkpoint('system-apps-plan',apps)\n"
        "            (report_path.parent/'system-apps-plan.json').write_text(json.dumps(apps,indent=2)+'\\n')")
    replace(d/'root_runtime.py',"        replace(addon, '// Myron Data mount: device-specific addons are not compiled.\\n')",
        "        import staged_apps\n"
        "        replace(addon, staged_apps.source(addon,Path(__file__).with_name('myron-apps-plan.json')))")
    replace(d/'root_runtime.py',"        replace('\\tif (!error) native_staged_apps_prepare(p, scratch, data_mount);\\n', '')",
        "        replace('\\tif (!error) native_staged_apps_prepare(p, scratch, data_mount);\\n',\n"
        "                '\\tif (!error) myron_staged_apps_prepare(p, data_mount);\\n')")
    replace(d/'boot_assets.py',"'myron27-keystore=1','boot-ui-trace=1'",
        "'myron27-keystore=1','staged-apps=1','boot-ui-trace=1'")

    replace(d/'boot_assets.py', "        report['required_boot_arguments'] += ['myron27-dyld-startup=1'",
        "        native=json.loads(Path(root_report).read_text())\n"
        "        gpu=native.get('gpu_build',{})\n"
        "        report['gpu_hardware_start_enabled']=gpu.get('native_objects_compiled') is True\n"
        "        if report['gpu_hardware_start_enabled']:\n"
        "            require(bool(native.get('gpu_firmware_link')), 'GPU firmware must be checked in the actual linked native kernel')\n"
        "            report['required_boot_arguments'] += ['myron-gpu=1']\n"
        "        report['required_boot_arguments'] += ['myron27-dyld-startup=1'")
    replace(u/'MyronBootLog.h','extern "C" size_t myron_touch_snapshot(char *,size_t);',
        'extern "C" size_t myron_touch_snapshot(char *,size_t);\n'
        'extern "C" size_t myron_staged_apps_snapshot(char *,size_t);\n'
        '#if MYRON_GPU_NATIVE\nextern "C" size_t myron_gpu_snapshot(char *,size_t);\n#endif')
    replace(u/'MyronBootLog.h','displayRemaining<1024?displayRemaining:1024','displayRemaining<1536?displayRemaining:1536')
    replace(u/'MyronBootLog.h','touchRemaining<256?touchRemaining:256','touchRemaining<768?touchRemaining:768')
    replace(u/'MyronBootLog.h','  const size_t processRemaining=',
        '#if MYRON_GPU_NATIVE\n'
        '  const size_t gpuRemaining=MyLogSlotBlocks*MyLogBlock-(size_t)prefix;\n'
        '  prefix+=(int)myron_gpu_snapshot((char *)slot+prefix,gpuRemaining<6144?gpuRemaining:6144);\n'
        '#endif\n'
        '  const size_t appsRemaining=MyLogSlotBlocks*MyLogBlock-(size_t)prefix;\n'
        '  prefix+=(int)myron_staged_apps_snapshot((char *)slot+prefix,appsRemaining<384?appsRemaining:384);\n'
        '  const size_t processRemaining=')

    # This board owns a state-only service and has no keybag/passcode support.
    # SLS 3 is no-passcode; 0 incorrectly describes an unlocked passcode state.
    replace(d/'display/MyronKeyStoreProbe.cpp',
        'uint32_t native_aks_lock_state(void) {return 0;}',
        'uint32_t native_aks_lock_state(void) {return 3; /* no keybag / no passcode */}')
    p=d/'prepare_userland.py'
    replace(p,'def prepare(upstream,out,report_path,archive_tool):',
        'def prepare(upstream,out,report_path,archive_tool,data_seed_path=None):')
    replace(p,"            data=volume.build_volume(out/'data',plan['volume_mib'],lambda target:volume.copy_var(var,target))",
        "            from reuse_data_seed import reuse\n"
        "            require(data_seed_path is not None, 'Persistent myron install requires its original Data seed')\n"
        "            data=reuse(data_seed_path,out/'data')")
    replace(p,'    a=p.parse_args();prepare(a.upstream,a.out,a.report,a.archive_tool)',
        "    p.add_argument('--data-seed',type=Path,required=True)\n"
        '    a=p.parse_args();prepare(a.upstream,a.out,a.report,a.archive_tool,a.data_seed)')

    replace(d/'prepare_data_volume.py','    set_render_preferences(target)',
        '    import ui_seed\n    ui_seed.clear(target)\n    set_render_preferences(target)')
    replace(d/'build_ufs_dormant.py', '            from ram_data import stage as stage_ram_data',
        "            keep += ('_myron_data_store_open','_myron_data_store_read','_myron_data_store_write','_myron_data_store_sync')\n            from ram_data import stage as stage_ram_data")
    p=d/'tests/test_root_runtime.py'
    replace(p,"        end = source.index('\\n}\\n#endif', start) + len('\\n}\\n#endif')\n        block = source[start:end]",
        "        end = source.index('\\n}\\n#endif', start) + len('\\n}\\n#endif')\n"
        "        block = source[start:end]\n"
        "        apps_start=block.index('/* The deletable system apps')\n"
        "        apps_end=block.index('extern volatile unsigned myron_data_start_state;',apps_start)\n"
        "        block=block[:apps_start]+'static unsigned appCalls; static void myron_staged_apps_prepare(proc_t p,mount_t m){assert(!p && m);++appCalls;}\\n'+block[apps_end:]")
    replace(p,'  int rc=myron_data_prepare(0,(uintptr_t)scratch_memory);',
        '  appCalls=0;\n  int rc=myron_data_prepare(0,(uintptr_t)scratch_memory);\n  assert(appCalls==(unsigned)(rc==0));')
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
    # The medium is now a durable seed-bound UFS overlay. Declaring it ephemeral
    # prevents the native first-boot SystemAppMigrator from installing apps.
    replace(d/'build_payload.py','packed_data_ramdisk=True,persistent_data=False)',
        'packed_data_ramdisk=True,persistent_data=True)')
    replace(d/'payload_adt.py',"        assert chosen['ephemeral-storage'] == struct.pack('<I',1)",
        "        assert 'ephemeral-storage' not in chosen")
    # Keep the boot-sidecar fixture consistent with the generated persistent ADT,
    # and prove that either value of the obsolete property is still rejected.
    p=d/'tests/test_boot_assets.py'
    replace(p,'def adt(root_mode=False):','def adt(root_mode=False, ephemeral=None):')
    replace(p,",('ephemeral-storage',struct.pack('<I',1))",'')
    replace(p,"        maps=[('PackedRAMDisk',bytes(16)),('TrustCache',bytes(16))]",
        "        if ephemeral is not None:\n"
        "            chosen.append(('ephemeral-storage',struct.pack('<I',ephemeral)))\n"
        "        maps=[('PackedRAMDisk',bytes(16)),('TrustCache',bytes(16))]")
    replace(p,'    def test_staging_names_args_and_existing_output(self):',
        '    def test_root_adt_ephemeral_property_refused(self):\n'
        '        reference=adt()\n'
        '        validate(adt(True),reference,OS)\n'
        '        for value in (0,1):\n'
        '            with self.subTest(ephemeral=value),self.assertRaises(AssertionError):\n'
        '                validate(adt(True,ephemeral=value),reference,OS)\n\n'
        '    def test_staging_names_args_and_existing_output(self):')
    # @3x phone presentation on the actual 1200x2608 GOP; no cropped canvas or
    # coordinate rescaling, and no change to the N104 kernel/security donor.
    p=d/'board.toml'
    for old,new in [('"display-scale" = 2','"display-scale" = 3'),('artwork-scale-factor = 2','artwork-scale-factor = 3'),
                    ('artwork-device-subtype = 1792','artwork-device-subtype = 2556'),
                    ('compatible-device-fallback = "iPhone11,8"','compatible-device-fallback = "iPhone15,2"')]:replace(p,old,new)

    from kernel_transport_integration import apply as apply_kernel_transport
    apply_kernel_transport(d,replace)
    from gpu_addon_integration import apply as apply_gpu_addon
    apply_gpu_addon(d,replace)
    from metal_payload_integration import apply as apply_metal_payload
    apply_metal_payload(d,replace)
    from data_capacity import apply as apply_data_capacity
    apply_data_capacity(root,replace)
    from early_task_evidence import apply as apply_early_task_evidence
    apply_early_task_evidence(d,replace)
    from display_failure_evidence import apply as apply_display_failure_evidence
    apply_display_failure_evidence(d,replace)

if __name__=='__main__':apply(Path(sys.argv[1]))
