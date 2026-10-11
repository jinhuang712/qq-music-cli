"""Regenerate the flat-channel copy of the skill from its source.

Claude Code and Codex namespace plugin skills, so `skills/cli` shows as `qq-music:cli` there.
Pi and OpenCode do not, so they get `flat-skills/qq-music-cli`, which is the same skill
with a self-describing name. Edit `skills/cli`, then run:

    uv run python scripts/sync_flat_skill.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skills" / "cli"
FLAT_NAME = "qq-music-cli"
TARGET = ROOT / "flat-skills" / FLAT_NAME


def render_skill(source_text: str) -> str:
    head, sep, rest = source_text.partition("\nname: cli\n")
    if not sep:
        raise SystemExit("skills/cli/SKILL.md must contain the line `name: cli` in its frontmatter")
    return f"{head}\nname: {FLAT_NAME}\n{rest}"


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)
    (TARGET / "SKILL.md").write_text(render_skill((SOURCE / "SKILL.md").read_text()))
    shutil.copytree(SOURCE / "references", TARGET / "references")
    print(f"wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
