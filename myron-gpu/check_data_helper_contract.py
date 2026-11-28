#!/usr/bin/env python3
"""Refuse a full build before helper binaries, source and addon pins agree."""
import hashlib,json
from pathlib import Path
from prepare_metal_sidecars import DATA_HELPER,owner_categories
from audit_userspace_artifact import require

def check():
    here=Path(__file__).resolve().parent
    contract=json.loads((here/'metal-addon-contract.json').read_text())
    manifest=here/'data-helper-sources.json'
    sources=json.loads(manifest.read_text())
    for name,digest in sources.items():
        require(hashlib.sha256((here.parent/'myron-runtime'/name).read_bytes()).hexdigest()==digest,
                'Unbound Data helper source: '+name)
    require(contract.get('data_helper_sources_sha256')==hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'Rebuilt Data helper contract is not bound to current sources; full package blocked')
    require(contract.get('data_helper')==DATA_HELPER and DATA_HELPER.get('earlyboot_cdhash'),
            'Early helper binaries are not pinned')
    files=contract['addon_files']
    require(len(files)==8 and not any('myron-data-daemons/' in p or 'myron-data-xpc/' in p for p in files),
            'Old daemon/cache addon inventory')
    for path,key in [('addons/myron-data-grow','binary_sha256'),
                     ('addons/myron-data-earlyboot/HorizonSetup','earlyboot_sha256')]:
        require(files[path]['mode']==0o755 and files[path]['sha256']==DATA_HELPER[key],'Wrong helper bytes/mode')
    hashes=contract['owner_cdhashes']
    require(len(set(hashes))==len(hashes)==4 and
            {DATA_HELPER['cdhash'],DATA_HELPER['earlyboot_cdhash']}<=set(hashes),'Incomplete owner platform trust')
    require(contract.get('owner_constraint_categories')==owner_categories(hashes),
            'Missing or stale early-boot system-service launch constraint policy')
    require(contract.get('service_cache_modified') is False and
            contract.get('earlyboot_program')=='/usr/libexec/HorizonSetup' and
            contract.get('earlyboot_task')=='restore-datapartition','Wrong early startup route')
    print('PASS: compiled helper, early adapter, source manifest, eight-file addon and four-entry trust pins agree')
if __name__=='__main__':check()
