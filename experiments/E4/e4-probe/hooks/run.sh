#!/bin/sh
# 実験 E4 の起動用スクリプト。python より前に、動いた環境を記録する
# （python が動かなくても記録が残るように。E5・S3 の run.sh の材料にする）
LOG_DIR="$HOME/.hojokin-e4"
mkdir -p "$LOG_DIR"
{
  printf '%s sh event=%s cwd=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" "$(pwd)"
  printf '  PATH=%s\n' "$PATH"
  printf '  python3=%s version=%s\n' "$(command -v python3)" "$(python3 --version 2>&1)"
  printf '  CLAUDE_PLUGIN_ROOT=%s\n' "$CLAUDE_PLUGIN_ROOT"
  printf '  CLAUDE_PLUGIN_DATA=%s\n' "$CLAUDE_PLUGIN_DATA"
  printf '  CLAUDE_PROJECT_DIR=%s\n' "$CLAUDE_PROJECT_DIR"
  printf '  CLAUDE_CODE_ENTRYPOINT=%s\n' "$CLAUDE_CODE_ENTRYPOINT"
} >> "$LOG_DIR/sh.log"
exec python3 "$(dirname "$0")/probe.py" "$1"
