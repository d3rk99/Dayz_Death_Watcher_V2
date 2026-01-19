from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
import json
import shutil


@dataclass
class LogEvent:
    server_id: str
    raw: str
    data: Optional[dict]


@dataclass
class TailerOptions:
    tail_mode: str = "newest_only"
    backlog_max_lines: int = 200
    strict_death_schema: bool = True
    archive_old_logs: bool = False


class LjsonTailer:
    def __init__(self, logs_dir: Path, cursor: int = 0, options: Optional[TailerOptions] = None) -> None:
        self.logs_dir = logs_dir
        self.cursor = cursor
        self.active_file: Optional[Path] = None
        self.options = options or TailerOptions()
        self._partial_line: Optional[str] = None

    def _find_latest_file(self) -> Optional[Path]:
        if not self.logs_dir.exists():
            return None
        candidates = sorted(self.logs_dir.glob("dl_*.ljson"), key=lambda p: p.stat().st_mtime)
        return candidates[-1] if candidates else None

    def _archive_if_needed(self, previous: Optional[Path]) -> None:
        if not previous or not self.options.archive_old_logs:
            return
        archive_dir = self.logs_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(previous), archive_dir / previous.name)

    def _initialize_cursor(self, file_path: Path) -> None:
        if self.cursor > 0:
            return
        if self.options.tail_mode == "newest_only":
            self.cursor = file_path.stat().st_size
            return
        if self.options.backlog_max_lines <= 0:
            self.cursor = file_path.stat().st_size
            return
        self.cursor = self._tail_offset(file_path, self.options.backlog_max_lines)

    def _tail_offset(self, file_path: Path, lines: int) -> int:
        with file_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            if size == 0:
                return 0
            block_size = 1024
            buffer = b""
            position = size
            while position > 0 and buffer.count(b"\n") <= lines:
                step = min(block_size, position)
                position -= step
                handle.seek(position)
                buffer = handle.read(step) + buffer
            if buffer.count(b"\n") < lines:
                return 0
            idx = len(buffer)
            for _ in range(lines):
                idx = buffer.rfind(b"\n", 0, idx)
            return position + idx + 1

    def ensure_latest(self) -> bool:
        latest = self._find_latest_file()
        if latest is None:
            return False
        if self.active_file != latest:
            previous = self.active_file
            self.active_file = latest
            self.cursor = 0
            self._partial_line = None
            self._initialize_cursor(latest)
            self._archive_if_needed(previous)
        return True

    def read_events(self, server_id: str) -> Iterator[LogEvent]:
        if not self.ensure_latest() or self.active_file is None:
            return
        with self.active_file.open("r", encoding="utf-8") as handle:
            handle.seek(self.cursor)
            while True:
                line = handle.readline()
                if not line:
                    break
                self.cursor = handle.tell()
                if not line.endswith("\n"):
                    self._partial_line = (self._partial_line or "") + line
                    continue
                combined = (self._partial_line or "") + line
                self._partial_line = None
                line = combined.strip()
                if not line:
                    continue
                data = None
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    pass
                yield LogEvent(server_id=server_id, raw=line, data=data)


def parse_death_event(event: LogEvent, strict_schema: bool = True) -> Optional[dict]:
    if not event.data:
        return None
    if event.data.get("event") != "PLAYER_DEATH":
        return None
    player = event.data.get("player", {})
    steam_id = player.get("steamId") or event.data.get("steamId")
    if not steam_id:
        return None
    if strict_schema:
        if event.data.get("player") is None:
            return None
        if player.get("dead") is not True:
            return None
    return {
        "steam_id": steam_id,
        "alive_sec": player.get("aliveSec") or event.data.get("aliveSec"),
        "raw": event.data,
    }
