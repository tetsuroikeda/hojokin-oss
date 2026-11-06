#!/bin/bash
# 保存した状態「1件目を終えた」（1件目で学んだことが会社の記録に残り、2件目の準備まで済んだ形）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目を終えた
