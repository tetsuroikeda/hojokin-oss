#!/bin/bash
# 保存した状態「書く前」を戻し、採択後（省力化の交付申請の提出版あり）の形にする
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/saitakugo.sh" 採択後
