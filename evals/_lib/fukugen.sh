#!/bin/bash
# 保存した状態を、eval の作業フォルダ（今いるフォルダ）に戻す（TASKS M13）。中身は fukugen.py。
# 使い方（ケースの scaffold.sh から）：bash "$here/../_lib/fukugen.sh" <段階>
# hook と同じく、Mac に初めから入っている /usr/bin/python3（3.9）で動かす。なければ PATH の python3。
set -eu
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
exec "$py" -B "$lib/fukugen.py" "$@"
