"""Collecting playlists and albums, and a playlist's visibility and cover, against the fake server."""

from __future__ import annotations

import json
import shutil
import struct
import zlib

import pytest
from typer.testing import CliRunner

from qq_music_cli import cli, cover, runs
from qq_music_cli.cli import app
from qq_music_cli.errors import UsageError

ALBUM = "ALBUM000000001"


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


# -- 收藏 -------------------------------------------------------------------------------------------


def test_fav_and_unfav_playlist_read_back_and_undo(lib, server, new_run):
    run = new_run()
    result = lib.set_faved("playlist", [8001, 8001, 9001], on=True, run=run)
    assert result["already"] == [9001] and result["changed"] == [8001] and result["not_changed"] == []
    assert server.calls_to("FavPlaylist") == [{"uin": lib.uin, "v_playlistId": [8001]}]
    assert run.data["ops"] == [{"op": "fav", "kind": "playlist", "items": [8001]}]
    assert runs._op_summary(run.data["ops"][0]) == "fav 1 playlist(s)"

    undone = lib.undo(run.data, run=new_run())
    assert undone == [{"undo": "fav", "kind": "playlist", "restored": [8001]}]
    assert {f["tid"] for f in server.faved} == {9001}


def test_fav_album_and_dry_run(lib, server, new_run):
    dry = lib.set_faved("album", [ALBUM], on=True, run=new_run(dry_run=True))
    assert dry["to_change"] == [ALBUM] and dry["changed"] == [] and server.calls_to("FavAlbum") == []
    lib.set_faved("album", [ALBUM], on=True, run=new_run())
    assert server.faved_album_mids == {ALBUM}
    again = lib.set_faved("album", [ALBUM], on=True, run=new_run())
    assert again["already"] == [ALBUM] and len(server.calls_to("FavAlbum")) == 1
    lib.set_faved("album", [ALBUM], on=False, run=new_run())
    assert server.faved_album_mids == set()


def test_fav_refuses_own_playlist(lib, server, new_run):
    mine = server.add_playlist("Mine")
    with pytest.raises(UsageError):
        lib.set_faved("playlist", [mine["tid"]], on=True, run=new_run())
    assert server.calls_to("FavPlaylist") == []


def test_fav_cli_validates_refs(runner, patched_lib, server):
    assert isinstance(runner.invoke(app, ["fav", "playlist", "abc"]).exception, UsageError)
    assert isinstance(runner.invoke(app, ["fav", "album", "123"]).exception, UsageError)
    assert isinstance(runner.invoke(app, ["fav", "singer", "x"]).exception, UsageError)
    out = out_json(runner.invoke(app, ["fav", "albums", ALBUM]))
    assert out["changed"] == [ALBUM] and out["run_id"]


# -- visibility and cover ---------------------------------------------------------------------------


def test_private_then_public_and_rename_keeps_private(lib, server, new_run):
    server.add_playlist("Secret")
    pl = lib.resolve_playlist("Secret")
    r = lib.edit_playlist(pl, run=new_run(), public=False)
    assert r["verified"] and server.calls_to("EditPlaylist")[-1]["dirShow"] == 2
    assert lib.resolve_playlist("Secret")["public"] is False
    lib.edit_playlist(lib.resolve_playlist("Secret"), run=new_run(), name="Still Secret")
    assert server.calls_to("EditPlaylist")[-1]["dirShow"] == 2
    lib.edit_playlist(lib.resolve_playlist("Still Secret"), run=new_run(), public=True)
    assert server.by_name("Still Secret")["dir_show"] == 1


def _png(path, w=40, h=20):
    raw = (b"\x00" + b"\x10\x20\x30" * w) * h

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    )


@pytest.mark.skipif(shutil.which("sips") is None, reason="needs macOS sips")
def test_square_jpeg_crops_to_square(tmp_path):
    src = tmp_path / "wide.png"
    _png(src)
    data = cover.square_jpeg(src)
    assert data[:2] == b"\xff\xd8"  # JPEG
    out = tmp_path / "out.jpg"
    out.write_bytes(data)
    import subprocess

    info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(out)], capture_output=True, text=True)
    assert "pixelWidth: 20" in info.stdout and "pixelHeight: 20" in info.stdout


def test_square_jpeg_rejects_missing_and_non_images(tmp_path):
    with pytest.raises(UsageError):
        cover.square_jpeg(tmp_path / "nope.png")
    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    if shutil.which("sips"):
        with pytest.raises(UsageError):
            cover.square_jpeg(bad)


def test_cover_upload_sets_cover_and_undo_restores(runner, patched_lib, server, monkeypatch, tmp_path):
    monkeypatch.setattr(cover, "square_jpeg", lambda path: b"\xff\xd8fake")
    server.add_playlist("Mix")
    img = tmp_path / "c.png"
    img.write_bytes(b"x")
    out = out_json(runner.invoke(app, ["edit", "Mix", "--cover", str(img)]))
    assert out["verified"] is True  # the stored URL has a resize suffix; the check ignores it
    assert out["after"]["cover"] == "https://music-file.y.qq.com/songlist/u/1.jpg"
    assert server.uploads[0]["FileName"].endswith(".jpg")
    undone = out_json(runner.invoke(app, ["undo", out["run_id"]]))
    assert undone["results"][0]["undo"] == "edit"
    assert server.by_name("Mix")["picurl"] == "http://example.invalid/cover.jpg"


def test_cover_dry_run_uploads_nothing(runner, patched_lib, server, tmp_path):
    server.add_playlist("Mix")
    out = out_json(runner.invoke(app, ["edit", "Mix", "--cover", str(tmp_path / "c.png"), "--dry-run"]))
    assert out["dry_run"] is True and server.uploads == [] and server.calls_to("EditPlaylist") == []


def test_undo_of_an_old_edit_run_leaves_visibility_and_cover(lib, server, new_run):
    server.add_playlist("Renamed")
    pl = lib.resolve_playlist("Renamed")
    lib.edit_playlist(pl, run=new_run(), public=False)
    old_run = {"ops": [{"op": "edit", "playlist": {**pl, "name": "Renamed"}, "before": {"name": "Orig", "desc": ""}}]}
    lib.undo(old_run, run=new_run())
    assert server.by_dir(pl["dir_id"])["dirName"] == "Orig"
    assert server.by_dir(pl["dir_id"])["dir_show"] == 2  # a 0.4 run never recorded visibility


def test_edit_needs_something(runner, patched_lib, server):
    server.add_playlist("Mix")
    assert isinstance(runner.invoke(app, ["edit", "Mix"]).exception, UsageError)
