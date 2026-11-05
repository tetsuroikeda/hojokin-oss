#!/bin/bash
# 保存した状態「1件目の途中」（「書いた後」の初稿の一部を書き換えた版がある形）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
