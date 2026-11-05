#!/bin/bash
# 保存した状態「書く前」を戻し、T6-6 の場面1 の終わり（2026-11-16。確認書と見積書を台帳に足し、目安の日数はまだ）を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/irai_scene.sh" 場面1-答え
