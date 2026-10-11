"""The one-line installers: present, executable, syntactically valid, and consistent with the manifests and docs."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ("claude", "codex", "pi", "opencode")
SCRIPTS = [f"install-{a}.sh" for a in AGENTS]
REPO = "jinhuang712/qq-music-cli"


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_is_executable_bash(name):
    path = ROOT / name
    text = path.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert os.access(path, os.X_OK), f"{name} is not executable"
    subprocess.run(["bash", "-n", str(path)], check=True)
    # the body runs only after the whole file has been downloaded
    assert text.rstrip().endswith('main "$@"')
    assert f"QQMUSIC_REPO:-{REPO}" in text


def test_install_cli_is_identical_everywhere():
    def body(name: str) -> str:
        text = (ROOT / name).read_text()
        match = re.search(r"^install_cli\(\) \{.*?^\}", text, re.S | re.M)
        assert match, f"{name} has no install_cli()"
        return match.group(0)

    bodies = {name: body(name) for name in SCRIPTS}
    assert len(set(bodies.values())) == 1, "install_cli() drifted between scripts"


def test_plugin_names_match_manifests():
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    selector = f"{market['plugins'][0]['name']}@{market['name']}"
    for agent in ("claude", "codex"):
        assert f'plugin="{selector}"' in (ROOT / f"install-{agent}.sh").read_text()
    assert "flat-skills/qq-music-cli" in (ROOT / "install-opencode.sh").read_text()


def test_docs_point_at_real_scripts():
    raw = f"https://raw.githubusercontent.com/{REPO}/master/"
    for doc in ("README.md", "INSTALL.md", "docs/index.html"):
        text = (ROOT / doc).read_text()
        referenced = set(re.findall(re.escape(raw) + r"(install[\w-]*\.sh)", text))
        assert referenced == set(SCRIPTS), (doc, referenced)


def test_markdown_links_resolve():
    for doc in ("README.md", "INSTALL.md", "USAGE.md", "HOW-IT-WORKS.md", "DEVELOPMENT.md"):
        for target in re.findall(r"\]\(([^)#:]+)\)", (ROOT / doc).read_text()):
            assert (ROOT / target).exists(), (doc, target)
