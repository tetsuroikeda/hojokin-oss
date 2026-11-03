#!/bin/sh
# 実験 E5 の4（その2）：Claude Code の中で、Python が動かないときにプラグインの hook が書き込みを止めるか。
# 使い方：sh hook_e2e.sh <作業用の一時フォルダ>
# このリポジトリを --plugin-dir で読み込み、一時フォルダの試しの会社で `claude -p` を3回流す（Haiku、1回 0.3 ドルまで）。
#   A：Python なし（PATH に python3 を置かない）
#   B：Python あり（/usr/bin/python3。比べるため）
#   C：Python が固まる（20秒待つだけの python3。PreToolUse の timeout は10秒）
# 利用者の設定（ほかのプラグインや hook）は読まない（--setting-sources project）。手元の環境は変えない。
set -u
work="${1:?作業用の一時フォルダを渡してください}"
here="$(cd "$(dirname "$0")" && pwd)"
plugin="$(cd "$here/../.." && pwd)"
CLAUDE="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROMPT='Write の道具で、このフォルダに「メモ.txt」を作り、中身を「試し」にしてください。Bash など、ほかの道具は使わないでください。拒まれたら、拒まれた理由の文をそのまま書いて終えてください。'

# Claude Code が使うことのある、Python と git 以外のコマンドだけを置いたフォルダ
base="$work/e2e/bin-base"
/bin/mkdir -p "$base"
for c in security env which uname sw_vers defaults; do /bin/ln -sf "/usr/bin/$c" "$base/$c"; done

run_case() {
  # $1 名前 $2 PATH の先頭に足すフォルダ（空なら足さない）
  name="$1"; extra="$2"
  folder="$work/e2e/$name/試しの会社"
  /bin/mkdir -p "$folder/.hojokin"
  path="$base:/bin:/usr/sbin:/sbin"
  [ -n "$extra" ] && path="$extra:$path"
  echo "## $name（PATH=$path）"
  start=$(/bin/date +%s)
  (cd "$folder" && /usr/bin/env -i HOME="$HOME" USER="${USER:-}" LOGNAME="${LOGNAME:-}" TMPDIR="${TMPDIR:-/tmp}" \
      LANG=ja_JP.UTF-8 PATH="$path" \
      "$CLAUDE" -p "$PROMPT" --plugin-dir "$plugin" --setting-sources project \
      --model haiku --max-budget-usd 0.3 --allowedTools Write --disallowedTools Bash \
      --output-format json > "$work/e2e/$name.json" 2> "$work/e2e/$name.err")
  echo "終了コード：$?、かかった秒数：$(( $(/bin/date +%s) - start ))"
  if [ -f "$folder/メモ.txt" ]; then echo "メモ.txt：作られた"; else echo "メモ.txt：作られていない"; fi
  /usr/bin/plutil -extract result raw -o - "$work/e2e/$name.json" 2>/dev/null | /usr/bin/head -c 600; echo
  /usr/bin/plutil -extract permission_denials json -o - "$work/e2e/$name.json" 2>/dev/null | /usr/bin/head -c 800; echo
  /usr/bin/plutil -extract total_cost_usd raw -o - "$work/e2e/$name.json" 2>/dev/null; echo
  /usr/bin/head -c 400 "$work/e2e/$name.err"
}

run_case A_Pythonなし ""

pybin="$work/e2e/bin-python"
/bin/mkdir -p "$pybin"
/bin/ln -sf /usr/bin/python3 "$pybin/python3"
run_case B_Pythonあり "$pybin"

hang="$work/e2e/bin-hang"
/bin/mkdir -p "$hang"
printf '#!/bin/sh\n/bin/sleep 20\n' > "$hang/python3"
/bin/chmod +x "$hang/python3"
run_case C_Pythonが固まる "$hang"
