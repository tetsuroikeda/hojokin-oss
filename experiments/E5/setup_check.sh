#!/bin/sh
# 実験 E5 の1：uv と git が PATH にない環境で、補助プログラム（Python のライブラリ）を準備できるか。
# 使い方：sh setup_check.sh <作業用の一時フォルダ>
# 手元の環境は変えない。HOME もプラグインのデータの置き場も、一時フォルダの中に作る。
# PATH は、python3 だけを置いたフォルダと /bin・/usr/sbin・/sbin にする
# （/usr/bin には git が、Homebrew と ~/.local/bin には git・uv がある）。
set -u
work="${1:?作業用の一時フォルダを渡してください}"
mkdir -p "$work/bin" "$work/home" "$work/data"
ln -sf /usr/bin/python3 "$work/bin/python3"
P="$work/bin:/bin:/usr/sbin:/sbin"
VENV="$work/data/venv"
run() { /usr/bin/env -i HOME="$work/home" PATH="$P" "$@"; }

echo "## PATH で見つかるもの"
run /bin/sh -c 'for c in python3 git uv pip3 soffice; do printf "%s: %s\n" "$c" "$(command -v "$c" || echo なし)"; done'

echo "## Python"
run python3 -c 'import sys, ssl; print(sys.executable, sys.version.split()[0], ssl.OPENSSL_VERSION)'

echo "## venv を作る（プラグインのデータの置き場に作る想定）"
start=$(/bin/date +%s)
run python3 -m venv "$VENV" || exit 1
echo "かかった秒数：$(( $(/bin/date +%s) - start ))"
/bin/ls -l "$VENV/bin/python3"

echo "## ライブラリを入れる（dulwich・python-docx・openpyxl）"
start=$(/bin/date +%s)
run "$VENV/bin/python3" -m pip install --disable-pip-version-check -q dulwich python-docx openpyxl || exit 1
echo "かかった秒数：$(( $(/bin/date +%s) - start ))"
run "$VENV/bin/python3" -m pip list --disable-pip-version-check --format=freeze

echo "## 入ったものを読み込めるか"
run "$VENV/bin/python3" -c 'import dulwich, docx, openpyxl; print("dulwich", dulwich.__version__, "openpyxl", openpyxl.__version__)'
echo "## dulwich の速くする拡張（なくても動く）"
run "$VENV/bin/python3" -c 'import importlib.util as u; print({m: bool(u.find_spec(m)) for m in ("dulwich._objects", "dulwich._diff_tree", "dulwich._pack")})'

echo "## 大きさ"
/usr/bin/du -sh "$VENV"
