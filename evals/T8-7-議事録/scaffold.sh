#!/bin/bash
# 保存した状態「書く前」を戻し、社長が入れ口に議事録（架空）を入れた形にする
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
mkdir -p 入れ口
cp "$here/../../testdata/会社の資料/材料/議事録_2026-09-10_工場の会議.docx" 入れ口/
