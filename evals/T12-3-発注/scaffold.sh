#!/bin/bash
# 保存した状態「書く前」を戻し、採択後（2027-06-02。省力化は交付申請を出した後で、交付決定の前）の状態を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/saitakugo.sh" 採択後
