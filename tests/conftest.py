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
                "singer": [{"id": 1, "mid": "singer1", "name": "Artist A"}, {"id": 2, "mid": "singer2", "name": "Artist B"}],
                "album": {"id": 77, "mid": "album77", "name": "Album 77"},
                "interval": 200,
                "time_public": "2020-01-01",
                "pay": {"pay_play": 0},
            }
        self.playlists: list[dict[str, Any]] = []
        self._next_dir = 301
        self._next_tid = 7001
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.max_visible: int | None = None  # server stops returning songs after this many (hasmore=0)
        self.add_playlist("我喜欢", dir_id=201, tid=5001)

    # -- state helpers
    def add_playlist(self, name: str, songs: list[int] | None = None, dir_id: int | None = None, tid: int | None = None) -> dict[str, Any]:
        if dir_id is None:
            dir_id, self._next_dir = self._next_dir, self._next_dir + 1
        if tid is None:
            tid, self._next_tid = self._next_tid, self._next_tid + 1
        pl = {"dirId": dir_id, "tid": tid, "dirName": name, "songs": list(songs or [])}
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
            else:
                out[key] = {"code": 0, "data": fn(req["param"])}
        return httpx.Response(200, json=out)

    # -- rpc methods
    def rpc_GetPlaylistByUin(self, p):
        return {
            "v_playlist": [
                {"dirId": pl["dirId"], "tid": pl["tid"], "dirName": pl["dirName"], "songNum": len(pl["songs"]), "dirShow": 1}
                for pl in self.playlists
            ]
        }

    def rpc_uniform_get_Dissinfo(self, p):
        pl = next((x for x in self.playlists if x["tid"] == p["disstid"]), None)
        if pl is None:
            return {"code": 1, "msg": "no such playlist"}
        visible = pl["songs"] if self.max_visible is None else pl["songs"][: self.max_visible]
        begin, num = p["song_begin"], p["song_num"]
        page = visible[begin : begin + num]
        return {
            "code": 0,
            "dirinfo": {"id": pl["tid"], "dirid": pl["dirId"], "title": pl["dirName"], "songnum": len(pl["songs"])},
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
