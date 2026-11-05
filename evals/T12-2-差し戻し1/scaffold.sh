#!/bin/bash
# 保存した状態「書く前」を戻し、採択後（交付申請の提出版あり）に、差し戻し1 と取り直した見積書を入れ口に入れる
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/saitakugo.sh" 差し戻し1
