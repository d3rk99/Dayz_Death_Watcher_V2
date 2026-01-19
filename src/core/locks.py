from __future__ import annotations

from pathlib import Path
from filelock import FileLock


def file_lock_for(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock")
