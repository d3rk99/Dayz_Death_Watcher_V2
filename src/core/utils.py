from __future__ import annotations

from pathlib import Path
from typing import Iterable
import os


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
