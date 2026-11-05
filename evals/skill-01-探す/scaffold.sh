#!/bin/bash
# 保存した状態「探す前」（会社のフォルダを作っただけの形。案件・原本・会社の記録はまだない）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 探す前
