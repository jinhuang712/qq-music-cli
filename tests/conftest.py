"""Shared fixtures: fake credentials and an in-memory fake QQ Music server on httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from qq_music_cli.api import Library
from qq_music_cli.auth import WECHAT, Credential
from qq_music_cli.client import Client
from qq_music_cli.runs import RunLog

FAKE_UIN = "1152921500000000001"
FAKE_KEY = "W_X_fake_key"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Nothing may touch the real Keychain, home directory or run logs."""
    monkeypatch.setenv("QQMUSIC_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(tmp_path / "default-cred.json"))
    monkeypatch.delenv("QQMUSIC_API_KEY", raising=False)
    import keyring

    def _boom(*a, **k):
        raise AssertionError("test touched the real keyring")

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, _boom)


@pytest.fixture
def cred() -> Credential:
    return Credential(
        uin=FAKE_UIN,
        musickey=FAKE_KEY,
        login_type=WECHAT,
        euin="fake_euin",
        created_at=1_800_000_000,
        expires_at=1_800_000_000 + 259_200,
        source="test",
        login={"refresh_key": "fake_refresh"},
    )


@pytest.fixture
def make_client(cred):
    clients: list[Client] = []

    def factory(handler, credential: Credential | None = cred, **kw: Any) -> Client:
        sleeps: list[float] = kw.pop("sleeps", [])
        c = Client(
            credential,
            transport=httpx.MockTransport(handler),
            sleep=lambda s: sleeps.append(s),
            min_interval=0,
            **kw,
        )
        c.sleeps = sleeps  # type: ignore[attr-defined]
        clients.append(c)
        return c

    yield factory
    for c in clients:
        c.close()


def rpc_body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def ok(*datas: Any, code: int = 0) -> httpx.Response:
    """A musicu.fcg response with one successful slot per `data`."""
    body: dict[str, Any] = {"code": 0}
    for i, d in enumerate(datas):
        body[f"req_{i}"] = {"code": code, "data": d}
    return httpx.Response(200, json=body)


# -- fake server ----------------------------------------------------------------------------------


class SlotError(Exception):
    """Raised by a fake RPC method to answer its slot with a non-zero code."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class FakeQQMusic:
    """In-memory playlists + song catalogue behind the same RPC names the library uses."""

    def __init__(self, catalog_size: int = 2000) -> None:
        self.catalog: dict[int, dict[str, Any]] = {}
        for i in range(catalog_size):
            sid = 100_000 + i
            self.catalog[sid] = {
                "id": sid,
                "mid": f"MID{sid:011d}",
                "type": 0,
                "name": f"Song {sid}",
                "title": f"Song {sid}",
                "singer": [
                    {"id": 1, "mid": "singer1", "name": "Artist A"},
                    {"id": 2, "mid": "singer2", "name": "Artist B"},
                ],
                "album": {"id": 77, "mid": "album77", "name": "Album 77"},
                "interval": 200,
                "time_public": "2020-01-01",
                "pay": {"pay_play": 0},
                "bpm": 90 if i % 2 else 0,
                "mv": {"vid": f"vid{sid}" if i % 3 == 0 else ""},
                "file": {"size_320mp3": 1, "size_flac": 1 if i % 2 else 0, "size_hires": 0, "size_dolby": 0},
                "index_album": i % 12 + 1,
            }
        self.playlists: list[dict[str, Any]] = []
        self._next_dir = 301
        self._next_tid = 7001
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.max_visible: int | None = None  # server stops returning songs after this many (hasmore=0)
        self.add_playlist("我喜欢", dir_id=201, tid=5001)
        self.followed_singers = [
            {"Name": f"Singer {i}", "MID": f"SMID{i:010d}", "FanNum": 1000 + i} for i in range(250)
        ]
        self.followed_users = [{"Name": "Some User", "MID": "", "EncUin": "user_euin_1", "FanNum": 3}]
        self.faved = [{"tid": 9001, "name": "Someone's Mix", "nickname": "someone", "songnum": 30, "logo": "http://x"}]
        # public playlists of other users, readable by tid
        self.public = {
            9001: {
                "title": "Someone's Mix",
                "listennum": 4820,
                "desc": "a long story",
                "tag": [{"id": 8, "name": "R&B"}],
            }
        }
        self.albums = {"ALBUM000000001": [100_000 + i for i in range(60)]}
        self.faved_album_mids: set[str] = set()
        self.hot_comments, self.new_comments = 12, 45
        self.closed_comments: set[str] = set()  # BizIds whose comments the server refuses (code 20022)
        self.uploads: list[dict[str, Any]] = []

    # -- state helpers
    def add_playlist(
        self, name: str, songs: list[int] | None = None, dir_id: int | None = None, tid: int | None = None
    ) -> dict[str, Any]:
        if dir_id is None:
            dir_id, self._next_dir = self._next_dir, self._next_dir + 1
        if tid is None:
            tid, self._next_tid = self._next_tid, self._next_tid + 1
        pl = {
            "dirId": dir_id,
            "tid": tid,
            "dirName": name,
            "songs": list(songs or []),
            "desc": "",
            "picurl": "http://example.invalid/cover.jpg",
            "picurl2": "",
            "tags": [{"id": 11, "name": "R&B"}, {"id": 22, "name": "Chill"}],
            "dir_show": 1,
        }
        self.playlists.append(pl)
        return pl

    def by_name(self, name: str) -> dict[str, Any]:
        return next(p for p in self.playlists if p["dirName"] == name)

    def by_dir(self, dir_id: int) -> dict[str, Any] | None:
        return next((p for p in self.playlists if p["dirId"] == dir_id), None)

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [p for _, m, p in self.calls if m == method]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # -- http
    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        out: dict[str, Any] = {"code": 0}
        for key, req in body.items():
            if not key.startswith("req_"):
                continue
            self.calls.append((req["module"], req["method"], req["param"]))
            fn = getattr(self, "rpc_" + req["method"], None)
            if fn is None:
                out[key] = {"code": 404, "data": {}}
                continue
            try:
                out[key] = {"code": 0, "data": fn(req["param"])}
            except SlotError as exc:
                out[key] = {"code": exc.code, "data": {}}
        return httpx.Response(200, json=out)

    # -- rpc methods
    def rpc_GetPlaylistByUin(self, p):
        return {
            "v_playlist": [
                {
                    "dirId": pl["dirId"],
                    "tid": pl["tid"],
                    "dirName": pl["dirName"],
                    "songNum": len(pl["songs"]),
                    "dirShow": pl["dir_show"],
                    "desc": "",
                    "strTagIdList": ",".join(str(t["id"]) for t in pl["tags"]),
                    "picUrl": pl["picurl"],
                }
                for pl in self.playlists
            ]
        }

    def rpc_uniform_get_Dissinfo(self, p):
        if "disstid" not in p:  # the web editor's read: by dirid, editable fields only
            pl = self.by_dir(p["dirid"])
            if pl is None:
                return {"code": 1, "msg": "no such playlist"}
            return {
                "code": 0,
                "dirinfo": {
                    "id": pl["tid"],
                    "dirid": pl["dirId"],
                    "title": pl["dirName"],
                    "desc": pl["desc"],
                    "picurl": pl["picurl"],
                    "picurl2": pl["picurl2"],
                    "tag": pl["tags"],
                    "dir_show": pl["dir_show"],
                },
            }
        pl = next((x for x in self.playlists if x["tid"] == p["disstid"]), None)
        if pl is None and p["disstid"] in self.public:
            info = {k: v for k, v in self.public[p["disstid"]].items() if k != "songs"}
            tags = info["tag"] if p.get("tag") == 1 else []
            ids = self.public[p["disstid"]].get("songs", [])
            begin, num = p["song_begin"], p["song_num"] or len(ids)
            page = ids[begin : begin + num]
            return {
                "code": 0,
                "dirinfo": {"id": p["disstid"], **info, "tag": tags, "songnum": len(ids)},
                "total_song_num": len(ids),
                "songlist": [self.catalog[i] for i in page],
                "hasmore": 1 if begin + len(page) < len(ids) else 0,
            }
        if pl is None:
            return {"code": 1, "msg": "no such playlist"}
        visible = pl["songs"] if self.max_visible is None else pl["songs"][: self.max_visible]
        begin, num = p["song_begin"], p["song_num"] or len(visible)  # 0 means every song, as on the server
        page = visible[begin : begin + num]
        return {
            "code": 0,
            "dirinfo": {
                "id": pl["tid"],
                "dirid": pl["dirId"],
                "title": pl["dirName"],
                "songnum": len(pl["songs"]),
                "listennum": 10 * len(pl["songs"]),
                "desc": pl["desc"],
                "picurl": pl["picurl"],
                # names only when asked for, like the real server
                "tag": pl["tags"] if p.get("tag") == 1 else [],
                "vec_tagid": [t["id"] for t in pl["tags"]],
            },
            "total_song_num": len(pl["songs"]),
            "songlist": [self.catalog[i] for i in page],
            "hasmore": 1 if begin + len(page) < len(visible) else 0,
        }

    def rpc_CgiGetTrackInfo(self, p):
        if "ids" in p:
            found = [self.catalog[i] for i in p["ids"] if i in self.catalog]
        else:
            by_mid = {s["mid"]: s for s in self.catalog.values()}
            found = [by_mid[m] for m in p["mids"] if m in by_mid]
        return {"tracks": found}

    def rpc_AddPlaylist(self, p):
        pl = self.add_playlist(p["dirName"])
        return {"result": {"dirId": pl["dirId"], "tid": pl["tid"], "dirName": pl["dirName"]}}

    def rpc_DelPlaylist(self, p):
        pl = self.by_dir(p["dirId"])
        if pl is None:
            return {"result": {"dirId": 0}}
        self.playlists.remove(pl)
        return {"result": {"dirId": p["dirId"]}}

    def rpc_AddSonglist(self, p):
        pl = self.by_dir(p["dirId"])
        items = []
        for s in p["v_songInfo"]:
            existed = s["songId"] in pl["songs"]
            if not existed:
                pl["songs"].append(s["songId"])
            items.append({"songId": s["songId"], "songType": s["songType"], "existed": existed})
        return {"result": {"dirId": p["dirId"], "songlist": items}}

    def rpc_DelSonglist(self, p):
        pl = self.by_dir(p["dirId"])
        removed = 0
        for s in p["v_songInfo"]:
            if s["songId"] in pl["songs"]:
                pl["songs"].remove(s["songId"])
                removed += 1
        return {"result": {"dirId": p["dirId"] if removed else 0}}

    def rpc_EditPlaylist(self, p):
        pl = self.by_dir(p["dirId"])
        pl["dirName"], pl["desc"] = p["dirNewName"], p["dirNewDesc"]
        pic = p["dirNewPicUrl"]
        if pic.startswith("https://music-file.") and "?" not in pic:
            pic += "?imageView2/4/w/300/h/300"  # the server stores uploads with a resize suffix
        pl["picurl"], pl["picurl2"] = pic, p["dirNewPicUrl2"]
        if p["dirShow"] in (1, 2):  # anything else is ignored, as on the server
            pl["dir_show"] = p["dirShow"]
        ids = [int(x) for x in p["dirNewtaglist"].split(",") if x]
        pl["tags"] = [t for t in pl["tags"] if t["id"] in ids]
        return {"result": {"dirId": p["dirId"]}}

    def _follow_page(self, items, p):
        page = items[p["From"] : p["From"] + p["Size"]]
        return {"List": page, "Total": len(items), "HasMore": p["From"] + len(page) < len(items)}

    def rpc_GetFollowSingerList(self, p):
        return self._follow_page(self.followed_singers, p)

    def rpc_GetFollowUserList(self, p):
        return self._follow_page(self.followed_users, p)

    def rpc_getPlaylistTag(self, p):
        return {
            "categories": [
                {"categoryGroupName": "流派", "items": [{"categoryId": 11, "categoryName": "R&B"}]},
                {"categoryGroupName": "心情", "items": [{"categoryId": 22, "categoryName": "Chill"}]},
            ]
        }

    def rpc_CgiGetPlaylistFavInfo(self, p):
        return {"v_list": self.faved, "hasmore": 0}

    def rpc_PutImage(self, p):
        self.uploads.append(p)
        assert p["BusID"] == "songlist" and p["Data"].startswith("data:image/jpeg;base64,")
        return {"ErrCode": 0, "ErrMsg": "", "URL": f"https://music-file.y.qq.com/songlist/u/{len(self.uploads)}.jpg"}

    def rpc_IsPlaylistFan(self, p):
        faved = {f["tid"] for f in self.faved}
        return {"m_fan": {str(t): t in faved for t in p["v_tid"]}}

    def rpc_FavPlaylist(self, p):
        for tid in p["v_playlistId"]:
            if tid not in {f["tid"] for f in self.faved}:
                self.faved.append({"tid": tid, "name": f"Public {tid}", "songnum": 1})
        return {"result": 0, "v_failedPlaylistId": []}

    def rpc_CancelFavPlaylist(self, p):
        self.faved = [f for f in self.faved if f["tid"] not in p["v_playlistId"]]
        return {"result": 0, "v_failedPlaylistId": []}

    def rpc_IsAlbumFan(self, p):
        return {"m_fan": {m: m in self.faved_album_mids for m in p["v_albumMid"]}}

    def rpc_FavAlbum(self, p):
        self.faved_album_mids.update(p["v_albumMid"])
        return {"result": 0, "v_failedAlbumMid": []}

    def rpc_CancelFavAlbum(self, p):
        self.faved_album_mids.difference_update(p["v_albumMid"])
        return {"result": 0, "v_failedAlbumMid": []}

    def _comment_page(self, p, hot: bool):
        assert p["PageSize"] <= 20, "the server refuses pages above 20"
        pool = [
            {
                "CmId": f"c{i}",
                "Content": f"{'hot' if hot else 'new'} comment {i}",
                "PraiseNum": 100 - i,
                "ReplyCnt": i % 3,
                "PubTime": 1_700_000_000 - i * 60,
                "Nick": f"user{i}",
                "SeqNo": f"s{i}",
            }
            for i in range(self.hot_comments if hot else self.new_comments)
        ]
        size = max(p["PageSize"], 5)  # the server sends at least 5
        page = pool[p["PageNum"] * size : (p["PageNum"] + 1) * size]
        total = 1000 + int(p["BizId"]) % 1000  # per item, so tests can tell counts apart
        return {
            "TotalCmNum": total,
            "CommentList": {
                "Total": len(pool),
                "HasMore": int((p["PageNum"] + 1) * size < len(pool)),
                "Comments": page,
            },
        }

    def rpc_GetHotCommentList(self, p):
        assert p["HotType"] == 1
        # The live server caches a tiny hot page and serves it to the next hot read for a while.
        assert p["PageSize"] >= 5, "a tiny hot-list page pollutes the next hot read"
        if p["BizId"] in self.closed_comments:
            raise SlotError(20022)
        return self._comment_page(p, hot=True)

    def rpc_GetNewCommentList(self, p):
        if p["BizId"] in self.closed_comments:
            raise SlotError(20022)
        return self._comment_page(p, hot=False)

    def rpc_DoSearchForQQMusicDesktop(self, p):
        if p["search_type"] != 3:  # only playlist search is faked
            return {"body": {}, "meta": {"sum": 0}}
        hits = [
            {"dissid": str(tid), "dissname": info["title"], "song_count": len(info.get("songs", [])), "listennum": 1}
            for tid, info in self.public.items()
            if p["query"].lower() in info["title"].lower()
        ]
        hits += [  # the user's own public playlists show up in search results too
            {"dissid": str(pl["tid"]), "dissname": pl["dirName"], "song_count": len(pl["songs"])}
            for pl in self.playlists
            if p["query"].lower() in pl["dirName"].lower()
        ]
        return {"body": {"songlist": {"list": hits[: p["num_per_page"]]}}, "meta": {"sum": len(hits)}}

    def rpc_get_song_detail_yqq(self, p):
        track = next(s for s in self.catalog.values() if s["mid"] == p["song_mid"])
        return {
            "track_info": track,
            "info": {"genre": {"content": [{"value": "Pop"}]}, "intro": {"content": [{"value": "About it."}]}},
            "extras": {"transname": "Translated"},
        }

    def rpc_GetAlbumDetail(self, p):
        if p["albumMid"] not in self.albums:
            raise SlotError(104400)  # what the server answers for an unknown album
        return {
            "basicInfo": {"albumMid": p["albumMid"], "albumID": 77, "albumName": "Album 77", "desc": "x" * 3000},
            "singer": {"singerList": [{"singerID": 1, "mid": "singer1", "name": "Artist A"}]},
            "company": {"name": "Label"},
        }

    def rpc_GetAlbumSongList(self, p):
        if p["albumMid"] not in self.albums:
            raise SlotError(104400)
        ids = self.albums[p["albumMid"]]
        page = ids[p["begin"] : p["begin"] + p["num"]]
        return {"totalNum": len(ids), "songList": [{"songInfo": self.catalog[i]} for i in page]}

    def rpc_CgiGetAlbumFavInfo(self, p):
        return {"v_list": [], "hasmore": 0}

    def rpc_GetLoginUserInfo(self, p):
        return {"info": {"nick": "Fake Nick", "logo": "http://example.invalid/a.png"}}


@pytest.fixture
def server() -> FakeQQMusic:
    return FakeQQMusic()


@pytest.fixture
def lib(server, cred) -> Library:
    client = Client(cred, transport=server.transport(), sleep=lambda s: None, min_interval=0)
    yield Library(client, sleep=lambda s: None, write_pause=(0, 0))
    client.close()


@pytest.fixture
def runs_path(tmp_path) -> Path:
    d = tmp_path / "runs"
    d.mkdir()
    return d


@pytest.fixture
def new_run(runs_path):
    def factory(command: str = "test", dry_run: bool = False) -> RunLog:
        return RunLog(command, directory=runs_path, dry_run=dry_run)

    return factory
