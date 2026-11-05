#!/bin/bash
# 保存した状態「書く前」を戻し、計画書の版を3件（初稿・直し1・直し2）足す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
"$py" -B "$here/../_lib/keikaku.py" sanpan
