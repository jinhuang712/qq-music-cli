---
name: qq-music-cli
description: 用 `qqmusic` 命令行管理用户自己的 QQ 音乐曲库。适用于：查看歌单和「我喜欢」、查歌曲信息、搜索曲库、新建或删除歌单、批量加歌删歌、加红心、导出整个曲库、撤销改动。也适用于整理类的需求，比如把「我喜欢」按语种、流派或心情分进不同歌单，根据一句描述生成歌单，合并、拆分、去重歌单，给曲库做一次体检。
compatibility: 需要 PATH 里有 `qqmusic` 命令（qq-music-cli，Python 3.11+，用 uv 安装）；钥匙串存储和登录窗口依赖 macOS；需要能访问 y.qq.com。
---

# QQ 音乐曲库（`qqmusic`）

`qqmusic` 通过 y.qq.com 网页端的接口，读写用户自己的 QQ 音乐账号。

- 每条命令在 stdout 只输出一个 JSON。
- 进度和报错以 JSON 行的形式写到 stderr。
- 想省 token，就在子命令前加 `--compact`，例如 `qqmusic --compact show RNB`。

按需阅读这两份参考文档：

- [references/concepts.md](references/concepts.md)：QQ 音乐的基本概念，包括各种 ID（`dir_id`、`tid`，歌曲的 `id`、`type`、`mid`）、「我喜欢」、收藏的歌单、同一首歌的不同版本、语种和流派代码、各项限制，以及 CLI 做不到的事。
- [references/workflows.md](references/workflows.md)：整理、生成、合并、拆分、去重、同步、备份、清理等场景的分步做法，附带实测过的 `jq` 查询。

## 一、先确认 CLI 能用

```sh
command -v qqmusic && qqmusic --compact status
```

- **找不到命令**：CLI 的源码和这个 skill 在同一个仓库里。从本文件所在目录往上找，第一个包含 `pyproject.toml` 的目录就是仓库根目录，用 `uv tool install --editable <仓库根目录>` 安装。如果一直找不到 `pyproject.toml`，就从 GitHub 安装：`uv tool install git+https://github.com/jinhuang712/qq-music-cli`。安装由你来做，不要让用户自己动手。
- **还没登录**：`logged_in` 为 false 或 `valid` 为 false（退出码 3）时，由你在后台发起登录。用微信扫码运行 `qqmusic login --wechat`，用 QQ 扫码运行 `qqmusic login`。用户的屏幕上会弹出一个小窗口，显示二维码和实时状态，你只需提醒用户拿手机扫码。扫码是整个流程里唯一需要用户动手的一步；用户在手机上确认后，命令会输出 `{"logged_in": true, ...}` 并退出。
- **没有图形界面**：只有这种情况才加 `--no-ui`。这时二维码图片的路径会以 `{"event": "qr_ready", "path": ...}` 的形式写到 stderr。
- **登录有效期**：登录 key 的有效期是 3 天，剩余不到 12 小时时，`qqmusic` 会自动续期。需要时也可以用 `qqmusic refresh` 手动续期。

## 二、命令

| 要做的事                                                                                | 命令                                                                                                                  |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 列出我的歌单（「我喜欢」的 `dir_id` 是 201）                                            | `qqmusic playlists`                                                                                                   |
| 看歌单里有哪些歌。歌单可以写名字、`dir_id`、`tid` 或 `liked`，任何公开歌单的 `tid` 也行 | `qqmusic show "RNB" --fields id,type,name,artist,album,duration,release_date`                                         |
| 看「我喜欢」                                                                            | `qqmusic liked --fields id,type,name,artist`                                                                          |
| 看收藏的歌单、专辑                                                                      | `qqmusic faved playlists`、`qqmusic faved albums`                                                                     |
| 查歌曲信息                                                                              | `qqmusic song 97773 0039MnYb0qxYhV`                                                                                   |
| 查文字版的流派、语种、唱片公司                                                          | `qqmusic song <歌曲> --detail`（每首歌多一次请求）                                                                    |
| 搜索                                                                                    | `qqmusic search "晴天 周杰伦" --type song --limit 10`（`--type` 可选 song、singer、album、playlist、mv、lyric、user） |
| 查歌词                                                                                  | `qqmusic lyrics 0039MnYb0qxYhV`                                                                                       |
| 导出整个曲库                                                                            | `qqmusic export`，输出 `{"path": ...}`                                                                                |
| 新建歌单（同名歌单已存在时，直接返回那一个）                                            | `qqmusic create "通勤"`                                                                                               |
| 加歌（已在歌单里的会跳过，每批 20 首，写完回读核对）                                    | `qqmusic add "通勤" 97773 0039MnYb0qxYhV`                                                                             |
| 删歌                                                                                    | `qqmusic remove "通勤" 97773`                                                                                         |
| 加红心、取消红心                                                                        | `qqmusic like 97773`、`qqmusic unlike 97773`                                                                          |
| 删除歌单（歌曲列表会先存档，可以撤销）                                                  | `qqmusic delete "通勤" --yes`                                                                                         |
| 预演任何写操作                                                                          | 加 `--dry-run`                                                                                                        |
| 查看写操作记录、撤销某次写操作                                                          | `qqmusic runs`、`qqmusic undo <run_id>`                                                                               |
| 听歌报告（需要 `QQMUSIC_API_KEY`）                                                      | `qqmusic report --period m`                                                                                           |

**指定歌曲**有四种写法：

- 数字 id，例如 `97773`
- `id:type`，例如 `97773:0`
- 14 位的 mid，例如 `0039MnYb0qxYhV`
- 带 `id`、`type` 或 `mid` 字段的 JSON 对象

**管道**：加上 `--stdin`，就能从标准输入读歌曲。输入可以是逐行的歌曲、JSON 数组，或者一整段 `qqmusic show` 的输出，所以上一条命令的结果可以直接接给下一条：

```sh
qqmusic show RNB --fields id,type | qqmusic add "RNB精选" --stdin --dry-run
```

在 zsh 里一次传多个 id，请走 `--stdin`，因为没加引号的 `$IDS` 变量不会按空格拆开。

**退出码**：

| 退出码 | 含义     | 怎么处理                           |
| ------ | -------- | ---------------------------------- |
| 0      | 成功     |                                    |
| 1      | 接口出错 |                                    |
| 2      | 用法有误 | 看报错信息，里面通常列出了可选的值 |
| 3      | 登录失效 | 按第一节的步骤重新登录             |
| 4      | 触发风控 | 停止写入并告诉用户，过几分钟再试   |
| 5      | 网络出错 |                                    |

## 三、规则

1. 涉及整个曲库的分析，都在本地完成。找重复、分组、找没进任何歌单的歌，都先运行一次 `qqmusic export`，再用 `jq` 查询导出的文件。不要逐个歌单调用 `show`。
2. 先出方案，再动手。一次改动超过 20 首，或者涉及多个歌单时，先把方案给用户看：每个目标歌单要加几首，再举几首例子。然后用 `--dry-run` 预演，用户确认后才真正写入。
3. 用户没有明确要求，就不要 `unlike`，不要从「我喜欢」里 `remove`，也不要 `delete` 任何歌单。「整理我喜欢」指的是把歌复制到别的歌单里，「我喜欢」本身保持原样。
4. 每次写完都要检查结果字段，不能只看退出码：
   - add 看 `added`、`already_present`、`missing_after_write`
   - remove 看 `removed`、`not_present`、`still_present`
5. 把每次写操作的 `run_id` 告诉用户，方便用户日后用 `qqmusic undo <run_id>` 撤销。
6. 控制写入量。CLI 已经做了分批和间隔；一旦遇到退出码 4，立即停下并告诉用户。
7. 歌单名不能超过 20 个字，这是 y.qq.com 新建歌单时的上限。新建之前先查有没有同名歌单，有就直接用。
