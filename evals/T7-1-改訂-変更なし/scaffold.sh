#!/bin/bash
# 保存した状態「書く前」を戻し、公募要領の後の版（変更なし。前の版と同じ文字）の資料の本文を置く
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/kaitei_scene.sh" 変更なし
