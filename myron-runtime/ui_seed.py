"""Invalidate only MobileGestalt answers on a newly prepared owned Data seed."""
from pathlib import Path
PATHS=('containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist',
       'mobile/Library/Preferences/com.apple.MobileGestalt.plist',
       'mobile/Library/Preferences/com.apple.mobilegestalt.plist')
def clear(root):
    root=Path(root);removed=[]
    for relative in PATHS:
        path=root
        for name in Path(relative).parts:
            path/=name
            if path.is_symlink():raise ValueError('Symlink in MobileGestalt seed cache path')
        if path.exists():
            if not path.is_file():raise ValueError('Non-file MobileGestalt cache')
            path.unlink();removed.append(relative)
    return removed
