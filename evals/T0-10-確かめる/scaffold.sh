#!/bin/bash
# 保存した状態「書く前」（1件目：省力化。制度データは第8回、資料の本文がある）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 書く前
