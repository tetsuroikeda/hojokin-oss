#!/bin/bash
# 保存した状態「書く前」（省力化 第9回の準備と書類の整理まで済んだ形）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
