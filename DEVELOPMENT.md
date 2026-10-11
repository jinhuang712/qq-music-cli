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

## 测试覆盖什么

测试全部离线运行，不会访问 QQ 音乐，也不会碰钥匙串。

- **接口层**：用模拟服务器覆盖请求的组装、错误映射，以及读写和撤销流程。
- **登录**：用抓到的真实「等待扫码」响应作为样本，把 QQ 和微信两条流程从头走到尾。
- **清单文件**：各清单里的名字、版本号、license 要一致；skill 的源头和副本要同步；每个渠道只能看到一个 skill。
- **安装脚本**：检查可执行权限和语法，并保证各脚本里安装 CLI 的那段函数完全相同。

## 代码风格

仓库里配置了 broom：ruff 负责 Python 的格式和检查，行宽 120；oxfmt 负责格式化 Markdown 和 JSON。

`docs/` 不参与格式化，因为格式化会把 Pages 页面里的代码块重排乱。

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
