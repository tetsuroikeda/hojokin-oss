#!/bin/bash
# 保存した状態「書類の前」（「書く前」から原本と書類の台帳を除いた形）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書類の前
