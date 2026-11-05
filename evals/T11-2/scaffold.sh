#!/bin/bash
# 保存した状態「書いた後」（1件目の申請書ができた後。説明の練習の前）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
