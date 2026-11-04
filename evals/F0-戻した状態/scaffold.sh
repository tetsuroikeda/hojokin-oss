#!/bin/bash
# 保存した状態「書く前」（省力化の前半を通した後のデモの会社）を戻す。公式資料は downloads/ から写す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
