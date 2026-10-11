#!/usr/bin/env bash
# 为 OpenCode 安装（或更新）QQ Music skill，并安装 qqmusic CLI。
#
#   curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install-opencode.sh | bash
#
# OpenCode 的插件机制是代码模块，不用来装 skill，所以这里把仓库克隆到本地，
# 再把 skill 目录链接进 OpenCode 的 skills 目录。重复运行即更新。
# 设置 QQMUSIC_SKIP_CLI=1 可以不动 CLI。
set -euo pipefail

main() {
  local repo="${QQMUSIC_REPO:-jinhuang712/qq-music-cli}"
  local src="${XDG_DATA_HOME:-$HOME/.local/share}/qq-music-cli-plugin"
  local skills="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills"

  command -v opencode >/dev/null 2>&1 || die "没找到 opencode 命令，请先安装 OpenCode"
  command -v git >/dev/null 2>&1 || die "没找到 git 命令"

  if [ -d "${src}/.git" ]; then
    say "更新 ${src}"
    git -C "${src}" pull --ff-only --quiet </dev/null
  else
    say "下载到 ${src}"
    git clone --quiet --depth 1 "https://github.com/${repo}" "${src}" </dev/null
  fi

  mkdir -p "${skills}"
  ln -sfn "${src}/flat-skills/qq-music-cli" "${skills}/qq-music-cli"
  say "已链接 ${skills}/qq-music-cli"

  install_cli "${repo}"
  say "完成。新开一个 OpenCode 会话后，skill 显示为 qq-music-cli"
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
