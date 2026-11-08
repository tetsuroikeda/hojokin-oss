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

import math  # noqa: E402
import unicodedata  # noqa: E402

import openpyxl  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402
from openpyxl.worksheet.page import PageMargins  # noqa: E402
from openpyxl.worksheet.properties import PageSetupProperties  # noqa: E402

from lib import zaimu  # noqa: E402

# 見た目（控えめにする。塗りの色は、見出しの灰色・入力の薄い黄色・仮の薄いオレンジの3つだけ。zaimu.FILL_*）
GRID = zaimu.LINE_GRID  # 表の罫線（細い、薄い灰色）
RULE = zaimu.LINE_RULE  # 合計・利益の行の上の線（細い、濃い灰色）
TITLE_SIZE = 13
LINE_HEIGHT = 15.5  # 折り返した行の1行の高さ（ポイント）
CHAR_PX = (7.0, 14.7)  # 1文字の幅の目安（半角, 全角。ピクセル）


def _side(color: str) -> Side:
    return Side(style="thin", color=color)


def _text_px(text: str) -> float:
    return sum(CHAR_PX[1] if unicodedata.east_asian_width(ch) in "WFA" else CHAR_PX[0] for ch in text)


def _lines(text: str, width: float) -> int:
    """列の幅（文字の数）の中で折り返したときの行の数（目安。少し多めに見る）。"""
    room = max(1.0, width * 7 + 5 - 8)  # 列の幅をピクセルにし、セルの左右の余白を除く
    return max(1, math.ceil(_text_px(text) * 1.05 / room))


def _style(ws, sheet: "zaimu.Sheet") -> None:
    """罫線・見出しの塗り・太字・折り返し・見出しの固定・印刷の設定（値と数式は変えない）。"""
    head_fill = PatternFill(fill_type="solid", start_color=zaimu.FILL_HEAD, end_color=zaimu.FILL_HEAD)
    grid = Border(left=_side(GRID), right=_side(GRID), top=_side(GRID), bottom=_side(GRID))
    ruled = Border(left=_side(GRID), right=_side(GRID), top=_side(RULE), bottom=_side(GRID))
    wrap_cols = {zaimu.col_number(c) for c in sheet.wrap}
    for r, (kind, ncols) in sorted(sheet.layout().items()):
        if kind == zaimu.ROW_TITLE:
            ws.cell(row=r, column=1).font = Font(bold=True, size=TITLE_SIZE)
            continue
        if kind == zaimu.ROW_SECTION:
            continue
        lines = 1
        for c in range(1, ncols + 1):
            target = ws.cell(row=r, column=c)
            if kind == zaimu.ROW_HEAD:
                target.fill = head_fill
                target.border = grid
                target.font = Font(bold=True)
                target.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                continue
            target.border = ruled if kind == zaimu.ROW_TOTAL else grid
            if kind == zaimu.ROW_TOTAL:
                target.font = Font(bold=True)
            own = sheet.cells.get(f"{zaimu.col_name(c)}{r}")
            wrap = ((c in wrap_cols or (own is not None and own.wrap)) and isinstance(target.value, str)
                    and not target.value.startswith("="))
            target.alignment = Alignment(vertical="top", wrap_text=wrap)
            if wrap:
                width = sheet.widths.get(zaimu.col_name(c), 8.43)
                lines = max(lines, _lines(target.value, width))
        if lines > 1:
            ws.row_dimensions[r].height = LINE_HEIGHT * lines + 2
    ws.freeze_panes = sheet.freeze
    ws.sheet_view.showGridLines = False  # 表には罫線を引くので、画面の目盛りの線は消す
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1  # 1ページの幅に収める（縦は何ページでもよい）
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5, header=0.3, footer=0.3)
    ws.oddFooter.center.text = "&A　&P / &N"
    if sheet.print_rows:
        ws.print_title_rows = sheet.print_rows


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
        _style(ws, sheet)
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
