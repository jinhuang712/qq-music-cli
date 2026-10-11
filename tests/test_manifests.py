"""The plugin ships one skill plus a manifest per agent; keep names, versions and links in sync."""

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import qq_music_cli

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "cli"  # namespaced channels: Claude Code, Codex -> qq-music:cli
FLAT_DIR = ROOT / "flat-skills" / "qq-music-cli"  # flat channels: Pi, OpenCode -> qq-music-cli
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")  # OpenCode / Pi / Agent Skills rule


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def frontmatter(skill_dir: Path = SKILL_DIR) -> dict[str, Any]:
    """Top-level `key: value` lines, plus one level of nesting (used by `metadata:`)."""
    text = (skill_dir / "SKILL.md").read_text()
    block = text.split("---", 2)[1]
    out: dict[str, Any] = {}
    parent = None
    for line in block.strip().splitlines():
        if line.startswith("  ") and parent:
            key, value = line.strip().split(": ", 1)
            out[parent][key] = value
        elif line.endswith(":"):
            parent = line[:-1]
            out[parent] = {}
        else:
            key, value = line.split(": ", 1)
            out[key], parent = value, None
    return out


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


def test_display_name_keeps_qq_uppercase():
    # UIs title-case the kebab name `qq-music` into "Qq Music"; displayName overrides that.
    assert load(".claude-plugin/plugin.json")["displayName"] == "QQ Music"
    assert load(".claude-plugin/marketplace.json")["plugins"][0]["displayName"] == "QQ Music"
    assert "displayName" not in load("plugin.json")  # agent-plugins.org schema forbids extra keys


def test_pi_package_points_at_skills():
    pkg = load("package.json")
    assert "pi-package" in pkg["keywords"]
    assert pkg["pi"]["skills"] == ["./flat-skills"]
    assert pkg["private"] is True


CORE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}  # Agent Skills


def test_skill_frontmatter_is_portable():
    for skill_dir in (SKILL_DIR, FLAT_DIR):
        fm = frontmatter(skill_dir)
        # The core set, plus the one extension Claude Code and Pi read (see the next test).
        assert set(fm) <= CORE_KEYS | {"disable-model-invocation"}
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


def test_skill_only_loads_when_the_user_asks():
    # Claude Code and Pi: hidden from the model, still a slash command.
    assert frontmatter(SKILL_DIR)["disable-model-invocation"] == "true"
    assert frontmatter(FLAT_DIR)["disable-model-invocation"] == "true"
    # Codex: explicit `$` mention only.
    policy = (SKILL_DIR / "agents" / "openai.yaml").read_text()
    assert "policy:\n  allow_implicit_invocation: false" in policy
    # OpenCode: out of <available_skills>, offered as /qq-music-cli.
    assert frontmatter(FLAT_DIR)["metadata"] == {"opencode/autoinvoke": '"false"', "opencode/slash": '"true"'}
    assert "metadata" not in frontmatter(SKILL_DIR)


def test_skill_greets_on_a_bare_load():
    text = (SKILL_DIR / "SKILL.md").read_text()
    assert "QQ 音乐 CLI 工具已加载，你想要做什么？" in text and "🎵" in text
