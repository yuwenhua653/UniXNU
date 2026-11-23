"""Wire retained accelerator ABI verification into the existing image build."""

def apply(device, replace):
    replace(device/'build_ufs_dormant.py',
        "                tree, here, out/'gpu', builder, target, env, record)",
        "                tree, here, out/'gpu', builder, target, env, record,\n"
        "                args.donor, native, args.baseline_map, upstream/'kits/XnuPrelink')\n"
        "            require(result['gpu_build']['accelerator_contract']['donor_checked'],\n"
        "                    'GPU link requires the actual iPhone donor/identity audit')")
    replace(device/'build_ufs_dormant.py',
        "                             name not in (display_contract['touch']['bindings'] if display_contract else {}))),",
        "                             name not in (display_contract['touch']['bindings'] if display_contract else {}) and\n"
        "                             name not in (result['gpu_build']['accelerator_contract']['bindings'] if gpu_enabled else {}))),")
    replace(device/'build_ufs_dormant.py',
        "                    result['gpu_firmware_link'] = verify_gpu_firmware(\n"
        "                        raw_native, here/'gpu/firmware-3.0.306.json')",
        "                    result['gpu_firmware_link'] = verify_gpu_firmware(\n"
        "                        raw_native, here/'gpu/firmware-3.0.306.json')\n"
        "                    from display_build import verify_linked as verify_accelerator_linked\n"
        "                    result['gpu_accelerator_link'] = verify_accelerator_linked(\n"
        "                        raw_native,result['gpu_build']['accelerator_contract'],upstream/'kits/XnuPrelink')")
    replace(device/'prepare_desktop.py',
        "                    display_contract=None\n                    extra_adapters=()",
        "                    display_contract=None\n                    accelerator_contract=None\n"
        "                    extra_adapters=()")
    replace(device/'prepare_desktop.py',
        "                                             for n,r in c['bindings'].items() if r['kind']=='function')",
        "                                             for n,r in c['bindings'].items() if r['kind']=='function')\n"
        "                        gpu_report=json.loads((out/'ufs'/mode/'report.json').read_text()).get('gpu_build')\n"
        "                        if gpu_report:\n"
        "                            accelerator_contract=json.loads((out/'ufs'/mode/'gpu/accelerator-abi.json').read_text())\n"
        "                            if not accelerator_contract['donor_checked']: raise ValueError('Unaudited GPU accelerator')\n"
        "                            extra_adapters+=tuple(n for n,r in accelerator_contract['bindings'].items() if r['kind']=='function')")
    replace(device/'prepare_desktop.py',
        "                            display_contract,upstream/'kits/XnuPrelink')",
        "                            display_contract,upstream/'kits/XnuPrelink')\n"
        "                        if accelerator_contract:\n"
        "                            evidence['gpu_accelerator']=verify_display_prelinked(\n"
        "                                retained_kernel/'kernel.macho',retained_output,\n"
        "                                accelerator_contract,upstream/'kits/XnuPrelink')")
