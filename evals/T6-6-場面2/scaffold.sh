#!/bin/bash
# 保存した状態「書く前」を戻し、T6-6 の場面2 の始まり（2026-11-18。目安の日数と頼む人を残した後）を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/irai_scene.sh" 場面2
