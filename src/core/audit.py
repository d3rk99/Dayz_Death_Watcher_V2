from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import json


@dataclass
class AuditEvent:
    event: str
    message: str
    context: Dict[str, Any]

    def to_line(self) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": self.event,
            "message": self.message,
            "context": self.context,
        }
        return json.dumps(payload, ensure_ascii=False)


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: AuditEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_line() + "\n")
