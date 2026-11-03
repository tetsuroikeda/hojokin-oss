#!/bin/sh
# 実験 E3 の起動用スクリプト。python より前に、動いた環境を作業フォルダに記録する
# （eval の中では HOME が一時の場所になるので、記録は作業フォルダの .e3/ に置く）
dir="${CLAUDE_PROJECT_DIR:-$(pwd)}/.e3"
mkdir -p "$dir"
{
  printf '%s sh event=%s pwd=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" "$(pwd)"
  printf '  python3=%s version=%s\n' "$(command -v python3)" "$(python3 --version 2>&1)"
  printf '  HOME=%s\n' "$HOME"
  printf '  CLAUDE_PLUGIN_ROOT=%s\n' "$CLAUDE_PLUGIN_ROOT"
  printf '  CLAUDE_PLUGIN_DATA=%s\n' "$CLAUDE_PLUGIN_DATA"
  printf '  CLAUDE_PROJECT_DIR=%s\n' "$CLAUDE_PROJECT_DIR"
  printf '  CLAUDE_CODE_ENTRYPOINT=%s\n' "$CLAUDE_CODE_ENTRYPOINT"
  printf '  EVAL_E3_ANSWER=%s\n' "$EVAL_E3_ANSWER"
} >> "$dir/sh.log"
exec python3 "$(dirname "$0")/probe.py" "$1"
