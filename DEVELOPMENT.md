# 开发与发布

## 本地开发

```sh
uv sync
uv run pytest -q                           # 离线测试，用 httpx.MockTransport 模拟所有服务器
uv run python scripts/sync_flat_skill.py   # 修改 skills/cli/ 之后运行，重新生成给 Pi 和 OpenCode 用的副本
```

想让本机的 `qqmusic` 直接用工作区里的代码：

```sh
uv tool install --editable .
```

用本地目录装的 Codex 插件会缓存一份副本，改完 skill 要重装才能看到：

```sh
codex plugin remove qq-music@qq-music
codex plugin add qq-music@qq-music
```

## 测试覆盖什么

测试全部离线运行，不会访问 QQ 音乐，也不会碰钥匙串。

- **接口层**：用模拟服务器覆盖请求的组装、错误映射，以及读写和撤销流程。
- **登录**：用抓到的真实「等待扫码」响应作为样本，把 QQ 和微信两条流程从头走到尾。
- **清单文件**：各清单里的名字、版本号、license 要一致；skill 的源头和副本要同步；每个渠道只能看到一个 skill。
- **安装脚本**：检查可执行权限和语法，并保证各脚本里安装 CLI 的那段函数完全相同。

## 代码风格

仓库里配置了 broom：ruff 负责 Python 的格式和检查，行宽 120；oxfmt 负责格式化 Markdown 和 JSON。

`docs/` 不参与格式化，因为格式化会把 Pages 页面里的代码块重排乱。

## 约定

需要长期记住的约定和结论，写进仓库：一般写在这份文档里，接口写进 HOW-IT-WORKS.md，使用上的经验写进 skill 的参考文档。不要只留在 agent 的 memory 里。

### 接口

- 不猜接口。新接口的 module、method 和参数，要么在 y.qq.com 网页的 JS 里找到原样的调用，要么在浏览器抓包里看到，然后用真实账号只读验证一次。验证过的接口记进 HOW-IT-WORKS.md 的接口表。
- 协议代码自己写。README 致谢里的项目只用来了解接口，不复制它们的代码。加协议相关的代码之前，先用 token 级的 k-gram 和这些项目比对一次，确认没有疑似重叠的片段。

### 实测

- 写操作只在临时歌单上实测，名字以 `qqm-` 开头。测完删掉，并确认歌单总数和测试前一样。要动账号里已有的歌单，先征得账号主人同意。
- 实测时不要运行 `qqmusic logout`，它会删掉钥匙串里真实的登录凭证。自动测试已经把钥匙串隔离开了。
- 文档里的结论按验证情况写：实际跑过的写「实测」，没跑过的写「未验证」，没检查过的写「推测」。

### 输出

- 输出是给 agent 读的，每个字节都会进上下文。列表类命令默认只输出常用字段，其余字段放进 `--fields` 让调用方自己要。
- 要多发请求的字段，只在 `--fields` 点名时才去查。
- 全量数据写成文件（`qqmusic export`），交给 `jq` 查询。
- 单个对象完整输出，包括简介，例如 `show` 的 `playlist` 和 `album` 的 `album`。

### 文档和 skill

- 面向人的内容只用中文：README、Pages、仓库描述、各清单里的描述。skill 也用中文。中文要写成母语的样子，不能有翻译腔。
- skill 只有一份源头，就是 `skills/cli/`。Pi 和 OpenCode 用的副本由 `scripts/sync_flat_skill.py` 生成。各渠道显示 skill 名字的规则不同，打包要按渠道分别处理，见 HOW-IT-WORKS.md 的「插件结构」。
- 插件的 `displayName` 设为 `QQ Music`，`.claude-plugin/plugin.json` 和 `.claude-plugin/marketplace.json` 各一处。不设的话，界面会把 `qq-music` 显示成「Qq Music」。

## 发布

1. **改版本号**：改了 skill 或 CLI，就把版本号同时改到这五个地方：
   - `pyproject.toml`
   - `src/qq_music_cli/__init__.py`
   - `.claude-plugin/plugin.json`
   - `plugin.json`
   - `package.json`

   测试会检查它们是否一致。Claude Code 和 Codex 按版本号缓存插件，版本号不变，用户重跑安装脚本也拿不到新内容。

2. **检查**：运行测试和 `claude plugin validate . --strict`。
3. **推送**：推送到 `master`。GitHub Pages 直接发布 `docs/` 目录，推送后自动更新。
