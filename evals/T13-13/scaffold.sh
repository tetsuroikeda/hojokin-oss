#!/bin/bash
# デモの会社の「1件目を終えた」を隣のフォルダに戻し、作業フォルダを別の会社の空の会社のフォルダにする
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
demo="$(dirname "$PWD")/やまぶき惣菜"
mkdir -p "$demo"
bash "$here/../_lib/fukugen.sh" 1件目を終えた "$demo"
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
"$py" -B "$here/../../skills/kiroku/scripts/init_company.py" --folder "$PWD"
