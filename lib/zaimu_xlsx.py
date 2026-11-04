"""財務モデルの中身（lib/zaimu.py の Book）を Excel のファイルに書き、計算し直したファイルから値を読む（TASKS M5）。

- ツールが一から作る Excel なので、同梱の openpyxl で書いてよい（実験 E2b。公式の様式は openpyxl で保存しない）。
- 数式はそのまま書く。計算済みの値は持たせない（Excel と LibreOffice が開くときに計算する。openpyxl はブックに
  「開くときに計算し直す」の印を付ける）。そのため、LibreOffice で計算し直さないと値が空のままになり、
  計算し直しが本当に起きたかを、値が入ったかで確かめられる。

同梱の openpyxl を使うので、テストの Python の中では読み込まない（lib/vendor/ に __pycache__ ができるため）。
/usr/bin/python3 -B で動かす。
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any, Dict, Tuple

# 同梱の openpyxl を読み込む。社長のパソコンに別の版が入っていても同梱の版を使うよう、先頭に入れる
VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import openpyxl  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402

from lib import zaimu  # noqa: E402


def write(book: "zaimu.Book", path: Path) -> None:
    """ブックの中身を path に書く。"""
    wb = openpyxl.Workbook()
    first = True
    for sheet in book.sheets:
        if first:
            ws = wb.active
            ws.title = sheet.title
            first = False
        else:
            ws = wb.create_sheet(sheet.title)
        for ref, cell in sheet.cells.items():
            target = ws[ref]
            target.value = cell.formula if cell.formula is not None else cell.value
            if cell.fmt:
                target.number_format = cell.fmt
            if cell.fill:
                target.fill = PatternFill(fill_type="solid", start_color=cell.fill, end_color=cell.fill)
            if cell.bold:
                target.font = Font(bold=True)
        for col, width in sheet.widths.items():
            ws.column_dimensions[col].width = width
        ws.freeze_panes = None
    for name, (sheet_title, ref) in book.names.items():
        attr = f"{zaimu._quoted(sheet_title)}!{ref}"
        wb.defined_names[name] = DefinedName(name, attr_text=attr)
    wb.save(str(path))


def read_values(path: Path) -> Dict[Tuple[str, str], Any]:
    """計算済みの値（data_only）を、(シート, セル) ごとに読む。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(str(path), data_only=True)
    try:
        return {(ws.title, c.coordinate): c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row}
    finally:
        wb.close()


def read_formulas(path: Path) -> Dict[Tuple[str, str], Any]:
    """数式（と数式でない値）を、(シート, セル) ごとに読む。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(str(path), data_only=False)
    try:
        return {(ws.title, c.coordinate): c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row}
    finally:
        wb.close()


def read_names(path: Path) -> Dict[str, str]:
    """名前を付けたセル（名前 → 指す場所）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(str(path))
    try:
        return {name: dn.attr_text for name, dn in wb.defined_names.items()}
    finally:
        wb.close()
