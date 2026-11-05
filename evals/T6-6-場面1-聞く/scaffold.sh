#!/bin/bash
# 保存した状態「書く前」を戻し、T6-6 の場面1 の始まり（2026-11-16。頼む書類はまだ台帳にない）を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/irai_scene.sh" 場面1-聞く
