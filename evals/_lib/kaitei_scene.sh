#!/bin/bash
# T7-1（改訂と新しい回）の場面の始まりを、eval の作業フォルダ（今いるフォルダ）に作る（TASKS B28）。
# 保存した状態「書く前」を戻し（fukugen.sh）、公募要領の後の版の資料の本文を置く（kaitei_setup.py）。
# 使い方（ケースの scaffold.sh から）：bash "$here/../_lib/kaitei_scene.sh" <変更あり|変更なし>
set -eu
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$lib/fukugen.sh" 書く前
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
exec "$py" -B "$lib/kaitei_setup.py" "$@"
