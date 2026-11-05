#!/bin/bash
# 保存した状態「書く前」を戻し、T6-6 の場面4 の始まり（2026-11-30。1件目の確認書が届いた後。2件目の持続化の案件がある）を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/irai_scene.sh" 場面4
