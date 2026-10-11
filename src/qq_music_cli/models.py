"""Normalise raw API objects into small, stable JSON shapes, and parse song references."""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import UsageError

LIKED_DIR_ID = 201
MID_RE = re.compile(r"^[0-9A-Za-z]{14}$")
COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg"  # album cover by album mid
# Page links in the form y.qq.com itself uses; agents should take these instead of building their own.
SONG_URL = "https://y.qq.com/n/ryqq_v2/songDetail/{mid}"
ALBUM_URL = "https://y.qq.com/n/ryqq_v2/albumDetail/{mid}"
PLAYLIST_URL = "https://y.qq.com/n/ryqq_v2/playlist/{tid}"
# Audio files a song has, judged by which file sizes are non-zero.
QUALITY_FILES = (("320k", "size_320mp3"), ("flac", "size_flac"), ("hires", "size_hires"), ("dolby", "size_dolby"))

# Field sets for `--fields`. Model functions return every field; commands print DEFAULT unless asked.
# Lists are what costs tokens, so defaults stay small and anything else is opt-in.
SONG_DEFAULT = ("id", "mid", "type", "name", "artist", "album", "duration")
SONG_FIELDS = (
    *SONG_DEFAULT,
    *("title", "subtitle", "singers", "release_date", "language", "genre", "vip"),
    *("bpm", "mv", "qualities", "track_no", "cover", "url"),
)
# Only `qqmusic song` has these: each needs one more call per song (`get_song_detail_yqq`).
SONG_DETAIL_FIELDS = ("genre_name", "language_name", "company", "publish_time", "intro", "trans_name")
SONG_DETAIL_DEFAULT = SONG_DETAIL_FIELDS[:4]  # what `--detail` adds
PLAYLIST_DEFAULT = ("dir_id", "tid", "name", "song_count", "liked", "public", "tags", "created_at", "updated_at")
# Read one `uniform_get_Dissinfo` call per playlist, so they are fetched only when asked for.
PLAYLIST_EXTRA_FIELDS = ("listen_count", "desc")
PLAYLIST_FIELDS = (*PLAYLIST_DEFAULT, "cover", "url", *PLAYLIST_EXTRA_FIELDS)
FAVED_PLAYLIST_DEFAULT = ("tid", "name", "creator", "song_count", "faved_at")
FAVED_PLAYLIST_EXTRA_FIELDS = ("listen_count", "desc", "tags")
FAVED_PLAYLIST_FIELDS = (*FAVED_PLAYLIST_DEFAULT, "updated_at", "cover", "url", *FAVED_PLAYLIST_EXTRA_FIELDS)
FAVED_ALBUM_DEFAULT = ("id", "mid", "name", "artist", "song_count", "release_date", "faved_at")
FAVED_ALBUM_FIELDS = (*FAVED_ALBUM_DEFAULT, "cover", "url")
FOLLOWED_DEFAULT = ("name", "mid", "euin", "fans")
FOLLOWED_FIELDS = (*FOLLOWED_DEFAULT, "avatar")
# One comment-list call per song (10 songs per request), so any song list offers it only on request.
SONG_COUNT_FIELDS = ("comment_count",)
COMMENT_DEFAULT = ("content", "likes", "replies", "time")
COMMENT_FIELDS = (*COMMENT_DEFAULT, "user", "id")
# `qqmusic match`: the user's songs found in public playlists. Meant to be shown to the user, so links are in.
MATCH_DEFAULT = ("id", "type", "name", "artist", "url", "hits", "in")
MATCH_FIELDS = (*MATCH_DEFAULT, *(f for f in SONG_FIELDS if f not in MATCH_DEFAULT))


def _singers(raw: Any) -> list[dict[str, Any]]:
    out = []
    for s in raw or []:
        if isinstance(s, dict):
            out.append({"id": s.get("id"), "mid": s.get("mid"), "name": s.get("name") or s.get("title")})
    return out


def song(raw: dict[str, Any]) -> dict[str, Any]:
    """Song object from playlist reads, track info and desktop search."""
    singers = _singers(raw.get("singer"))
    album = raw.get("album") or {}
    pay = raw.get("pay") or {}
    name = raw.get("name") or raw.get("title") or ""
    title = raw.get("title") or name
    return {
        "id": raw.get("id"),
        "mid": raw.get("mid"),
        "type": raw.get("type", 0) or 0,
        "name": name,
        "title": title if title != name else None,
        "subtitle": raw.get("subtitle") or None,
        "artist": " / ".join(s["name"] for s in singers if s.get("name")),
        "singers": singers,
        "album": {"id": album.get("id"), "mid": album.get("mid"), "name": album.get("name") or album.get("title")}
        if album
        else None,
        "duration": raw.get("interval"),
        "release_date": raw.get("time_public") or album.get("time_public") or None,
        "language": raw.get("language"),
        "genre": raw.get("genre"),
        "vip": bool(pay.get("pay_play")),
        "bpm": raw.get("bpm") or None,
        "mv": (raw.get("mv") or {}).get("vid") or None,
        "qualities": [name for name, key in QUALITY_FILES if (raw.get("file") or {}).get(key)],
        "track_no": raw.get("index_album") or None,
        "cover": _cover(album.get("mid")),
        "url": SONG_URL.format(mid=raw["mid"]) if raw.get("mid") else None,
    }


def playlist(raw: dict[str, Any], tag_names: dict[int, str] | None = None) -> dict[str, Any]:
    """Own playlist from `PlaylistBaseRead.GetPlaylistByUin`.

    That API always leaves `desc` empty (checked live), so no description here; `qqmusic show` has it.
    Tags come only as ids (`strTagIdList`); `tag_names` maps them to names from `getPlaylistTag`.
    """
    dir_id = raw.get("dirId")
    ids = [int(x) for x in str(raw.get("strTagIdList") or "").split(",") if x.strip().isdigit()]
    names = tag_names or {}
    return {
        "dir_id": dir_id,
        "tid": raw.get("tid"),
        "name": raw.get("dirName"),
        "song_count": raw.get("songNum"),
        "liked": dir_id == LIKED_DIR_ID,
        "public": raw.get("dirShow") == 1,
        "tags": [names.get(i, str(i)) for i in ids],
        "created_at": raw.get("createTime"),
        "updated_at": raw.get("updateTime"),
        "cover": raw.get("picUrl") or None,
        "url": _playlist_url(raw.get("tid")),
    }


def playlist_info(dirinfo: dict[str, Any]) -> dict[str, Any]:
    """`dirinfo` block from `uniform_get_Dissinfo`; works for any public playlist too.

    Tag names come only when the call asks for them (`tag: 1`); otherwise `tag` is empty.
    """
    tags = [t.get("name") for t in dirinfo.get("tag") or [] if isinstance(t, dict) and t.get("name")]
    return {
        "dir_id": dirinfo.get("dirid"),
        "tid": dirinfo.get("id"),
        "name": dirinfo.get("title"),
        "song_count": dirinfo.get("songnum"),
        "creator": dirinfo.get("host_nick") or None,
        "desc": dirinfo.get("desc") or None,
        "tags": tags or dirinfo.get("vec_tagname") or [],
        "listen_count": dirinfo.get("listennum"),
        "cover": dirinfo.get("picurl") or None,
        "url": _playlist_url(dirinfo.get("id")),
        "created_at": dirinfo.get("ctime"),
        "updated_at": dirinfo.get("mtime"),
    }


def faved_playlist(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "tid": raw.get("tid"),
        "name": raw.get("name"),
        "creator": raw.get("nickname") or None,
        "song_count": raw.get("songnum"),
        "faved_at": raw.get("orderTime"),
        "updated_at": raw.get("updateTime"),
        "cover": raw.get("logo") or None,
        "url": _playlist_url(raw.get("tid")),
    }


def faved_album(raw: dict[str, Any]) -> dict[str, Any]:
    singers = _singers(raw.get("v_singer"))
    return {
        "id": raw.get("id"),
        "mid": raw.get("mid"),
        "name": raw.get("name"),
        "artist": " / ".join(s["name"] for s in singers if s.get("name")),
        "song_count": raw.get("songnum"),
        "release_date": _date(raw.get("pubtime")),
        "faved_at": raw.get("ordertime"),
        "cover": raw.get("logo") or None,
        "url": ALBUM_URL.format(mid=raw["mid"]) if raw.get("mid") else None,
    }


def followed(raw: dict[str, Any]) -> dict[str, Any]:
    """A followed singer or user from `music.concern.RelationList`."""
    return {
        "name": (raw.get("Name") or "").strip(),
        "mid": raw.get("MID") or None,
        "euin": raw.get("EncUin") or None,
        "fans": raw.get("FanNum"),
        "avatar": raw.get("AvatarUrl") or None,
    }


def comment(raw: dict[str, Any]) -> dict[str, Any]:
    """One comment from `music.globalComment.CommentRead` (hot or newest list)."""
    return {
        "content": raw.get("Content") or "",
        "likes": raw.get("PraiseNum"),
        "replies": raw.get("ReplyCnt"),
        "time": raw.get("PubTime"),
        "user": raw.get("Nick") or None,
        "id": raw.get("CmId") or None,
    }


def song_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """`get_song_detail_yqq`: the only call that returns genre / language / release as text."""
    info = raw.get("info") or {}

    def values(key: str) -> list[str]:
        block = info.get(key) or {}
        return [str(c["value"]).strip() for c in block.get("content") or [] if str(c.get("value") or "").strip()]

    out = song(raw.get("track_info") or {})
    out.update(
        genre_name=", ".join(values("genre")) or None,
        language_name=", ".join(values("lan")) or None,
        company=", ".join(values("company")) or None,
        publish_time=", ".join(values("pub_time")) or None,
        intro="\n".join(values("intro")) or None,
        trans_name=(raw.get("extras") or {}).get("transname") or None,
    )
    return out


def album(detail: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    """`AlbumInfoServer.GetAlbumDetail`; `total` is the song count from `GetAlbumSongList`."""
    basic = detail.get("basicInfo") or {}
    singers = [
        {"id": s.get("singerID"), "mid": s.get("mid"), "name": s.get("name")}
        for s in (detail.get("singer") or {}).get("singerList") or []
        if isinstance(s, dict)
    ]
    return {
        "id": basic.get("albumID"),
        "mid": basic.get("albumMid"),
        "name": basic.get("albumName"),
        "trans_name": basic.get("tranName") or None,
        "artist": " / ".join(s["name"] for s in singers if s.get("name")),
        "singers": singers,
        "release_date": basic.get("publishDate") or None,
        "type": basic.get("albumType") or None,
        "language": basic.get("language") or None,
        "genre": basic.get("genre") or basic.get("genreNew") or None,
        "company": (detail.get("company") or {}).get("name") or None,
        "song_count": total,
        "labels": [x for x in basic.get("recLabels") or [] if x],
        "awards": [a.get("name") for a in basic.get("awards") or [] if isinstance(a, dict) and a.get("name")],
        "rec_text": basic.get("recText") or None,
        "desc": basic.get("desc") or None,
        "cover": _cover(basic.get("albumMid")),
        "url": ALBUM_URL.format(mid=basic["albumMid"]) if basic.get("albumMid") else None,
    }


def _playlist_url(tid: Any) -> str | None:
    return PLAYLIST_URL.format(tid=tid) if tid else None


def _cover(album_mid: Any) -> str | None:
    return COVER_URL.format(mid=album_mid) if album_mid else None


def _date(value: Any) -> str | None:
    """Unix seconds or an existing date string -> `YYYY-MM-DD`."""
    if isinstance(value, (int, float)) and value > 0:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(value, _dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    return str(value) if value else None


def project(item: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    if not fields:
        return item
    return {f: item.get(f) for f in fields}


def select_fields(spec: str | None, default: tuple[str, ...], available: tuple[str, ...]) -> list[str]:
    """Parse `--fields`: nothing = `default`; `a,b` = exactly these; `+a,b` = default plus these; `all`."""
    spec = (spec or "").strip()
    if not spec:
        return list(default)
    if spec == "all":
        return list(available)
    names = [f.strip() for f in spec.removeprefix("+").split(",") if f.strip()]
    unknown = [n for n in names if n not in available]
    if unknown:
        raise UsageError(f"unknown field(s): {', '.join(unknown)}. Available: {', '.join(available)}")
    return list(dict.fromkeys([*default, *names])) if spec.startswith("+") else names


# -- song references ----------------------------------------------------------------------------


def parse_song_ref(token: str | int | dict[str, Any]) -> dict[str, Any]:
    """Accept `123456` (id), `123456:0` (id:type), a 14-char mid, or a JSON object with id/type or mid.

    JSON objects can be whole song objects as printed by `qqmusic show`, so output pipes back into input.
    """
    if isinstance(token, bool):
        raise UsageError(f"not a song reference: {token!r}")
    if isinstance(token, int):
        return {"id": token}
    if isinstance(token, dict):
        obj = token
    else:
        token = token.strip()
        if not token:
            raise UsageError("empty song reference")
        if token.startswith("{"):
            try:
                obj = json.loads(token)
            except json.JSONDecodeError as exc:
                raise UsageError(f"bad JSON song reference: {token[:80]}") from exc
        elif ":" in token and token.split(":", 1)[0].isdigit() and token.split(":", 1)[1].isdigit():
            sid, stype = token.split(":", 1)
            return {"id": int(sid), "type": int(stype)}
        elif token.isdigit():
            return {"id": int(token)}
        elif MID_RE.match(token):
            return {"mid": token}
        else:
            raise UsageError(f"not a song id, id:type or mid: {token!r}")
    if obj.get("id"):
        ref: dict[str, Any] = {"id": int(obj["id"])}
        if obj.get("type") is not None:
            ref["type"] = int(obj["type"])
        return ref
    if obj.get("mid"):
        return {"mid": str(obj["mid"])}
    raise UsageError(f"song object has neither id nor mid: {str(obj)[:80]}")


def read_song_refs(args: list[str], stdin_text: str | None) -> list[dict[str, Any]]:
    """Refs from argv plus stdin (one per line, or a JSON array, or a `qqmusic show` JSON document)."""
    refs = [parse_song_ref(a) for a in args]
    text = (stdin_text or "").strip()
    if not text:
        return refs
    items: list[Any]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        items = [line for line in text.splitlines() if line.strip()]  # plain tokens or JSONL
    else:
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("songs"), list):
            items = data["songs"]
        else:
            items = [data if isinstance(data, dict) else str(data)]
    refs.extend(parse_song_ref(i) for i in items)
    return refs
