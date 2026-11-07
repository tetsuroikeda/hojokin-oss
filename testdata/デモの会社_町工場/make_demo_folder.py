"""デモの会社（みずなら精工）のフォルダを作る（TASKS D14、DESIGN 3章）。

社長が書類をあちこちに入れた形のフォルダを、指定した場所に作る。会社のフォルダの用意（目印・設定・版の履歴）は、
デモの最初の場面でツールが社長の了承を得て行うので、ここではしない（前からあったファイルは「社長」の版になる。DESIGN 4.7）。

使い方：
  /usr/bin/python3 -B testdata/デモの会社_町工場/make_demo_folder.py <作る先のフォルダ> [--requote]

- 作る先は、まだないか、空のフォルダにする。同期されるフォルダ（Google ドライブなど）は避ける（ツールが断るため）。
- 書類は、先に作るスクリプトで作っておく（書類/書類の一覧.md と 会社の資料/資料の一覧.md の作り方）。
- 入れるのは、正しい書類と、デモの不備の書類（期限切れの見積、「一式」の見積、名義の違い、交付決定前の注文書）。
- --requote：しらうめソフトの取り直した見積（積算の根拠があるもの）も入れる（不備を直した後の場面を作るとき）。
- 終了コード：0 作った、1 作れなかった（理由を標準エラーに書く）。標準のライブラリだけで動く。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE / "書類"
FLAWS = DOCS / "デモの不備"
MATERIALS = HERE / "会社の資料"

# (元のファイル, 作る先の中の場所)。名前は、社長が付けたばらばらの名前にする
LAYOUT = [
    (DOCS / "決算書_第36期.pdf", "入れ口/決算書 R7年度.pdf"),
    (DOCS / "決算書_第35期.pdf", "入れ口/決算書(前の期).pdf"),
    (DOCS / "履歴事項全部証明書.pdf", "入れ口/登記簿.pdf"),
    (DOCS / "納税証明書_その2.pdf", "入れ口/税務署でもらったもの.pdf"),
    (DOCS / "法人事業概況説明書_第36期.pdf", "入れ口/概況説明書.pdf"),
    (DOCS / "役員名簿.docx", "入れ口/役員名簿.docx"),
    (DOCS / "株主名簿.docx", "入れ口/株主.docx"),
    (DOCS / "労働者名簿.xlsx", "入れ口/名簿_202611.xlsx"),
    (DOCS / "見積依頼書.pdf", "メールの添付/見積依頼書_1015.pdf"),
    (DOCS / "要件の概要.pdf", "メールの添付/要件まとめ.pdf"),
    (DOCS / "見積書_かすみ野システム工房.pdf", "メールの添付/見積_かすみ野.pdf"),
    (FLAWS / "見積書_かすみ野システム工房_旧.pdf", "メールの添付/見積_かすみ野_春.pdf"),
    (FLAWS / "見積書_しらうめソフト_一式.pdf", "メールの添付/しらうめ見積.pdf"),
    (FLAWS / "注文書_試しの開発.pdf", "入れ口/注文書_かすみ野.pdf"),
    (MATERIALS / "会社案内.pdf", "入れ口/会社案内2026.pdf"),
    (MATERIALS / "議事録_2026-09-30_見積の困りごと.docx", "入れ口/議事録0930.docx"),
    (MATERIALS / "図面の例_ブラケット.pdf", "入れ口/図面サンプル.pdf"),
]
REQUOTE = (DOCS / "見積書_しらうめソフト.pdf", "メールの添付/しらうめ見積_取り直し.pdf")


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    target = Path(args[0]).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        print(f"作る先が空ではありません：{target}", file=sys.stderr)
        return 1
    layout = list(LAYOUT) + ([REQUOTE] if "--requote" in argv else [])
    missing = [str(src.relative_to(HERE)) for src, _ in layout if not src.is_file()]
    if missing:
        print("書類がまだありません（先に作るスクリプトを流してください）：" + "、".join(missing), file=sys.stderr)
        return 1
    for src, rel in layout:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    print(f"デモの会社のフォルダを作りました：{target}（書類 {len(layout)} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
