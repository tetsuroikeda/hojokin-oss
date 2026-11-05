#!/bin/bash
# 保存した状態「書いた後」を、食い違いを混ぜた計画書（D9 の2）に差し替えて戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書いた後 --plan 2_食い違いを混ぜた計画書
