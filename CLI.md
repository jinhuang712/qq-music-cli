# CLI

命令行的查阅表：每条命令的写法、参数、取值、默认值、输出字段，以及退出码。内容以 `src/qq_music_cli/` 的代码和各命令的 `--help` 为准（0.5.5）。怎么用、注意什么，见 [USAGE.md](USAGE.md) 和 `skills/cli/`；接口原理见 [HOW-IT-WORKS.md](HOW-IT-WORKS.md)。

```
qqmusic [--compact] [--version] <命令> [参数] [选项]
```

| 命令        | 功能                             | 需要登录                 | 写操作 |
| ----------- | -------------------------------- | ------------------------ | ------ |
| `login`     | 扫码登录，或导入 Cookie          | 否                       |        |
| `logout`    | 删除保存的凭证                   | 否                       |        |
| `status`    | 查看凭证，并检查是否还有效       | 否                       |        |
| `refresh`   | 续期登录 key                     | 是                       |        |
| `playlists` | 自建歌单                         | 是                       |        |
| `show`      | 歌单详情和歌曲                   | 是                       |        |
| `liked`     | 「我喜欢」的歌曲                 | 是                       |        |
| `faved`     | 收藏的歌单或专辑                 | 是                       |        |
| `following` | 关注的歌手或用户                 | 是                       |        |
| `song`      | 歌曲信息                         | 是                       |        |
| `search`    | 搜索                             | 是                       |        |
| `album`     | 专辑信息和曲目                   | 否                       |        |
| `match`     | 曲库里的歌出现在哪些热门公开歌单 | 是                       |        |
| `comments`  | 热门或最新评论                   | 歌曲、专辑否；歌单是     |        |
| `lyrics`    | 歌词                             | 否                       |        |
| `export`    | 导出整个曲库                     | 是                       |        |
| `create`    | 新建歌单                         | 是                       | 是     |
| `edit`      | 改名、简介、公开或私密、封面     | 是                       | 是     |
| `delete`    | 删除歌单                         | 是                       | 是     |
| `add`       | 往歌单加歌                       | 是                       | 是     |
| `remove`    | 从歌单删歌                       | 是                       | 是     |
| `like`      | 加到「我喜欢」                   | 是                       | 是     |
| `unlike`    | 从「我喜欢」删除                 | 是                       | 是     |
| `fav`       | 收藏别人的歌单或专辑             | 是                       | 是     |
| `unfav`     | 取消收藏                         | 是                       | 是     |
| `runs`      | 写操作记录                       | 否                       |        |
| `undo`      | 撤销一次写操作                   | 是                       | 是     |
| `raw`       | 直接调用任意 `musicu.fcg` 接口   | 否（有凭证就带上）       |        |
| `report`    | 听歌报告（腾讯官方接口）         | 否，要 `QQMUSIC_API_KEY` |        |

「需要登录」指代码里是否要求有凭证：`album`、`comments`（歌曲和专辑）、`lyrics`、`raw` 没有凭证也能跑，有就带上；`comments playlist` 要先读自己的歌单列表，所以要登录。凭证缺失时退出码是 3；已过期同样是 3。

## 全局选项

写在子命令之前。

| 选项        | 含义                                         | 默认              |
| ----------- | -------------------------------------------- | ----------------- |
| `--compact` | stdout 的 JSON 压成一行                      | 关，缩进 2 个空格 |
| `--version` | 输出 `{"version": "0.5.5"}` 后退出，退出码 0 |                   |
| `--help`    | 显示用法                                     |                   |

不带命令运行，显示帮助。每条子命令也有 `--help`。

## 输入输出约定

- stdout 只输出一个 JSON 文档（`ensure_ascii=false`）。进度写到 stderr，每行一个 JSON：`{"event": "...", ...}`。
- 出错时 stdout 为空，stderr 一行 `{"error": {"kind": ..., "message": ..., "code"?, "module"?, "method"?}}`。`code`、`module`、`method` 没有就省略。
- 例外：Typer/Click 自己检查出的用法错误（缺参数、未知命令、`min`/`max` 越界、类型不对）不走这条路，stderr 是 Click 的文字提示，退出码同样是 2。
- 所有字段没有值时输出 `null`，不省略（`--fields` 里点名了但对象没有的字段也是 `null`）。
- 时间字段（`created_at`、`updated_at`、`faved_at`、评论的 `time`）原样取自接口，CLI 不转换；只有评论的 `time`（见 concepts.md）和 `exported_at`、`expires_at` 确定是 Unix 秒。专辑的 `release_date` 是日期字符串，收藏专辑的 `release_date` 是 `YYYY-MM-DD`。

### `--fields`

`playlists`、`show`、`liked`、`faved`、`following`、`song`、`search`、`album`、`match`、`comments` 都接受。

| 写法   | 含义                                         |
| ------ | -------------------------------------------- |
| 不给   | 该命令的默认字段                             |
| `a,b`  | 只输出这几个，按给定顺序                     |
| `+a,b` | 默认字段加上这几个                           |
| `all`  | 该命令的全部可选字段（包括要多发请求的字段） |

- 字段名写错：退出码 2，报错列出所有可选字段。
- 逗号两侧的空格会被去掉。
- `--fields` 只作用于列表里的对象。`show` 的 `playlist`、`album` 的 `album` 是单个对象，总是完整输出。
- 多发请求的字段，只在点名（或 `all`）时才去取：

| 字段                                                                            | 适用命令                       | 代价                           |
| ------------------------------------------------------------------------------- | ------------------------------ | ------------------------------ |
| `comment_count`                                                                 | 所有输出歌曲的命令             | 每 10 首歌 1 次请求            |
| `listen_count`、`desc`                                                          | `playlists`、`faved playlists` | 每 10 个歌单 1 次请求          |
| `tags`                                                                          | `faved playlists`              | 同上                           |
| `genre_name`、`language_name`、`company`、`publish_time`、`intro`、`trans_name` | `song`                         | 每首歌 1 次请求，同 `--detail` |

### 指定歌曲

接受歌曲的参数（`song`、`add`、`remove`、`like`、`unlike` 的 `<歌曲>`，`lyrics`、`comments song` 的单个歌曲）都认下面四种写法：

| 写法              | 例子                      | 解析结果                                         |
| ----------------- | ------------------------- | ------------------------------------------------ |
| 数字 id           | `97773`                   | `{id}`，type 按 0                                |
| `id:type`         | `97773:0`                 | `{id, type}`                                     |
| 14 位字母数字 mid | `0039MnYb0qxYhV`          | `{mid}`                                          |
| JSON 对象         | `'{"id":97773,"type":0}'` | 有 `id` 用 `id`（`type` 有就带上），否则用 `mid` |

都不是就退出码 2。`lyrics`、`comments` 一次只收一个；`song`、`add`、`remove`、`like`、`unlike` 收多个。

`--stdin`（`song`、`add`、`remove`、`like`、`unlike`）：在命令行参数之外，再从标准输入读歌曲。输入可以是逐行的歌曲写法（含 JSONL）、一个 JSON 数组、或一整段含 `songs` 数组的 JSON（即 `qqmusic show` 的输出）。命令行和 stdin 的歌曲合并。一首都没有：退出码 2，`give at least one song`。

### 指定歌单

`show`、`add`、`remove`、`edit`、`delete`、`comments playlist` 的 `<歌单>`：

| 写法                             | 含义                                                                                                                 |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `liked`、`like`、`我喜欢`、`201` | 「我喜欢」                                                                                                           |
| 数字                             | 先按自己歌单的 `dir_id` 或 `tid` 找；`show` 和 `comments` 找不到时当作任意公开歌单的 `tid`，其他命令找不到则退出码 2 |
| 名字                             | 精确匹配；没有再忽略大小写匹配；有多个同名则退出码 2，报错列出各自的 `dir_id`                                        |

`add`、`remove`、`edit`、`delete` 只能动自己的歌单，对别人的歌单（没有 `dir_id`）退出码 2。

## 退出码

| 退出码 | `kind`         | 含义                                                     |
| ------ | -------------- | -------------------------------------------------------- |
| 0      |                | 成功，包括「没有结果」「未登录」（`status`）这类正常答案 |
| 1      | `api`          | 接口返回错误，或响应读不懂                               |
| 2      | `usage`        | 用法有误：缺参数、值不对、找不到对象                     |
| 3      | `auth`         | 没登录，或登录失效；`QQMUSIC_API_KEY` 没设（`report`）   |
| 4      | `risk_control` | QQ 音乐判定请求太频繁（错误码 2001）                     |
| 5      | `network`      | 网络失败，或 HTTP 429、5xx                               |

读请求遇到网络错误、429、5xx 最多重试 3 次，遇到风控最多重试 2 次；写请求不重试。

## 环境变量

| 变量                          | 作用                                            | 默认                                                                |
| ----------------------------- | ----------------------------------------------- | ------------------------------------------------------------------- |
| `QQMUSIC_CLI_CREDENTIAL_FILE` | 凭证存到这个路径的文件（权限 0600），不用钥匙串 | 未设：macOS 钥匙串，服务名 `qq-music-cli`                           |
| `QQMUSIC_CLI_HOME`            | 数据目录                                        | `$XDG_DATA_HOME/qq-music-cli`，再退到 `~/.local/share/qq-music-cli` |
| `QQMUSIC_API_KEY`             | `report` 用的腾讯官方接口 key                   |                                                                     |

数据目录里：`runs/<run_id>.json` 是写操作记录，`exports/` 是导出文件，`login-qr.png` 或 `login-qr.jpg` 是登录二维码。

## 对象字段

下面几张表被多条命令引用。「默认」列打勾的字段不加 `--fields` 也会输出。

### 歌曲

`show`、`liked`、`song`、`album`、`search --type song|lyric`、`match`、`lyrics` 的 `song`。

| 字段            | 默认 | 含义                                        |
| --------------- | ---- | ------------------------------------------- |
| `id`            | 是   | 歌曲 id                                     |
| `mid`           | 是   | 歌曲 mid（14 位）                           |
| `type`          | 是   | 歌曲 type，没有时为 0                       |
| `name`          | 是   | 歌名                                        |
| `artist`        | 是   | 所有歌手，用 `/` 连接                       |
| `album`         | 是   | `{id, mid, name}`，没有专辑时 `null`        |
| `duration`      | 是   | 时长，秒                                    |
| `title`         |      | 只在和 `name` 不同时有值，否则 `null`       |
| `subtitle`      |      | 副标题                                      |
| `singers`       |      | `[{id, mid, name}]`                         |
| `release_date`  |      | 发行日期                                    |
| `language`      |      | 语种数字代码                                |
| `genre`         |      | 流派数字代码                                |
| `vip`           |      | 播放是否需要 VIP                            |
| `bpm`           |      | 每分钟节拍数，没有为 `null`                 |
| `mv`            |      | MV 的 vid，没有为 `null`                    |
| `qualities`     |      | 音质，取自 `320k`、`flac`、`hires`、`dolby` |
| `track_no`      |      | 专辑内序号                                  |
| `cover`         |      | 专辑封面 URL（300×300）                     |
| `url`           |      | y.qq.com 上的歌曲页                         |
| `comment_count` |      | 评论总数；取不到为 `null`                   |

仅 `song` 命令还有（要多发请求）：

| 字段            | 默认             | 含义     |
| --------------- | ---------------- | -------- |
| `genre_name`    | 加 `--detail` 时 | 流派名   |
| `language_name` | 加 `--detail` 时 | 语种名   |
| `company`       | 加 `--detail` 时 | 唱片公司 |
| `publish_time`  | 加 `--detail` 时 | 发行时间 |
| `intro`         |                  | 歌曲简介 |
| `trans_name`    |                  | 译名     |

`match` 的歌曲对象另有 `hits`（出现在几个公开歌单里）和 `in`（在你的哪些歌单里，歌单名数组）。

### 自建歌单

`playlists`；其他命令输出里的 `playlist` 引用只有 `dir_id`、`tid`、`name`。

| 字段           | 默认 | 含义                                   |
| -------------- | ---- | -------------------------------------- |
| `dir_id`       | 是   | 歌单 dir_id（「我喜欢」是 201）        |
| `tid`          | 是   | 歌单 tid                               |
| `name`         | 是   | 名字                                   |
| `song_count`   | 是   | 歌曲数                                 |
| `liked`        | 是   | 是否「我喜欢」                         |
| `public`       | 是   | 是否所有人可见                         |
| `tags`         | 是   | 标签名数组                             |
| `created_at`   | 是   | 创建时间                               |
| `updated_at`   | 是   | 更新时间                               |
| `cover`        |      | 封面 URL                               |
| `url`          |      | y.qq.com 上的歌单页                    |
| `listen_count` |      | 播放量（所有人的），多发请求           |
| `desc`         |      | 简介，多发请求；列表接口本身不返回简介 |

## 登录

### `qqmusic login`

```
qqmusic login [--wechat] [--cookie-file <文件>] [--ui | --no-ui] [--timeout <秒>]
```

| 选项            | 含义                                   | 取值                                                                        | 默认   |
| --------------- | -------------------------------------- | --------------------------------------------------------------------------- | ------ |
| `--wechat`      | 用微信扫码，不给就用 QQ 扫码           | 开关                                                                        | 关     |
| `--cookie-file` | 导入 Cookie，不扫码                    | Playwright storage-state JSON、Cookie 列表 JSON、`Cookie:` 头文本的文件路径 |        |
| `--ui/--no-ui`  | 弹出小浏览器窗口，显示二维码和实时状态 |                                                                             | `--ui` |
| `--timeout`     | 等待扫码的秒数                         | 浮点数                                                                      | 180    |

- 给了 `--cookie-file` 时不扫码，`--wechat`、`--ui`、`--timeout` 都不起作用。
- 存之前先用凭证请求一次账号信息，证明可用。失败则不保存。
- stderr 事件：`login_page`（`url`，仅 `--ui`）、`qr_ready`（`path` 二维码图片、`scan_with` 为 `QQ` 或 `WeChat`）、`scanned`、`waiting`、`expired`、`refused`。stderr 是终端时，还会在 stderr 画出 ASCII 二维码。
- 扫码超时、被拒绝、过期：退出码 3。

输出：

| 字段                                                                                                                | 含义                                     |
| ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `logged_in`                                                                                                         | 恒为 `true`                              |
| `nickname`                                                                                                          | 昵称                                     |
| `store`                                                                                                             | `keychain:qq-music-cli` 或 `file:<路径>` |
| `uin`、`euin`、`login_type`（`qq` / `wechat`）、`source`、`created_at`、`expires_at`、`seconds_left`、`can_refresh` | 同 `status`                              |

### `qqmusic logout`

无参数。输出 `{"logged_out": <是否真的删了>, "store": ...}`。没有凭证时 `logged_out` 为 `false`，退出码仍是 0。

### `qqmusic status`

| 选项        | 含义                 | 默认 |
| ----------- | -------------------- | ---- |
| `--offline` | 不联网检查，只读本地 | 关   |

| 字段           | 含义                                                             |
| -------------- | ---------------------------------------------------------------- |
| `logged_in`    | 有没有凭证。没有时只输出 `logged_in: false` 和 `store`，退出码 0 |
| `store`        | 同上                                                             |
| `uin`          | 账号                                                             |
| `euin`         | 加密账号，没有为 `null`                                          |
| `login_type`   | `qq`、`wechat`、`unknown`                                        |
| `source`       | 凭证来源                                                         |
| `created_at`   | 创建时间                                                         |
| `expires_at`   | key 过期时间（Unix 秒）                                          |
| `seconds_left` | 剩余秒数，可能为负；没有过期时间为 `null`                        |
| `can_refresh`  | 是否能续期                                                       |
| `valid`        | 联网检查结果；加 `--offline` 时没有这一项                        |
| `nickname`     | `valid` 为 `true` 时有                                           |
| `error`        | `valid` 为 `false` 时有                                          |

联网检查发现失效，仍输出 `valid: false`，退出码是 0。要靠 `valid` 判断，不能只看退出码。

### `qqmusic refresh`

无参数。没有凭证：退出码 3。成功输出 `{"refreshed": true, ...}` 加上 `status` 里的凭证字段（`uin` 到 `can_refresh`）。

所有需要登录的命令在剩余时间不足 12 小时且能续期时会自动续期，在 stderr 写 `{"event": "credential_refreshed", "expires_at": ...}`；续期失败写 `credential_refresh_failed`（带 `error`），继续用旧凭证。已过期则退出码 3。

## 读

### `qqmusic playlists`

| 选项       | 含义 | 默认                                                                 |
| ---------- | ---- | -------------------------------------------------------------------- |
| `--fields` | 见上 | `dir_id,tid,name,song_count,liked,public,tags,created_at,updated_at` |

可选字段见「自建歌单」。输出：歌单数组。

### `qqmusic show <歌单>`

| 参数 / 选项 | 含义         | 取值                 | 默认                                     |
| ----------- | ------------ | -------------------- | ---------------------------------------- |
| `<歌单>`    | 要看的歌单   | 见「指定歌单」，必填 |                                          |
| `--offset`  | 跳过前几首   | 整数                 | 0                                        |
| `--limit`   | 最多返回几首 | 整数                 | 全部                                     |
| `--fields`  | 作用于歌曲   | 见「歌曲」           | `id,mid,type,name,artist,album,duration` |

输出：

| 字段       | 含义                                                                                                                                                                                |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `playlist` | 歌单详情，总是完整：`dir_id`、`tid`、`name`、`song_count`、`creator`、`desc`、`tags`、`listen_count`、`cover`、`url`、`created_at`、`updated_at`。别人的歌单 `dir_id` 通常为 `null` |
| `total`    | 歌单总歌曲数                                                                                                                                                                        |
| `offset`   | 实际用的 `--offset`                                                                                                                                                                 |
| `count`    | 本次返回几首                                                                                                                                                                        |
| `complete` | 是否取全了（按 `--offset`、`--limit` 算）                                                                                                                                           |
| `songs`    | 歌曲数组                                                                                                                                                                            |

每次请求 500 首，分页读到够数或读完。

### `qqmusic liked`

`show liked` 的简写，选项只有 `--limit`（默认全部）和 `--fields`，没有 `--offset`。输出同 `show`。

### `qqmusic faved [playlists|albums]`

| 参数 / 选项 | 含义 | 取值                                                                                | 默认        |
| ----------- | ---- | ----------------------------------------------------------------------------------- | ----------- |
| `kind`      | 类型 | 以 `playlist` 或 `album` 开头的任意文字（`playlists`、`albums` 都行）；其他退出码 2 | `playlists` |
| `--fields`  |      |                                                                                     | 见下        |

收藏的歌单，默认 `tid,name,creator,song_count,faved_at`；可选还有 `updated_at`、`cover`、`url`、`listen_count`、`desc`、`tags`（后三个多发请求）。

收藏的专辑，默认 `id,mid,name,artist,song_count,release_date,faved_at`；可选还有 `cover`、`url`。

输出：数组。

### `qqmusic following [singers|users]`

| 参数 / 选项 | 含义                                                                           | 取值                                               | 默认                                                                |
| ----------- | ------------------------------------------------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------- |
| `kind`      | 类型                                                                           | 以 `singer` 或 `user` 开头的任意文字；其他退出码 2 | `singers`                                                           |
| `--saved`   | 加 `liked_songs`、`saved_songs`：你存的歌里有几首是这位歌手的，按歌手 mid 统计 | 开关                                               | 关                                                                  |
| `--fields`  |                                                                                |                                                    | `name,mid,euin,fans`，加 `--saved` 时再加 `liked_songs,saved_songs` |

可选字段：`name`、`mid`、`euin`、`fans`、`avatar`。`liked_songs` 数「我喜欢」里的歌，`saved_songs` 数所有自建歌单里去重后的歌。没有 `mid` 的人这两项是 `null`。`--saved` 要读完所有歌单，很慢。`--saved` 对 `users` 的结果未验证。输出：数组。

### `qqmusic song [<歌曲>...]`

| 参数 / 选项 | 含义                                               | 默认                                     |
| ----------- | -------------------------------------------------- | ---------------------------------------- |
| `<歌曲>...` | 见「指定歌曲」                                     |                                          |
| `--stdin`   | 另从 stdin 读                                      | 关                                       |
| `--detail`  | 加 `genre_name,language_name,company,publish_time` | 关                                       |
| `--fields`  | 点名 `genre_name` 等详情字段，效果同 `--detail`    | `id,mid,type,name,artist,album,duration` |

输出：歌曲数组，顺序同输入。找不到的歌：退出码 2，`unknown song(s)`。

### `qqmusic search <关键词>`

| 参数 / 选项 | 含义         | 取值                                                         | 默认                   |
| ----------- | ------------ | ------------------------------------------------------------ | ---------------------- |
| `<关键词>`  | 搜索词，必填 |                                                              |                        |
| `--type`    | 搜什么       | `song`、`singer`、`album`、`playlist`、`mv`、`lyric`、`user` | `song`                 |
| `--page`    | 第几页       | 整数，≥ 1                                                    | 1                      |
| `--limit`   | 每页几条     | 整数，1 到 50                                                | 20                     |
| `--fields`  |              |                                                              | 歌曲同上；其他类型见下 |

输出：`query`、`type`、`page`、`total`（接口给的总数）、`results`。

| `--type`        | `results` 每项                                              |
| --------------- | ----------------------------------------------------------- |
| `song`、`lyric` | 歌曲对象，`--fields` 规则同 `show`                          |
| `album`         | `id`、`mid`、`name`、`artist`、`release_date`、`song_count` |
| `playlist`      | `tid`、`name`、`creator`、`song_count`、`listen_count`      |
| `singer`        | `id`、`mid`、`name`、`song_count`                           |
| `mv`、`user`    | 接口原样的对象，不整理字段                                  |

非歌曲类型的 `--fields` 只认 `a,b`，原样按名字取，不检查名字对不对，不认 `+` 和 `all`。

### `qqmusic album <ALBUM_MID>`

| 参数 / 选项 | 含义                | 取值      | 默认       |
| ----------- | ------------------- | --------- | ---------- |
| `ALBUM_MID` | 14 位专辑 mid，必填 |           |            |
| `--limit`   | 最多返回几首        | 整数，≥ 1 | 全部       |
| `--fields`  | 作用于歌曲          |           | 同歌曲默认 |

mid 格式不对或查无此专辑：退出码 2。

| 输出字段   | 含义                                                                                                                                                                                                            |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `album`    | 总是完整：`id`、`mid`、`name`、`trans_name`、`artist`、`singers`、`release_date`、`type`、`language`、`genre`、`company`、`song_count`、`labels`、`awards`、`rec_text`、`desc`、`cover`、`url`、`comment_count` |
| `total`    | 专辑总曲数                                                                                                                                                                                                      |
| `count`    | 本次返回几首                                                                                                                                                                                                    |
| `complete` | 是否取全了                                                                                                                                                                                                      |
| `songs`    | 歌曲数组                                                                                                                                                                                                        |

### `qqmusic match <关键词>...`

| 参数 / 选项   | 含义                               | 取值                    | 默认                              |
| ------------- | ---------------------------------- | ----------------------- | --------------------------------- |
| `<关键词>...` | 气质或风格，至少一个               |                         |                                   |
| `--lists`     | 每个关键词读几个公开歌单           | 整数，1 到 30           | 8                                 |
| `--per-list`  | 每个歌单最多读几首                 | 整数，≥ 1               | 300                               |
| `--min-hits`  | 只留下至少出现在这么多个歌单里的歌 | 整数，≥ 1               | 1                                 |
| `--fields`    |                                    | 歌曲字段加 `hits`、`in` | `id,type,name,artist,url,hits,in` |

先读完你所有自建歌单，再搜每个关键词的歌单（搜索类型 `playlist`），跳过你自己的歌单，逐个读歌曲，统计你的歌出现了几次。很慢，请求量大。

| 输出字段     | 含义                                            |
| ------------ | ----------------------------------------------- |
| `keywords`   | 输入的关键词                                    |
| `lists`      | 实际读了的公开歌单：`[{tid, name, songs_read}]` |
| `your_songs` | 你的曲库去重后的歌曲数                          |
| `count`      | 过滤 `--min-hits` 之后的 `matches` 条数         |
| `matches`    | 按 `hits` 降序、再按歌名排序                    |

### `qqmusic comments <kind> <ref>`

| 参数 / 选项 | 含义               | 取值                                                                   | 默认                         |
| ----------- | ------------------ | ---------------------------------------------------------------------- | ---------------------------- |
| `kind`      | 对象类型           | `song`、`album`、`playlist`（结尾的 `s` 会被去掉，`songs` 也行）       |                              |
| `ref`       | 对象               | 歌曲：id、`id:type`、mid；专辑：14 位 mid；歌单：名字、`dir_id`、`tid` |                              |
| `--new`     | 最新评论而不是热门 | 开关                                                                   | 关                           |
| `--limit`   | 最多几条           | 整数，1 到 200                                                         | 20                           |
| `--fields`  |                    |                                                                        | `content,likes,replies,time` |

可选字段：`content`、`likes`、`replies`、`time`、`user`、`id`。

| 输出字段         | 含义                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| `target`         | `{kind, id, mid, name, artist}`（专辑同；歌单只有 `kind, id, name`） |
| `order`          | `hot` 或 `newest`                                                    |
| `total_comments` | 评论总数                                                             |
| `listed`         | 该榜单（热门或最新）的总条数                                         |
| `count`          | 本次返回几条                                                         |
| `comments`       | 评论数组                                                             |

QQ 音乐不给列评论的对象：退出码 1，错误码 20022。

### `qqmusic lyrics <SONG>`

`SONG`：一首歌，见「指定歌曲」。无其他选项。输出：`song`（歌曲对象，默认字段之外的字段都有）、`lyric`（LRC 文本）、`trans`（翻译，没有为 `null`）。

### `qqmusic export`

| 选项    | 含义       | 取值     | 默认                    |
| ------- | ---------- | -------- | ----------------------- |
| `--out` | 写入的目录 | 目录路径 | 数据目录下的 `exports/` |

写 `library-YYYYMMDD-HHMMSS.json`（缩进 2 个空格）。文件内容：`exported_at`、`uin`、`playlists`（自建歌单，每个含歌单字段全集、`complete`、`songs`，歌曲对象字段全集不含 `comment_count`）、`faved_playlists`（含 `listen_count`、`desc`、`tags`）、`faved_albums`、`following_singers`。

stdout 输出：

| 字段                   | 含义                               |
| ---------------------- | ---------------------------------- |
| `path`                 | 写出的文件                         |
| `playlists`            | 自建歌单数                         |
| `songs`                | 所有自建歌单里的歌曲条数（不去重） |
| `faved_playlists`      | 收藏的歌单数                       |
| `faved_albums`         | 收藏的专辑数                       |
| `incomplete_playlists` | 没读全的歌单名数组                 |

## 写

所有写命令都有 `--dry-run`：只预演，不写入，不产生 `run_id`。

写命令的输出里，如果这次真的改动了东西，会多一个 `run_id`（`runs`、`undo` 用它）。记录在写之前逐步落盘，中断也留得下已完成的部分。

### `qqmusic create <名字>`

| 参数 / 选项         | 含义                           | 默认 |
| ------------------- | ------------------------------ | ---- |
| `<名字>`            | 歌单名，空白会被规整成单个空格 |      |
| `--allow-duplicate` | 同名也照样新建                 | 关   |
| `--dry-run`         |                                | 关   |

名字为空：退出码 2。内容安全拒绝：退出码 1。

| 输出字段   | 含义                                                                              |
| ---------- | --------------------------------------------------------------------------------- |
| `created`  | 是否真的新建了。同名已存在、或 `--dry-run` 时为 `false`                           |
| `playlist` | 新建的是 `{dir_id, tid, name}`；已存在的是完整歌单对象；`--dry-run` 只有 `{name}` |
| `note`     | 同名已存在时有                                                                    |
| `dry_run`  | 仅 `--dry-run` 时有，`true`                                                       |
| `run_id`   | 真的新建了才有                                                                    |

### `qqmusic edit <歌单>`

| 参数 / 选项            | 含义                            | 取值                       | 默认 |
| ---------------------- | ------------------------------- | -------------------------- | ---- |
| `<歌单>`               | 自建歌单：名字、`dir_id`、`tid` |                            |      |
| `--name`               | 新名字                          | 1 到 20 个字符             | 不改 |
| `--desc`               | 新简介                          | 最多 2000 个字符           | 不改 |
| `--public / --private` | 所有人可见 / 仅自己可见         |                            | 不改 |
| `--cover`              | 新封面                          | 图片文件，裁成正方形后上传 | 不改 |
| `--dry-run`            |                                 |                            | 关   |

四项一个都没给：退出码 2。系统歌单（`dir_id` 201 到 206，含「我喜欢」）不能改：退出码 2。`--dry-run` 时封面不上传，`after.cover` 是 `(upload <路径>)`。

| 输出字段   | 含义                                                                      |
| ---------- | ------------------------------------------------------------------------- |
| `playlist` | `{dir_id, tid, name}`                                                     |
| `before`   | 改前：`{name, desc, public, cover}`                                       |
| `after`    | 改后，同上结构；没给的项等于 `before`                                     |
| `dry_run`  |                                                                           |
| `changed`  | 是否真的写了。没有变化、或 `--dry-run` 时为 `false`                       |
| `verified` | 写后回读是否一致（封面比较时忽略 `?` 之后的缩放后缀）。仅 `changed: true` |
| `now`      | 回读到的当前状态。仅 `changed: true`                                      |
| `run_id`   | 真的写了才有                                                              |

### `qqmusic delete <歌单>`

| 参数 / 选项 | 含义             | 默认 |
| ----------- | ---------------- | ---- |
| `<歌单>`    | 自建歌单         |      |
| `--yes`     | 确认删除，必须给 | 关   |
| `--dry-run` |                  | 关   |

没有 `--yes` 也没有 `--dry-run`：退出码 2。「我喜欢」不能删：退出码 2。删之前先读全歌曲存进记录；读不全则不删，退出码 1。

输出：`deleted`（`--dry-run` 时 `false`）、`dry_run`（仅 `--dry-run`）、`playlist`（真删时 `{dir_id, tid, name}`；`--dry-run` 时完整歌单对象）、`song_count`、`run_id`。

### `qqmusic add <歌单> [<歌曲>...]`

| 参数 / 选项              | 含义                     | 默认       |
| ------------------------ | ------------------------ | ---------- |
| `<歌单>`                 | 目标，自建歌单或 `liked` |            |
| `<歌曲>...`              | 见「指定歌曲」           |            |
| `--stdin`                | 另从 stdin 读            | 关         |
| `--dry-run`              |                          | 关         |
| `--verify / --no-verify` | 写完回读歌单核对         | `--verify` |

先查出歌曲信息并按 `(id, type)` 去重，已在歌单里的跳过。每批 20 首，批与批之间停约 0.8 到 1.6 秒。

| 输出字段              | 含义                                             |
| --------------------- | ------------------------------------------------ |
| `playlist`            | `{dir_id, tid, name}`                            |
| `requested`           | 去重后要加几首                                   |
| `already_present`     | 本来就在的歌：`[{id, type, name, artist}]`       |
| `added`               | 这次加进去的歌，同上结构                         |
| `dry_run`             |                                                  |
| `would_add`           | 仅 `--dry-run`：会加的歌                         |
| `verified`            | 仅做了回读时有，`true`                           |
| `missing_after_write` | 仅做了回读时有：写了但回读没找到的歌，应为空数组 |
| `run_id`              | 真的加了才有                                     |

`--dry-run` 时 `added` 为空数组。

### `qqmusic remove <歌单> [<歌曲>...]`

选项同 `add`。输出：

| 输出字段        | 含义                                                         |
| --------------- | ------------------------------------------------------------ |
| `playlist`      | `{dir_id, tid, name}`                                        |
| `requested`     | 去重后要删几首                                               |
| `not_present`   | 本来就不在歌单里的歌：`[{id, type, name, artist}]`，不算错误 |
| `removed`       | 这次删掉的歌                                                 |
| `dry_run`       |                                                              |
| `would_remove`  | 仅 `--dry-run`                                               |
| `verified`      | 仅做了回读时有                                               |
| `still_present` | 仅做了回读时有：删了但回读还在的歌，应为空数组               |
| `run_id`        | 真的删了才有                                                 |

### `qqmusic like [<歌曲>...]` / `qqmusic unlike [<歌曲>...]`

`add liked ...` / `remove liked ...` 的简写，选项只有 `--stdin`、`--dry-run`；一定回读核对。输出同 `add` / `remove`。

### `qqmusic fav <kind> <项>...` / `qqmusic unfav <kind> <项>...`

| 参数 / 选项 | 含义           | 取值                                                       |
| ----------- | -------------- | ---------------------------------------------------------- |
| `kind`      | 类型           | `playlist` 或 `album`（结尾的 `s` 会被去掉）；其他退出码 2 |
| `<项>...`   | 对象，至少一个 | 歌单：纯数字的 `tid`；专辑：14 位 mid；格式不对退出码 2    |
| `--dry-run` |                |                                                            |

`fav` 不能收藏自己的歌单，退出码 2。已经是目标状态的项不动，也不记录。逐个写，之间停顿，写完回读。

| 输出字段      | 含义                                             |
| ------------- | ------------------------------------------------ |
| `kind`        | `playlist` 或 `album`                            |
| `action`      | `fav` 或 `unfav`                                 |
| `to_change`   | 需要改的项                                       |
| `already`     | 本来就是目标状态的项                             |
| `dry_run`     |                                                  |
| `changed`     | 改成功的项（`--dry-run` 或没有要改的时为空数组） |
| `not_changed` | 写了但回读没变的项；只有真的写了才有             |
| `run_id`      | 真的改了才有                                     |

### `qqmusic runs`

| 选项      | 含义     | 取值      | 默认 |
| --------- | -------- | --------- | ---- |
| `--limit` | 最多几条 | 整数，≥ 1 | 20   |

输出：数组，新的在前。每项：`run_id`、`created_at`、`command`（如 `add 通勤 (3 songs)`）、`ops`（字符串数组，每步一句话）、`undone_by`（已撤销时是撤销那次的 `run_id`，否则 `null`）。

### `qqmusic undo <run_id>`

| 参数 / 选项 | 含义                                       | 默认 |
| ----------- | ------------------------------------------ | ---- |
| `<run_id>`  | 要撤销的记录，必填                         |      |
| `--force`   | 已撤销过也再撤销；也删掉不再为空的新建歌单 | 关   |
| `--dry-run` |                                            | 关   |

记录不存在：退出码 2。已被撤销且没有 `--force`：退出码 2。按相反顺序逐步撤销：

| 原操作          | 撤销做什么                                                   |
| --------------- | ------------------------------------------------------------ |
| `add`           | 删掉当时加进去的歌                                           |
| `remove`        | 把当时删掉的歌加回去                                         |
| `create`        | 删除那个歌单；不为空且没有 `--force` 则跳过                  |
| `edit`          | 恢复改前的名字、简介、公开状态、封面                         |
| `fav` / `unfav` | 反向操作                                                     |
| `delete`        | 用原名重新建歌单（`dir_id` 和 `tid` 会变），再加回存档的歌曲 |

撤销本身也是一条记录，也能撤销。

输出：`undone`（原 `run_id`）、`dry_run`、`results`、`run_id`（撤销这次的，真的改了才有）。`results` 每项是下面之一，单步失败不中断，记在该项的 `error` 里（`{kind, message, ...}`），退出码仍是 0：

| 形状                                                                 |
| -------------------------------------------------------------------- |
| `{undo: "add", removed: N, playlist}`                                |
| `{undo: "remove", added: N, playlist}`                               |
| `{undo: "create", deleted}` 或 `{undo: "create", skipped, playlist}` |
| `{undo: "edit", restored, playlist}`                                 |
| `{undo: "fav" \| "unfav", kind, restored}`                           |
| `{undo: "delete", recreated, added}`                                 |
| `{undo, error, playlist}`                                            |

## 其他

### `qqmusic raw <module> <method>`

| 参数 / 选项 | 含义                     | 取值          | 默认 |
| ----------- | ------------------------ | ------------- | ---- |
| `module`    | 接口的 module，必填      |               |      |
| `method`    | 接口的 method，必填      |               |      |
| `--param`   | 参数                     | JSON 对象文本 | `{}` |
| `--write`   | 标记为非幂等：不自动重试 | 开关          | 关   |

`--param` 不是合法 JSON：退出码 2。输出：接口返回的 `data` 原样。有凭证就带上，没有也发。不检查是不是写接口，不产生 `run_id`。

### `qqmusic report`

| 选项       | 含义 | 取值                            | 默认 |
| ---------- | ---- | ------------------------------- | ---- |
| `--period` | 周期 | `d`（日）、`w`（周）、`m`（月） | `m`  |

要环境变量 `QQMUSIC_API_KEY`；没设：退出码 3。请求发到 `https://a.y.qq.com/me/report`。输出：接口原样的 JSON。接口返回的 `ret` 或 `sub_ret` 不为 0：退出码 1。网络失败：退出码 5。这条命令没有用真实 key 验证过（`official.py` 注明「Untested: needs a key」）。
