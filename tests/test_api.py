from __future__ import annotations

import pytest

from qq_music_cli import api
from qq_music_cli.errors import ApiError, UsageError

IDS = list(range(100_000, 100_000 + 2000))


def refs(ids):
    return [{"id": i} for i in ids]


def ids_in(server, name):
    return list(server.by_name(name)["songs"])


@pytest.fixture
def seeded(server):
    server.add_playlist("Road Trip", IDS[:5])
    server.add_playlist("Gym", IDS[5:8])
    return server


# -- resolve_playlist -----------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["liked", "LIKED", "like", "我喜欢", "201"])
def test_resolve_liked(lib, seeded, ref):
    pl = lib.resolve_playlist(ref)
    assert pl["liked"] is True and pl["dir_id"] == 201


def test_resolve_by_dir_id_and_tid(lib, seeded):
    rt = seeded.by_name("Road Trip")
    assert lib.resolve_playlist(str(rt["dirId"]))["name"] == "Road Trip"
    assert lib.resolve_playlist(str(rt["tid"]))["name"] == "Road Trip"


def test_resolve_by_name_exact_and_case_insensitive(lib, seeded):
    assert lib.resolve_playlist("Road Trip")["dir_id"] == seeded.by_name("Road Trip")["dirId"]
    assert lib.resolve_playlist("  road trip ")["name"] == "Road Trip"
    assert lib.resolve_playlist("GYM")["name"] == "Gym"


def test_resolve_exact_name_beats_case_variant(lib, server):
    server.add_playlist("Mix")
    server.add_playlist("mix")
    assert lib.resolve_playlist("mix")["name"] == "mix"
    assert lib.resolve_playlist("Mix")["name"] == "Mix"


def test_resolve_duplicate_names(lib, server):
    a = server.add_playlist("Dup")
    b = server.add_playlist("Dup")
    with pytest.raises(UsageError) as e:
        lib.resolve_playlist("Dup")
    assert str(a["dirId"]) in e.value.message and str(b["dirId"]) in e.value.message


def test_resolve_duplicate_case_insensitive(lib, server):
    server.add_playlist("Alpha")
    server.add_playlist("ALPHA")
    with pytest.raises(UsageError):
        lib.resolve_playlist("alpha")


def test_resolve_unknown(lib, seeded):
    with pytest.raises(UsageError, match="no playlist named"):
        lib.resolve_playlist("Nope")
    with pytest.raises(UsageError, match="dir_id or tid"):
        lib.resolve_playlist("999999")


def test_resolve_foreign_tid_allowed_when_not_own(lib, seeded):
    pl = lib.resolve_playlist("999999", own=False)
    assert pl["tid"] == 999999 and pl["dir_id"] is None


def test_playlists_cached_until_refresh(lib, server):
    lib.playlists()
    lib.playlists()
    assert len(server.calls_to("GetPlaylistByUin")) == 1
    lib.playlists(refresh=True)
    assert len(server.calls_to("GetPlaylistByUin")) == 2


def test_resolve_liked_when_missing(lib, server):
    server.playlists.clear()
    with pytest.raises(UsageError):
        lib.resolve_playlist("liked")


# -- playlist_songs -------------------------------------------------------------------------------


def test_playlist_songs_pages_through_1200(lib, server):
    pl = server.add_playlist("Big", IDS[:1200])
    result = lib.playlist_songs(pl["tid"])
    assert api.PAGE_SIZE == 500
    assert result["complete"] is True
    assert result["count"] == 1200 and result["total"] == 1200
    assert [s["id"] for s in result["songs"]] == IDS[:1200]
    reads = server.calls_to("uniform_get_Dissinfo")
    assert [(r["song_begin"], r["song_num"]) for r in reads] == [(0, 500), (500, 500), (1000, 500)]
    assert result["playlist"]["name"] == "Big"


def test_playlist_songs_stops_early_is_incomplete(lib, server):
    pl = server.add_playlist("Big", IDS[:1200])
    server.max_visible = 700
    result = lib.playlist_songs(pl["tid"])
    assert result["complete"] is False
    assert result["count"] == 700 and result["total"] == 1200


def test_playlist_songs_limit_and_offset(lib, server):
    pl = server.add_playlist("Big", IDS[:1200])
    r = lib.playlist_songs(pl["tid"], limit=30)
    assert r["count"] == 30 and r["complete"] is True
    assert server.calls_to("uniform_get_Dissinfo")[-1]["song_num"] == 30
    r = lib.playlist_songs(pl["tid"], offset=1190)
    assert [s["id"] for s in r["songs"]] == IDS[1190:1200] and r["complete"] is True


def test_playlist_songs_empty_playlist(lib, server):
    pl = server.add_playlist("Empty")
    r = lib.playlist_songs(pl["tid"])
    assert r["songs"] == [] and r["complete"] is True


def test_playlist_songs_server_error(lib, server):
    with pytest.raises(ApiError, match="no such playlist"):
        lib.playlist_songs(424242)


def test_song_keys_refuses_incomplete(lib, server):
    pl = server.add_playlist("Big", IDS[:900])
    server.max_visible = 100
    with pytest.raises(ApiError, match="could not read the whole"):
        lib.song_keys(pl["tid"])


# -- tracks ---------------------------------------------------------------------------------------


def test_tracks_by_id_and_mid_keep_input_order(lib, server):
    mid = server.catalog[IDS[3]]["mid"]
    out = lib.tracks([{"id": IDS[5]}, {"mid": mid}, {"id": IDS[1]}])
    assert [s["id"] for s in out] == [IDS[5], IDS[3], IDS[1]]
    assert out[0]["artist"] == "Artist A / Artist B"


def test_tracks_unknown_raises(lib):
    with pytest.raises(UsageError, match="unknown song"):
        lib.tracks([{"id": 1}])


def test_tracks_batches_by_50(lib, server):
    lib.tracks(refs(IDS[:120]))
    assert [len(c["ids"]) for c in server.calls_to("CgiGetTrackInfo")] == [50, 50, 20]


# -- add_songs ------------------------------------------------------------------------------------


def test_add_songs_skips_present(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run()
    report = lib.add_songs(pl, refs(IDS[3:8]), run=run)
    assert [s["id"] for s in report["already_present"]] == IDS[3:5]
    assert [s["id"] for s in report["added"]] == IDS[5:8]
    assert ids_in(seeded, "Road Trip") == IDS[:8]
    assert report["verified"] is True and report["missing_after_write"] == []
    assert len(run.data["ops"]) == 1 and run.data["ops"][0]["op"] == "add"


def test_add_songs_all_present_writes_nothing(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run()
    report = lib.add_songs(pl, refs(IDS[:5]), run=run)
    assert report["added"] == [] and seeded.calls_to("AddSonglist") == []
    assert run.has_ops is False and not run.path.exists()


def test_add_songs_batches_20_20_5(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run()
    # 50 requested, 5 already present -> 45 new
    report = lib.add_songs(pl, refs(IDS[:50]), run=run)
    writes = seeded.calls_to("AddSonglist")
    assert [len(w["v_songInfo"]) for w in writes] == [20, 20, 5]
    assert len(report["added"]) == 45 and len(report["already_present"]) == 5
    ops = run.data["ops"]
    assert [len(o["songs"]) for o in ops] == [20, 20, 5]
    recorded = [s["id"] for o in ops for s in o["songs"]]
    assert recorded == IDS[5:50]
    assert report["verified"] is True and report["missing_after_write"] == []
    assert ids_in(seeded, "Road Trip") == IDS[:50]
    assert run.path.exists()


def test_add_songs_dedupes_request(lib, seeded, new_run):
    pl = lib.resolve_playlist("Gym")
    report = lib.add_songs(pl, refs([IDS[20], IDS[20], IDS[21]]), run=new_run())
    assert report["requested"] == 2 and len(report["added"]) == 2


def test_add_songs_by_mid(lib, seeded, new_run):
    pl = lib.resolve_playlist("Gym")
    mid = seeded.catalog[IDS[30]]["mid"]
    lib.add_songs(pl, [{"mid": mid}], run=new_run())
    assert IDS[30] in ids_in(seeded, "Gym")


def test_add_songs_records_only_newly_added_when_server_says_existed(lib, seeded, new_run, monkeypatch):
    pl = lib.resolve_playlist("Road Trip")
    monkeypatch.setattr(lib, "song_keys", lambda tid: set())  # stale read: pretend nothing is there
    run = new_run()
    report = lib.add_songs(pl, refs(IDS[3:7]), run=run, verify=False)
    assert [s["id"] for s in report["added"]] == IDS[5:7]
    assert [s["id"] for s in report["already_present"]] == IDS[3:5]
    assert [s["id"] for s in run.data["ops"][0]["songs"]] == IDS[5:7]
    assert "verified" not in report


def test_add_songs_dry_run_writes_and_records_nothing(lib, seeded, new_run, runs_path):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run(dry_run=True)
    report = lib.add_songs(pl, refs(IDS[:30]), run=run)
    assert report["dry_run"] is True
    assert len(report["would_add"]) == 25 and report["added"] == []
    assert seeded.calls_to("AddSonglist") == []
    assert ids_in(seeded, "Road Trip") == IDS[:5]
    assert run.data["ops"] == [] and list(runs_path.iterdir()) == []


def test_add_songs_requires_own_playlist(lib, new_run):
    with pytest.raises(UsageError, match="your own"):
        lib.add_songs({"dir_id": None, "tid": 5, "name": None}, refs(IDS[:1]), run=new_run())


def test_add_songs_pauses_between_batches(server, cred, new_run):
    from qq_music_cli.client import Client

    pauses = []
    client = Client(cred, transport=server.transport(), sleep=lambda s: None, min_interval=0)
    lib = api.Library(client, sleep=pauses.append, write_pause=(0.5, 0.5))
    server.add_playlist("P")
    lib.add_songs(lib.resolve_playlist("P"), refs(IDS[:45]), run=new_run())
    assert pauses == [0.5, 0.5]  # 3 batches -> 2 pauses
    client.close()


def test_add_to_liked(lib, server, new_run):
    lib.add_songs(lib.resolve_playlist("liked"), refs(IDS[:3]), run=new_run())
    assert ids_in(server, "我喜欢") == IDS[:3]


# -- remove_songs ---------------------------------------------------------------------------------


def test_remove_songs_reports_not_present(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run()
    report = lib.remove_songs(pl, refs([IDS[0], IDS[1], IDS[900]]), run=run)
    assert [s["id"] for s in report["removed"]] == [IDS[0], IDS[1]]
    assert [s["id"] for s in report["not_present"]] == [IDS[900]]
    assert ids_in(seeded, "Road Trip") == IDS[2:5]
    assert report["verified"] is True and report["still_present"] == []
    assert len(run.data["ops"]) == 1 and run.data["ops"][0]["op"] == "remove"
    assert [s["id"] for s in run.data["ops"][0]["songs"]] == [IDS[0], IDS[1]]


def test_remove_songs_nothing_present_no_calls(lib, seeded, new_run):
    run = new_run()
    report = lib.remove_songs(lib.resolve_playlist("Gym"), refs([IDS[900]]), run=run)
    assert report["removed"] == [] and seeded.calls_to("DelSonglist") == [] and not run.has_ops


def test_remove_songs_server_reports_nothing_removed(lib, seeded, new_run, monkeypatch):
    pl = lib.resolve_playlist("Gym")
    monkeypatch.setattr(lib, "song_keys", lambda tid: {(IDS[900], 0)})  # claims present, server disagrees
    run = new_run()
    report = lib.remove_songs(pl, refs([IDS[900]]), run=run, verify=False)
    assert report["removed"] == [] and not run.has_ops


def test_remove_songs_batches(lib, server, new_run):
    server.add_playlist("Big", IDS[:45])
    run = new_run()
    report = lib.remove_songs(lib.resolve_playlist("Big"), refs(IDS[:45]), run=run)
    assert [len(w["v_songInfo"]) for w in server.calls_to("DelSonglist")] == [20, 20, 5]
    assert len(report["removed"]) == 45 and ids_in(server, "Big") == []
    assert [len(o["songs"]) for o in run.data["ops"]] == [20, 20, 5]


def test_remove_songs_dry_run(lib, seeded, new_run, runs_path):
    run = new_run(dry_run=True)
    report = lib.remove_songs(lib.resolve_playlist("Road Trip"), refs(IDS[:2]), run=run)
    assert len(report["would_remove"]) == 2 and seeded.calls_to("DelSonglist") == []
    assert ids_in(seeded, "Road Trip") == IDS[:5] and list(runs_path.iterdir()) == []


# -- create / delete ------------------------------------------------------------------------------


def test_create_playlist(lib, server, new_run):
    run = new_run()
    r = lib.create_playlist("  Fresh  ", run=run)
    assert r["created"] is True and r["playlist"]["name"] == "Fresh"
    assert server.by_name("Fresh")["dirId"] == r["playlist"]["dir_id"]
    assert run.data["ops"][0]["op"] == "create"
    assert lib.resolve_playlist("Fresh")["tid"] == r["playlist"]["tid"]  # cache was invalidated


def test_create_existing_name_returns_existing(lib, seeded, new_run):
    run = new_run()
    r = lib.create_playlist("Road Trip", run=run)
    assert r["created"] is False and r["playlist"]["name"] == "Road Trip"
    assert seeded.calls_to("AddPlaylist") == [] and not run.has_ops


def test_create_allow_duplicate(lib, seeded, new_run):
    r = lib.create_playlist("Road Trip", run=new_run(), allow_duplicate=True)
    assert r["created"] is True and len([p for p in seeded.playlists if p["dirName"] == "Road Trip"]) == 2


def test_create_dry_run_and_empty_name(lib, server, new_run):
    r = lib.create_playlist("X", run=new_run(dry_run=True))
    assert r["dry_run"] is True and server.calls_to("AddPlaylist") == []
    with pytest.raises(UsageError):
        lib.create_playlist("   ", run=new_run())


def test_delete_refuses_liked(lib, server, new_run):
    liked = lib.resolve_playlist("liked")
    with pytest.raises(UsageError, match="我喜欢"):
        lib.delete_playlist(liked, run=new_run())
    with pytest.raises(UsageError):
        lib.delete_playlist({"dir_id": 201, "tid": 1, "name": "renamed", "liked": False}, run=new_run())
    assert server.calls_to("DelPlaylist") == []


def test_delete_snapshots_songs_into_run(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run()
    r = lib.delete_playlist(pl, run=run)
    assert r["deleted"] is True and r["song_count"] == 5
    assert all(p["dirName"] != "Road Trip" for p in seeded.playlists)
    op = run.data["ops"][0]
    assert op["op"] == "delete" and op["playlist"]["name"] == "Road Trip"
    assert [s["id"] for s in op["songs"]] == IDS[:5]
    assert op["songs"][0]["name"] == f"Song {IDS[0]}"


def test_delete_dry_run(lib, seeded, new_run):
    run = new_run(dry_run=True)
    r = lib.delete_playlist(lib.resolve_playlist("Road Trip"), run=run)
    assert r["dry_run"] is True and r["song_count"] == 5
    assert seeded.calls_to("DelPlaylist") == [] and not run.has_ops


def test_delete_aborts_when_snapshot_incomplete(lib, server, new_run):
    server.add_playlist("Big", IDS[:900])
    server.max_visible = 100
    with pytest.raises(ApiError, match="nothing was deleted"):
        lib.delete_playlist(lib.resolve_playlist("Big"), run=new_run())
    assert server.calls_to("DelPlaylist") == []


def test_delete_server_reports_nothing_deleted(lib, new_run):
    run = new_run()
    with pytest.raises(ApiError, match="nothing deleted"):
        lib.delete_playlist({"dir_id": 999, "tid": 1, "name": "ghost", "song_count": 0}, run=run)
    assert not run.has_ops


def test_delete_empty_playlist_skips_snapshot(lib, server, new_run):
    server.add_playlist("Empty")
    lib.delete_playlist(lib.resolve_playlist("Empty"), run=new_run())
    assert server.calls_to("uniform_get_Dissinfo") == []


# -- undo -----------------------------------------------------------------------------------------


def test_undo_add_removes_those_songs(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    run = new_run("add")
    lib.add_songs(pl, refs(IDS[:50]), run=run)
    assert len(ids_in(seeded, "Road Trip")) == 50
    undo_run = new_run("undo")
    results = lib.undo(run.data, run=undo_run)
    assert ids_in(seeded, "Road Trip") == IDS[:5]  # pre-existing songs untouched
    assert sum(r["removed"] for r in results) == 45 and all(r["undo"] == "add" for r in results)
    assert [o["op"] for o in undo_run.data["ops"]] == ["remove", "remove", "remove"]


def test_undo_remove_readds(lib, seeded, new_run):
    run = new_run()
    lib.remove_songs(lib.resolve_playlist("Road Trip"), refs(IDS[:3]), run=run)
    lib.undo(run.data, run=new_run("undo"))
    assert sorted(ids_in(seeded, "Road Trip")) == IDS[:5]


def test_undo_delete_recreates_playlist_and_songs(lib, seeded, new_run):
    pl = lib.resolve_playlist("Road Trip")
    old_dir = pl["dir_id"]
    run = new_run("delete")
    lib.delete_playlist(pl, run=run)
    undo_run = new_run("undo")
    results = lib.undo(run.data, run=undo_run)
    assert results == [{"undo": "delete", "recreated": "Road Trip", "added": 5}]
    assert ids_in(seeded, "Road Trip") == IDS[:5]
    assert seeded.by_name("Road Trip")["dirId"] != old_dir  # server hands out a new id
    assert [o["op"] for o in undo_run.data["ops"]] == ["create", "add"]


def test_undo_create_deletes_empty_playlist(lib, server, new_run):
    run = new_run()
    lib.create_playlist("Temp", run=run)
    results = lib.undo(run.data, run=new_run("undo"))
    assert results == [{"undo": "create", "deleted": "Temp"}]
    assert all(p["dirName"] != "Temp" for p in server.playlists)


def test_undo_create_skips_non_empty_without_force(lib, server, new_run):
    run = new_run()
    lib.create_playlist("Temp", run=run)
    lib.add_songs(lib.resolve_playlist("Temp"), refs(IDS[:2]), run=new_run())
    res = lib.undo(run.data, run=new_run("undo"))
    assert "skipped" in res[0] and server.by_name("Temp")
    res = lib.undo(run.data, run=new_run("undo2"), force=True)
    assert res[0].get("deleted") == "Temp"


def test_undo_reports_error_for_vanished_playlist(lib, seeded, new_run):
    run = new_run()
    lib.add_songs(lib.resolve_playlist("Gym"), refs(IDS[20:22]), run=run)
    seeded.playlists.remove(seeded.by_name("Gym"))
    lib._playlists = None
    res = lib.undo(run.data, run=new_run("undo"))
    assert res[0]["undo"] == "add" and res[0]["error"]["kind"] == "usage"


def test_undo_dry_run_changes_nothing(lib, seeded, new_run):
    run = new_run()
    lib.add_songs(lib.resolve_playlist("Gym"), refs(IDS[20:22]), run=run)
    before = ids_in(seeded, "Gym")
    lib.undo(run.data, run=new_run("undo", dry_run=True))
    assert ids_in(seeded, "Gym") == before


# -- misc -----------------------------------------------------------------------------------------


def test_whoami(lib, cred):
    assert lib.whoami() == {"uin": cred.uin, "nickname": "Fake Nick", "avatar": "http://example.invalid/a.png"}


def test_unauthenticated_library_raises_auth_error():
    from qq_music_cli.client import Client
    from qq_music_cli.errors import AuthError

    with pytest.raises(AuthError):
        _ = api.Library(Client(None)).uin


def test_search_rejects_unknown_type(lib):
    with pytest.raises(UsageError):
        lib.search("x", kind="bogus")


def test_faved_requires_euin(server, cred):
    from qq_music_cli.client import Client
    from qq_music_cli.errors import AuthError

    cred.euin = ""
    client = Client(cred, transport=server.transport(), sleep=lambda s: None, min_interval=0)
    with pytest.raises(AuthError):
        api.Library(client).faved_albums()
    client.close()
