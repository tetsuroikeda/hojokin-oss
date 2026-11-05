#!/bin/bash
# 保存した状態「書いた後」（計画書に、機械を入れた後は2人・1日に延べ約14時間で回す見込みが書かれている）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後
