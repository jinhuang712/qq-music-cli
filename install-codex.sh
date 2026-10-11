#!/usr/bin/env bash
# 为 Codex 安装（或更新）QQ Music 插件，并安装 qqmusic CLI。
#
#   curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-codex.sh | bash
#
# 重复运行即更新。设置 QQMUSIC_SKIP_CLI=1 可以不动 CLI。
set -euo pipefail

main() {
  local repo="${QQMUSIC_REPO:-jinhuang712/qq-music-cli}"
  local market="qq-music"
  local plugin="qq-music@qq-music"

  command -v codex >/dev/null 2>&1 || die "没找到 codex 命令，请先安装 Codex CLI"

  if codex plugin marketplace list </dev/null 2>/dev/null | grep -q "^${market} "; then
    say "更新插件市场 ${market}"
    # 本地路径添加的市场没有可拉取的快照，这一步失败不影响后面的重装
    codex plugin marketplace upgrade "${market}" </dev/null || true
  else
    say "添加插件市场 ${repo}"
    codex plugin marketplace add "${repo}" </dev/null
  fi

  # Codex 会把插件复制进缓存，先卸载再装才能拿到最新内容
  if codex plugin list </dev/null 2>/dev/null | grep -Eq "^${plugin} +installed"; then
    say "更新插件 ${plugin}"
    codex plugin remove "${plugin}" </dev/null
  else
    say "安装插件 ${plugin}"
  fi
  codex plugin add "${plugin}" </dev/null

  install_cli "${repo}"
  say "完成。新开一个 Codex 会话后，skill 显示为 qq-music:cli"
}

say() { printf '==> %s\n' "$*"; }
warn() { printf '提示：%s\n' "$*" >&2; }
die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

install_cli() {
  if [ "${QQMUSIC_SKIP_CLI:-0}" = "1" ]; then
    say "跳过 qqmusic CLI（QQMUSIC_SKIP_CLI=1）"
    return
  fi
  if ! command -v uv >/dev/null 2>&1; then
    warn "没找到 uv，这次先不装 qqmusic CLI。装好 uv 后重新运行本脚本即可："
    warn "curl -LsSf https://astral.sh/uv/install.sh | sh"
    return
  fi
  say "安装 qqmusic CLI"
  uv tool install --force --quiet "git+https://github.com/$1" </dev/null
}

main "$@"
