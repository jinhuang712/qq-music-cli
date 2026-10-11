"""Normalise raw API objects into small, stable JSON shapes, and parse song references."""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import UsageError

LIKED_DIR_ID = 201
MID_RE = re.compile(r"^[0-9A-Za-z]{14}$")


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
    }


def playlist_info(dirinfo: dict[str, Any]) -> dict[str, Any]:
    """`dirinfo` block from `uniform_get_Dissinfo`; works for any public playlist too."""
    return {
        "dir_id": dirinfo.get("dirid"),
        "tid": dirinfo.get("id"),
        "name": dirinfo.get("title"),
        "song_count": dirinfo.get("songnum"),
        "creator": dirinfo.get("host_nick") or None,
        "desc": dirinfo.get("desc") or None,
        "tags": dirinfo.get("vec_tagname") or [],
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
    }


def followed(raw: dict[str, Any]) -> dict[str, Any]:
    """A followed singer or user from `music.concern.RelationList`."""
    return {
        "name": (raw.get("Name") or "").strip(),
        "mid": raw.get("MID") or None,
        "euin": raw.get("EncUin") or None,
        "fans": raw.get("FanNum"),
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
    )
    return out


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
