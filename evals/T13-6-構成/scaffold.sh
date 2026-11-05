#!/bin/bash
# 保存した状態「1件目の途中」（初稿の強みの段落に、病院・介護施設向けとスーパー向けの話が混ざっている）を戻す
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" 1件目の途中
