#!/bin/bash
# 保存した状態「書いた後」（省力化の計画書が書けた形）を戻し、過去の申請の不採択の通知と、不採択の後の相談で受けた指摘のメモ
# （架空。testdata/会社の資料/材料/）を入れ口に入れる
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
mkdir -p 入れ口
cp "$here/../../testdata/会社の資料/材料/2025_ものづくり補助金_採択結果の通知.pdf" 入れ口/
cp "$here/../../testdata/会社の資料/材料/2025_ものづくり補助金_不採択の後の相談のメモ.docx" 入れ口/
