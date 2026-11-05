#!/bin/bash
# 保存した状態「書く前」を戻し、記録と違う従業員数の会社概要（架空）を入れ口に入れる
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
mkdir -p 入れ口
cp "$here/../../testdata/書類の変化/従業員数の食い違い/会社概要_2026年11月.docx" 入れ口/
