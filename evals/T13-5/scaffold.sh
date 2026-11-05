#!/bin/bash
# 保存した状態「書く前」を戻し、両方の採択後（省力化の差し戻し1 を不備の型として残した後。2027-06-14）の状態を作る
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/saitakugo.sh" 差し戻しの後
