"""Write-ahead run log. Every write command records what it actually changed, so `qqmusic undo` can reverse it.

The log is flushed after each operation, so an interrupted run still shows what was applied.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import UsageError
from .paths import runs_dir


_last_ns = 0


def _created_ns() -> int:
    """Strictly increasing within a process; time.time_ns() can repeat on macOS (microsecond clock)."""
    global _last_ns
    _last_ns = max(time.time_ns(), _last_ns + 1)
    return _last_ns


class RunLog:
    def __init__(self, command: str, *, directory: Path | None = None, dry_run: bool = False) -> None:
        self.directory = directory or runs_dir()
        self.dry_run = dry_run
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.run_id = f"{stamp}-{secrets.randbelow(16**6):06x}"
        self.data: dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": int(time.time()),
            "created_ns": _created_ns(),
            "command": command,
            "ops": [],
        }

    @property
    def path(self) -> Path:
        return self.directory / f"{self.run_id}.json"

    def record(self, op: dict[str, Any]) -> None:
        if self.dry_run:
            return
        self.data["ops"].append(op)
        self._flush()

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)

    @property
    def has_ops(self) -> bool:
        return bool(self.data["ops"])


def list_runs(limit: int = 20, directory: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or runs_dir()
    loaded = [json.loads(p.read_text()) for p in directory.glob("*.json")]
    loaded.sort(key=lambda d: (d.get("created_ns", d["created_at"] * 10**9), d["run_id"]), reverse=True)
    out = []
    for data in loaded[:limit]:
        out.append(
            {
                "run_id": data["run_id"],
                "created_at": data["created_at"],
                "command": data["command"],
                "ops": [_op_summary(op) for op in data["ops"]],
                "undone_by": data.get("undone_by"),
            }
        )
    return out


def load_run(run_id: str, directory: Path | None = None) -> dict[str, Any]:
    directory = directory or runs_dir()
    path = directory / f"{run_id}.json"
    if not path.exists():
        raise UsageError(f"no such run: {run_id}")
    return json.loads(path.read_text())


def mark_undone(run_id: str, undo_run_id: str, directory: Path | None = None) -> None:
    directory = directory or runs_dir()
    path = directory / f"{run_id}.json"
    data = json.loads(path.read_text())
    data["undone_by"] = undo_run_id
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _op_summary(op: dict[str, Any]) -> str:
    name = op.get("playlist", {}).get("name")
    kind = op["op"]
    if kind in ("add", "remove"):
        return f"{kind} {len(op.get('songs', []))} song(s) {'to' if kind == 'add' else 'from'} {name!r}"
    if kind == "edit":
        return f"edit playlist {op['before']['name']!r} -> {op['after']['name']!r}"
    return f"{kind} playlist {name!r}"
