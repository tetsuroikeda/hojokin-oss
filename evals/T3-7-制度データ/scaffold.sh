#!/bin/bash
# 保存した状態「制度データの前」（第8回の公式資料と資料の本文はあるが、制度データはない）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 制度データの前
