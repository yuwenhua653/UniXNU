"""Round-trip compositor preferences on the exact Data seed from the tested package."""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import stat
import sys
import tempfile
from test_myron_retained_data_layout import unpack_seed


def snapshot(root, rel):
    path = root / rel
    if not path.exists():
        return None
    st = path.stat()
    return plistlib.loads(path.read_bytes()), (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.package.read_bytes()).hexdigest() == 'fa107a69f59713edbc3d3edf030acd35c5ec3214891e1d7d6e5aff28560eff3e'
    sys.path.insert(0, str(args.device.resolve()))
    import data_seed
    import prepare_data_volume as volume
    paths = [Path(home)/'Library/Preferences'/name for home in ('root', 'mobile')
             for name in ('backboardd.plist', '.GlobalPreferences.plist')]
    with tempfile.TemporaryDirectory() as private:
        work = Path(private)
        image = work/'original.cdr'
        original_digest = unpack_seed(args.package, image)
        with volume.attached(image, work/'before', True) as mounted:
            before = {p:snapshot(mounted['path'],p) for p in paths}
            uuid = mounted['uuid']
            for path, record in before.items():
                print('original', path, {k:record[0].get(k) for k in volume.RENDER_PREFS} if record else 'absent')
            assert all(record is None or all(k not in record[0] for k in volume.RENDER_PREFS) for record in before.values())
        with volume.attached(image, work/'update', False) as mounted:
            volume.set_render_preferences(mounted['path'])
            times = [(mounted['path']/p).stat().st_mtime_ns for p in paths]
            volume.set_render_preferences(mounted['path'])
            assert times == [(mounted['path']/p).stat().st_mtime_ns for p in paths]
        with volume.attached(image, work/'after', True) as mounted:
            assert mounted['uuid'] == uuid
            for path in paths:
                old = before[path]
                prefs, metadata = snapshot(mounted['path'],path)
                uid = 501 if path.parts[0]=='mobile' else 0
                assert metadata == (old[1] if old else (uid,uid,0o644))
                assert all(prefs[k] is False for k in volume.RENDER_PREFS)
                assert {k:v for k,v in prefs.items() if k not in volume.RENDER_PREFS} == (old[0] if old else {})
            volume.run('diskutil','verifyVolume',mounted['device'])
        assert data_seed.pack(image, work/'data.dbr')['transport_sha256'] != original_digest
        print('PASS four preference domains on retained Data, 12 Boolean values, other keys, numeric ownership, idempotence, APFS and packing')


if __name__ == '__main__':
    main()
