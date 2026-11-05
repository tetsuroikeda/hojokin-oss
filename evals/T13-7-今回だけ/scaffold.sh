#!/bin/bash
# 保存した状態「1件目の途中」（初稿の本文は会社を「当社」と書いている）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
