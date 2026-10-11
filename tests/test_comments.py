"""Comments and comment counts, against the fake server."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from qq_music_cli import cli, models
from qq_music_cli.cli import app
from qq_music_cli.errors import UsageError

IDS = [100_000 + i for i in range(30)]


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


def test_hot_comments_page_until_the_list_ends(lib, server):
    server.hot_comments = 30
    out = lib.comments("song", str(IDS[0]), limit=50)
    assert out["order"] == "hot" and out["count"] == 30 and out["listed"] == 30
    assert out["total_comments"] == 1000 + IDS[0] % 1000
    assert out["target"]["kind"] == "song" and out["target"]["name"] == f"Song {IDS[0]}"
    calls = server.calls_to("GetHotCommentList")
    assert [c["PageNum"] for c in calls] == [0, 1] and all(c["BizType"] == 1 for c in calls)


def test_newest_comments_respect_limit(lib, server):
    out = lib.comments("song", str(IDS[0]), newest=True, limit=25)
    assert out["order"] == "newest" and out["count"] == 25
    assert [c["LastCommentSeqNo"] for c in server.calls_to("GetNewCommentList")] == ["", "s19"]


def test_album_and_playlist_targets(lib, server):
    album = lib.comments("album", "ALBUM000000001", limit=3)
    assert album["target"]["id"] == 77 and server.calls_to("GetHotCommentList")[-1]["BizType"] == 2
    server.add_playlist("Mix", IDS[:2])
    pl = lib.comments("playlist", "Mix", limit=3)
    assert pl["target"]["name"] == "Mix" and server.calls_to("GetHotCommentList")[-1]["BizType"] == 3
    with pytest.raises(UsageError):
        lib.comments("singer", "x")
    with pytest.raises(UsageError):
        lib.comments("album", "not-a-mid")


def test_comments_cli_default_fields(runner, patched_lib, server):
    out = out_json(runner.invoke(app, ["comments", "songs", str(IDS[0]), "--limit", "2"]))
    assert [list(c) for c in out["comments"]] == [list(models.COMMENT_DEFAULT)] * 2
    more = out_json(runner.invoke(app, ["comments", "song", str(IDS[0]), "--limit", "1", "--fields", "+user"]))
    assert more["comments"][0]["user"] == "user0"


def test_comment_count_only_when_asked(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:12])
    plain = out_json(runner.invoke(app, ["show", "Mix"]))
    assert "comment_count" not in plain["songs"][0] and server.calls_to("GetNewCommentList") == []
    counted = out_json(runner.invoke(app, ["show", "Mix", "--fields", "name,comment_count"]))
    assert counted["songs"][0] == {"name": f"Song {IDS[0]}", "comment_count": 1000 + IDS[0] % 1000}
    calls = server.calls_to("GetNewCommentList")
    assert len(calls) == 12 and all(c["PageSize"] == 1 for c in calls)
    assert server.calls_to("GetHotCommentList") == []  # counts never touch the hot list
    song = out_json(runner.invoke(app, ["song", str(IDS[3]), "--fields", "+comment_count"]))
    assert song[0]["comment_count"] == 1000 + IDS[3] % 1000


def test_album_header_has_its_comment_count(runner, patched_lib, server):
    out = out_json(runner.invoke(app, ["album", "ALBUM000000001", "--limit", "1"]))
    assert out["album"]["comment_count"] == 1077


def test_one_refused_song_does_not_sink_the_counts(runner, patched_lib, server):
    server.add_playlist("Mix", IDS[:3])
    server.closed_comments.add(str(IDS[1]))
    out = out_json(runner.invoke(app, ["show", "Mix", "--fields", "name,comment_count"]))
    assert [s["comment_count"] for s in out["songs"]] == [1000 + IDS[0] % 1000, None, 1000 + IDS[2] % 1000]
    refused = runner.invoke(app, ["comments", "song", str(IDS[1])])
    assert "20022" in refused.exception.message


def test_auth_errors_still_raise_inside_a_batch(lib, server, monkeypatch):
    from qq_music_cli.errors import AuthError

    from conftest import SlotError

    def expired(p):
        raise SlotError(1000)

    monkeypatch.setattr(server, "rpc_GetNewCommentList", expired)
    with pytest.raises(AuthError):
        lib.comment_counts("song", IDS[:2])


def test_counting_then_reading_hot_comments(runner, patched_lib, server):
    # The sequence an agent used live: count first, then read the hot list.
    out_json(runner.invoke(app, ["song", str(IDS[0]), "--fields", "+comment_count"]))
    hot = out_json(runner.invoke(app, ["comments", "song", str(IDS[0])]))
    assert hot["count"] == 12
