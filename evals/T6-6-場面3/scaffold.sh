#!/bin/bash
# 保存した状態「書く前」を戻し、T6-6 の場面3 の始まり（2026-11-30。確認書を 11-18 に頼み、届いた確認書が入れ口にある）を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/irai_scene.sh" 場面3
