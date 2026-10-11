# qq-music-cli

让 AI 帮你打理 QQ 音乐歌单。`qqmusic` 是管理你自己 QQ 音乐账号的命令行工具，同时也是 Claude Code、Codex、Pi、OpenCode 的插件。

项目主页：<https://jinhuang712.github.io/qq-music-cli/>

> [!IMPORTANT]
> 非官方项目，与腾讯、QQ 音乐没有任何关联。它调用的是 y.qq.com 网页端未公开的接口，随时可能失效；请只用于你自己的账号，风险自负。本工具只管理歌单信息，不播放、不下载、也不解密任何音频。

## 能做什么

- 读取自建歌单、「我喜欢」、收藏的歌单和专辑，以及每首歌的专辑、时长、语种、流派
- 把「我喜欢」按语种、流派、心情整理成歌单，或者根据一句描述生成歌单
- 批量加歌、删歌，合并、拆分、去重歌单，每次改动都能先预演、事后撤销
- 导出整个曲库，给曲库做体检

## 快速开始

按你用的 agent 选一条运行，插件和 `qqmusic` 会一起装好，重复运行就是更新：

```sh
# Claude Code
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-claude.sh | bash
# Codex
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-codex.sh | bash
# Pi
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-pi.sh | bash
# OpenCode
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-opencode.sh | bash
```

手动安装、卸载和脚本细节见 [INSTALL.md](INSTALL.md)。

装好后新开一个会话，直接对 agent 说：

- 「看看我的曲库有什么问题」
- 「把我喜欢的歌按语种整理成歌单」
- 「做一个适合通勤的歌单，30 首左右」

agent 会弹出一个显示二维码的小窗口，用微信或 QQ 扫码即可。扫码是唯一需要你动手的步骤。

## 直接用命令行

```sh
qqmusic login --wechat              # 扫码登录
qqmusic playlists                   # 我的歌单
qqmusic show liked                  # 「我喜欢」里的歌
qqmusic search "晴天 周杰伦"          # 搜索
qqmusic add "通勤" 97773 --dry-run   # 先预演，再去掉 --dry-run 真正加歌
qqmusic undo <run_id>               # 撤销某次改动
```

全部命令、参数和退出码见 [USAGE.md](USAGE.md)。

## 文档

- [INSTALL.md](INSTALL.md)：各 agent 的安装、更新和卸载
- [USAGE.md](USAGE.md)：命令参考
- [HOW-IT-WORKS.md](HOW-IT-WORKS.md)：原理和插件结构
- [DEVELOPMENT.md](DEVELOPMENT.md)：开发与发布

## 参考过的项目

- [L-1124/QQMusicApi](https://github.com/L-1124/QQMusicApi)
- [baoozak/qqmusic-mcp](https://github.com/baoozak/qqmusic-mcp)
- [tencentmusic/qqmusic-skills](https://github.com/tencentmusic/qqmusic-skills)

## License

[MIT](LICENSE)
