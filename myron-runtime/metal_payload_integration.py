"""Wire sidecar packaging and readback while retaining native/final kernel checks."""
from pathlib import Path
import shutil

def apply(d,replace):
    here=Path(__file__).resolve().parent;root=here.parent
    for name in ('prepare_metal_sidecars.py','audit_userspace_artifact.py'):
        shutil.copyfile(root/'myron-gpu'/name,d/name)
    shutil.copyfile(here/'metal_payload.py',d/'metal_payload.py')
    shutil.copyfile(root/'myron_continuous_contract.py',d/'myron_continuous_contract.py')
    p=d/'boot_assets.py'
    replace(p,'import hashlib','import hashlib\nimport os')
    replace(p,"    budget=capacity(kernel,seed['transport_bytes'],len(trust),kernel_transport_bytes)\n    out=Path(out);out.mkdir(parents=True,exist_ok=False)",
        "    out=Path(out);out.mkdir(parents=True,exist_ok=False)\n"
        "    metal=None;archive=os.environ.get('MYRON_METAL_ARTIFACT')\n"
        "    if archive:\n"
        "        require(os.environ.get('MYRON_PACKED_KERNEL')=='1','Metal addon requires qualified packed transport')\n"
        "        from metal_payload import stage as stage_metal\n"
        "        metal=stage_metal(archive,trust,out/'metal',kernel,root_report)\n"
        "        trust=(out/'metal/kernel.macho.trustcache').read_bytes()\n"
        "        shutil.copyfile(out/'metal/gpuaddon.bin',out/'kernel.macho.gpuaddon')\n"
        "    budget=capacity(kernel,seed['transport_bytes'],len(trust),kernel_transport_bytes,metal['addon_bytes'] if metal else 0)")
    replace(p,'own_code_entries_added=False,original_modules_modified=False,budget=budget,',
        'own_code_entries_added=bool(metal),original_modules_modified=False,budget=budget,metal_addon=metal,')
    replace(p,'    if startup_probe:\n',
        "    if metal:\n        report['adt_properties']+=['GpuAddon']\n"
        "    if startup_probe:\n"
        "        if metal:report['required_boot_arguments']+=['myron-gpu-metal=1']\n")
    # These tests construct a tiny synthetic kernel without GPU objects. The
    # real build's component selection must not turn that fixture into a Metal
    # integration candidate. Scope the override to each test and restore it.
    p=d/'tests/test_boot_assets.py'
    replace(p,'import hashlib','import hashlib\nimport os')
    replace(p,'    def setUp(self):\n',
        '    def setUp(self):\n'
        '        environment=patch.dict(os.environ)\n'
        '        environment.start();self.addCleanup(environment.stop)\n'
        "        os.environ.pop('MYRON_METAL_ARTIFACT',None)\n")
    replace(p,'    def test_staging_names_args_and_existing_output(self):',
        '''    def test_metal_selection_keeps_real_audit_guards(self):
        self.bind()
        pins=dict(zip(assets.TRUST_PINS,[data_seed.sha(self.static),data_seed.sha(self.system)]))
        for packed,message in [('0','qualified packed transport'),
                               ('1','audited iPhone accelerator objects')]:
            with self.subTest(packed=packed),patch.object(assets,'TRUST_PINS',pins),patch.dict(os.environ,
                    MYRON_METAL_ARTIFACT=str(self.work/'unread-component.zip'),MYRON_PACKED_KERNEL=packed):
                out=self.work/('metal-refused-'+packed)
                with self.assertRaisesRegex(ValueError,message):
                    assets.prepare(self.kernel,self.bundle,self.native_path,self.final_path,
                                   self.static,self.system,out)
                self.assertFalse((out/'kernel.macho.gpuaddon').exists())
                self.assertFalse((out/'boot-assets.json').exists())

    def test_staging_names_args_and_existing_output(self):''')
    p=d/'build_payload.py'
    replace(p,'data=bool(assets),trust=bool(assets))',
        "data=bool(assets),trust=bool(assets),addon=bool(assets and assets.get('metal_addon')))")
    replace(p,"assets['root_uuid'] if assets else None)",
        "assets['root_uuid'] if assets else None,addon=bool(assets and assets.get('metal_addon')))")
    replace(p,"for name in ('kernel.macho.trustcache','scratch-data.img'):",
        "for name in ('kernel.macho.trustcache','scratch-data.img')+(('kernel.macho.gpuaddon',) if assets.get('metal_addon') else ()):")
    p=d/'payload_adt.py'
    replace(p,'def validate(blob, reference, root_uuid=None):','def validate(blob, reference, root_uuid=None, addon=False):')
    replace(p,"assert set(mappings) == {'name','PackedRAMDisk','TrustCache'}",
        "assert set(mappings) == {'name','PackedRAMDisk','TrustCache'} | ({'GpuAddon'} if addon else set())\n"
        "        if addon:assert mappings['GpuAddon']==bytes(16)")
    p=d/'tests/check_boot_payload.py'
    replace(p,"assets['root_uuid'])","assets['root_uuid'],addon=bool(assets.get('metal_addon')))")
    p=d/'package_root_image.py'
    replace(p,'    checks = {}',
        "    if proof['boot_assets'].get('metal_addon'):\n"
        "        expected['kernel.macho.gpuaddon']=proof['boot_assets']['metal_addon']['addon_sha256']\n"
        "    checks = {}")
    p=d/'build_root_firmware.py'
    replace(p,"    assert sha(payload/'payload.img') == proof['sha256']",
        "    if assets.get('metal_addon'):\n"
        "        assert hashlib.sha256(read('Payloads/kernel.macho.gpuaddon')).hexdigest()==assets['metal_addon']['addon_sha256']\n"
        "    assert sha(payload/'payload.img') == proof['sha256']")
    p=d/'tests/check_root_handoff.py'
    replace(p,'for name,expected in inputs.items():',
        "if assets.get('metal_addon'):inputs['kernel.macho.gpuaddon']=assets['metal_addon']['addon_sha256']\n"
        'for name,expected in inputs.items():')
    replace(p,'subprocess.run(command,check=True)',
        "if assets.get('metal_addon'):command+=['--gpu-addon',str(a.out/'kernel.macho.gpuaddon')]\n"
        'subprocess.run(command,check=True)')
    replace(p,"assert report['kernel_sha256']==proof['kernel_sha256']",
        "assert report['kernel_sha256']==proof['kernel_sha256']\n"
        "if assets.get('metal_addon'):assert report['gpu_addon_sha256']==assets['metal_addon']['addon_sha256']")
    p=d/'tests/test_loader_boot.py'
    replace(p,"p.add_argument('--trust-cache', type=Path)","p.add_argument('--trust-cache', type=Path)\np.add_argument('--gpu-addon',type=Path)")
    replace(p,'a.ramdisk,a.trust_cache,a.capture','a.ramdisk,a.trust_cache,a.capture,a.gpu_addon')
    replace(p,'if bool(a.ramdisk) != bool(a.trust_cache)',
        "if a.gpu_addon and not a.ramdisk:p.error('Addon requires complete root sidecars')\nif bool(a.ramdisk) != bool(a.trust_cache)")
    replace(p,"assert set(mappings)=={'name','PackedRAMDisk','TrustCache'}",
        "assert set(mappings)=={'name','PackedRAMDisk','TrustCache'}|({'GpuAddon'} if a.gpu_addon else set())")
    replace(p,"for key, env in [('PackedRAMDisk','MYRON_RAM_SLOT'),('TrustCache','MYRON_TRUST_SLOT')]:",
        "for key, env in [('PackedRAMDisk','MYRON_RAM_SLOT'),('TrustCache','MYRON_TRUST_SLOT')]+([('GpuAddon','MYRON_ADDON_SLOT')] if a.gpu_addon else []):")
    replace(p,'if a.capture:\n',
        "if a.gpu_addon:environment['MYRON_TEST_ADDON']=str(a.gpu_addon.resolve())\nif a.capture:\n")
    replace(p,'root_sidecars_checked=bool(a.ramdisk),',
        "root_sidecars_checked=bool(a.ramdisk),gpu_addon_sha256=hashlib.sha256(a.gpu_addon.read_bytes()).hexdigest() if a.gpu_addon else None,\n"
        "              gpu_addon_handoff_checked=bool(a.gpu_addon),gpu_addon_failure_cases=5 if a.gpu_addon else 0,")
    p=d/'tests/loader_boot_host.c'
    replace(p,'static UINT8 *expected_ramdisk, *expected_trust;',
        'static UINT8 *expected_ramdisk, *expected_trust, *expected_addon;\nstatic UINTN expected_addon_size,addon_slot;')
    replace(p,'static FILE_MOCK root_file, kernel_file, tree_file, trust_file, logical_kernel;',
        'static FILE_MOCK root_file, kernel_file, tree_file, trust_file, logical_kernel, addon_file;')
    replace(p,'MISSING_RAM_SLOT, MISSING_TRUST_SLOT, SHORT_TRUST, END_ROOT_CASES };',
        'MISSING_RAM_SLOT, MISSING_TRUST_SLOT, SHORT_TRUST, END_ROOT_CASES };\n'
        'enum { NO_ADDON=END_ROOT_CASES, BAD_ADDON, IO_ADDON, STALE_ADDON_SLOT, MISSING_ADDON_SLOT, END_ADDON_CASES };')
    replace(p,'!kernel_file.open&&!tree_file.open&&!trust_file.open','!kernel_file.open&&!tree_file.open&&!trust_file.open&&!addon_file.open')
    replace(p,'if(f->kind==3&&mode==IO_TRUST)return EFI_DEVICE_ERROR;',
        'if(f->kind==3&&mode==IO_TRUST)return EFI_DEVICE_ERROR;\n if(f->kind==4&&mode==IO_ADDON)return EFI_DEVICE_ERROR;')
    replace(p,'&&mode!=NO_TRUST)f=&trust_file;else return EFI_NOT_FOUND;',
        '&&mode!=NO_TRUST)f=&trust_file;\n'
        ' else if(!strcmp(path,"\\\\Payloads\\\\kernel.macho.gpuaddon")&&expected_addon&&mode!=NO_ADDON)f=&addon_file;else return EFI_NOT_FOUND;')
    replace(p,'  UINT64 top=(trust_pa+expected_trust_size+16383)&~16383ULL;',
        '  UINT64 addon_pa=(trust_pa+expected_trust_size+16383)&~16383ULL;\n'
        '  UINT64 top=(addon_pa+expected_addon_size+16383)&~16383ULL;')
    replace(p,'  memcpy(wanted+ram_slot,values,16);memcpy(wanted+trust_slot,values+2,16);',
        '  memcpy(wanted+ram_slot,values,16);memcpy(wanted+trust_slot,values+2,16);\n'
        '  if(expected_addon){UINT64 slots[2]={addon_pa,expected_addon_size};memcpy(wanted+addon_slot,slots,16);\n'
        '    assert(!memcmp((VOID*)(UINTN)addon_pa,expected_addon,expected_addon_size));\n'
        '    for(UINT64 i=trust_pa+expected_trust_size;i<addon_pa;i++)assert(!*(UINT8*)(UINTN)i);}\n')
    # Each mutation is undone by the identical end-of-scenario branch.
    anchor=' if(mode==BAD_RAMDISK)expected_ramdisk[8]^=1;'
    new=anchor+'\n if(mode==BAD_ADDON)addon_file.data[0]^=1;\n if(mode==STALE_ADDON_SLOT)tree_file.data[addon_slot]^=1;\n if(mode==MISSING_ADDON_SLOT)tree_file.data[addon_slot-36]^=1;'
    raw=p.read_text();assert raw.count(anchor)==2;p.write_text(raw.replace(anchor,new))
    replace(p,' fs.OpenVolume=open_volume;',
        ' if(getenv("MYRON_TEST_ADDON")){\n'
        '  assert(root_mode&&getenv("MYRON_ADDON_SLOT"));init_file(&addon_file,4);load(&addon_file,getenv("MYRON_TEST_ADDON"));\n'
        '  expected_addon=addon_file.data;expected_addon_size=addon_file.size;addon_slot=strtoull(getenv("MYRON_ADDON_SLOT"),NULL,10);\n'
        '  assert(addon_slot>=36&&addon_slot+16<=expected_tree_size&&!memcmp(expected_tree+addon_slot-36,"GpuAddon",9));\n'
        ' }\n fs.OpenVolume=open_volume;')
    replace(p,' if(root_mode)for(int i=NO_RAMDISK;i<END_ROOT_CASES;i++)run(i,0);',
        ' if(root_mode)for(int i=NO_RAMDISK;i<END_ROOT_CASES;i++)run(i,0);\n'
        ' if(expected_addon)for(int i=NO_ADDON;i<END_ADDON_CASES;i++)run(i,0);')
    replace(p,'free(logical_kernel.data);','free(addon_file.data);free(logical_kernel.data);')
