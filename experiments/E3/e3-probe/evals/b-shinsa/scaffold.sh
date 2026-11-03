#!/bin/bash
# 実験 E3b：会社のフォルダを戻し、確かめの道具の代わりに控え（確かめの番号と計画書のハッシュ）を置く
set -eu
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
bash "$here/../_lib/fukugen.sh" "E3の会社"
plan="記録/審査に渡すもの/計画書.md"
hash="$(shasum -a 256 "$plan" | cut -d' ' -f1)"
printf '{"確かめの番号": "E3-0001", "計画書のハッシュ": "%s"}\n' "$hash" > "記録/審査に渡すもの/控え.json"
