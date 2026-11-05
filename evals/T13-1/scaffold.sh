#!/bin/bash
# 保存した状態「取り込みの前」（会社の記録が空）を戻し、会社の資料と過去の申請の書類（架空。testdata/会社の資料/材料/ の11ファイル）を入れ口に入れる
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 取り込みの前
mkdir -p 入れ口
cp "$here/../../testdata/会社の資料/材料/"* 入れ口/
