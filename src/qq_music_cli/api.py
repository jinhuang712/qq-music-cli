"""Library operations on top of the transport. Each call name below was verified live on 2026-10-11."""

from __future__ import annotations

import random
import secrets
import time
from collections.abc import Callable, Iterable
from typing import Any

from . import models
from .client import Client
from .errors import ApiError, AuthError, UsageError
from .models import LIKED_DIR_ID
from .runs import RunLog

WRITE_BATCH = 20  # songs per add/remove call; conservative, not a documented server cap
TRACK_BATCH = 50  # ids per CgiGetTrackInfo call
PAGE_SIZE = 500  # songs per uniform_get_Dissinfo page; the server returned 285 songs in one page
FOLLOW_PAGE = 100  # largest page size observed to work for GetFollowSingerList
FOLLOW_METHODS = {"singers": "GetFollowSingerList", "users": "GetFollowUserList"}
# What y.qq.com's playlist editor sends: every editable field at once. Values we do not change are
# read back first and sent unchanged, so the cover, tags and visibility survive a rename.
EDIT_MASK = 95
UNEDITABLE_DIRS = range(201, 207)  # 我喜欢 and other system lists; the web editor refuses these too
NAME_MAX, DESC_MAX = 20, 2000  # limits the web editor enforces
SEARCH_TYPES = {"song": 0, "singer": 1, "album": 2, "playlist": 3, "mv": 4, "lyric": 7, "user": 8}


class Library:
    def __init__(
        self,
        client: Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        write_pause: tuple[float, float] = (0.8, 1.6),
    ) -> None:
        self.client = client
        self._sleep = sleep
        self.write_pause = write_pause
        self._playlists: list[dict[str, Any]] | None = None

    @property
    def uin(self) -> str:
        cred = self.client.credential
        if not cred:
            raise AuthError("not logged in; run `qqmusic login`")
        return cred.uin

    def _pause(self) -> None:
        lo, hi = self.write_pause
        self._sleep(random.uniform(lo, hi))

    # -- identity ---------------------------------------------------------------------------

    def whoami(self) -> dict[str, Any]:
        data = self.client.rpc("music.UserInfo.userInfoServer", "GetLoginUserInfo", {})
        info = data.get("info") or {}
        return {"uin": self.uin, "nickname": info.get("nick") or None, "avatar": info.get("logo") or None}

    # -- playlists --------------------------------------------------------------------------

    def playlists(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if self._playlists is None or refresh:
            data = self.client.rpc(
                "music.musicasset.PlaylistBaseRead", "GetPlaylistByUin", {"uin": self.uin, "bWithoutStatus": False}
            )
            self._playlists = [models.playlist(p) for p in data.get("v_playlist") or []]
        return self._playlists

    def resolve_playlist(self, ref: str, *, own: bool = True) -> dict[str, Any]:
        """Find a playlist by `liked`, dir_id, tid or exact name. `own=False` also allows any public tid."""
        ref = ref.strip()
        lists = self.playlists()
        if ref.lower() in ("liked", "like", "我喜欢") or ref == str(LIKED_DIR_ID):
            liked = next((p for p in lists if p["liked"]), None)
            if liked is None:
                raise UsageError("this account has no 我喜欢 playlist (dir_id 201)")
            return liked
        if ref.isdigit():
            num = int(ref)
            for p in lists:
                if num in (p["dir_id"], p["tid"]):
                    return p
            if not own:
                return {"dir_id": None, "tid": num, "name": None, "liked": False}
            raise UsageError(f"no playlist of yours has dir_id or tid {num}")
        exact = [p for p in lists if p["name"] == ref]
        if len(exact) == 1:
            return exact[0]
        folded = [p for p in lists if (p["name"] or "").casefold() == ref.casefold()]
        if len(exact) > 1 or len(folded) > 1:
            dupes = exact or folded
            raise UsageError(
                f"{len(dupes)} playlists are named {ref!r}; use a dir_id: " + ", ".join(str(p["dir_id"]) for p in dupes)
            )
        if len(folded) == 1:
            return folded[0]
        names = ", ".join(repr(p["name"]) for p in lists)
        raise UsageError(f"no playlist named {ref!r}. Yours: {names}")

    def playlist_songs(self, tid: int, *, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
        """Read songs page by page until `limit` or the end. Reports `complete` honestly."""
        songs: list[dict[str, Any]] = []
        info: dict[str, Any] = {}
        total = None
        begin = offset
        while True:
            want = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(songs))
            if want <= 0:
                break
            data = self.client.rpc(
                "music.srfDissInfo.aiDissInfo",
                "uniform_get_Dissinfo",
                {"disstid": tid, "song_begin": begin, "song_num": want, "ctx": 1},
            )
            if data.get("code") not in (0, None):
                raise ApiError(
                    data.get("msg") or f"playlist read failed (code {data.get('code')})", code=data.get("code")
                )
            info = data.get("dirinfo") or info
            total = data.get("total_song_num", total)
            page = data.get("songlist") or []
            songs.extend(models.song(s) for s in page)
            begin += len(page)
            if not page or not data.get("hasmore") or (total is not None and begin >= total):
                break
        expected = None if total is None else max(total - offset, 0)
        if limit is not None:
            expected = limit if expected is None else min(limit, expected)
        complete = expected is None or len(songs) >= expected
        return {
            "playlist": models.playlist_info(info),
            "total": total,
            "offset": offset,
            "count": len(songs),
            "complete": complete,
            "songs": songs,
        }

    def song_keys(self, tid: int) -> set[tuple[int, int]]:
        result = self.playlist_songs(tid)
        if not result["complete"]:
            raise ApiError(f"could not read the whole playlist {tid} ({result['count']}/{result['total']})")
        return {(s["id"], s["type"]) for s in result["songs"]}

    def faved_playlists(self) -> list[dict[str, Any]]:
        return self._paged_fav(
            "music.musicasset.PlaylistFavRead", "CgiGetPlaylistFavInfo", "uin", models.faved_playlist
        )

    def faved_albums(self) -> list[dict[str, Any]]:
        return self._paged_fav("music.musicasset.AlbumFavRead", "CgiGetAlbumFavInfo", "euin", models.faved_album)

    def _paged_fav(self, module: str, method: str, key: str, norm: Callable[[dict], dict]) -> list[dict[str, Any]]:
        euin = self.client.credential.euin if self.client.credential else ""
        if not euin:
            raise AuthError("credential has no euin; log in again")
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self.client.rpc(module, method, {key: euin, "offset": offset, "size": 100})
            page = data.get("v_list") or []
            out.extend(norm(x) for x in page)
            offset += len(page)
            if not page or not data.get("hasmore"):
                return out

    def following(self, kind: str = "singers") -> list[dict[str, Any]]:
        """Singers or users the account follows (`music.concern.RelationList`), all pages."""
        if kind not in FOLLOW_METHODS:
            raise UsageError("kind must be `singers` or `users`")
        euin = self.client.credential.euin if self.client.credential else ""
        if not euin:
            raise AuthError("credential has no euin; log in again")
        out: list[dict[str, Any]] = []
        while True:
            data = self.client.rpc(
                "music.concern.RelationList",
                FOLLOW_METHODS[kind],
                {"HostUin": euin, "From": len(out), "Size": FOLLOW_PAGE},
            )
            page = data.get("List") or []
            out.extend(models.followed(x) for x in page)
            if not page or not data.get("HasMore"):
                return out

    # -- songs ------------------------------------------------------------------------------

    def tracks(self, refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Resolve refs to full song objects, keeping input order. Unknown refs raise."""
        refs = list(refs)
        found: dict[str, dict[str, Any]] = {}
        by_id = [r for r in refs if "id" in r]
        by_mid = [r for r in refs if "mid" in r]
        for chunk in _chunks(by_id, TRACK_BATCH):
            data = self.client.rpc(
                "music.trackInfo.UniformRuleCtrl",
                "CgiGetTrackInfo",
                {
                    "ids": [r["id"] for r in chunk],
                    "types": [r.get("type", 0) for r in chunk],
                    "modify_stamp": [0] * len(chunk),
                    "ctx": 0,
                    "client": 1,
                },
            )
            for t in data.get("tracks") or []:
                found[f"id:{t.get('id')}"] = models.song(t)
        for chunk in _chunks(by_mid, TRACK_BATCH):
            data = self.client.rpc(
                "music.trackInfo.UniformRuleCtrl",
                "CgiGetTrackInfo",
                {
                    "mids": [r["mid"] for r in chunk],
                    "types": [0] * len(chunk),
                    "modify_stamp": [0] * len(chunk),
                    "ctx": 0,
                    "client": 1,
                },
            )
            for t in data.get("tracks") or []:
                found[f"mid:{t.get('mid')}"] = models.song(t)
        out, missing = [], []
        for r in refs:
            key = f"id:{r['id']}" if "id" in r else f"mid:{r['mid']}"
            if key in found and found[key].get("id"):
                out.append(found[key])
            else:
                missing.append(r)
        if missing:
            raise UsageError(f"unknown song(s): {missing[:5]}{' ...' if len(missing) > 5 else ''}")
        return out

    def song_details(self, refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        songs = self.tracks(refs)
        out: list[dict[str, Any]] = []
        for chunk in _chunks(songs, 20):
            calls = [("music.pf_song_detail_svr", "get_song_detail_yqq", {"song_mid": s["mid"]}) for s in chunk]
            out.extend(models.song_detail(d) for d in self.client.rpc_many(calls))
        return out

    def search(self, query: str, *, kind: str = "song", page: int = 1, limit: int = 20) -> dict[str, Any]:
        if kind not in SEARCH_TYPES:
            raise UsageError(f"--type must be one of {', '.join(SEARCH_TYPES)}")
        data = self.client.rpc(
            "music.search.SearchCgiService",
            "DoSearchForQQMusicDesktop",
            {
                "query": query,
                "search_type": SEARCH_TYPES[kind],
                "num_per_page": limit,
                "page_num": page,
                "searchid": str(secrets.randbelow(10**18)),
            },
        )
        body = data.get("body") or {}
        meta = data.get("meta") or {}
        block = {
            "song": "song",
            "singer": "singer",
            "album": "album",
            "playlist": "songlist",
            "mv": "mv",
            "lyric": "song",
            "user": "user",
        }[kind]
        items = (body.get(block) or {}).get("list") or []
        results = [models.song(i) for i in items] if block == "song" else [_search_item(kind, i) for i in items]
        return {"query": query, "type": kind, "page": page, "total": meta.get("sum"), "results": results}

    def lyrics(self, ref: dict[str, Any]) -> dict[str, Any]:
        track = self.tracks([ref])[0]
        data = self.client.get_legacy(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg", {"songmid": track["mid"], "nobase64": 1}
        )
        return {
            "song": track,
            "lyric": _unescape(data.get("lyric", "")),
            "trans": _unescape(data.get("trans", "")) or None,
        }

    # -- writes -----------------------------------------------------------------------------

    def create_playlist(self, name: str, *, run: RunLog, allow_duplicate: bool = False) -> dict[str, Any]:
        name = " ".join(name.split())
        if len(name) == 0:
            raise UsageError("playlist name is empty")
        existing = [p for p in self.playlists() if p["name"] == name]
        if existing and not allow_duplicate:
            return {"created": False, "playlist": existing[0], "note": "a playlist with this name already exists"}
        if run.dry_run:
            return {"created": False, "dry_run": True, "playlist": {"name": name}}
        request = {"dirName": name}
        data = self.client.rpc("music.musicasset.PlaylistBaseWrite", "AddPlaylist", request, idempotent=False)
        result = data.get("result") or {}
        if result.get("bSafetyHitName"):
            raise ApiError("the name was rejected by content safety", data=data)
        # The response echoes dirName in a non-UTF-8 encoding for CJK names; the stored name is correct.
        created = {"dir_id": result.get("dirId"), "tid": result.get("tid"), "name": name}
        run.record({"op": "create", "playlist": created})
        self._playlists = None
        return {"created": True, "playlist": created}

    def playlist_meta(self, dir_id: int) -> dict[str, Any]:
        """Editable fields of an own playlist, read the way the web editor reads them."""
        data = self.client.rpc(
            "music.srfDissInfo.aiDissInfo",
            "uniform_get_Dissinfo",
            {"dirid": dir_id, "optype": 3, "tag": 1, "userinfo": 0, "pic_dpi": 300},
        )
        info = data.get("dirinfo")
        if not info:
            raise ApiError(f"could not read playlist dir_id {dir_id}", data=data)
        return info

    def edit_playlist(
        self, pl: dict[str, Any], *, run: RunLog, name: str | None = None, desc: str | None = None
    ) -> dict[str, Any]:
        _require_own(pl)
        if pl["dir_id"] in UNEDITABLE_DIRS:
            raise UsageError("this playlist cannot be renamed or edited (QQ Music does not allow it)")
        if name is not None:
            name = name.strip()
            if not name or len(name) > NAME_MAX:
                raise UsageError(f"playlist name must be 1-{NAME_MAX} characters")
        if desc is not None and len(desc) > DESC_MAX:
            raise UsageError(f"description must be at most {DESC_MAX} characters")
        info = self.playlist_meta(pl["dir_id"])
        before = {"name": info.get("title") or "", "desc": info.get("desc") or ""}
        after = {"name": before["name"] if name is None else name, "desc": before["desc"] if desc is None else desc}
        report: dict[str, Any] = {"playlist": _pl_ref(pl), "before": before, "after": after, "dry_run": run.dry_run}
        if after == before:
            return {**report, "changed": False}
        if run.dry_run:
            return {**report, "changed": False}
        tags = ",".join(str(t.get("id")) for t in info.get("tag") or [] if isinstance(t, dict) and t.get("id"))
        self.client.rpc(
            "music.musicasset.PlaylistBaseWrite",
            "EditPlaylist",
            {
                "dirId": pl["dir_id"],
                "mask": EDIT_MASK,
                "dirNewName": after["name"],
                "dirNewDesc": after["desc"],
                "dirNewPicUrl": info.get("picurl") or "",
                "dirNewPicUrl2": info.get("picurl2") or "",
                "dirNewtaglist": tags,
                "dirShow": info.get("dir_show", 1),
            },
        )
        run.record({"op": "edit", "playlist": _pl_ref(pl), "before": before, "after": after})
        check = self.playlist_meta(pl["dir_id"])
        seen = {"name": check.get("title") or "", "desc": check.get("desc") or ""}
        self._playlists = None
        return {**report, "changed": True, "verified": seen == after, "now": seen}

    def delete_playlist(self, pl: dict[str, Any], *, run: RunLog) -> dict[str, Any]:
        if pl.get("liked") or pl.get("dir_id") == LIKED_DIR_ID:
            raise UsageError("refusing to delete 我喜欢")
        snapshot = self.playlist_songs(pl["tid"]) if pl.get("song_count") else {"songs": [], "complete": True}
        if not snapshot["complete"]:
            raise ApiError("could not snapshot the playlist before deleting it; nothing was deleted")
        if run.dry_run:
            return {"deleted": False, "dry_run": True, "playlist": pl, "song_count": len(snapshot["songs"])}
        data = self.client.rpc(
            "music.musicasset.PlaylistBaseWrite", "DelPlaylist", {"dirId": pl["dir_id"]}, idempotent=False
        )
        result = data.get("result") or {}
        if not result.get("dirId"):
            raise ApiError("server reported nothing deleted", data=data)
        run.record({"op": "delete", "playlist": _pl_ref(pl), "songs": [_song_ref(s) for s in snapshot["songs"]]})
        self._playlists = None
        return {"deleted": True, "playlist": _pl_ref(pl), "song_count": len(snapshot["songs"])}

    def add_songs(
        self, pl: dict[str, Any], refs: list[dict[str, Any]], *, run: RunLog, verify: bool = True
    ) -> dict[str, Any]:
        _require_own(pl)
        songs = _dedupe(self.tracks(refs))
        present = self.song_keys(pl["tid"])
        already = [s for s in songs if (s["id"], s["type"]) in present]
        todo = [s for s in songs if (s["id"], s["type"]) not in present]
        report: dict[str, Any] = {
            "playlist": _pl_ref(pl),
            "requested": len(songs),
            "already_present": [_brief(s) for s in already],
            "added": [],
            "dry_run": run.dry_run,
        }
        if run.dry_run:
            report["would_add"] = [_brief(s) for s in todo]
            return report
        for i, chunk in enumerate(_chunks(todo, WRITE_BATCH)):
            if i:
                self._pause()
            data = self.client.rpc(
                "music.musicasset.PlaylistDetailWrite",
                "AddSonglist",
                {"dirId": pl["dir_id"], "v_songInfo": [{"songType": s["type"], "songId": s["id"]} for s in chunk]},
            )
            existed = {
                (x.get("songId"), x.get("songType"))
                for x in (data.get("result") or {}).get("songlist") or []
                if x.get("existed")
            }
            new = [s for s in chunk if (s["id"], s["type"]) not in existed]
            if new:
                run.record({"op": "add", "playlist": _pl_ref(pl), "songs": [_song_ref(s) for s in new]})
            report["added"].extend(_brief(s) for s in new)
            report["already_present"].extend(_brief(s) for s in chunk if (s["id"], s["type"]) in existed)
        if verify and todo:
            after = self.song_keys(pl["tid"])
            report["verified"] = True
            report["missing_after_write"] = [_brief(s) for s in todo if (s["id"], s["type"]) not in after]
        self._playlists = None
        return report

    def remove_songs(
        self, pl: dict[str, Any], refs: list[dict[str, Any]], *, run: RunLog, verify: bool = True
    ) -> dict[str, Any]:
        _require_own(pl)
        songs = _dedupe(self.tracks(refs))
        present = self.song_keys(pl["tid"])
        absent = [s for s in songs if (s["id"], s["type"]) not in present]
        todo = [s for s in songs if (s["id"], s["type"]) in present]
        report: dict[str, Any] = {
            "playlist": _pl_ref(pl),
            "requested": len(songs),
            "not_present": [_brief(s) for s in absent],
            "removed": [],
            "dry_run": run.dry_run,
        }
        if run.dry_run:
            report["would_remove"] = [_brief(s) for s in todo]
            return report
        for i, chunk in enumerate(_chunks(todo, WRITE_BATCH)):
            if i:
                self._pause()
            data = self.client.rpc(
                "music.musicasset.PlaylistDetailWrite",
                "DelSonglist",
                {"dirId": pl["dir_id"], "v_songInfo": [{"songType": s["type"], "songId": s["id"]} for s in chunk]},
            )
            # dirId comes back as 0 when nothing was removed
            if (data.get("result") or {}).get("dirId"):
                run.record({"op": "remove", "playlist": _pl_ref(pl), "songs": [_song_ref(s) for s in chunk]})
                report["removed"].extend(_brief(s) for s in chunk)
        if verify and todo:
            after = self.song_keys(pl["tid"])
            report["verified"] = True
            report["still_present"] = [_brief(s) for s in todo if (s["id"], s["type"]) in after]
        self._playlists = None
        return report

    # -- undo -------------------------------------------------------------------------------

    def undo(self, run_data: dict[str, Any], *, run: RunLog, force: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for op in reversed(run_data["ops"]):
            kind = op["op"]
            try:
                if kind == "add":
                    pl = self._current(op["playlist"])
                    r = self.remove_songs(pl, [_ref_of(s) for s in op["songs"]], run=run)
                    results.append({"undo": "add", "removed": len(r["removed"]), "playlist": pl["name"]})
                elif kind == "remove":
                    pl = self._current(op["playlist"])
                    r = self.add_songs(pl, [_ref_of(s) for s in op["songs"]], run=run)
                    results.append({"undo": "remove", "added": len(r["added"]), "playlist": pl["name"]})
                elif kind == "create":
                    pl = self._current(op["playlist"])
                    if pl.get("song_count") and not force:
                        results.append(
                            {"undo": "create", "skipped": "playlist is not empty; use --force", "playlist": pl["name"]}
                        )
                        continue
                    self.delete_playlist(pl, run=run)
                    results.append({"undo": "create", "deleted": pl["name"]})
                elif kind == "edit":
                    pl = self._current(op["playlist"])
                    old = op["before"]
                    self.edit_playlist(pl, run=run, name=old["name"], desc=old["desc"])
                    results.append({"undo": "edit", "restored": old["name"], "playlist": pl["name"]})
                elif kind == "delete":
                    created = self.create_playlist(op["playlist"]["name"], run=run, allow_duplicate=True)
                    pl = self._current(created["playlist"]) if not run.dry_run else created["playlist"]
                    added = 0
                    if op["songs"] and not run.dry_run:
                        added = len(self.add_songs(pl, [_ref_of(s) for s in op["songs"]], run=run)["added"])
                    results.append({"undo": "delete", "recreated": op["playlist"]["name"], "added": added})
            except (UsageError, ApiError) as exc:
                results.append({"undo": kind, "error": exc.to_dict(), "playlist": op.get("playlist", {}).get("name")})
        return results

    def _current(self, ref: dict[str, Any]) -> dict[str, Any]:
        for p in self.playlists(refresh=True):
            if p["tid"] == ref.get("tid") or (
                ref.get("dir_id") and p["dir_id"] == ref.get("dir_id") and p["name"] == ref.get("name")
            ):
                return p
        raise UsageError(f"playlist {ref.get('name')!r} no longer exists")

    # -- export -----------------------------------------------------------------------------

    def export(self) -> dict[str, Any]:
        lists = []
        for p in self.playlists(refresh=True):
            result = self.playlist_songs(p["tid"]) if p["song_count"] else {"songs": [], "complete": True, "total": 0}
            lists.append({**p, "complete": result["complete"], "songs": result["songs"]})
        return {
            "exported_at": int(time.time()),
            "uin": self.uin,
            "playlists": lists,
            "faved_playlists": self.faved_playlists(),
            "faved_albums": self.faved_albums(),
            "following_singers": self.following("singers"),
        }


# -- helpers --------------------------------------------------------------------------------------


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _dedupe(songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for s in songs:
        key = (s["id"], s["type"])
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _require_own(pl: dict[str, Any]) -> None:
    if not pl.get("dir_id"):
        raise UsageError("you can only change your own playlists")


def _pl_ref(pl: dict[str, Any]) -> dict[str, Any]:
    return {"dir_id": pl.get("dir_id"), "tid": pl.get("tid"), "name": pl.get("name")}


def _song_ref(s: dict[str, Any]) -> dict[str, Any]:
    return {"id": s["id"], "type": s["type"], "mid": s.get("mid"), "name": s.get("name"), "artist": s.get("artist")}


def _brief(s: dict[str, Any]) -> dict[str, Any]:
    return {"id": s["id"], "type": s["type"], "name": s.get("name"), "artist": s.get("artist")}


def _ref_of(s: dict[str, Any]) -> dict[str, Any]:
    return {"id": s["id"], "type": s["type"]}


def _unescape(text: str) -> str:
    import html

    return html.unescape(text or "")


def _search_item(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    if kind == "album":
        singers = raw.get("singer_list") or raw.get("singer") or []
        return {
            "id": raw.get("albumID"),
            "mid": raw.get("albumMID"),
            "name": raw.get("albumName"),
            "artist": raw.get("singerName") or " / ".join(s.get("name", "") for s in singers if isinstance(s, dict)),
            "release_date": raw.get("publicTime") or None,
            "song_count": raw.get("song_count"),
        }
    if kind == "playlist":
        return {
            "tid": int(raw["dissid"]) if str(raw.get("dissid", "")).isdigit() else raw.get("dissid"),
            "name": raw.get("dissname"),
            "creator": (raw.get("creator") or {}).get("name"),
            "song_count": raw.get("song_count"),
            "listen_count": raw.get("listennum"),
        }
    if kind == "singer":
        return {
            "id": raw.get("singerID"),
            "mid": raw.get("singerMID"),
            "name": raw.get("singerName"),
            "song_count": raw.get("songNum"),
        }
    return raw
