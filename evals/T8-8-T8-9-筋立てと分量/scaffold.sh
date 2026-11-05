#!/bin/bash
# 保存した状態「書いた後」（全項目が書けた計画書）を戻す。公式資料は downloads/ から写す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
