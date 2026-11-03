"""実験 E5 の3で PDF にする、試しの Word と Excel を作る（公式の様式は使わない）。

使い方：<venv の python3> make_docs.py <出力のフォルダ>
"""

import sys
from pathlib import Path

import docx
import openpyxl

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

d = docx.Document()
d.add_heading("試しの計画書", level=1)
for i in range(1, 4):
    d.add_heading(f"{i}. 試しの章", level=2)
    d.add_paragraph("これは実験 E5 の試しの文です。日本語の文字が PDF に正しく出るかを見ます。" * 8)
d.add_page_break()
d.add_paragraph("2ページ目")
d.save(str(out / "試しの計画書.docx"))

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "経費"
ws.append(["経費の区分", "金額（円）"])
ws.append(["機械装置", 3000000])
ws.append(["専門家経費", 200000])
ws.append(["合計", "=SUM(B2:B3)"])
wb.save(str(out / "試しの経費.xlsx"))
print("作った：", ", ".join(p.name for p in sorted(out.iterdir())))
