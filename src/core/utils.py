from __future__ import annotations

from pathlib import Path
from typing import Iterable
import os

from .locks import file_lock_for


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)


def read_lines(path: Path) -> Iterable[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def atomic_write_locked(path: Path, content: str) -> None:
    lock = file_lock_for(path)
    with lock:
        atomic_write(path, content)


def read_lines_locked(path: Path) -> Iterable[str]:
    lock = file_lock_for(path)
    with lock:
        return read_lines(path)
