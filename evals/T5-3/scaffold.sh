#!/bin/bash
# T5-3 の準備（中身は setup.py）。hook と同じく /usr/bin/python3（3.9）で動かす。なければ PATH の python3
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
exec "$py" -B "$here/setup.py"
