"""見るだけの Excel（今の状態.xlsx）を、標準のライブラリだけで書く（DESIGN 4.6。TASKS B27）。

- ツールが一から作る、見るだけの表なので、セルは文字か整数だけ（数式・入力規則・図形は使わない）。
  文字はセルに直接持たせる（inlineStr）。書式は、見出し（太字と灰色）・帯（青）・期限の印（赤）・今日（黄）の4つだけ。
- 同じ中身なら同じバイト列になる（zip の日時を固定する）。呼ぶ側が、中身が同じなら書き直さない形にできるようにするため。
- hook（開いたとき・応答の終わり）からも呼ぶので、同梱の openpyxl は読み込まない（読み込みに時間がかかるため）。
  /usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import io
import zipfile
from typing import List, Sequence, Tuple, Union
from xml.sax.saxutils import escape

PLAIN, HEAD, BAR, MARK, TODAY = 0, 1, 2, 3, 4  # 書式の番号（styles.xml の cellXfs の順）
Cell = Union[str, int, None, Tuple[Union[str, int, None], int]]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheets}
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3"><font><sz val="11"/><name val="Yu Gothic"/></font><font><b/><sz val="11"/><name val="Yu Gothic"/></font>
<font><b/><color rgb="FFCF222E"/><sz val="11"/><name val="Yu Gothic"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF6F8FA"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF9EC5FE"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF8C5"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment wrapText="1" vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment wrapText="1" vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1"/>
<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="1" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>
</styleSheet>"""


def column_name(index: int) -> str:
    """0 → A、25 → Z、26 → AA。"""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref: str, cell: Cell) -> str:
    value, style = cell if isinstance(cell, tuple) else (cell, PLAIN)
    attr = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{attr}/>' if style else ""
    if isinstance(value, int) and not isinstance(value, bool):
        return f'<c r="{ref}"{attr}><v>{value}</v></c>'
    text = escape(str(value)).replace("\r", "")
    return f'<c r="{ref}"{attr} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def sheet_xml(rows: Sequence[Sequence[Cell]], widths: Sequence[int] = ()) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths) if w)
    body = []
    for r, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{column_name(c)}{r}", cell) for c, cell in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>'
            + (f"<cols>{cols}</cols>" if cols else "") + f"<sheetData>{''.join(body)}</sheetData></worksheet>")


def book_bytes(sheets: List[Tuple[str, Sequence[Sequence[Cell]], Sequence[int]]]) -> bytes:
    """シート（名前・行・列の幅）の並びから、xlsx のバイト列を作る。"""
    names = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _r, _w) in enumerate(sheets, 1))
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"<sheets>{names}</sheets></workbook>")
    rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   f'worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    rels += (f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
             'relationships/styles" Target="styles.xml"/>')
    overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
                        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
    parts = [("[Content_Types].xml", CONTENT_TYPES.format(sheets=overrides)), ("_rels/.rels", ROOT_RELS),
             ("xl/workbook.xml", workbook),
             ("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
              f'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>'),
             ("xl/styles.xml", STYLES)]
    parts += [(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows, widths)) for i, (_n, rows, widths) in enumerate(sheets, 1)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()
