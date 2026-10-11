"""`qqmusic` command line. stdout is always one JSON document; progress and prompts go to stderr.

Exit codes: 0 ok, 1 API error, 2 usage, 3 auth (log in again), 4 risk control (slow down), 5 network.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import typer

from . import __version__, login as login_flows, official
from .api import SEARCH_TYPES, Library
from .auth import CredentialStore, credential_from_cookies, parse_cookie_text
from .client import Client
from .errors import AuthError, QQMusicError, UsageError
from .login_ui import LoginPage
from .models import project, read_song_refs, parse_song_ref
from .paths import data_dir, exports_dir
from .runs import RunLog, list_runs, load_run, mark_undone

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Manage your own QQ Music library from the command line. Output is JSON.",
)
_state: dict[str, Any] = {"compact": False}
REFRESH_MARGIN = 12 * 3600  # refresh automatically when the key has less than this left


# -- output helpers -------------------------------------------------------------------------------


def emit(data: Any) -> None:
    indent = None if _state["compact"] else 2
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=indent, default=str) + "\n")


def note(event: str, **fields: Any) -> None:
    sys.stderr.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def _fields(spec: str | None) -> list[str] | None:
    return [f.strip() for f in spec.split(",") if f.strip()] if spec else None


def _stdin_text(use_stdin: bool) -> str | None:
    return sys.stdin.read() if use_stdin else None


# -- session --------------------------------------------------------------------------------------


def _library(*, required: bool = True) -> Library:
    store = CredentialStore()
    cred = store.load()
    if cred is None and required:
        raise AuthError("not logged in; run `qqmusic login`")
    if cred is not None:
        left = cred.seconds_left()
        if (
            left is not None
            and left < REFRESH_MARGIN
            and (cred.login.get("refresh_key") or cred.login.get("refresh_token"))
        ):
            try:
                cred = login_flows.refresh(cred)
                store.save(cred)
                left = cred.seconds_left()
                note("credential_refreshed", expires_at=cred.expires_at)
            except QQMusicError as exc:
                note("credential_refresh_failed", error=exc.message)
        if left is not None and left <= 0:
            raise AuthError("login expired; run `qqmusic login`")
    return Library(Client(cred))


def _print_version(value: bool) -> None:
    if value:
        emit({"version": __version__})
        raise typer.Exit()


@app.callback()
def _main(
    compact: bool = typer.Option(False, "--compact", help="Print JSON on one line."),
    version: bool = typer.Option(
        False, "--version", callback=_print_version, is_eager=True, help="Print the version and exit."
    ),
) -> None:
    _state["compact"] = compact


# -- auth -----------------------------------------------------------------------------------------


@app.command()
def login(
    wechat: bool = typer.Option(False, "--wechat", help="Scan with WeChat instead of QQ."),
    cookie_file: Path | None = typer.Option(
        None,
        "--cookie-file",
        help="Import cookies (Playwright storage-state JSON, cookie list JSON, or a Cookie header).",
    ),
    ui: bool = typer.Option(True, "--ui/--no-ui", help="Show the QR code and live status in a small browser window."),
    timeout: float = typer.Option(180, help="Seconds to wait for the scan."),
) -> None:
    """Log in by scanning a QR code, or import cookies. The credential is stored in the macOS Keychain."""
    store = CredentialStore()
    page = None
    try:
        if cookie_file:
            cookies, expiry = parse_cookie_text(cookie_file.expanduser().read_text())
            cred = credential_from_cookies(cookies, key_expiry=expiry)
        else:
            if ui:
                page = LoginPage()
                note("login_page", url=page.start())
                page.open()
            deadline = time.time() + timeout

            def on_event(event: str, info: dict[str, Any]) -> None:
                if event == login_flows.QR_READY:
                    ext = "png" if info["mimetype"] == "image/png" else "jpg"
                    path = data_dir() / f"login-qr.{ext}"
                    path.write_bytes(info["image"])
                    app_name = "微信" if info["kind"] == "wechat" else "QQ"
                    note("qr_ready", path=str(path), scan_with="WeChat" if info["kind"] == "wechat" else "QQ")
                    if page:
                        page.set_qr(info["image"], info["mimetype"], app_name, deadline)
                    if info.get("url") and sys.stderr.isatty():
                        import qrcode

                        qr = qrcode.QRCode(border=1)
                        qr.add_data(info["url"])
                        qr.print_ascii(out=sys.stderr, invert=True)
                else:
                    note(event)
                    if page:
                        page.update(status=event)

            flow = login_flows.wechat_login if wechat else login_flows.qq_login
            cred = flow(on_event, timeout=timeout)
        with Client(cred) as client:
            who = Library(client).whoami()  # proves the credential works before saving it
        store.save(cred)
    except QQMusicError as exc:
        if page:
            page.update(
                status="error"
                if page.snapshot()["status"] not in ("expired", "refused")
                else page.snapshot()["status"],
                message=exc.message,
            )
            page.close()
        raise
    if page:
        page.update(status="success", nickname=who["nickname"])
        page.close()
    emit({"logged_in": True, "nickname": who["nickname"], "store": store.backend, **cred.summary()})


@app.command()
def logout() -> None:
    """Forget the stored credential."""
    store = CredentialStore()
    emit({"logged_out": store.clear(), "store": store.backend})


@app.command()
def status(offline: bool = typer.Option(False, "--offline", help="Do not contact the server.")) -> None:
    """Show the stored credential and check that it still works."""
    store = CredentialStore()
    cred = store.load()
    if cred is None:
        emit({"logged_in": False, "store": store.backend})
        return
    out: dict[str, Any] = {"logged_in": True, "store": store.backend, **cred.summary()}
    if not offline:
        try:
            with Client(cred) as client:
                out.update(valid=True, nickname=Library(client).whoami()["nickname"])
        except AuthError as exc:
            out.update(valid=False, error=exc.message)
    emit(out)


@app.command()
def refresh() -> None:
    """Renew the login key before it expires (keys last 3 days)."""
    store = CredentialStore()
    cred = store.load()
    if cred is None:
        raise AuthError("not logged in; run `qqmusic login`")
    fresh = login_flows.refresh(cred)
    store.save(fresh)
    emit({"refreshed": True, **fresh.summary()})


# -- reads ----------------------------------------------------------------------------------------


@app.command()
def playlists() -> None:
    """List your own playlists (including 我喜欢, dir_id 201)."""
    emit(_library().playlists())


@app.command()
def show(
    playlist: str = typer.Argument(..., help="Name, dir_id, tid, or `liked`. Any public tid works too."),
    offset: int = typer.Option(0, help="Skip this many songs."),
    limit: int | None = typer.Option(None, help="Return at most this many songs (default: all)."),
    fields: str | None = typer.Option(None, help="Comma-separated song fields to keep, e.g. id,type,name,artist."),
) -> None:
    """List the songs in a playlist."""
    lib = _library()
    pl = lib.resolve_playlist(playlist, own=False)
    result = lib.playlist_songs(pl["tid"], offset=offset, limit=limit)
    result["songs"] = [project(s, _fields(fields)) for s in result["songs"]]
    emit(result)


@app.command()
def liked(
    limit: int | None = typer.Option(None, help="Return at most this many songs (default: all)."),
    fields: str | None = typer.Option(None, help="Comma-separated song fields to keep."),
) -> None:
    """List the songs in 我喜欢."""
    show(playlist="liked", offset=0, limit=limit, fields=fields)


@app.command()
def faved(kind: str = typer.Argument("playlists", help="`playlists` or `albums`.")) -> None:
    """List playlists or albums you have collected (收藏)."""
    lib = _library()
    if kind.startswith("playlist"):
        emit(lib.faved_playlists())
    elif kind.startswith("album"):
        emit(lib.faved_albums())
    else:
        raise UsageError("kind must be `playlists` or `albums`")


@app.command()
def following(
    kind: str = typer.Argument("singers", help="`singers` or `users`."),
    fields: str | None = typer.Option(None, help="Comma-separated fields to keep, e.g. name,fans."),
) -> None:
    """List the singers (or users) you follow (关注)."""
    lib = _library()
    key = "singers" if kind.startswith("singer") else "users" if kind.startswith("user") else kind
    emit([project(x, _fields(fields)) for x in lib.following(key)])


@app.command()
def song(
    songs: list[str] = typer.Argument(None, help="Song ids, id:type pairs or mids."),
    stdin: bool = typer.Option(False, "--stdin", help="Also read song refs from stdin."),
    detail: bool = typer.Option(
        False, "--detail", help="Add genre/language/company as text (one extra call per song)."
    ),
    fields: str | None = typer.Option(None, help="Comma-separated fields to keep."),
) -> None:
    """Show song metadata (album, duration, release date, language, genre)."""
    refs = read_song_refs(songs or [], _stdin_text(stdin))
    if not refs:
        raise UsageError("give at least one song")
    lib = _library()
    result = lib.song_details(refs) if detail else lib.tracks(refs)
    emit([project(s, _fields(fields)) for s in result])


@app.command()
def search(
    query: str = typer.Argument(...),
    type_: str = typer.Option("song", "--type", help=f"One of: {', '.join(SEARCH_TYPES)}."),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(20, min=1, max=50),
    fields: str | None = typer.Option(None, help="Comma-separated fields to keep."),
) -> None:
    """Search the QQ Music catalogue."""
    result = _library(required=False).search(query, kind=type_, page=page, limit=limit)
    result["results"] = [project(r, _fields(fields)) for r in result["results"]]
    emit(result)


@app.command()
def lyrics(song_ref: str = typer.Argument(..., metavar="SONG")) -> None:
    """Print a song's lyrics (LRC) and translation if any."""
    emit(_library(required=False).lyrics(parse_song_ref(song_ref)))


@app.command()
def export(out: Path | None = typer.Option(None, help="Directory to write into (default: the data dir).")) -> None:
    """Snapshot your whole library (all playlists with songs, collected playlists and albums) to a JSON file."""
    data = _library().export()
    directory = (out or exports_dir()).expanduser()
    os.makedirs(directory, exist_ok=True)
    path = directory / f"library-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    incomplete = [p["name"] for p in data["playlists"] if not p["complete"]]
    emit(
        {
            "path": str(path),
            "playlists": len(data["playlists"]),
            "songs": sum(len(p["songs"]) for p in data["playlists"]),
            "faved_playlists": len(data["faved_playlists"]),
            "faved_albums": len(data["faved_albums"]),
            "incomplete_playlists": incomplete,
        }
    )


# -- writes ---------------------------------------------------------------------------------------

_dry = typer.Option(False, "--dry-run", help="Show what would change without writing.")
_verify = typer.Option(True, "--verify/--no-verify", help="Read the playlist back after writing.")


def _finish(run: RunLog, result: Any) -> None:
    if isinstance(result, dict) and run.has_ops:
        result["run_id"] = run.run_id
    emit(result)


@app.command()
def create(
    name: str = typer.Argument(...),
    allow_duplicate: bool = typer.Option(False, "--allow-duplicate", help="Create even if the name is taken."),
    dry_run: bool = _dry,
) -> None:
    """Create a playlist. Returns the existing one if the name is already taken."""
    run = RunLog(f"create {name}", dry_run=dry_run)
    _finish(run, _library().create_playlist(name, run=run, allow_duplicate=allow_duplicate))


@app.command()
def edit(
    playlist: str = typer.Argument(..., help="Your playlist: name, dir_id or tid."),
    name: str | None = typer.Option(None, "--name", help="New name (1-20 characters)."),
    desc: str | None = typer.Option(None, "--desc", help="New description (up to 2000 characters)."),
    dry_run: bool = _dry,
) -> None:
    """Rename a playlist or change its description. Cover, tags and visibility stay as they are."""
    if name is None and desc is None:
        raise UsageError("give --name, --desc, or both")
    lib = _library()
    pl = lib.resolve_playlist(playlist)
    run = RunLog(f"edit {pl['name']}", dry_run=dry_run)
    _finish(run, lib.edit_playlist(pl, run=run, name=name, desc=desc))


@app.command()
def delete(
    playlist: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Required: confirm the deletion."),
    dry_run: bool = _dry,
) -> None:
    """Delete one of your playlists. Its songs are saved in the run log so `qqmusic undo` can recreate it."""
    if not yes and not dry_run:
        raise UsageError("deleting a playlist needs --yes (or try --dry-run)")
    lib = _library()
    run = RunLog(f"delete {playlist}", dry_run=dry_run)
    _finish(run, lib.delete_playlist(lib.resolve_playlist(playlist), run=run))


@app.command()
def add(
    playlist: str = typer.Argument(..., help="Target playlist: name, dir_id, tid or `liked`."),
    songs: list[str] = typer.Argument(None, help="Song ids, id:type pairs or mids."),
    stdin: bool = typer.Option(
        False, "--stdin", help="Also read song refs (lines, JSON array, or `qqmusic show` output) from stdin."
    ),
    dry_run: bool = _dry,
    verify: bool = _verify,
) -> None:
    """Add songs to a playlist. Songs already in it are skipped."""
    refs = read_song_refs(songs or [], _stdin_text(stdin))
    if not refs:
        raise UsageError("give at least one song")
    lib = _library()
    pl = lib.resolve_playlist(playlist)
    run = RunLog(f"add {pl['name']} ({len(refs)} songs)", dry_run=dry_run)
    _finish(run, lib.add_songs(pl, refs, run=run, verify=verify))


@app.command()
def remove(
    playlist: str = typer.Argument(..., help="Playlist: name, dir_id, tid or `liked`."),
    songs: list[str] = typer.Argument(None, help="Song ids, id:type pairs or mids."),
    stdin: bool = typer.Option(False, "--stdin", help="Also read song refs from stdin."),
    dry_run: bool = _dry,
    verify: bool = _verify,
) -> None:
    """Remove songs from a playlist. Songs not in it are reported, not an error."""
    refs = read_song_refs(songs or [], _stdin_text(stdin))
    if not refs:
        raise UsageError("give at least one song")
    lib = _library()
    pl = lib.resolve_playlist(playlist)
    run = RunLog(f"remove {pl['name']} ({len(refs)} songs)", dry_run=dry_run)
    _finish(run, lib.remove_songs(pl, refs, run=run, verify=verify))


@app.command()
def like(
    songs: list[str] = typer.Argument(None),
    stdin: bool = typer.Option(False, "--stdin"),
    dry_run: bool = _dry,
) -> None:
    """Add songs to 我喜欢."""
    add(playlist="liked", songs=songs, stdin=stdin, dry_run=dry_run, verify=True)


@app.command()
def unlike(
    songs: list[str] = typer.Argument(None),
    stdin: bool = typer.Option(False, "--stdin"),
    dry_run: bool = _dry,
) -> None:
    """Remove songs from 我喜欢."""
    remove(playlist="liked", songs=songs, stdin=stdin, dry_run=dry_run, verify=True)


@app.command()
def runs(limit: int = typer.Option(20, min=1)) -> None:
    """List recent write runs (newest first)."""
    emit(list_runs(limit))


@app.command()
def undo(
    run_id: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Also delete created playlists that are no longer empty."),
    dry_run: bool = _dry,
) -> None:
    """Reverse a previous write run. The undo is itself a run, so it can be undone."""
    data = load_run(run_id)
    if data.get("undone_by") and not force:
        raise UsageError(f"run {run_id} was already undone by {data['undone_by']}; use --force to undo again")
    lib = _library()
    run = RunLog(f"undo {run_id}", dry_run=dry_run)
    results = lib.undo(data, run=run, force=force)
    if run.has_ops:
        mark_undone(run_id, run.run_id)
    _finish(run, {"undone": run_id, "dry_run": dry_run, "results": results})


@app.command("raw")
def raw_call(
    module: str = typer.Argument(...),
    method: str = typer.Argument(...),
    param: str = typer.Option("{}", help="JSON object."),
    write: bool = typer.Option(False, "--write", help="Mark as non-idempotent: no automatic retries."),
) -> None:
    """Call any musicu.fcg module/method with your session (escape hatch for exploration)."""
    try:
        parsed = json.loads(param)
    except json.JSONDecodeError as exc:
        raise UsageError(f"--param is not JSON: {exc}") from exc
    emit(_library(required=False).client.rpc(module, method, parsed, idempotent=not write))


@app.command()
def report(period: str = typer.Option("m", help="d (day), w (week) or m (month).")) -> None:
    """Listening report from Tencent's official skill API (needs QQMUSIC_API_KEY)."""
    if period not in ("d", "w", "m"):
        raise UsageError("--period must be d, w or m")
    emit(official.call("/me/report", {"timeKey": period}))


def main() -> None:
    try:
        app()
    except QQMusicError as exc:
        sys.stderr.write(json.dumps({"error": exc.to_dict()}, ensure_ascii=False) + "\n")
        sys.exit(exc.exit_code)
