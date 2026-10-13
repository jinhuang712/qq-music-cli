# 原理

## 数据接口

`qqmusic` 以明文 JSON 请求 `https://u.y.qq.com/cgi-bin/musicu.fcg`。请求里带的东西和 y.qq.com 网页相同：

- 同样的 `comm`（`ct=24`、`cv=4747474`）
- 账号 Cookie
- `g_tk`，即对 session key 做 hash33 的结果

y.qq.com 网页自己现在用的是另一个加密并签名的接口。但截至最近一次检查（2026-10-11），这个明文接口的读写仍然照常响应。

以下接口都在真实账号上验证过：

| 能力                         | module / method                                                                                                                          |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 列出歌单                     | `music.musicasset.PlaylistBaseRead` / `GetPlaylistByUin`                                                                                 |
| 读歌单                       | `music.srfDissInfo.aiDissInfo` / `uniform_get_Dissinfo`                                                                                  |
| 建歌单、删歌单               | `music.musicasset.PlaylistBaseWrite` / `AddPlaylist`、`DelPlaylist`                                                                      |
| 歌单标签名                   | `music.musicasset.PlaylistTag` / `getPlaylistTag`                                                                                        |
| 改名、改简介、设私密、换封面 | `music.musicasset.PlaylistBaseWrite` / `EditPlaylist`（`dirShow` 1 公开、2 私密），封面先用 `music.filesys.FileSystem` / `PutImage` 上传 |
| 收藏、取消收藏歌单           | `music.musicasset.PlaylistFavWrite` / `FavPlaylist`、`CancelFavPlaylist`，回读用 `music.musicasset.PlaylistFavRead` / `IsPlaylistFan`    |
| 收藏、取消收藏专辑           | `music.musicasset.AlbumFavWrite` / `FavAlbum`、`CancelFavAlbum`，回读用 `music.musicasset.AlbumFavRead` / `IsAlbumFan`                   |
| 加歌、删歌                   | `music.musicasset.PlaylistDetailWrite` / `AddSonglist`、`DelSonglist`                                                                    |
| 歌曲元数据                   | `music.trackInfo.UniformRuleCtrl` / `CgiGetTrackInfo`、`music.pf_song_detail_svr` / `get_song_detail_yqq`                                |
| 收藏的歌单和专辑             | `music.musicasset.PlaylistFavRead`、`music.musicasset.AlbumFavRead`                                                                      |
| 专辑信息和曲目               | `music.musichallAlbum.AlbumInfoServer` / `GetAlbumDetail`、`music.musichallAlbum.AlbumSongList` / `GetAlbumSongList`                     |
| 评论和评论总数               | `music.globalComment.CommentRead` / `GetHotCommentList`、`GetNewCommentList`（`BizType` 1 歌曲、2 专辑、3 歌单）                         |
| 关注的歌手、用户             | `music.concern.RelationList` / `GetFollowSingerList`、`GetFollowUserList`                                                                |
| 搜索                         | `music.search.SearchCgiService` / `DoSearchForQQMusicDesktop`                                                                            |
| 歌词                         | `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg`                                                                                      |

网页上还有两件事，CLI 没有做：

- 关注、取消关注歌手：`Concern.ConcernSystemServer` / `cgi_concern_user_v2`。参数和网页一致，但走普通请求时返回 10018。网页发的是签名加密过的请求，CLI 不实现这种请求。
- 调整歌单里歌曲的顺序：网页上没有这个功能，也找不到对应的接口。

## 登录

- **扫码流程**：QQ 扫码走 QQ 的 ptlogin 和 graph.qq.com OAuth，微信扫码走微信开放平台，两条路最后都由 QQ 音乐的登录接口换取凭证。
- **不用浏览器**：整个过程都是普通 HTTP 请求，不依赖浏览器自动化。
- **登录窗口**：你看到的窗口是 `127.0.0.1` 上的一个本地页面，只负责显示二维码和登录状态，登录结束后就关闭。如果装了 Chrome，它会单独开一个临时的 Chrome 实例，结束后连同临时 profile 一起清理掉。
- **续期**：登录 key 3 天过期，续期调用同一个登录接口的 `loginMode=2`。

## 插件结构

插件的全部内容只有一份 Agent Skill。Claude Code 和 Codex 会在 skill 名前加插件名，Pi 和 OpenCode 不会，所以按渠道分两种打包：

| 渠道               | 目录                                                                | 显示的名字     |
| ------------------ | ------------------------------------------------------------------- | -------------- |
| Claude Code、Codex | `skills/cli/`（源头）                                               | `qq-music:cli` |
| Pi、OpenCode       | `flat-skills/qq-music-cli/`（由 `scripts/sync_flat_skill.py` 生成） | `qq-music-cli` |

skill 只在用户手动加载时才会用上，模型不会自己加载它。四个 agent 的设置各不相同：

| 渠道        | 关掉自动加载                                                                   | 用户怎么加载                                                                                                           |
| ----------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| Claude Code | `SKILL.md` 里的 `disable-model-invocation: true`                               | `/qq-music:cli`                                                                                                        |
| Codex       | `skills/cli/agents/openai.yaml` 里的 `policy.allow_implicit_invocation: false` | `$qq-music:cli`                                                                                                        |
| Pi          | 同样是 `disable-model-invocation: true`，生成副本时保留                        | `/skill:qq-music-cli`                                                                                                  |
| OpenCode    | 副本 `metadata` 里的 `opencode/autoinvoke: "false"`                            | 对 agent 说「加载 qq-music-cli skill」。副本里也写了 `opencode/slash: "true"`，但 OpenCode 2.0.20 还不认这个键（实测） |

只加载、不带要求时，skill 会先回一段引导，列出能做的事。

skill 由这几份文件组成：

- `SKILL.md`：安装、登录、命令和安全规则。
- `references/concepts.md`：QQ 音乐的数据模型，包括 `dir_id` 和 `tid` 的区别、「我喜欢」、同一首歌的不同版本、语种和流派代码，以及各项限制。
- `agents/openai.yaml`：只给 Codex 用，关掉自动加载。

各渠道的清单文件：

- `.claude-plugin/`：Claude Code 用，Codex 也读其中的 marketplace。
- `plugin.json`：[agent-plugins.org](https://agent-plugins.org) 格式，Codex 读取。
- `package.json`：`pi.skills` 字段，Pi 读取。

## 协议知识的来源

协议知识一部分来自抓取 y.qq.com 网页自身的请求，一部分来自阅读 README「致谢」里列出的几个开源项目。本项目没有包含这些项目的任何代码。
