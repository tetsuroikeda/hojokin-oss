#!/bin/sh
# hook の起動用（DESIGN 5章「補助プログラムが動かないときは止める」）。
# 使い方：sh run.sh <場面> [guard]
#   guard は、書き込み（Write・Edit・NotebookEdit）、Bash、ブラウザの道具を受け取る PreToolUse に付ける
#   （hooks.json の matcher で分ける）。会社のフォルダの外を読む道具の PreToolUse には付けない。
# - 会社のフォルダの目印（.hojokin/）がなければ、Python を動かさず、何も出さずに終える。
# - 目印があれば Python の hook（main.py）を動かし、終了コードが0のときだけ、その出力を返す。
# - Python を見張り、hook の時間切れ（hooks.json の timeout）より前に終わらなければ止める。
#   時間切れになると Claude Code は道具をそのまま通すため（実験 E5）、その前に止めて拒む。
# - Python が見つからない・動かない・途中で落ちた・時間内に終わらないときは、
#   guard の場面は拒み、開いたとき（SessionStart）は Python なしで決まった案内を渡す。ほかの場面は何もしない。
# PATH に何もなくても動くよう、外のコマンドは使わない（見張りの /bin/sleep だけは、決まった場所で呼ぶ）。

folder="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$folder/.hojokin" ] || exit 0

event="$1"
role="$2"
hooks_dir="${0%/*}"
[ "$hooks_dir" = "$0" ] && hooks_dir=.

# 見張りの秒数。hooks.json の timeout より短くする（tests/test_hooks_run.py で照らす）
case "$event" in
  SessionStart|UserPromptSubmit) limit=25 ;;  # timeout 30秒
  Stop) limit=55 ;;                           # timeout 60秒
  *) limit=8 ;;                               # PreToolUse・PostToolUse：timeout 10秒
esac
# テストのために短くだけできる（長くはできない。守りが弱まらないように）
case "${HOJOKIN_WATCH_SECONDS:-}" in
  ''|*[!0-9]*) ;;
  *) if [ "$HOJOKIN_WATCH_SECONDS" -ge 1 ] && [ "$HOJOKIN_WATCH_SECONDS" -lt "$limit" ]; then
       limit="$HOJOKIN_WATCH_SECONDS"
     fi ;;
esac

sleep_cmd=
if [ -x /bin/sleep ]; then
  sleep_cmd=/bin/sleep
elif command -v sleep >/dev/null 2>&1; then
  sleep_cmd=sleep
fi

status=127
if command -v python3 >/dev/null 2>&1; then
  if [ -n "$sleep_cmd" ]; then
    # 後ろで動かす道具は、標準入力が空になるので、元の標準入力（hook の入力）と標準エラーを控えて渡す
    exec 3<&0 4>&2
    output=$(
      # 終わった道具の知らせ（Killed など）を出さない。Python の標準エラーは控えた 4 に出す
      exec 2>/dev/null
      python3 -B "$hooks_dir/main.py" "$event" "$role" <&3 2>&4 3<&- 4>&- &
      py=$!
      # 見張り：秒数が過ぎたら Python を止める。出力の管につながないので、待たされない
      (
        trap 'kill "$s" 2>/dev/null; exit 0' TERM
        "$sleep_cmd" "$limit" &
        s=$!
        wait "$s"
        kill -9 "$py" 2>/dev/null
      ) </dev/null >/dev/null 3<&- 4>&- &
      watcher=$!
      wait "$py"
      code=$?
      kill "$watcher" 2>/dev/null
      exit "$code"
    )
    status=$?
    exec 3<&- 4>&-
  else
    # 見張りに使う道具がないとき（期間中は確かめない環境）は、見張らずに動かす
    output=$(python3 -B "$hooks_dir/main.py" "$event" "$role")
    status=$?
  fi
  if [ "$status" -eq 0 ]; then
    [ -n "$output" ] && printf '%s\n' "$output"
    exit 0
  fi
fi

# ここに来たら、Python が動かないか、時間内に終わらなかった。
# 残りの入力を読み捨てる（送る側が書けずに止まらないように）
while IFS= read -r _line; do :; done

prepare='Mac の「ターミナル」で xcode-select --install を実行し、出てきた画面に従って開発ツール（コマンドライン・デベロッパ・ツール）を入れてから、Claude を開き直す'
if [ "$status" -eq 137 ]; then
  # 見張りが止めた（kill -9 の終了コード）
  cause='補助プログラム（Python）が時間内に終わらなかったため'
  advice="社長に、補助プログラムが固まったことを伝えてください。もう一度試しても続くときは、Claude を開き直すよう案内してください。開き直しても続くときの準備は次のとおりです：${prepare}。"
else
  cause='補助プログラム（Python）が動かないため'
  advice="社長に、補助プログラムが動いていないことを伝え、次の準備を案内してください：${prepare}。"
fi

if [ "$role" = guard ]; then
  printf '%s\n' "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"${cause}、会社のフォルダでのファイルの書き込み、Bash、ブラウザの道具を止めました（hojokin プラグインの決まり）。${advice}\"}}"
elif [ "$event" = SessionStart ]; then
  printf '%s\n' "{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"【hojokin】${cause}、この会社のフォルダでは、ファイルの書き込み、Bash、ブラウザの道具を止めています（hojokin プラグインの決まり）。社長の最初の発言に答えるときに、まず次のことをしてください。${advice}\"}}"
fi
exit 0
