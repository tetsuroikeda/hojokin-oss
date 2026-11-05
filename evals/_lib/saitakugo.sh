#!/bin/bash
# 採択後の場面の始まりの状態を、eval の作業フォルダ（今いるフォルダ）に作る（TASKS B31c・B32）。
# 保存した状態「書く前」を戻し（fukugen.sh）、採択後の準備（saitakugo.py）をする。
# 使い方（ケースの scaffold.sh から）：bash "$here/../_lib/saitakugo.sh" <場面>（申請の後・採択後・差し戻しの後）
set -eu
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$lib/fukugen.sh" 書く前
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
exec "$py" -B "$lib/saitakugo.py" "$@"
