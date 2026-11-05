#!/bin/bash
# 保存した状態「質問の前」（省力化 第8回と持続化 第20回の公式資料の本文がある）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 質問の前
