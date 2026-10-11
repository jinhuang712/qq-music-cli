# 安装、更新与卸载

## 用脚本安装

每个 agent 一个脚本，按你用的选，可以选多个。

**Claude Code**，装好后用 `/qq-music:cli` 加载：

```sh
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-claude.sh | bash
```

**Codex**，装好后用 `$qq-music:cli` 加载：

```sh
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-codex.sh | bash
```

**Pi**，装好后用 `/skill:qq-music-cli` 加载：

```sh
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-pi.sh | bash
```

**OpenCode**，装好后对 agent 说「加载 qq-music-cli skill」：

```sh
curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-opencode.sh | bash
```

skill 只在你手动加载时才会用上，agent 不会自己加载它。Claude Code 和 Codex 会在 skill 名前加上插件名，Pi 和 OpenCode 不会，所以几个 agent 里的名字不一样。各 agent 的设置见 [HOW-IT-WORKS.md](HOW-IT-WORKS.md)。

## 关于这些脚本

- **更新**：重复运行就是更新，插件和 CLI 都会更新到最新版。
- **uv**：安装 CLI 需要 [uv](https://docs.astral.sh/uv/)。没装 uv 时，脚本只装插件，并告诉你怎么装 uv；装好后再运行一次即可。
- **跳过 CLI**：不想动 CLI，就在命令前加 `QQMUSIC_SKIP_CLI=1`。
- **环境要求**：macOS，因为登录窗口和钥匙串都依赖 macOS。另外，Python 由 uv 负责，OpenCode 的安装还需要 git。
- **装到了哪里**：
  - CLI 由 `uv tool` 管理。
  - OpenCode 的 skill 会把仓库克隆到 `~/.local/share/qq-music-cli-plugin`，再链接到 `~/.config/opencode/skills/qq-music-cli`。
- **先看再装**：每个脚本只有几十行，都在仓库根目录。

## 不用脚本，手动安装

**Claude Code**：

```sh
claude plugin marketplace add jinhuang712/qq-music-cli
claude plugin install qq-music@qq-music
```

**Codex**：

```sh
codex plugin marketplace add jinhuang712/qq-music-cli
codex plugin add qq-music@qq-music
```

**Pi**：

```sh
pi install git:github.com/jinhuang712/qq-music-cli
```

**OpenCode**：

```sh
git clone https://github.com/jinhuang712/qq-music-cli ~/.local/share/qq-music-cli-plugin
ln -s ~/.local/share/qq-music-cli-plugin/flat-skills/qq-music-cli ~/.config/opencode/skills/qq-music-cli
```

**只装 CLI**：

```sh
uv tool install git+https://github.com/jinhuang712/qq-music-cli
```

## 卸载

```sh
# Claude Code
claude plugin uninstall qq-music@qq-music && claude plugin marketplace remove qq-music
# Codex
codex plugin remove qq-music@qq-music && codex plugin marketplace remove qq-music
# Pi
pi remove git:github.com/jinhuang712/qq-music-cli
# OpenCode
rm ~/.config/opencode/skills/qq-music-cli && rm -rf ~/.local/share/qq-music-cli-plugin
# CLI：先删掉钥匙串里的登录凭证，再卸载
qqmusic logout && uv tool uninstall qq-music-cli
```

写操作记录和导出的曲库放在 `~/.local/share/qq-music-cli/`。卸载不会删除这个目录，不需要的话可以手动删掉。
