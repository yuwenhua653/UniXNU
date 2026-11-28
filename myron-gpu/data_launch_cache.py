"""Add exactly one owner job to the hash-pinned, otherwise unchanged iOS cache."""
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import zipfile

ORIGINAL_SHA256 = '5e0c65cf8ee4e6551325afdc4c283c350281d98e14f67b45bc55acfa536ae6e1'
ORIGINAL_BYTES = 2474924
JOB_PATH = '/System/Library/LaunchDaemons/org.unixnu.myron.data-grow.plist'
ADDON_PATH = 'addons/myron-data-xpc/launchd.plist'
LABEL = 'org.unixnu.myron.data-grow'


def require(ok, why):
    if not ok:
        raise ValueError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def daemon():
    return dict(Label=LABEL,
        ProgramArguments=['/private/var/ngpu/addons/myron-data-grow', '--grow'],
        UserName='root', RunAtLoad=True, KeepAlive=False, ProcessType='Background',
        StandardOutPath='/private/var/root/myron-data-grow.log',
        StandardErrorPath='/private/var/root/myron-data-grow.err')


def add_job(root):
    require(isinstance(root, dict), 'Launch cache must be a dictionary')
    jobs = root.get('LaunchDaemons')
    require(isinstance(jobs, dict) and 0 < len(jobs) < 8192,
            'Unexpected LaunchDaemons cache shape')
    require(JOB_PATH not in jobs, 'Owner job already exists')
    for path, job in jobs.items():
        require(isinstance(path, str) and path.startswith('/') and
                isinstance(job, dict), 'Unexpected cached job entry')
        require(isinstance(job.get('Label'), str) and 0 < len(job['Label']) <= 512,
                'Cached jobs must use the direct launchd plist schema')
        require(job.get('Label') != LABEL, 'Owner label collides with existing job')
    result = copy.deepcopy(root)
    result['LaunchDaemons'][JOB_PATH] = daemon()
    return result


def verify_delta(original, candidate):
    require(isinstance(candidate, dict) and isinstance(candidate.get('LaunchDaemons'), dict),
            'Invalid merged cache')
    canonical = lambda value: plistlib.dumps(value, fmt=plistlib.FMT_BINARY, sort_keys=True)
    require(JOB_PATH in candidate['LaunchDaemons'] and
            canonical(candidate['LaunchDaemons'][JOB_PATH]) == canonical(daemon()), 'Changed owner job')
    restored = copy.deepcopy(candidate)
    del restored['LaunchDaemons'][JOB_PATH]
    # Python equality conflates bool and int; plist consumers distinguish them.
    require(canonical(restored) == canonical(original), 'Original system cache entries changed')


def build(original):
    require(len(original) == ORIGINAL_BYTES and sha(original) == ORIGINAL_SHA256,
            'Wrong original iPhone12,1/24A446 launch cache')
    root = plistlib.loads(original)
    candidate = add_job(root)
    raw = plistlib.dumps(candidate, fmt=plistlib.FMT_BINARY, sort_keys=True)
    verify_delta(root, plistlib.loads(raw))
    report = dict(format=1, original_sha256=sha(original), original_bytes=len(original),
        merged_sha256=sha(raw), merged_bytes=len(raw),
        original_job_count=len(root['LaunchDaemons']), merged_job_count=len(candidate['LaunchDaemons']),
        added_job=JOB_PATH, original_entries_preserved=True, phone_tested=False,
        helper_executed=False, apfs_resized=False)
    return raw, report


def prepare(original_path, out):
    original = Path(original_path).read_bytes()
    raw, report = build(original)
    out = Path(out)
    require(out.is_dir() and not any(out.glob('*launchd.plist')), 'Fresh cache output required')
    # The unmodified firmware plist permits independent readback/delta checking.
    # Neither file comes from a phone or contains user Data.
    (out/'original-launchd.plist').write_bytes(original)
    (out/'launchd.plist').write_bytes(raw)
    (out/'cache-build.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def load_archive(archive, identity):
    raw = Path(archive).read_bytes()
    require(sha(raw) == identity['artifact_sha256'], 'Wrong service-cache artifact')
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == 3 and set(names) == {
            'original-launchd.plist', 'launchd.plist', 'cache-build.json'}, 'Service-cache inventory')
        original = z.read('original-launchd.plist')
        merged = z.read('launchd.plist')
        record = json.loads(z.read('cache-build.json'))
    expected, report = build(original)
    require(merged == expected, 'Service cache differs from exact one-job merge')
    require(all(record.get(k) == v for k, v in report.items()), 'Service-cache audit mismatch')
    require(record.get('source_commit') == identity['commit'], 'Service-cache source mismatch')
    return {ADDON_PATH: (0o644, merged)}
