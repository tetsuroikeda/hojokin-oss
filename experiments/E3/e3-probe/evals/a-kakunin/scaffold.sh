#!/bin/bash
# 実験 E3a：保存した会社のフォルダを戻し、downloads/ の公式資料を写す
set -eu
mkdir -p .e3
echo "case scaffold: \$0=$0 BASH_SOURCE=${BASH_SOURCE[0]:-} pwd=$(pwd)" >> .e3/scaffold.log
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
echo "case scaffold: here=$here" >> .e3/scaffold.log
bash "$here/../_lib/fukugen.sh" "E3の会社"
