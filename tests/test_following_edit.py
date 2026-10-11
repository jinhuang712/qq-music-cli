"""Followed singers/users and playlist rename/description, against the fake server."""

import pytest

from qq_music_cli import api, runs
from qq_music_cli.errors import AuthError, UsageError


def test_following_singers_pages_and_normalises(lib, server):
    singers = lib.following("singers")
    assert len(singers) == 250
    assert [c["Size"] for c in server.calls_to("GetFollowSingerList")] == [100, 100, 100]
    assert [c["From"] for c in server.calls_to("GetFollowSingerList")] == [0, 100, 200]
    assert singers[0] == {"name": "Singer 0", "mid": "SMID0000000000", "euin": None, "fans": 1000}


def test_following_users_and_bad_kind(lib):
    assert lib.following("users") == [{"name": "Some User", "mid": None, "euin": "user_euin_1", "fans": 3}]
    with pytest.raises(UsageError):
        lib.following("albums")


def test_following_needs_euin(lib):
    lib.client.credential.euin = ""
    with pytest.raises(AuthError):
        lib.following()


def test_edit_renames_and_keeps_cover_tags_visibility(lib, server, new_run):
    server.add_playlist("Old", [100_001])
    run = new_run()
    result = lib.edit_playlist(lib.resolve_playlist("Old"), run=run, name="  New Name  ", desc="for the road")
    assert result["changed"] and result["verified"]
    assert result["before"] == {"name": "Old", "desc": ""}
    assert result["after"] == {"name": "New Name", "desc": "for the road"}
    sent = server.calls_to("EditPlaylist")[0]
    assert sent["mask"] == api.EDIT_MASK
    assert sent["dirNewPicUrl"] == "http://example.invalid/cover.jpg"
    assert sent["dirNewtaglist"] == "11,22" and sent["dirShow"] == 1
    assert server.by_name("New Name")["tags"] == [{"id": 11, "name": "R&B"}, {"id": 22, "name": "Chill"}]
    assert run.data["ops"] == [
        {
            "op": "edit",
            "playlist": {"dir_id": sent["dirId"], "tid": server.by_name("New Name")["tid"], "name": "Old"},
            "before": {"name": "Old", "desc": ""},
            "after": {"name": "New Name", "desc": "for the road"},
        }
    ]
    assert runs._op_summary(run.data["ops"][0]) == "edit playlist 'Old' -> 'New Name'"


def test_edit_only_desc_keeps_name(lib, server, new_run):
    server.add_playlist("Keep")
    lib.edit_playlist(lib.resolve_playlist("Keep"), run=new_run(), desc="hello")
    assert server.by_name("Keep")["desc"] == "hello"


def test_edit_undo_restores(lib, server, new_run):
    server.add_playlist("Before")
    first = new_run()
    lib.edit_playlist(lib.resolve_playlist("Before"), run=first, name="After", desc="x")
    results = lib.undo(first.data, run=new_run())
    assert results == [{"undo": "edit", "restored": "Before", "playlist": "After"}]
    restored = server.by_name("Before")
    assert restored["desc"] == ""


@pytest.mark.parametrize(
    "kwargs, message",
    [({"name": ""}, "1-20"), ({"name": "x" * 21}, "1-20"), ({"desc": "y" * 2001}, "2000")],
)
def test_edit_validates(lib, server, new_run, kwargs, message):
    server.add_playlist("V")
    with pytest.raises(UsageError, match=message):
        lib.edit_playlist(lib.resolve_playlist("V"), run=new_run(), **kwargs)
    assert server.calls_to("EditPlaylist") == []


def test_edit_refuses_liked(lib, new_run):
    with pytest.raises(UsageError):
        lib.edit_playlist(lib.resolve_playlist("liked"), run=new_run(), name="Nope")


def test_edit_no_change_and_dry_run_write_nothing(lib, server, new_run):
    server.add_playlist("Same")
    pl = lib.resolve_playlist("Same")
    assert lib.edit_playlist(pl, run=new_run(), name="Same")["changed"] is False
    dry = new_run(dry_run=True)
    assert lib.edit_playlist(pl, run=dry, name="Other")["dry_run"] is True
    assert server.calls_to("EditPlaylist") == [] and dry.data["ops"] == []


def test_export_includes_followed_singers(lib):
    assert len(lib.export()["following_singers"]) == 250


def test_following_with_saved_counts_by_mid(lib, server):
    # catalog songs are sung by singer1 + singer2; make the first followed singer one of them
    server.followed_singers[0]["MID"] = "singer1"
    server.followed_singers[0]["Name"] = "Artist A (别名)"  # alias must not matter
    server.by_dir(201)["songs"] = [100_001, 100_002]
    server.add_playlist("Mix", [100_002, 100_003, 100_004])
    people = lib.following_with_saved()
    first = people[0]
    assert first["liked_songs"] == 2
    assert first["saved_songs"] == 4  # 100_001..100_004, the shared song counted once
    assert all(p["saved_songs"] == 0 for p in people[1:])
