#!/bin/bash
# 保存した状態「1件目の途中」（初稿と会社の記録に、わざと入れた誤り「スーパー14社」がある）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
