#!/bin/bash
# 保存した状態「書いた後」（財務モデルと計画書の本文・根拠対照表まで作った形）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
