#!/bin/bash
# 実験 E3：段階ごとに保存した会社のフォルダを、今のフォルダ（eval の作業フォルダ）に戻す。
# 公式資料は保存した状態に入れず、リポの downloads/ から写す（DESIGN 11章）。
# 使い方：bash fukugen.sh <段階の名前>
set -eu
stage="$1"
mkdir -p .e3
log=.e3/scaffold.log
lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
evals="$(dirname "$lib")"
{
  echo "fukugen: \$0=$0 BASH_SOURCE=${BASH_SOURCE[0]} pwd=$(pwd)"
  echo "fukugen: lib=$lib"
  echo "--- env"
  env | sort
  echo "---"
} >> "$log"

# 保存した状態を写す（目印・会社の記録・.claude/ なども含めて）
cp -R "$evals/状態/$stage/." .

# downloads/ を、上へたどって探す
d="$lib"
root=""
while [ "$d" != "/" ]; do
  if [ -d "$d/downloads" ]; then root="$d"; break; fi
  d="$(dirname "$d")"
done
if [ -z "$root" ]; then
  echo "fukugen: downloads/ が見つからない" >> "$log"
  exit 1
fi
echo "fukugen: downloads=$root/downloads" >> "$log"

dest="案件/2026_省力化（一般型）第8回/公式資料"
mkdir -p "$dest"
cp "$root/downloads/shoryokuka_ippan/"*.pdf "$root/downloads/shoryokuka_ippan/"*.docx "$root/downloads/shoryokuka_ippan/"*.xlsx "$dest/"
ls -la "$dest" >> "$log"

# 版の履歴（製品では dulwich。ここでは git で試す）
git init -q
git add -A
git -c user.name=e3 -c user.email=e3@example.invalid commit -q -m "E3: 戻した状態"
git log --oneline >> "$log"
echo "fukugen: ok" >> "$log"
