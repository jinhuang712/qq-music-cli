# Library workflows

Each recipe follows the same loop. Steps that change the account are marked **(write)**.

1. Read the state with `qqmusic export` or `qqmusic show`.
2. Analyse it locally.
3. Show the user a plan with counts and examples.
4. Get the user's confirmation.
5. Run the change with `--dry-run`.
6. **(write)** Apply the change.
7. Check the result fields and report the `run_id`s.

The `jq` queries below were tested against a real export.
`$F` is the export file path from `qqmusic export`, for example `F=$(qqmusic export | jq -r .path)`.

## 1. Library health check (read-only)

Run this first when the user asks what is going on in their library or wants to clean up.

```sh
F=$(qqmusic export | jq -r .path)

# songs that sit in more than one own playlist (ignoring 我喜欢)
jq '[.playlists[] | select(.dir_id != 201) | .name as $p | .songs[] | {id, name, artist, p: $p}]
    | group_by(.id) | map(select(length > 1))' "$F"

# liked songs that are in no other playlist ("未整理")
jq '([.playlists[] | select(.dir_id != 201) | .songs[].id] | unique) as $placed
    | [.playlists[] | select(.dir_id == 201) | .songs[] | select(.id as $i | $placed | index($i) | not)]' "$F"

# the same song in several versions (same name and artist, different id)
jq '[.playlists[].songs[]] | unique_by(.id) | group_by([(.name | ascii_downcase), .artist])
    | map(select(length > 1))' "$F"

# empty and tiny playlists
jq '[.playlists[] | {name, n: (.songs | length)}] | sort_by(.n) | .[:5]' "$F"

# overlap between two playlists
jq '[.playlists[] | select(.name == "RNB") | .songs[].id] as $a
    | [.playlists[] | select(.name == "Chill") | .songs[].id] as $b
    | {both: ([$a[] | select(. as $x | $b | index($x))] | length)}' "$F"
```

Report what you found as a short table: counts plus a few examples per finding. Do not change anything until the user picks what to fix.

## 2. Organise 我喜欢 into themed playlists

Typical asks: "按语言/流派/心情/年代整理我喜欢的歌". The result is a set of playlists that the liked songs are *copied* into. Never remove songs from 我喜欢.

1. Export the library, then choose the grouping.
   - **Language:** use the `language` code (see concepts.md). It is cheap and exact.
   - **Genre:** use the `genre` code. Many songs have code 0 (unknown), so fill the gaps with `qqmusic song --stdin --detail` on those songs in chunks of about 50, or classify them by artist.
   - **Era:** use `release_date`, for example `select((.release_date // "") >= "2020")`.
   - **Mood, scene or activity** (通勤, 运动, 深夜, 下雨天): use your own judgement from name, artist, album and genre. For the few songs that stay ambiguous, read `qqmusic lyrics`.
2. Decide the category list with the user, and agree on these points:
   - At most 15 categories.
   - Names of 20 characters or fewer.
   - Reuse existing playlists whose names match exactly.
   - Put low-confidence songs in a "待整理" playlist instead of guessing.
   - Decide whether one song may go into several playlists. Allow at most 3.
3. Show the plan: one line per target playlist with the song count and 3 example songs, plus the size of "待整理".
4. **(write)** For each category, run `qqmusic create "<name>"`. It returns the existing playlist when the name is already taken.
5. **(write)** Pipe the song ids in. Run each command with `--dry-run` first.

   ```sh
   jq -c '[.playlists[] | select(.dir_id == 201) | .songs[] | select(.language == 1) | {id, type}]' "$F" \
     | qqmusic add "粤语" --stdin
   ```

6. Sum up `added` and `already_present` per playlist, report any `missing_after_write`, and list the `run_id`s.

Language buckets for a quick overview:

```sh
jq '{"0":"国语","1":"粤语","3":"日语","4":"韩语","5":"英语","9":"纯音乐"} as $L
    | [.playlists[] | select(.dir_id == 201) | .songs[] | ($L[(.language|tostring)] // "其他")]
    | group_by(.) | map({lang: .[0], n: length})' "$F"
```

## 3. Build a playlist from a description

Typical asks: "做一个下雨天听的华语 R&B 歌单，30 首左右".

1. Turn the description into 3–6 search queries: artist names, song titles you know fit, and genre words. Run `qqmusic search "<q>" --limit 20 --fields id,type,name,artist,album,release_date`.
2. Optionally mine the user's own taste: songs in 我喜欢 or in related playlists that match. A playlist that mixes known favourites with new songs usually works better than search results alone.
3. Clean up the candidates:
   - Drop duplicate versions. Keep the studio version unless the user wants live.
   - Drop accompaniment and karaoke versions.
   - Respect the requested size.
4. Show the list (name, artist, album) and let the user strike songs.
5. **(write)** Create the playlist, then add the songs:

   ```sh
   qqmusic create "<name>"
   printf '%s\n' <id> <id> ... | qqmusic add "<name>" --stdin
   ```

## 4. Merge, split or copy playlists

- **Merge:** the sources stay untouched and `add` removes duplicates.

  ```sh
  qqmusic create "驾驶精选"
  qqmusic show "通勤" --fields id,type | qqmusic add "驾驶精选" --stdin
  qqmusic show "开车" --fields id,type | qqmusic add "驾驶精选" --stdin
  ```

- **Split:** read the source, assign each song to a group as in recipe 2, create the target playlists, then add each group. The source playlist stays unchanged unless the user asks to empty it.
- **Copy a collected or public playlist into your own:** get the tid from `qqmusic faved playlists` or from a share link `…/playlist/<tid>`.

  ```sh
  qqmusic create "<name>"
  qqmusic show <tid> --fields id,type | qqmusic add "<name>" --stdin
  ```

- **Rename:** the CLI cannot rename. Create the new name, copy the songs, check the counts, then `qqmusic delete "<old>" --yes`, but only if the user agrees. The new playlist gets a new tid.

## 5. Remove duplicates

- **Same song id in several playlists:** this is often intentional, for example a song in both "RAP" and "通勤". List the cases and ask before removing anything.
- **Several versions inside one playlist:**

  ```sh
  jq '[.playlists[] | select(.name == "RNB") | .songs[]]
      | group_by([(.name | ascii_downcase | sub(" *\\(.*\\)$"; "")), .artist])
      | map(select(length > 1) | map({id, name, album: .album.name, release_date}))' "$F"
  ```

  Propose which version to keep: studio over live, the original album over a compilation. **(write)** Then run `qqmusic remove "<playlist>" <ids...>`.

## 6. Keep a rule-based playlist in sync

Typical asks: "把我喜欢里 Post Malone 的歌都放进 RAP", or "每周把新喜欢的英文歌同步到 英文精选".

```sh
jq -c '([.playlists[] | select(.name == "RAP") | .songs[].id]) as $have
       | [.playlists[] | select(.dir_id == 201) | .songs[]
          | select(.artist | test("Post Malone")) | select(.id as $i | $have | index($i) | not) | {id, type}]' "$F" \
  | qqmusic add "RAP" --stdin --dry-run
```

- Only add the missing songs.
- Removing songs that no longer match the rule needs explicit permission. The user may have added them by hand.

## 7. Organise only the newly liked songs

Keep the previous export, export again, and classify only the difference:

```sh
jq -n --slurpfile old "$OLD" --slurpfile new "$NEW" '
  ($old[0].playlists[] | select(.dir_id == 201) | [.songs[].id]) as $o
  | [$new[0].playlists[] | select(.dir_id == 201) | .songs[] | select(.id as $i | $o | index($i) | not)
     | {id, type, name, artist}]'
```

Then continue with recipe 2 on those songs. Songs that disappeared from 我喜欢 should only be reported, never acted on.

## 8. Backup and history

- `qqmusic export --out <dir>` writes `library-<timestamp>.json`. It is a complete snapshot of every own playlist with all songs, plus collected playlists and albums. Suggest one before any large reorganisation.
- `qqmusic runs` lists recent writes. `qqmusic undo <run_id>` reverses one, and the undo is itself a run that can be undone.

## 9. Clean up

- Find empty or tiny playlists and playlists that have not been updated in a long time. In `qqmusic playlists`, `updated_at` is in unix seconds.
- Present the candidates, and delete only the ones the user names: `qqmusic delete "<name>" --yes`. Mention that `undo` can recreate a deleted playlist with its songs, but under a new tid.

## 10. Listening report (optional)

`qqmusic report --period d|w|m` returns Tencent's listening report through the official skill API. It includes top songs and artists, genre mix, favourite hour, streaks and cities. It needs `QQMUSIC_API_KEY`, which the user creates at https://y.qq.com/n/ryqq_v2/qqmusic_skills. Use the report to ground recommendations in what the user actually plays.
