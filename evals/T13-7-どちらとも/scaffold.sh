#!/bin/bash
# 保存した状態「1件目の途中」（初稿の本文の金額は千円か円で書いている）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
