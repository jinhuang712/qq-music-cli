"""`qqmusic match`, page links, and search needing login."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from qq_music_cli import cli, models
from qq_music_cli.cli import app
from qq_music_cli.errors import AuthError

IDS = [100_000 + i for i in range(40)]


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patched_lib(monkeypatch, lib):
    monkeypatch.setattr(cli, "_library", lambda required=True: lib)
    return lib


def out_json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_links_use_the_sites_own_form():
    song = models.song({"id": 1, "mid": "0039MnYb0qxYhV"})
    assert song["url"] == "https://y.qq.com/n/ryqq_v2/songDetail/0039MnYb0qxYhV"
    assert models.playlist({"tid": 42})["url"] == "https://y.qq.com/n/ryqq_v2/playlist/42"
    assert (
        models.faved_album({"mid": "000MkMni19ClKG"})["url"] == "https://y.qq.com/n/ryqq_v2/albumDetail/000MkMni19ClKG"
    )
    assert models.song({"id": 1})["url"] is None


def test_url_is_opt_in_on_lists(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:2])
    plain = out_json(runner.invoke(app, ["show", "Mix"]))
    assert "url" not in plain["songs"][0] and plain["playlist"]["url"].endswith(str(server.by_name("Mix")["tid"]))
    linked = out_json(runner.invoke(app, ["show", "Mix", "--fields", "name,url"]))
    assert linked["songs"][0]["url"].startswith("https://y.qq.com/n/ryqq_v2/songDetail/")


def test_match_counts_public_lists_and_skips_own(runner, patched_lib, server):
    server.add_playlist("City", IDS[:5])
    server.add_playlist("Citypop mine", IDS[5:8])  # own playlist that also matches the search
    server.by_dir(201)["songs"] = [IDS[0], IDS[30]]
    server.public = {
        9101: {
            "title": "Best City Pop",
            "listennum": 1,
            "desc": "",
            "tag": [],
            "songs": [IDS[0], IDS[1], IDS[30], 101_500],
        },
        9102: {"title": "city pop night", "listennum": 1, "desc": "", "tag": [], "songs": [IDS[0], IDS[0], IDS[6]]},
    }
    out = out_json(runner.invoke(app, ["match", "city pop"]))
    assert [x["name"] for x in out["lists"]] == ["Best City Pop", "city pop night"]
    hits = {m["id"]: m for m in out["matches"]}
    assert hits[IDS[0]]["hits"] == 2  # counted once per list, even when a list repeats it
    assert sorted(hits[IDS[0]]["in"]) == ["City", "我喜欢"]
    assert hits[IDS[30]]["hits"] == 1 and hits[IDS[6]]["in"] == ["Citypop mine"]
    assert list(out["matches"][0]) == list(models.MATCH_DEFAULT)
    strong = out_json(runner.invoke(app, ["match", "city pop", "--min-hits", "2"]))
    assert [m["id"] for m in strong["matches"]] == [IDS[0]]


def test_search_needs_login(runner, monkeypatch):
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", "/nonexistent/cred.json")
    result = runner.invoke(app, ["search", "x"])
    assert isinstance(result.exception, AuthError)


def test_match_takes_several_keywords_and_reads_each_list_once(runner, patched_lib, server):
    server.add_playlist("City", IDS[:3])
    server.public = {
        9101: {"title": "Best City Pop", "listennum": 1, "desc": "", "tag": [], "songs": [IDS[0]]},
        9102: {"title": "Korean city pop", "listennum": 1, "desc": "", "tag": [], "songs": [IDS[0], IDS[1]]},
    }
    out = out_json(runner.invoke(app, ["match", "city pop", "korean"]))
    assert out["keywords"] == ["city pop", "korean"] and len(out["lists"]) == 2  # 9102 matched both keywords
    assert {m["id"]: m["hits"] for m in out["matches"]} == {IDS[0]: 2, IDS[1]: 1}
