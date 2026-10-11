# qq-music-cli

让 coding agent 帮你打理 QQ 音乐曲库。`qqmusic` 是一个管理你自己 QQ 音乐账号的命令行工具，同时也是 **Claude Code、Codex、Pi、OpenCode** 的插件。agent 可以用它：

- 读取你的歌单和「我喜欢」
- 按语言、流派、心情整理歌曲
- 新建、合并、拆分歌单，以及去重
- 撤销任何一次改动

项目主页：<https://jinhuang712.github.io/qq-music-cli/>

> [!IMPORTANT]
> **非官方项目。**
> - 本项目与腾讯、QQ 音乐没有任何关联，也未获其认可。
> - 它调用的是 y.qq.com 网页端未公开的接口，随时可能变化或失效。
> - 请只用于你自己的账号，风险自负，并遵守 QQ 音乐的服务条款。
>
> 本工具只管理歌单信息，不播放、不下载、也不解密任何音频。

## 能做什么

| | |
|---|---|
| **读取曲库** | 自建歌单；「我喜欢」，不受网页只显示一页的限制；收藏的歌单和专辑；歌曲元数据，包括专辑、时长、发行日期、语言、流派 |
| **安全地修改** | 建歌单、删歌单，批量加歌、删歌、加红心。已在歌单里的歌会自动跳过，写完会回读核对，`--dry-run` 可以先预览，`qqmusic undo <run_id>` 可以撤销某次改动 |
| **曲库级操作** | `qqmusic export` 把整个曲库导出成一个 JSON 文件，方便做体检、去重和分组 |
| **搜索** | QQ 音乐曲库（歌曲、专辑、歌单、歌手）和歌词 |
| **为 agent 设计** | 每条命令只输出一个 JSON 文档，退出码固定。附带的 skill 会教 agent 用法、QQ 音乐的业务概念，以及 10 个实测过的工作流 |

## 快速开始（配合 agent）

1. **在 agent 里安装插件**，各渠道的安装方式见下表。

   | Agent | 安装 | skill 显示为 |
   |---|---|---|
   | Claude Code | `claude plugin marketplace add jinhuang712/qq-music-cli && claude plugin install qq-music@qq-music` | `qq-music:cli` |
   | Codex | `codex plugin marketplace add jinhuang712/qq-music-cli && codex plugin add qq-music@qq-music` | `qq-music:cli` |
   | Pi | `pi install git:github.com/jinhuang712/qq-music-cli` | `qq-music-cli` |
   | OpenCode | `git clone https://github.com/jinhuang712/qq-music-cli ~/.local/share/qq-music-cli-src && ln -s ~/.local/share/qq-music-cli-src/flat-skills/qq-music-cli ~/.config/opencode/skills/qq-music-cli` | `qq-music-cli` |

2. **直接对 agent 说**，比如「把我喜欢的歌按语言整理成歌单」。
   - 如果需要，agent 会自己安装 CLI。
   - 然后 agent 会发起登录，弹出一个显示二维码的小窗口，你用微信或 QQ 扫码即可。扫码是唯一需要你动手的步骤。
   - 登录 key 有效期 3 天，会自动续期。

## 直接使用 CLI

用 [uv](https://docs.astral.sh/uv/) 安装 CLI。需要 Python 3.11 以上和 macOS：凭证存储依赖 macOS 钥匙串，登录窗口也依赖 macOS。

```sh
uv tool install git+https://github.com/jinhuang712/qq-music-cli
qqmusic login --wechat     # 用 QQ 扫码则运行 qqmusic login
qqmusic status
```

| 命令 | 作用 |
|---|---|
| `qqmusic playlists` | 列出自建歌单（「我喜欢」的 `dir_id` 是 201） |
| `qqmusic show <歌单> [--fields id,name,artist] [--limit N]` | 列出歌单里的歌，`<歌单>` 可以是名字、`dir_id`、`tid` 或 `liked` |
| `qqmusic liked` | 列出「我喜欢」 |
| `qqmusic faved playlists\|albums` | 列出收藏的歌单或专辑 |
| `qqmusic song <歌...> [--detail]` | 歌曲元数据。加 `--detail` 返回文字版的流派、语言、唱片公司 |
| `qqmusic search <关键词> [--type song\|album\|playlist\|singer\|mv\|lyric\|user]` | 搜索 |
| `qqmusic lyrics <歌>` | 歌词（LRC 格式）和翻译 |
| `qqmusic export` | 把整个曲库导出成一个 JSON 文件 |
| `qqmusic create <名字>` | 新建歌单。同名歌单已存在时，直接返回已有的那个 |
| `qqmusic add <歌单> <歌...> [--stdin]` | 加歌。已在歌单里的会跳过，每批 20 首，写完回读核对 |
| `qqmusic remove <歌单> <歌...> [--stdin]` | 删歌 |
| `qqmusic like` / `qqmusic unlike <歌...>` | 加红心、取消红心 |
| `qqmusic delete <歌单> --yes` | 删除歌单。删除前把歌曲列表存进 run 日志，undo 时能重建 |
| `qqmusic runs` / `qqmusic undo <run_id>` | 查看写操作记录，或撤销某次写操作 |
| `qqmusic raw <module> <method> --param '{}'` | 直接调用任意 `musicu.fcg` 接口，用于探索 |
| `qqmusic report --period d\|w\|m` | 听歌报告，走腾讯官方 skill 接口，需要 `QQMUSIC_API_KEY` |

**歌曲引用**支持这几种写法：
- 数字 id，例如 `97773`
- `id:type`，例如 `97773:0`
- 14 位 mid，例如 `0039MnYb0qxYhV`
- 带 `id`/`type` 或 `mid` 字段的 JSON 对象

加 `--stdin` 后可以从管道读入歌曲，例如 `qqmusic show RNB --fields id,type | qqmusic add "RNB精选" --stdin`。

**退出码**：0 成功，1 接口错误，2 用法错误，3 需要重新登录，4 触发风控（请放慢），5 网络错误。

## Agent 插件

插件的全部内容只有一份 Agent Skill。Claude Code 和 Codex 会给插件里的 skill 加命名空间，Pi 和 OpenCode 不会，所以按渠道分两种打包：

| 渠道 | 目录 | 名字 |
|---|---|---|
| Claude Code、Codex | `skills/cli/`（源头） | `qq-music:cli` |
| Pi、OpenCode | `flat-skills/qq-music-cli/`（由 `scripts/sync_flat_skill.py` 生成） | `qq-music-cli` |

skill 由三份文件组成：
- `SKILL.md`：安装、命令和安全规则。
- `references/concepts.md`：QQ 音乐的数据模型，包括 `dir_id` 和 `tid` 的区别、「我喜欢」、歌曲的多个版本、语言和流派代码、限制。
- `references/workflows.md`：曲库体检、整理「我喜欢」、根据描述生成歌单、合并、拆分、复制、去重、规则同步、备份、清理等场景。里面的 `jq` 查询都实测过。

清单文件：`.claude-plugin/`（Claude Code 用，Codex 也读其中的 marketplace）、`plugin.json`（[agent-plugins.org](https://agent-plugins.org) 格式，Codex 读取）、`package.json`（`pi.skills` 字段）。

## 原理

- **数据接口**：以明文 JSON 请求 `https://u.y.qq.com/cgi-bin/musicu.fcg`，带上和 y.qq.com 网页相同的 `comm`（`ct=24`、`cv=4747474`）、账号 Cookie，以及 `g_tk`（对 session key 做 hash33）。y.qq.com 网页自己现在用的是另一个加密并签名的接口，但截至最近一次检查（2026-10-11），这个明文接口的读写仍然照常响应。
- **登录**：使用 QQ ptlogin 和微信开放平台的扫码流程，最后由 QQ 音乐换取凭证。整个过程不依赖浏览器自动化。你看到的窗口是一个 `127.0.0.1` 上的本地页面，只负责显示二维码和登录状态。
- **凭证**保存在 macOS 钥匙串，服务名 `qq-music-cli`。run 日志和导出文件放在 `~/.local/share/qq-music-cli/`。

以下接口都在真实账号上验证过：

| 能力 | module / method |
|---|---|
| 列出歌单 | `music.musicasset.PlaylistBaseRead` / `GetPlaylistByUin` |
| 读歌单 | `music.srfDissInfo.aiDissInfo` / `uniform_get_Dissinfo` |
| 建歌单 / 删歌单 | `music.musicasset.PlaylistBaseWrite` / `AddPlaylist`、`DelPlaylist` |
| 加歌 / 删歌 | `music.musicasset.PlaylistDetailWrite` / `AddSonglist`、`DelSonglist` |
| 歌曲元数据 | `music.trackInfo.UniformRuleCtrl` / `CgiGetTrackInfo`、`music.pf_song_detail_svr` / `get_song_detail_yqq` |
| 搜索 | `music.search.SearchCgiService` / `DoSearchForQQMusicDesktop` |

## 开发

```sh
uv sync
uv run pytest -q                           # 离线测试，用 httpx.MockTransport 模拟所有服务器
uv run python scripts/sync_flat_skill.py   # 修改 skills/cli/ 之后运行
```

## 致谢

本项目的协议知识，一部分来自抓取 y.qq.com 网页自身的请求，一部分来自阅读这些公开项目：[L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi)（GPL-3.0）、[baoozak/qqmusic-mcp](https://github.com/baoozak/qqmusic-mcp)（MIT），以及腾讯官方 [qqmusic-skills](https://github.com/tencentmusic/qqmusic-skills) 的文档。本项目没有包含这些项目的任何代码。

## License

[MIT](LICENSE)
