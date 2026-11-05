#!/bin/bash
# 保存した状態「書いた後」（省力化の計画書・財務モデル・その3 ができた形。入力シートはまだない）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
