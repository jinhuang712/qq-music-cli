"""The plugin ships one skill plus a manifest per agent; keep names, versions and links in sync."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import qq_music_cli

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "cli"  # namespaced channels: Claude Code, Codex -> qq-music:cli
FLAT_DIR = ROOT / "flat-skills" / "qq-music-cli"  # flat channels: Pi, OpenCode -> qq-music-cli
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # OpenCode / Pi / Agent Skills rule


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def frontmatter(skill_dir: Path = SKILL_DIR) -> dict[str, str]:
    text = (skill_dir / "SKILL.md").read_text()
    block = text.split("---", 2)[1]
    return dict(line.split(": ", 1) for line in block.strip().splitlines())


def test_versions_and_names_match():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert qq_music_cli.__version__ == version
    for rel in (".claude-plugin/plugin.json", "plugin.json", "package.json"):
        data = load(rel)
        assert data["name"] == "qq-music", rel
        assert data["version"] == version, rel
    market = load(".claude-plugin/marketplace.json")
    assert market["name"] == "qq-music"
    assert [p["name"] for p in market["plugins"]] == ["qq-music"]
    assert market["plugins"][0]["source"] == "./"


def test_license_is_mit_everywhere():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["license"] == "MIT"
    for rel in (".claude-plugin/plugin.json", "plugin.json", "package.json"):
        assert load(rel)["license"] == "MIT", rel


def test_pi_package_points_at_skills():
    pkg = load("package.json")
    assert "pi-package" in pkg["keywords"]
    assert pkg["pi"]["skills"] == ["./flat-skills"]
    assert pkg["private"] is True


def test_skill_frontmatter_is_portable():
    for skill_dir in (SKILL_DIR, FLAT_DIR):
        fm = frontmatter(skill_dir)
        # Only keys every agent accepts (Agent Skills core set).
        assert set(fm) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
        assert fm["name"] == skill_dir.name and NAME_RE.match(fm["name"])  # OpenCode requires name == dir
        assert 1 <= len(fm["description"]) <= 1024
        assert len(fm.get("compatibility", "")) <= 500


def test_flat_skill_is_in_sync_with_source():
    spec = importlib.util.spec_from_file_location("sync_flat_skill", ROOT / "scripts" / "sync_flat_skill.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    hint = "run: uv run python scripts/sync_flat_skill.py"
    assert (FLAT_DIR / "SKILL.md").read_text() == sync.render_skill((SKILL_DIR / "SKILL.md").read_text()), hint

    def files(base: Path) -> dict:
        return {p.relative_to(base): p.read_bytes() for p in base.rglob("*") if p.is_file()}

    assert files(SKILL_DIR / "references") == files(FLAT_DIR / "references"), hint


def test_each_channel_sees_exactly_one_skill():
    # Claude Code and Codex auto-discover ./skills; Pi reads package.json pi.skills; OpenCode gets a symlink.
    assert sorted(p.parent.name for p in (ROOT / "skills").rglob("SKILL.md")) == ["cli"]
    assert sorted(p.parent.name for p in (ROOT / "flat-skills").rglob("SKILL.md")) == ["qq-music-cli"]


def test_skill_links_resolve():
    text = (SKILL_DIR / "SKILL.md").read_text()
    links = re.findall(r"\]\(([^)#]+\.md)\)", text)
    assert links, "SKILL.md should link its reference files"
    for link in links:
        assert (SKILL_DIR / link).is_file(), link
    assert len(text.splitlines()) < 500
