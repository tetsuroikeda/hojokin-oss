#!/bin/bash
# 保存した状態「書いた後」を、社長の答えが要る計画書（D9 の3）に差し替えて戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後 --plan 3_社長の答えが要る計画書
