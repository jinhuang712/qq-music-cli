"""`--fields` selection, the opt-in fields that cost extra calls, and `qqmusic album`."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from qq_music_cli import cli, models
from qq_music_cli.cli import app
from qq_music_cli.errors import UsageError

IDS = [100_000 + i for i in range(10)]


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


# -- select_fields ----------------------------------------------------------------------------------


def test_select_fields_grammar():
    default, available = ("a", "b"), ("a", "b", "c", "d")
    assert models.select_fields(None, default, available) == ["a", "b"]
    assert models.select_fields("  ", default, available) == ["a", "b"]
    assert models.select_fields("c,a", default, available) == ["c", "a"]
    assert models.select_fields("+d, c", default, available) == ["a", "b", "d", "c"]
    assert models.select_fields("+a", default, available) == ["a", "b"]
    assert models.select_fields("all", default, available) == ["a", "b", "c", "d"]


def test_select_fields_unknown_lists_available():
    with pytest.raises(UsageError) as e:
        models.select_fields("a,nope", ("a",), ("a", "b"))
    assert e.value.exit_code == 2
    assert "nope" in e.value.message and "Available: a, b" in e.value.message


# -- songs -----------------------------------------------------------------------------------------


def test_song_model_extra_fields():
    s = models.song(
        {
            "id": 1,
            "bpm": 87,
            "mv": {"vid": "w0026q7f01a"},
            "file": {"size_320mp3": 5, "size_flac": 9, "size_hires": 0, "size_dolby": 3},
            "index_album": 2,
            "album": {"mid": "000MkMni19ClKG", "name": "叶惠美"},
        }
    )
    assert s["bpm"] == 87 and s["mv"] == "w0026q7f01a" and s["track_no"] == 2
    assert s["qualities"] == ["320k", "flac", "dolby"]
    assert s["cover"] == "https://y.gtimg.cn/music/photo_new/T002R300x300M000000MkMni19ClKG.jpg"
    empty = models.song({"id": 1, "bpm": 0, "mv": {"vid": ""}})
    assert empty["bpm"] is None and empty["mv"] is None and empty["qualities"] == [] and empty["cover"] is None


def test_show_default_plus_and_all(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:3])
    songs = out_json(runner.invoke(app, ["show", "Mix"]))["songs"]
    assert list(songs[0]) == list(models.SONG_DEFAULT)
    plus = out_json(runner.invoke(app, ["show", "Mix", "--fields", "+bpm,qualities"]))["songs"]
    assert list(plus[1]) == [*models.SONG_DEFAULT, "bpm", "qualities"]
    assert plus[1]["bpm"] == 90 and plus[1]["qualities"] == ["320k", "flac"]
    every = out_json(runner.invoke(app, ["show", "Mix", "--fields", "all"]))["songs"]
    assert list(every[0]) == list(models.SONG_FIELDS)


def test_unknown_field_is_usage_error(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:1])
    result = runner.invoke(app, ["show", "Mix", "--fields", "+nope"])
    assert isinstance(result.exception, UsageError)
    assert server.calls_to("uniform_get_Dissinfo") == []  # rejected before any request


def test_song_detail_fields_fetch_only_when_asked(runner, patched_lib, server):
    plain = out_json(runner.invoke(app, ["song", str(IDS[0])]))
    assert list(plain[0]) == list(models.SONG_DEFAULT)
    assert server.calls_to("get_song_detail_yqq") == []
    detail = out_json(runner.invoke(app, ["song", str(IDS[0]), "--detail"]))
    assert list(detail[0]) == [*models.SONG_DEFAULT, *models.SONG_DETAIL_DEFAULT]
    intro = out_json(runner.invoke(app, ["song", str(IDS[0]), "--fields", "name,intro,trans_name"]))
    assert intro == [{"name": f"Song {IDS[0]}", "intro": "About it.", "trans_name": "Translated"}]
    assert len(server.calls_to("get_song_detail_yqq")) == 2


def test_search_non_song_types_keep_free_fields(runner, patched_lib, server, monkeypatch):
    monkeypatch.setattr(
        patched_lib,
        "search",
        lambda q, kind, page, limit: {"results": [{"tid": 1, "name": "x", "listen_count": 5}]},
    )
    out = out_json(runner.invoke(app, ["search", "x", "--type", "playlist", "--fields", "name,listen_count"]))
    assert out["results"] == [{"name": "x", "listen_count": 5}]


# -- playlists -------------------------------------------------------------------------------------


def test_playlists_extra_fields_cost_requests_only_when_asked(runner, patched_lib, server):
    for i in range(12):
        server.add_playlist(f"P{i}", IDS[: i % 3])
    server.by_name("P1")["desc"] = "my notes"
    pls = out_json(runner.invoke(app, ["playlists"]))
    assert list(pls[0]) == list(models.PLAYLIST_DEFAULT)
    assert server.calls_to("uniform_get_Dissinfo") == []

    pls = out_json(runner.invoke(app, ["playlists", "--fields", "name,listen_count,desc,tags"]))
    reads = server.calls_to("uniform_get_Dissinfo")
    assert len(reads) == 13 and all(r["song_num"] == 1 and r["tag"] == 1 for r in reads)
    p1 = next(p for p in pls if p["name"] == "P1")
    assert p1 == {"name": "P1", "listen_count": 10, "desc": "my notes", "tags": ["R&B", "Chill"]}


def test_show_header_has_tags_and_listen_count_for_any_playlist(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:2])
    own = out_json(runner.invoke(app, ["show", "Mix"]))["playlist"]
    assert own["tags"] == ["R&B", "Chill"] and own["listen_count"] == 20
    public = out_json(runner.invoke(app, ["show", "9001"]))["playlist"]
    assert public["tags"] == ["R&B"] and public["listen_count"] == 4820 and public["desc"] == "a long story"


def test_faved_playlists_extras(runner, patched_lib, server):
    plain = out_json(runner.invoke(app, ["faved", "playlists"]))
    assert list(plain[0]) == list(models.FAVED_PLAYLIST_DEFAULT)
    assert server.calls_to("uniform_get_Dissinfo") == []
    more = out_json(runner.invoke(app, ["faved", "playlists", "--fields", "name,listen_count,tags,cover"]))
    assert more == [{"name": "Someone's Mix", "listen_count": 4820, "tags": ["R&B"], "cover": "http://x"}]


def test_export_keeps_every_field(lib, server):
    server.add_playlist("Mix", IDS[:2])
    server.add_playlist("Empty")
    data = lib.export()
    mix = next(p for p in data["playlists"] if p["name"] == "Mix")
    empty = next(p for p in data["playlists"] if p["name"] == "Empty")
    assert mix["listen_count"] == 20 and mix["desc"] is None and mix["cover"]
    assert empty["listen_count"] == 0 and "tags" in empty
    assert set(mix["songs"][0]) == set(models.SONG_FIELDS)
    assert data["faved_playlists"][0]["listen_count"] == 4820


# -- album -----------------------------------------------------------------------------------------


def test_album_pages_and_limits(runner, patched_lib, server):
    out = out_json(runner.invoke(app, ["album", "ALBUM000000001"]))
    assert out["album"]["name"] == "Album 77" and out["album"]["company"] == "Label"
    assert out["album"]["song_count"] == 60 and len(out["album"]["desc"]) == 3000
    assert out["count"] == 60 and out["complete"] is True
    assert list(out["songs"][0]) == list(models.SONG_DEFAULT)
    assert len(server.calls_to("GetAlbumDetail")) == 1
    assert [c["begin"] for c in server.calls_to("GetAlbumSongList")] == [0, 50]

    short = out_json(runner.invoke(app, ["album", "ALBUM000000001", "--limit", "5", "--fields", "id,type"]))
    assert short["count"] == 5 and short["complete"] is True and short["songs"][0] == {"id": IDS[0], "type": 0}


def test_album_bad_mid(runner, patched_lib, server):
    assert isinstance(runner.invoke(app, ["album", "not-a-mid"]).exception, UsageError)
    assert server.calls == []
    assert isinstance(runner.invoke(app, ["album", "ALBUM000000404"]).exception, UsageError)


def test_album_output_pipes_into_add(runner, patched_lib, server):
    server.add_playlist("From Album")
    doc = runner.invoke(app, ["album", "ALBUM000000001", "--limit", "3", "--fields", "id,type"]).stdout
    added = out_json(runner.invoke(app, ["add", "From Album", "--stdin"], input=doc))
    assert len(added["added"]) == 3
