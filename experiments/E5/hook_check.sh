#!/bin/sh
# 実験 E5 の4（その1）：Python が動かないとき、hook（S3 の hooks/run.sh）が書き込みを止めるか。
# 使い方：sh hook_check.sh <作業用の一時フォルダ>
# run.sh を env -i で、Claude Code と同じ形の入力を渡して動かす。手元の環境は変えない。
# 「開発ツールなし」は、DEVELOPER_DIR をない場所にして、/usr/bin/python3（xcrun の入口）を動かなくしたもの
# （CLT のない Mac では、同じ入口がインストールのダイアログを出す。ダイアログの動きは、ここでは再現しない）。
set -u
work="${1:?作業用の一時フォルダを渡してください}"
here="$(cd "$(dirname "$0")" && pwd)"
plugin="$(cd "$here/../.." && pwd)"
company="$work/hook/試しの会社"
plain="$work/hook/ふつうのフォルダ"
/bin/mkdir -p "$company/.hojokin" "$plain"

WRITE='{"session_id":"e5","cwd":"CWD","hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"CWD/計画書_v2.docx","content":"x"}}'
STOP='{"session_id":"e5","cwd":"CWD","hook_event_name":"Stop","stop_hook_active":false}'

try() {
  # $1 説明 $2 フォルダ $3 PATH $4 DEVELOPER_DIR（空なら付けない） $5 場面と役割 $6 入力
  label="$1"; folder="$2"; path="$3"; devdir="$4"; args="$5"; input="$6"
  if [ -n "$devdir" ]; then set -- DEVELOPER_DIR="$devdir"; else set --; fi
  out=$(printf '%s' "$input" | /usr/bin/env -i HOME="$work/home" PATH="$path" "$@" \
        CLAUDE_PROJECT_DIR="$folder" CLAUDE_PLUGIN_ROOT="$plugin" \
        /bin/sh -c "cd \"\$CLAUDE_PROJECT_DIR\" && sh \"\$CLAUDE_PLUGIN_ROOT/hooks/run.sh\" $args" 2>&1)
  printf '%s｜終了コード %s｜出力：%s\n' "$label" "$?" "${out:-（なし）}"
}

echo "## 目印のある会社のフォルダ"
try "Python なし（PATH=/bin）・Write" "$company" /bin "" "PreToolUse guard" "$WRITE"
try "Python なし（PATH=/bin）・Stop" "$company" /bin "" "Stop" "$STOP"
try "開発ツールなし・Write" "$company" /usr/bin:/bin /nonexistent-developer-dir "PreToolUse guard" "$WRITE"
try "開発ツールなし・Stop" "$company" /usr/bin:/bin /nonexistent-developer-dir "Stop" "$STOP"
try "Python あり（/usr/bin/python3）・Write" "$company" /usr/bin:/bin "" "PreToolUse guard" "$WRITE"

echo "## 目印のないフォルダ"
try "Python なし・Write" "$plain" /bin "" "PreToolUse guard" "$WRITE"
try "開発ツールなし・Write" "$plain" /usr/bin:/bin /nonexistent-developer-dir "PreToolUse guard" "$WRITE"
echo "## 書かれたもの（目印のないフォルダは空のまま）"
/bin/ls -A "$plain" "$company" "$company/.hojokin"
