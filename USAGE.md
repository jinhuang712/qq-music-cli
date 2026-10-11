# 命令参考

每条命令在 stdout 只输出一个 JSON；进度和报错以 JSON 行的形式写到 stderr。想让输出压成一行，就在子命令前加 `--compact`，例如 `qqmusic --compact playlists`。

## 登录

```sh
qqmusic login --wechat     # 用微信扫码；用 QQ 扫码则运行 qqmusic login
qqmusic status             # 检查登录态是否有效
qqmusic refresh            # 手动续期
qqmusic logout             # 删除保存的凭证
```

- **登录窗口**：`qqmusic login` 会弹出一个小窗口，显示二维码和实时状态。没有图形界面时加 `--no-ui`，二维码图片的路径会写到 stderr。
- **凭证存放**：凭证保存在 macOS 钥匙串，服务名 `qq-music-cli`。设置环境变量 `QQMUSIC_CLI_CREDENTIAL_FILE` 后，凭证改存到该路径的文件里，权限为 0600。
- **有效期**：登录 key 有效期 3 天，剩余不到 12 小时时会自动续期。
- **导入 Cookie**：也可以用 `qqmusic login --cookie-file <文件>` 导入 Cookie。支持 Playwright storage-state JSON、Cookie 列表 JSON，或一行 `Cookie:` 头。

## 命令

| 命令                                                        | 作用                                                                             |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `qqmusic playlists`                                         | 列出自建歌单，带歌曲数和标签（「我喜欢」的 `dir_id` 是 201）。简介要用 `show` 看 |
| `qqmusic show <歌单> [--fields id,name,artist] [--limit N]` | 列出歌单里的歌，`<歌单>` 可以写名字、`dir_id`、`tid` 或 `liked`                  |
| `qqmusic liked`                                             | 列出「我喜欢」                                                                   |
| `qqmusic faved playlists` / `qqmusic faved albums`          | 列出收藏的歌单或专辑                                                             |
| `qqmusic following` / `qqmusic following users`             | 列出关注的歌手或用户                                                             |
| `qqmusic following --saved`                                 | 每位关注的歌手在「我喜欢」和所有歌单里各收藏了几首，按歌手 mid 统计              |
| `qqmusic song <歌曲...> [--detail]`                         | 歌曲信息。加 `--detail` 返回文字版的流派、语种、唱片公司                         |
| `qqmusic search <关键词> [--type <类型>]`                   | 搜索，类型可选 song、album、playlist、singer、mv、lyric、user                    |
| `qqmusic lyrics <歌曲>`                                     | 歌词（LRC 格式）和翻译                                                           |
| `qqmusic export`                                            | 把整个曲库导出成一个 JSON 文件                                                   |
| `qqmusic create <名字>`                                     | 新建歌单。同名歌单已存在时，直接返回那一个                                       |
| `qqmusic add <歌单> <歌曲...> [--stdin]`                    | 加歌。已在歌单里的会跳过，每批 20 首，写完回读核对                               |
| `qqmusic remove <歌单> <歌曲...> [--stdin]`                 | 删歌                                                                             |
| `qqmusic like <歌曲...>` / `qqmusic unlike <歌曲...>`       | 加红心、取消红心                                                                 |
| `qqmusic delete <歌单> --yes`                               | 删除歌单。删除前把歌曲列表存档，撤销时能重建                                     |
| `qqmusic edit <歌单> [--name 新名字] [--desc 新简介]`       | 改名、改简介。封面、标签、是否公开保持不变，可以撤销                             |
| `qqmusic runs` / `qqmusic undo <run_id>`                    | 查看写操作记录，撤销某次写操作                                                   |
| `qqmusic raw <module> <method> --param '{}'`                | 直接调用任意 `musicu.fcg` 接口，用于探索                                         |
| `qqmusic report --period d\|w\|m`                           | 听歌报告，走腾讯官方 skill 接口，需要 `QQMUSIC_API_KEY`                          |

所有写操作都支持 `--dry-run`，先预演、不真正写入。

## 怎么指定歌曲

- 数字 id，例如 `97773`
- `id:type`，例如 `97773:0`
- 14 位的 mid，例如 `0039MnYb0qxYhV`
- 带 `id`、`type` 或 `mid` 字段的 JSON 对象

加上 `--stdin`，就能从管道读入歌曲。输入可以是逐行的歌曲、JSON 数组，也可以是一整段 `qqmusic show` 的输出：

```sh
qqmusic show RNB --fields id,type | qqmusic add "RNB精选" --stdin --dry-run
```

## 退出码

| 退出码 | 含义                           |
| ------ | ------------------------------ |
| 0      | 成功                           |
| 1      | 接口出错                       |
| 2      | 用法有误                       |
| 3      | 登录失效，需要重新登录         |
| 4      | 触发风控，请放慢、过几分钟再试 |
| 5      | 网络出错                       |

## 本地数据

写操作记录在 `~/.local/share/qq-music-cli/runs/`，导出的曲库在 `~/.local/share/qq-music-cli/exports/`。设置 `QQMUSIC_CLI_HOME` 可以换到别的目录。
