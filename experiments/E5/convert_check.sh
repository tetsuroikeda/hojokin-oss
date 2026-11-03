#!/bin/sh
# 実験 E5 の3：PDF への変換に使う LibreOffice か Word があるか。デスクトップアプリから見つけられるか。
# 使い方：sh convert_check.sh <作業用の一時フォルダ>（setup_check.sh で venv を作った後）
# 手元の LibreOffice の設定を変えないよう、LibreOffice の利用者の設定は一時フォルダに作る。
# Word で PDF にするには Word を外から操作する許可（オートメーション）が要り、許可の設定が変わるので、ここでは試さない。
set -u
work="${1:?作業用の一時フォルダを渡してください}"
VENV="$work/data/venv"
P="$work/bin:/bin:/usr/sbin:/sbin"

echo "## アプリの場所（決まった場所と Spotlight）"
for app in "/Applications/LibreOffice.app" "$HOME/Applications/LibreOffice.app" \
           "/Applications/Microsoft Word.app" "/Applications/Microsoft Excel.app" "/Applications/Pages.app"; do
  if [ -d "$app" ]; then
    printf '%s：あり（版 %s）\n' "$app" "$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$app/Contents/Info.plist" 2>/dev/null)"
  else
    printf '%s：なし\n' "$app"
  fi
done
for id in org.libreoffice.script com.microsoft.Word; do
  printf 'Spotlight（%s）：%s\n' "$id" "$(/usr/bin/mdfind "kMDItemCFBundleIdentifier == '$id'" | /usr/bin/tr '\n' ' ')"
done

echo "## 社長の Mac に近い PATH（Homebrew なし）で soffice の名前を引けるか"
/usr/bin/env -i PATH="$P" /bin/sh -c 'command -v soffice || echo "なし（アプリの中の場所を直接使う必要がある）"'

SOFFICE="/Applications/LibreOffice.app/Contents/MacOS/soffice"
[ -x "$SOFFICE" ] || { echo "LibreOffice がないので、変換は試さない"; exit 0; }

echo "## 試しの Word と Excel を作る"
/usr/bin/env -i HOME="$work/home" PATH="$P" "$VENV/bin/python3" -B "$(cd "$(dirname "$0")" && pwd)/make_docs.py" "$work/docs" || exit 1

/sbin/md5 "$work/docs"/* > "$work/docs.md5.before"

echo "## LibreOffice で PDF にする（Homebrew なしの PATH、利用者の設定は一時フォルダ）"
start=$(/bin/date +%s)
/usr/bin/env -i HOME="$work/home" PATH="$P" "$SOFFICE" --headless --norestore \
  "-env:UserInstallation=file://$work/lo-profile" \
  --convert-to pdf --outdir "$work/pdf" "$work/docs/試しの計画書.docx" "$work/docs/試しの経費.xlsx"
echo "終了コード：$?、かかった秒数：$(( $(/bin/date +%s) - start ))"
for f in "$work/pdf"/*.pdf; do
  pages=$(/usr/bin/grep -c -a '/Type */Page[^s]' "$f")
  printf '%s：%s バイト、ページの数 %s\n' "${f##*/}" "$(/usr/bin/wc -c < "$f" | /usr/bin/tr -d ' ')" "$pages"
done
echo "## 元の Word と Excel は変わらないか"
/sbin/md5 "$work/docs"/* | /usr/bin/diff "$work/docs.md5.before" - && echo "変わらない"
