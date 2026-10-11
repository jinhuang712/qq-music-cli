#!/usr/bin/env bash
# 给本机装了的每个 agent（Claude Code、Codex、Pi、OpenCode）安装或更新 QQ Music 插件，
# 最后安装一次 qqmusic CLI。
#
#   curl -fsSL https://raw.githubusercontent.com/jinhuang712/qq-music-cli/master/install.sh | bash
#
# 只想装某一个 agent，用对应的 install-<agent>.sh。设置 QQMUSIC_SKIP_CLI=1 可以不动 CLI。
set -euo pipefail

main() {
  local repo="${QQMUSIC_REPO:-jinhuang712/qq-music-cli}"
  local raw="https://raw.githubusercontent.com/${repo}/${QQMUSIC_REF:-master}"
  local here=""
  # 从克隆的仓库里运行时用同目录的脚本；通过 curl | bash 运行时从 GitHub 拉取
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  fi

  local found=0 agent cmd
  for agent in claude codex pi opencode; do
    cmd="${agent}"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      continue
    fi
    found=1
    printf '\n## %s\n' "${agent}"
    if [ -n "${here}" ] && [ -f "${here}/install-${agent}.sh" ]; then
      QQMUSIC_SKIP_CLI=1 bash "${here}/install-${agent}.sh" </dev/null
    else
      curl -fsSL "${raw}/install-${agent}.sh" | QQMUSIC_SKIP_CLI=1 bash
    fi
  done

  if [ "${found}" = "0" ]; then
    die "没找到 claude、codex、pi、opencode 中的任何一个，请先安装其中一个 agent"
  fi

  printf '\n## qqmusic CLI\n'
  install_cli "${repo}"
  say "全部完成。新开 agent 会话后，就可以直接对它说「看看我的 QQ 音乐歌单」"
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
