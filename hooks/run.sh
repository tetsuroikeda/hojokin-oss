#!/bin/sh
# hook の起動用（DESIGN 5章「補助プログラムが動かないときは止める」）。
# 使い方：sh run.sh <場面> [guard]
#   guard は、書き込みとブラウザの操作の道具だけを受け取る PreToolUse に付ける（hooks.json の matcher で分ける）。
# - 会社のフォルダの目印（.hojokin/）がなければ、Python を動かさず、何も出さずに終える。
# - 目印があれば Python の hook（main.py）を動かし、終了コードが0のときだけ、その出力を返す。
# - Python が見つからない・動かない・途中で落ちたときは、guard の場面だけ拒む。ほかの場面は何もしない。
# PATH に何もなくても動くよう、外のコマンド（dirname、cat など）は使わない。

folder="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$folder/.hojokin" ] || exit 0

event="$1"
role="$2"
hooks_dir="${0%/*}"
[ "$hooks_dir" = "$0" ] && hooks_dir=.

if command -v python3 >/dev/null 2>&1; then
  # -B：会社のフォルダで動くたびに __pycache__ を書かない
  if output=$(python3 -B "$hooks_dir/main.py" "$event" "$role"); then
    [ -n "$output" ] && printf '%s\n' "$output"
    exit 0
  fi
fi

# ここに来たら、Python が動かない。残りの入力を読み捨てる（送る側が書けずに止まらないように）
while IFS= read -r _line; do :; done

if [ "$role" = guard ]; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"補助プログラム（Python）が動かないため、会社のフォルダでのファイルの書き込みとブラウザの操作を止めました（hojokin プラグインの決まり）。社長に、補助プログラムが動いていないことを伝えてください。"}}'
fi
exit 0
