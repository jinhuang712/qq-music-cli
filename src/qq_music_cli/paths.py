"""Local data locations. Everything lives under one directory so a run is easy to inspect or wipe."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """`$QQMUSIC_CLI_HOME`, else `$XDG_DATA_HOME/qq-music-cli`, else `~/.local/share/qq-music-cli`."""
    if home := os.environ.get("QQMUSIC_CLI_HOME"):
        root = Path(home).expanduser()
    else:
        base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
        root = Path(base).expanduser() / "qq-music-cli"
    os.makedirs(root, exist_ok=True)
    return root


def runs_dir() -> Path:
    return _subdir("runs")


def exports_dir() -> Path:
    return _subdir("exports")


def _subdir(name: str) -> Path:
    path = data_dir() / name
    os.makedirs(path, exist_ok=True)
    return path
