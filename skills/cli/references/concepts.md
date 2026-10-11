# QQ Music concepts for library work

Read this before you plan changes. It explains how QQ Music models a library and what the CLI can and cannot do.
Facts marked _observed_ were seen on a real account in October 2026. Facts marked _unverified_ were not tested.

## Account and session

- A user logs in with WeChat (`login_type: wechat`) or QQ (`login_type: qq`). The account id is `uin`, and some read calls also use the encrypted id `euin`. The CLI handles both, so you never pass them yourself.
- The session key lasts 3 days (_observed_). `qqmusic` refreshes it automatically, and a refresh issues a new key valid for another 3 days.
- How long the refresh token itself lasts is _unverified_. When refresh stops working, the user has to scan a QR code again.
- Only the QR scan needs a human. Run `qqmusic login --wechat` in the background and let the window guide the user.

## Playlists

| Kind                            | Identified by                                          | Editable            | Notes                                                                                                           |
| ------------------------------- | ------------------------------------------------------ | ------------------- | --------------------------------------------------------------------------------------------------------------- |
| Own playlist (自建歌单)         | `dir_id` (small per-user number) and `tid` (global id) | yes                 | `qqmusic playlists` lists them. Commands accept the name, `dir_id` or `tid`                                     |
| 我喜欢 (liked songs)            | `dir_id` 201                                           | add and remove only | Each account has exactly one. It cannot be deleted or renamed. "Like a song" means adding it here               |
| Collected playlist (收藏的歌单) | `tid` only                                             | no                  | Other people's or official playlists. `qqmusic faved playlists` lists them, and `qqmusic show <tid>` reads them |
| Collected album (收藏的专辑)    | album `id` / `mid`                                     | no                  | `qqmusic faved albums`                                                                                          |

- `dir_id` only means something inside one account. `tid` is what share links use, such as `https://y.qq.com/n/ryqq_v2/playlist/<tid>`.
- Deleting and recreating a playlist (including `undo` of a delete) gives it a new `tid`. Old share links break.
- The server allows duplicate names, but `qqmusic create` is idempotent by exact name: it returns the existing playlist. Use `--allow-duplicate` only on request.
- Names must be 20 characters or fewer (_observed_ in the y.qq.com create dialog).
- The web page shows only the first page of a playlist. `qqmusic show` and `export` return every song, and `complete: false` means some songs could not be read.
- Official collected playlists such as "每日30首" or "红心雷达" change on their own. Treat them as snapshots.

## Songs

- A song is identified by a numeric `id` plus a `type`. Type 0 is a normal track, and other types are rare (long audio, video).
- Writes use `id` + `type`. Reads also accept the 14-character `mid`, which appears in share links: `https://y.qq.com/n/ryqq_v2/songDetail/<mid>`.
- The same song often exists as several versions with different ids: studio album, live (`(Live)`), compilation, remaster, explicit or clean, and accompaniment (`(伴奏)`).
  - Example: searching "晴天 周杰伦" returns the studio version on 《叶惠美》 and several concert versions.
  - Use `album.name`, `release_date` and the title suffix to tell them apart.
  - Prefer the original studio version unless the user asks for live or another version.
- Song fields in CLI output:

  | Field               | Meaning                                                                           |
  | ------------------- | --------------------------------------------------------------------------------- |
  | `id`, `type`, `mid` | Identity                                                                          |
  | `name`              | Display name                                                                      |
  | `title`             | Present only when it differs from `name`, for example with an `(Explicit)` suffix |
  | `artist`            | All singers joined with `/`                                                       |
  | `singers`           | List of `{id, mid, name}`                                                         |
  | `album`             | `{id, mid, name}`                                                                 |
  | `duration`          | Seconds                                                                           |
  | `release_date`      | `YYYY-MM-DD`                                                                      |
  | `language`, `genre` | Numeric codes                                                                     |
  | `vip`               | `true` means playing it needs a VIP membership                                    |

### Language and genre codes

Text names come from `qqmusic song <refs> --detail` (`language_name`, `genre_name`). These codes were _observed_ by looking up sample songs:

| `language` | Name                        |     | `genre` | Name              |
| ---------- | --------------------------- | --- | ------- | ----------------- |
| 0          | 国语 (Mandarin), or unknown |     | 1       | Pop               |
| 1          | 粤语 (Cantonese)            |     | 3       | Jazz              |
| 3          | 日语 (Japanese)             |     | 12      | Other             |
| 4          | 韩语 (Korean)               |     | 20      | Dance             |
| 5          | 英语 (English)              |     | 21      | Easy Listening    |
| 9          | 纯音乐 (instrumental)       |     | 22      | Electronica       |
| 20         | 瑞典语 (Swedish)            |     | 23      | Folk              |
| 24         | 越南语 (Vietnamese)         |     | 31      | New Age           |
|            |                             |     | 33      | R&B               |
|            |                             |     | 34      | Rap/Hip Hop       |
|            |                             |     | 36      | Rock              |
|            |                             |     | 37      | Soundtrack        |
|            |                             |     | 50      | Alternative       |
|            |                             |     | 58      | Singer Songwriter |

- `genre` 0 means unknown. Many songs, especially Chinese ones, have no genre at all.
- For codes not listed here, look up one sample song with `--detail`.
- `--detail` costs one request per song. Use it on a sample or in chunks of about 50 songs, not on the whole library at once.

## Limits and safety

- Writes go out in batches of 20 songs, with a pause of about one second between batches. The CLI does this for you.
- Exit code 4 means QQ Music's risk control (code 2001) triggered. Stop writing, tell the user, and wait several minutes. The exact thresholds are _unverified_.
- Every write is recorded as a run under the CLI data dir (`~/.local/share/qq-music-cli/runs/`). `qqmusic undo <run_id>` reverses it:
  - an add becomes a remove
  - a remove becomes an add
  - a create becomes a delete (only if the playlist is empty, unless `--force`)
  - a delete recreates the playlist and re-adds its songs
- Songs restored by undo may come back in a different order (_unverified_).
- `add` skips songs that are already present, and `remove` reports songs that were not there. Running the same command twice is safe.

## What the CLI cannot do (yet)

- Reorder songs, rename a playlist, change its description, cover or privacy.
- Collect or uncollect other people's playlists or albums.
- Play or download music, or read play history. The official listening report is the closest substitute: `qqmusic report`, which needs `QQMUSIC_API_KEY`.
- Comments and social features.

If the user asks for one of these, say so plainly and offer what is possible. For example, a rename can be done as create new, copy songs, delete old, which gives the playlist a new `tid`.
