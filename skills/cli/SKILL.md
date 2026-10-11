---
name: cli
description: Manage the user's own QQ Music (QQ音乐) library with the `qqmusic` CLI. Use it to list playlists (歌单) and liked songs (我喜欢), read songs with metadata, search the catalogue, create and delete playlists, add, remove and like songs in bulk, export the library, and undo changes. Also use it for library work such as organising 我喜欢 into playlists by language, genre or mood, building a playlist from a description, merging, splitting or deduplicating playlists, and running a library health check.
compatibility: Needs the `qqmusic` command (qq-music-cli, Python 3.11+, installed with uv) on PATH, macOS for Keychain storage and the login window, and network access to y.qq.com.
---

# QQ Music library (`qqmusic`)

`qqmusic` reads and changes the user's own QQ Music account through the y.qq.com web API.
Every command prints exactly one JSON document on stdout. Progress events and errors go to stderr as JSON lines.
Put `--compact` before the subcommand to save tokens: `qqmusic --compact show RNB`.

Read these when the task needs them:
- [references/concepts.md](references/concepts.md): ids (`dir_id`, `tid`, song `id`/`type`/`mid`), 我喜欢, collected playlists, song versions, language and genre codes, limits, and what the CLI cannot do.
- [references/workflows.md](references/workflows.md): step-by-step recipes for organising, building, merging, splitting, deduplicating, syncing, backing up and cleaning up, with tested `jq` queries.

## 1. Make sure the CLI works

```sh
command -v qqmusic && qqmusic --compact status
```

- **Missing command:** the CLI source ships with this skill. The repository root is the nearest parent directory of this file that contains `pyproject.toml`. Install it with `uv tool install --editable <repo-root>`. If no `pyproject.toml` is found, install from GitHub: `uv tool install git+https://github.com/jinhuang712/qq-music-cli`. Do not ask the user to do it.
- **Not logged in:** if `logged_in` is false, or `valid` is false (exit code 3), start the login yourself as a background command: `qqmusic login --wechat`, or `qqmusic login` for a QQ scan. It opens a small window on the user's screen with the QR code and live status. Tell the user to scan it with their phone. Scanning is the only step that needs the user. The command exits with `{"logged_in": true, ...}` once they confirm.
- **No display:** use `--no-ui` only when there is no display. The QR image path then arrives on stderr as `{"event": "qr_ready", "path": ...}`.
- **Key expiry:** login keys last 3 days. `qqmusic` refreshes them automatically when less than 12 hours are left. `qqmusic refresh` forces a refresh.

## 2. Commands

| Task | Command |
|---|---|
| My playlists (我喜欢 is `dir_id` 201) | `qqmusic playlists` |
| Songs in a playlist (name, dir_id, tid or `liked`; any public tid works) | `qqmusic show "RNB" --fields id,type,name,artist,album,duration,release_date` |
| Liked songs | `qqmusic liked --fields id,type,name,artist` |
| Collected playlists / albums | `qqmusic faved playlists`, `qqmusic faved albums` |
| Song metadata | `qqmusic song 97773 0039MnYb0qxYhV` |
| Genre / language / label as text | `qqmusic song <refs> --detail` (one extra call per song) |
| Search | `qqmusic search "晴天 周杰伦" --type song --limit 10` (types: song, singer, album, playlist, mv, lyric, user) |
| Lyrics | `qqmusic lyrics 0039MnYb0qxYhV` |
| Whole library to one file | `qqmusic export` prints `{"path": ...}` |
| Create (returns the existing one if the name is taken) | `qqmusic create "通勤"` |
| Add (skips songs already present, batches of 20, reads back) | `qqmusic add "通勤" 97773 0039MnYb0qxYhV` |
| Remove | `qqmusic remove "通勤" 97773` |
| Like / unlike | `qqmusic like 97773`, `qqmusic unlike 97773` |
| Delete a playlist (song list is kept for undo) | `qqmusic delete "通勤" --yes` |
| Preview any write | add `--dry-run` |
| Write history / undo | `qqmusic runs`, `qqmusic undo <run_id>` |
| Listening report (needs `QQMUSIC_API_KEY`) | `qqmusic report --period m` |

**Song references** can take these forms:
- an id, such as `97773`
- `id:type`, such as `97773:0`
- a 14-character mid, such as `0039MnYb0qxYhV`
- a JSON object with `id`/`type` or `mid`

**Piping:** with `--stdin`, refs are read from lines, a JSON array, or a whole `qqmusic show` document. Output therefore pipes straight back in:

```sh
qqmusic show RNB --fields id,type | qqmusic add "RNB精选" --stdin --dry-run
```

In zsh, pass several ids through `--stdin`. An unquoted `$IDS` variable is not split into words.

**Exit codes:**

| Code | Meaning | What to do |
|---|---|---|
| 0 | OK | |
| 1 | API error | |
| 2 | Usage error | Read the message. It often lists valid names |
| 3 | Auth | Run the login flow above |
| 4 | Risk control | Stop writing and tell the user. Wait several minutes before trying again |
| 5 | Network | |

## 3. Rules

1. Library-wide analysis is local work. For duplicates, grouping, or finding songs that are in no playlist, run `qqmusic export` once and query the file with `jq`. Do not call `show` once per playlist.
2. Plan before you write. If a change touches more than 20 songs or more than one playlist, show the user a plan first: counts per target playlist plus a few example songs. Then run it with `--dry-run`, and write only after the user confirms.
3. Never `unlike`, never `remove` from 我喜欢, and never `delete` a playlist, unless the user asked for that exact change. Organising 我喜欢 means copying songs into other playlists.
4. After every write, check the result fields, not just the exit code:
   - add: `added`, `already_present`, `missing_after_write`
   - remove: `removed`, `not_present`, `still_present`
5. Give the user every `run_id`, so they can run `qqmusic undo <run_id>`.
6. Keep writes modest. The CLI already batches and pauses. If you see exit code 4, stop and report it.
7. Playlist names must be 20 characters or fewer, the limit the y.qq.com create dialog shows. Before creating a playlist, reuse an existing one whose name matches exactly.
