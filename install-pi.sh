#!/usr/bin/env bash
# 为 Pi 安装（或更新）QQ Music 插件，并安装 qqmusic CLI。
#
#   curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-pi.sh | bash
#
# 重复运行即更新。设置 QQMUSIC_SKIP_CLI=1 可以不动 CLI。
set -euo pipefail

main() {
  local repo="${QQMUSIC_REPO:-jinhuang712/qq-music-cli}"
  local source="git:github.com/${repo}"

  command -v pi >/dev/null 2>&1 || die "没找到 pi 命令，请先安装 Pi"

  if pi list </dev/null 2>/dev/null | grep -q "github.com/${repo}"; then
    say "更新 Pi 包 ${source}"
    pi update "${source}" </dev/null
  else
    say "安装 Pi 包 ${source}"
    pi install "${source}" </dev/null
  fi

  install_cli "${repo}"
  say "完成。新开一个 Pi 会话（或在会话里运行 /reload）后，skill 显示为 qq-music-cli"
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
