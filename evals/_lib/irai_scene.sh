#!/bin/bash
# T6-6（依頼と待ち）の場面の始まりの状態を、eval の作業フォルダ（今いるフォルダ）に作る（TASKS K2）。
# 保存した状態「書く前」を戻し（fukugen.sh）、場面の準備（irai_setup.py）をする。
# 使い方（ケースの scaffold.sh から）：bash "$here/../_lib/irai_scene.sh" <場面>
set -eu
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$lib/fukugen.sh" 書く前
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
exec "$py" -B "$lib/irai_setup.py" "$@"
