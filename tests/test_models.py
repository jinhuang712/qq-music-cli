from __future__ import annotations

import json

import pytest

from qq_music_cli import models
from qq_music_cli.errors import UsageError

MID = "0039MnYb0qxYhV"


def test_mid_fixture_is_14_chars():
    assert len(MID) == 14


# -- parse_song_ref -------------------------------------------------------------------------------


def test_parse_plain_id():
    assert models.parse_song_ref("123") == {"id": 123}
    assert models.parse_song_ref("  123 ") == {"id": 123}


def test_parse_id_type():
    assert models.parse_song_ref("123:1") == {"id": 123, "type": 1}
    assert models.parse_song_ref("123:0") == {"id": 123, "type": 0}


def test_parse_mid():
    assert models.parse_song_ref(MID) == {"mid": MID}


def test_parse_json_object_id_wins_and_extra_fields_dropped():
    ref = models.parse_song_ref('{"id": 5, "type": 0, "mid": "x", "name": "n"}')
    assert ref == {"id": 5, "type": 0}
    assert models.parse_song_ref({"id": "7"}) == {"id": 7}
    assert models.parse_song_ref(json.dumps({"mid": MID, "name": "n"})) == {"mid": MID}


@pytest.mark.parametrize(
    "bad", ["", "   ", "hello", "12:ab", "short", "{bad json", '{"name": "no ids"}', "has space 1234"]
)
def test_parse_invalid_raises_usage_error(bad):
    with pytest.raises(UsageError) as e:
        models.parse_song_ref(bad)
    assert e.value.exit_code == 2


# -- read_song_refs -------------------------------------------------------------------------------


def test_read_refs_args_only():
    assert models.read_song_refs(["1", "2:1"], None) == [{"id": 1}, {"id": 2, "type": 1}]
    assert models.read_song_refs([], "  \n") == []


def test_read_refs_json_array():
    text = json.dumps([{"id": 1, "type": 0}, "2", {"mid": MID}])
    assert models.read_song_refs([], text) == [{"id": 1, "type": 0}, {"id": 2}, {"mid": MID}]


def test_read_refs_show_document():
    doc = {
        "playlist": {"name": "x"},
        "count": 2,
        "complete": True,
        "songs": [{"id": 10, "type": 0, "name": "a"}, {"id": 11, "type": 0, "name": "b"}],
    }
    assert models.read_song_refs([], json.dumps(doc, indent=2)) == [{"id": 10, "type": 0}, {"id": 11, "type": 0}]


def test_read_refs_jsonl():
    text = f'{{"id": 1, "type": 0}}\n{{"id": 2}}\n\n{{"mid": "{MID}"}}\n'
    assert models.read_song_refs([], text) == [{"id": 1, "type": 0}, {"id": 2}, {"mid": MID}]


def test_read_refs_plain_lines_and_single_token():
    assert models.read_song_refs([], "1\n2:1\n" + MID + "\n") == [{"id": 1}, {"id": 2, "type": 1}, {"mid": MID}]
    assert models.read_song_refs([], "42") == [{"id": 42}]
    assert models.read_song_refs([], '{"id": 9}') == [{"id": 9}]


def test_read_refs_args_come_before_stdin():
    assert models.read_song_refs(["1"], "2\n3") == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_read_refs_bad_line_raises():
    with pytest.raises(UsageError):
        models.read_song_refs([], "1\nnot-a-song")


def test_read_refs_json_array_of_numbers():
    assert models.read_song_refs([], "[1, 2, 3]") == [{"id": 1}, {"id": 2}, {"id": 3}]


# -- normalisers ----------------------------------------------------------------------------------

RAW_SONG = {
    "id": 237773700,
    "mid": "002Zkt5S2z8JZx",
    "type": 0,
    "name": "晴天",
    "title": "晴天",
    "subtitle": "",
    "singer": [
        {"id": 4558, "mid": "0025NhlN2yWrP4", "name": "周杰伦", "title": "周杰伦"},
        {"id": 99, "mid": "x", "title": "Guest"},
        "garbage",
    ],
    "album": {"id": 8220, "mid": "000MkMni19ClKG", "name": "叶惠美", "time_public": "2003-07-31"},
    "interval": 269,
    "time_public": "2003-07-31",
    "language": 0,
    "genre": 1,
    "pay": {"pay_play": 1, "pay_month": 1},
}


def test_song_normaliser_realistic():
    s = models.song(RAW_SONG)
    assert s["id"] == 237773700 and s["mid"] == "002Zkt5S2z8JZx" and s["type"] == 0
    assert s["name"] == "晴天"
    assert s["title"] is None  # same as name
    assert s["subtitle"] is None
    assert s["artist"] == "周杰伦 / Guest"
    assert [x["id"] for x in s["singers"]] == [4558, 99]
    assert s["album"] == {"id": 8220, "mid": "000MkMni19ClKG", "name": "叶惠美"}
    assert s["duration"] == 269
    assert s["release_date"] == "2003-07-31"
    assert s["vip"] is True
    json.dumps(s)


def test_song_normaliser_sparse():
    s = models.song({"id": 1, "title": "T", "name": "N", "type": None})
    assert s["type"] == 0
    assert s["title"] == "T" and s["name"] == "N"
    assert s["album"] is None and s["artist"] == "" and s["vip"] is False and s["release_date"] is None
    assert models.song({"id": 1, "title": "Only"})["name"] == "Only"


def test_song_release_date_falls_back_to_album():
    s = models.song({"id": 1, "name": "n", "album": {"id": 2, "name": "a", "time_public": "2001-02-03"}})
    assert s["release_date"] == "2001-02-03"


def test_faved_album_unix_pubtime_to_date():
    raw = {
        "id": 1,
        "mid": "m",
        "name": "Album",
        "songnum": 10,
        "pubtime": 1577808000,
        "ordertime": 5,
        "v_singer": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
    }
    a = models.faved_album(raw)
    assert a["release_date"] == "2020-01-01"  # 2019-12-31T16:00Z is already Jan 1 in UTC+8
    assert a["artist"] == "A / B"
    assert a["song_count"] == 10 and a["faved_at"] == 5


def test_faved_album_date_edge_cases():
    assert models.faved_album({"pubtime": "2020-05-06"})["release_date"] == "2020-05-06"
    assert models.faved_album({"pubtime": 0})["release_date"] is None
    assert models.faved_album({})["release_date"] is None


def test_playlist_normalisers():
    p = models.playlist({"dirId": 201, "tid": 5, "dirName": "我喜欢", "songNum": 3, "dirShow": 1})
    assert p["liked"] is True and p["public"] is True and p["name"] == "我喜欢" and p["song_count"] == 3
    q = models.playlist({"dirId": 301, "tid": 6, "dirName": "x", "dirShow": 0})
    assert q["liked"] is False and q["public"] is False
    info = models.playlist_info({"id": 6, "dirid": 301, "title": "x", "songnum": 2, "host_nick": ""})
    assert info["tid"] == 6 and info["dir_id"] == 301 and info["creator"] is None and info["tags"] == []


def test_song_detail_and_project():
    raw = {
        "track_info": {"id": 1, "name": "n"},
        "info": {"genre": {"content": [{"value": "Pop"}, {"value": "Rock"}]}, "lan": {"content": [{"value": "国语"}]}},
    }
    d = models.song_detail(raw)
    assert d["genre_name"] == "Pop, Rock" and d["language_name"] == "国语" and d["company"] is None
    assert models.project({"a": 1, "b": 2}, ["a", "z"]) == {"a": 1, "z": None}
    assert models.project({"a": 1}, None) == {"a": 1}
