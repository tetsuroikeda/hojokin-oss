#!/bin/bash
# 保存した状態「書く前」を戻し、ツールが書いた計画書を版に残して、社長が言い回しを1か所直した版に置き換える
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
py=/usr/bin/python3
if [ ! -x "$py" ]; then
  py="$(command -v python3)"
fi
"$py" -B "$here/../_lib/keikaku.py" tenaoshi
