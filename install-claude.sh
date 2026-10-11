#!/usr/bin/env bash
# 为 Claude Code 安装（或更新）QQ Music 插件，并安装 qqmusic CLI。
#
#   curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-claude.sh | bash
#
# 重复运行即更新。设置 QQMUSIC_SKIP_CLI=1 可以不动 CLI。
set -euo pipefail

main() {
  local repo="${QQMUSIC_REPO:-jinhuang712/qq-music-cli}"
  local market="qq-music"
  local plugin="qq-music@qq-music"

  command -v claude >/dev/null 2>&1 || die "没找到 claude 命令，请先安装 Claude Code"

  if claude plugin marketplace list </dev/null 2>/dev/null | grep -q "❯ ${market}\$"; then
    say "更新插件市场 ${market}"
    claude plugin marketplace update "${market}" </dev/null
  else
    say "添加插件市场 ${repo}"
    claude plugin marketplace add "${repo}" </dev/null
  fi

  if claude plugin list </dev/null 2>/dev/null | grep -q "❯ ${plugin}\$"; then
    say "更新插件 ${plugin}"
    claude plugin update "${plugin}" </dev/null
  else
    say "安装插件 ${plugin}"
    claude plugin install "${plugin}" </dev/null
  fi

  install_cli "${repo}"
  say "完成。新开一个 Claude Code 会话（或在会话里运行 /reload-plugins）后，skill 显示为 qq-music:cli"
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
