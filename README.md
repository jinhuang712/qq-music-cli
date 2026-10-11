# qq-music-cli

**English** | [简体中文](README.zh-CN.md)

Let your coding agent manage your QQ Music library. `qqmusic` is a command-line tool for your own QQ Music (QQ音乐) account. It also ships as a plugin for **Claude Code, Codex, Pi and OpenCode**.

With it, an agent can:
- read your playlists and liked songs
- organise them by language, genre or mood
- build new playlists, merge or split existing ones, and deduplicate them
- undo any change

Website: <https://jinhuang712.github.io/qq-music-cli/>

> [!IMPORTANT]
> **Unofficial project.**
> - It is not affiliated with, endorsed by, or connected to Tencent or QQ Music.
> - It talks to the undocumented web API that y.qq.com uses, which can change or break at any time.
> - Use it only with your own account, at your own risk, and within QQ Music's terms of service.
>
> It only manages playlist metadata. It does not play, download or decrypt any audio.

## What it does

| | |
|---|---|
| **Read your library** | Your playlists, 我喜欢 (liked songs) with no page limit, collected playlists and albums, and song metadata: album, duration, release date, language, genre |
| **Change it safely** | Create and delete playlists, add, remove and like songs in batches. Songs already present are skipped, every write is read back, `--dry-run` previews a change, and `qqmusic undo <run_id>` reverses one |
| **Work at library scale** | `qqmusic export` writes your whole library to one JSON file for health checks, deduplication and grouping |
| **Search** | The QQ Music catalogue (songs, albums, playlists, singers) and lyrics |
| **Agent-first** | Every command prints exactly one JSON document, with stable exit codes. The bundled skill teaches agents the commands, the QQ Music data model and ten tested workflows |

## Quick start (with an agent)

1. **Install the plugin** in your agent. The table shows each channel.

   | Agent | Install | The skill shows as |
   |---|---|---|
   | Claude Code | `claude plugin marketplace add jinhuang712/qq-music-cli && claude plugin install qq-music@qq-music` | `qq-music:cli` |
   | Codex | `codex plugin marketplace add jinhuang712/qq-music-cli && codex plugin add qq-music@qq-music` | `qq-music:cli` |
   | Pi | `pi install git:github.com/jinhuang712/qq-music-cli` | `qq-music-cli` |
   | OpenCode | `git clone https://github.com/jinhuang712/qq-music-cli ~/.local/share/qq-music-cli-src && ln -s ~/.local/share/qq-music-cli-src/flat-skills/qq-music-cli ~/.config/opencode/skills/qq-music-cli` | `qq-music-cli` |

2. **Ask your agent** something like "organise my liked songs into playlists by language".
   - If needed, the agent installs the CLI itself.
   - The agent then starts the login. A small window opens with a QR code, and you scan it with WeChat or QQ. This scan is the only manual step.
   - Login keys last 3 days and refresh automatically.

## Using the CLI directly

Install the CLI with [uv](https://docs.astral.sh/uv/). Python 3.11+ and macOS are required: macOS supplies the Keychain storage and the login window.

```sh
uv tool install git+https://github.com/jinhuang712/qq-music-cli
qqmusic login --wechat     # or `qqmusic login` to scan with QQ
qqmusic status
```

| Command | What it does |
|---|---|
| `qqmusic playlists` | Your playlists (我喜欢 is `dir_id` 201) |
| `qqmusic show <playlist> [--fields id,name,artist] [--limit N]` | Songs in a playlist, given by name, `dir_id`, `tid` or `liked` |
| `qqmusic liked` | Your liked songs |
| `qqmusic faved playlists\|albums` | Collected playlists or albums |
| `qqmusic song <songs...> [--detail]` | Song metadata. `--detail` adds genre, language and label as text |
| `qqmusic search <query> [--type song\|album\|playlist\|singer\|mv\|lyric\|user]` | Search the catalogue |
| `qqmusic lyrics <song>` | Lyrics (LRC) and translation |
| `qqmusic export` | Your whole library as one JSON file |
| `qqmusic create <name>` | Create a playlist. Returns the existing one if the name is taken |
| `qqmusic add <playlist> <songs...> [--stdin]` | Add songs, skipping ones already present. Writes in batches of 20 and reads back |
| `qqmusic remove <playlist> <songs...> [--stdin]` | Remove songs |
| `qqmusic like` / `qqmusic unlike <songs...>` | Add songs to, or remove them from, 我喜欢 |
| `qqmusic delete <playlist> --yes` | Delete a playlist. Its songs are kept in the run log for undo |
| `qqmusic runs` / `qqmusic undo <run_id>` | Write history and undo |
| `qqmusic raw <module> <method> --param '{}'` | Call any `musicu.fcg` method (for exploration) |
| `qqmusic report --period d\|w\|m` | Listening report from Tencent's official skill API. Needs `QQMUSIC_API_KEY` |

**Song references** can take these forms:
- an id, such as `97773`
- `id:type`, such as `97773:0`
- a 14-character mid, such as `0039MnYb0qxYhV`
- a JSON object with `id`/`type` or `mid`

With `--stdin`, songs can be piped in from other commands: `qqmusic show RNB --fields id,type | qqmusic add "RNB picks" --stdin`.

**Exit codes:** 0 ok, 1 API error, 2 usage error, 3 log in again, 4 risk control (slow down), 5 network error.

## The agent plugin

The plugin is a single Agent Skill, with nothing else in it. Claude Code and Codex namespace plugin skills and Pi and OpenCode do not, so the skill is packaged per channel:

| Channels | Directory | Name |
|---|---|---|
| Claude Code, Codex | `skills/cli/` (the source) | `qq-music:cli` |
| Pi, OpenCode | `flat-skills/qq-music-cli/` (generated by `scripts/sync_flat_skill.py`) | `qq-music-cli` |

The skill has three files:
- `SKILL.md` covers setup, the commands and the safety rules.
- `references/concepts.md` describes the QQ Music data model: `dir_id` vs `tid`, 我喜欢, song versions, language and genre codes, and limits.
- `references/workflows.md` has recipes for library health checks, organising 我喜欢, building a playlist from a description, merge, split, copy, dedupe, rule-based sync, backup and cleanup. Every `jq` query in it is tested.

Manifests: `.claude-plugin/` (Claude Code; Codex also reads its marketplace), `plugin.json` (the [agent-plugins.org](https://agent-plugins.org) format, read by Codex) and `package.json` (`pi.skills`).

## How it works

- **Data:** plain JSON POSTs to `https://u.y.qq.com/cgi-bin/musicu.fcg`, with the same `comm` block y.qq.com sends (`ct=24`, `cv=4747474`), the session cookies, and `g_tk` (hash33 of the session key). The y.qq.com page itself now sends encrypted, signed requests to a different endpoint, but this plain endpoint still served reads and writes when last checked (2026-10-11).
- **Login:** the QR flows of QQ's ptlogin service and of WeChat Open Platform, followed by QQ Music's code exchange. No browser automation is involved. The window you see is a local page served on `127.0.0.1` that only displays the QR code and the login status.
- **Credentials** stay in the macOS Keychain (service `qq-music-cli`). Run logs and exports live in `~/.local/share/qq-music-cli/`.

These calls were verified against a live account:

| Capability | module / method |
|---|---|
| List playlists | `music.musicasset.PlaylistBaseRead` / `GetPlaylistByUin` |
| Read a playlist | `music.srfDissInfo.aiDissInfo` / `uniform_get_Dissinfo` |
| Create / delete a playlist | `music.musicasset.PlaylistBaseWrite` / `AddPlaylist`, `DelPlaylist` |
| Add / remove songs | `music.musicasset.PlaylistDetailWrite` / `AddSonglist`, `DelSonglist` |
| Song metadata | `music.trackInfo.UniformRuleCtrl` / `CgiGetTrackInfo`, `music.pf_song_detail_svr` / `get_song_detail_yqq` |
| Search | `music.search.SearchCgiService` / `DoSearchForQQMusicDesktop` |

## Development

```sh
uv sync
uv run pytest -q                           # offline tests; httpx.MockTransport fakes every server
uv run python scripts/sync_flat_skill.py   # after editing skills/cli/
```

## Acknowledgements

The protocol knowledge here came from capturing y.qq.com's own traffic, and from reading public projects: [L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi) (GPL-3.0), [baoozak/qqmusic-mcp](https://github.com/baoozak/qqmusic-mcp) (MIT), and Tencent's [qqmusic-skills](https://github.com/tencentmusic/qqmusic-skills) docs. No code from those projects is included.

## License

[MIT](LICENSE)
