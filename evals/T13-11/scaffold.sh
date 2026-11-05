#!/bin/bash
# 保存した状態「1件目の途中」（会社の記録に強みの事実がある）を戻し、社長が記録の強みを手で直した形にする（版には入れない）
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
"$py" -B "$here/../_lib/kiroku_tenaoshi.py"
