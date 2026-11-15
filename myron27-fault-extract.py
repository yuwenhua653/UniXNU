#!/usr/bin/env python3
"""Read the original SystemOS cache for one photographed launchd fault.

This job does not compile XNU, access a phone, or change original firmware.
Only bounded analysis JSON is public. AEA output and images stay private.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from types import SimpleNamespace

UPSTREAM = '04573c510c5fd4892ca6948739389141cc9e05f5'
SYSTEMOS = ('B12BB6BB-EF0C-4DC3-A14A-AD1917051534', 6012534784,
            'fd48f4d89b7cf833f0bf83c35f6b55e4702510341346710201028a67fb11aa44')
MEMBER = ('043-69708-712.dmg.aea', 2348810240)
OBSERVATION = dict(pc='0x183257140', lr='0x037670c183257474',
                   slide='0x02e3c000', fault='0x00000741e9d71f70')
MAX_REPORT = 2 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def check_raw_image(image, backend, expected=SYSTEMOS):
    """ROOT_PINS identify raw disk bytes, not the containing UDIF/DMG file."""
    size = backend.image_size(image)
    require(size == expected[1], 'SystemOS raw disk size differs from installed root')
    digest, count = hashlib.sha256(), 0
    with contextlib.closing(backend.disk_blocks(image, size)) as blocks:
        for block in blocks:
            require(block and count + len(block) <= size, 'Invalid SystemOS raw disk stream')
            digest.update(block)
            count += len(block)
    require(count == size, 'Truncated SystemOS raw disk stream')
    require(digest.hexdigest() == expected[2], 'SystemOS raw disk hash differs from installed root')
    return dict(bytes=count, sha256=digest.hexdigest(), complete_raw_disk_checked=True)


def checked_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_REPORT,
            'Analysis report missing or exceeds the bounded output limit')
    report = json.loads(path.read_text())
    require(isinstance(report, dict), 'Analysis report must be an object')
    return report


def save(path, record):
    raw = (json.dumps(record, indent=2) + '\n').encode()
    require(len(raw) <= MAX_REPORT, 'Provenance report exceeds the bounded output limit')
    Path(path).write_bytes(raw)


def analyze(args):
    require(sys.platform == 'darwin' and os.geteuid() == 0,
            'Original APFS inspection requires the macOS CI host and root image reads')
    require(re.fullmatch('[0-9a-f]{40}', args.source_commit or '') and
            re.fullmatch('[0-9]+', args.run_id or ''), 'Missing exact CI provenance')
    repo = Path(__file__).resolve().parent
    device, upstream, work, output, tool = map(lambda p: Path(p).resolve(),
        (args.device, args.upstream, args.work, args.output, args.archive_tool))
    require(not work.exists(), 'Require a new private analysis working directory')
    require(not output.exists(), 'Require a new bounded public report directory')
    work.mkdir(parents=True, mode=0o700)
    output.mkdir(parents=True)
    record = dict(format=1, status='running', source_commit=args.source_commit,
                  workflow_run=args.run_id, target='iPhone12,1/27.0.1/24A446',
                  upstream_commit=UPSTREAM, observation=OBSERVATION,
                  associated_tested_boot_run='43674287810',
                  associated_tested_boot_sha256='044fe04ef3c959c65283b6f076951c0e1cf2f451f598e71edaa2e7f4e601177a',
                  boot_attribution='User photo follows this package; run identity is not visible in the photograph.',
                  phone_accessed=False, kernel_compiled=False, images_published=False,
                  original_files_modified=False, stages={})
    report_path = output / 'extraction.json'
    stage = 'source-validation'
    save(report_path, record)
    try:
        head = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        require(head == UPSTREAM, 'Unexpected original extraction helper revision')
        sys.path[:0] = [str(device), str(upstream / 'scripts')]
        import prepare_userland
        import prepare_data_volume as volume
        from unixnu.ipsw import Ipsw
        from unixnu import userdata
        # The known root pins were produced from raw disk_blocks(), while a
        # decoded AEA can still be a compressed UDIF container.
        config = tomllib.loads((device / 'upstream-overlay/profiles/os/ios-27.0.1-24A446-iphone12-1/profile.toml').read_text())
        require(prepare_userland.MEMBERS['Cryptex1,SystemOS'] == MEMBER,
                'Source capsule selected a different SystemOS member')
        require(tool.is_file() and not tool.is_symlink(), 'Require the resolved installed archive tool')
        require(shutil.disk_usage(work).free >= MEMBER[1] + SYSTEMOS[1] + 2 * 1024**3,
                'Insufficient space for the original SystemOS inspection')
        record['analysis_source_sha256'] = {
            name: sha(repo / name) for name in
            ('myron27-fault-extract.py', 'myron27-fault-symbolicate.py')}
        source = Ipsw(SimpleNamespace(board=config, out_root=work), config['ipsw']['url'])
        try:
            stage = 'original-manifest'
            prepare_userland.validate_manifest(source)
            require(source.info('Cryptex1,SystemOS')[:2] == MEMBER, 'Wrong SystemOS archive identity')
            record['stages'][stage] = dict(passed=True, sha256=prepare_userland.MANIFEST_SHA256)
            save(report_path, record)
            stage = 'systemos-download'
            encrypted = source.extract('Cryptex1,SystemOS')
            require(encrypted.stat().st_size == MEMBER[1], 'Incomplete original SystemOS download')
            encrypted_sha = sha(encrypted)
        finally:
            source.zip.close()
            source.stream.close()
        stage = 'systemos-decode'
        dest = work / 'decoded'
        dest.mkdir()
        print('Decoding the original SystemOS only', flush=True)
        # The archive utility can print decryption material. Never inherit its
        # stdout/stderr or put these captured bytes in reports, even on failure.
        decoded = subprocess.run([str(tool), 'fw', 'aea', str(encrypted), '--output', str(dest)],
                                 capture_output=True)
        require(decoded.returncode == 0, 'Original SystemOS AEA decode failed; private output withheld')
        image = volume.regular(dest / Path(MEMBER[0]).with_suffix('').name)
        image_sha = sha(image)
        encrypted.unlink()
        stage = 'raw-systemos-verification'
        raw = check_raw_image(image, userdata)
        record['stages'][stage] = dict(passed=True, **raw, decoded_container_bytes=image.stat().st_size,
            decoded_container_sha256=image_sha, encrypted_member=MEMBER[0],
            encrypted_member_sha256=encrypted_sha)
        save(report_path, record)
        print('PASS complete original SystemOS raw bytes match installed root', flush=True)
        stage = 'readonly-symbolication'
        with volume.attached(image, work / 'systemos-mount', True) as mounted:
            require(mounted['uuid'] == SYSTEMOS[0], 'Unexpected SystemOS volume UUID')
            caches = mounted['path'] / 'System/Library/Caches/com.apple.dyld'
            require(caches.is_dir() and not caches.is_symlink(), 'Original shared cache directory missing')
            command = [sys.executable, str(repo / 'myron27-fault-symbolicate.py'),
                       '--cache-dir', str(caches), '--output', str(output / 'symbolication.json')]
            for key, value in OBSERVATION.items():
                command += ['--' + key, value]
            result = subprocess.run(command, capture_output=True)
            if result.returncode:
                # This is our bounded parser, not the AEA utility. Retain its
                # actual failure text so another image download is not needed
                # merely to identify a parser-format error.
                diagnostic = result.stderr[-8192:].decode('utf-8', errors='replace')
                diagnostic = diagnostic.replace(str(caches), '<original-cache>').replace(str(work), '<private-work>')
                record['parser_failure'] = dict(returncode=result.returncode, stderr_tail=diagnostic)
                raise ValueError('Bounded cache symbolication failed; see parser_failure')
            analysis = checked_json(output / 'symbolication.json')
            record['stages'][stage] = dict(passed=True, readonly=True, volume_uuid=mounted['uuid'],
                report_sha256=sha(output / 'symbolication.json'), report_bytes=(output / 'symbolication.json').stat().st_size)
        require(sha(image) == image_sha, 'Original SystemOS container changed during readonly inspection')
        record['status'] = 'passed'
        record['limitations'] = [
            'Static original-cache analysis of the photographed saved state; no phone execution.',
            'The first unresolved abort is not necessarily the eventual fatal instruction.',
            'LR stripping is only an address candidate and does not authenticate its signature.']
        save(report_path, record)
        print('PASS original cache analysis; no kernel build or device access', flush=True)
    except BaseException as error:
        # Failed/partial parser output is never uploaded. Keep only this small
        # controlled failure record, even if a future parser violates its bound.
        (output / 'symbolication.json').unlink(missing_ok=True)
        record['status'] = 'failed'
        record['failed_stage'] = stage
        record['error_type'] = type(error).__name__
        # Do not serialize arbitrary exceptions or decryption subprocess output.
        save(report_path, record)
        raise RuntimeError('Fault analysis stopped at ' + stage + '; private tool output withheld') from None


def self_test():
    from types import SimpleNamespace as NS
    data = b'original raw disk test'
    pin = ('fixture', len(data), hashlib.sha256(data).hexdigest())
    def backend(chunks, size=len(data)):
        return NS(image_size=lambda _: size, disk_blocks=lambda *_: (x for x in chunks))
    assert check_raw_image('fixture', backend([data[:4], data[4:]]), pin)['sha256'] == pin[2]
    cases = [backend([data], size=len(data)+1), backend([data[:-1]]),
             backend([data + b'x']), backend([b'']), backend([b'x' * len(data)])]
    for case in cases:
        try:
            check_raw_image('fixture', case, pin)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid raw stream was accepted')
    with tempfile.TemporaryDirectory() as directory:
        p = Path(directory) / 'report.json'
        save(p, {'status': 'fixture'})
        assert checked_json(p)['status'] == 'fixture'
        p.write_bytes(b' ' * (MAX_REPORT + 1))
        try:
            checked_json(p)
        except ValueError:
            pass
        else:
            raise AssertionError('Oversized public report was accepted')
    print('PASS raw-disk identity, short/long/empty/corrupt stream rejection and bounded-report smoke checks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    for name in ('device', 'upstream', 'work', 'output', 'archive-tool'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--source-commit')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not all(getattr(args, name) is not None for name in
               ('device', 'upstream', 'work', 'output', 'archive_tool', 'source_commit', 'run_id')):
        parser.error('Extraction requires all source, output, tool and CI provenance arguments')
    analyze(args)


if __name__ == '__main__':
    main()
