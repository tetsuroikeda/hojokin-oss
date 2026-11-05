#!/bin/bash
# 保存した状態「1件目の途中」（会社の記録と初稿に「台所」の言葉はない）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
