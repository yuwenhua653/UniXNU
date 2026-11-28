"""Verify the exact read-only donor before adding its optional early boot task."""
from pathlib import Path
LAUNCHD_SHA256='c640246d38aaeb2d2372aff1e5aa0de59dec267f53c0dfc155f7837e717af68b'

def verify(root,launchd_sha256):
    if launchd_sha256!=LAUNCHD_SHA256:
        raise ValueError('Early task requires the analyzed original launchd')
    directory=Path(root)/'usr/libexec'
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('Early task requires the original executable directory')
    try:(directory/'HorizonSetup').lstat()
    except FileNotFoundError:pass
    else:raise ValueError('Existing original HorizonSetup must not be shadowed')
    return dict(launchd_sha256=launchd_sha256,program='/usr/libexec/HorizonSetup',
                original_path_absent=True,original_modified=False)
