"""根拠対照表.xlsx（計画書の本文の数字・固有名詞・日付と、その出典の対応表）を作り、読む
（SPEC 用語「根拠対照表」・F8「根拠は根拠対照表に残す」・共通の要件「作業の記録」、DESIGN 4.5・8章。TASKS M7）。

- 置き場所：`案件/<案件>/<段階>/申請書/根拠対照表.xlsx`。
- ツールが一から作る Excel なので、入力シート（lib/input_sheet.py）と同じく標準のライブラリで zip と XML を作る
  （同じ中身からは同じバイト列。版の履歴で、変わっていない回を見分けやすい）。
- 書いてよい範囲（DESIGN 1.1。このひな形で決める）：見出しの行より下の行。道具は行を足すか、置き換える。
  前からある行は、読み直してそのまま残す（社長が Excel で直した文字も残る）。
- 1行は「記述」（本文に書いた数字・固有名詞・日付など）、「種類」、「書いた場所」（様式の項目）、「出典」
  （書類とページ、社長の答えと日付、会社の記録の項目、財務モデルの前提の番号など）。出典が空の行は
  「根拠のない記述」として、確かめ（lib/kakunin.py）が数える。
  本文と表の突き合わせ（根拠なし0・食い違い0・本文に出典の書き込み0。T9-1）は、後のタスクで足す。

ひな形の列（M7 の仮の形）
  番号｜記述｜種類｜書いた場所｜出典

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence

from lib import input_sheet
from lib.docx_min import FIXED_ZIP_TIME, clean_text

FILE_NAME = "根拠対照表.xlsx"
SHEET_NAME = "根拠対照表"
TITLE = "根拠対照表（計画書の本文の数字・固有名詞・日付と、その出典）"
COLUMNS = (("番号", 8), ("記述", 44), ("種類", 10), ("書いた場所", 26), ("出典", 56))
KEYS = ("記述", "種類", "書いた場所", "出典")
KINDS = ("数字", "固有名詞", "日付", "そのほか")
HEADER_ROW = 2
MAX_ROWS = 2000


class EvidenceError(ValueError):
    """根拠対照表の行が正しくない、または表が読めない。"""


def _workbook() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="{input_sheet.S}" xmlns:r="{input_sheet.R}"><bookViews><workbookView/></bookViews>'
        f'<sheets><sheet name="{SHEET_NAME}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )


def _sheet_xml(rows: Sequence[Dict[str, str]]) -> str:
    cell = input_sheet._inline
    letter = input_sheet.col_letter
    out = [f'<row r="1">{cell("A1", input_sheet.ST_TITLE, TITLE)}</row>']
    head = "".join(cell(f"{letter(i)}{HEADER_ROW}", input_sheet.ST_HEAD, name) for i, (name, _w) in enumerate(COLUMNS, 1))
    out.append(f'<row r="{HEADER_ROW}">{head}</row>')
    for n, row in enumerate(rows, 1):
        r = HEADER_ROW + n
        cells = [input_sheet._number(f"A{r}", input_sheet.ST_TEXT, n)]
        for i, key in enumerate(KEYS, 2):
            style = input_sheet.ST_TOOL if key == "出典" and not row.get(key) else input_sheet.ST_TEXT
            cells.append(cell(f"{letter(i)}{r}", style, row.get(key, "")))
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, (_n, w) in enumerate(COLUMNS, 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{input_sheet.S}" xmlns:r="{input_sheet.R}">'
        '<sheetViews><sheetView workbookViewId="0">'
        f'<pane ySplit="{HEADER_ROW}" topLeftCell="A{HEADER_ROW + 1}" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        f"<cols>{cols}</cols>"
        f"<sheetData>{''.join(out)}</sheetData>"
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        "</worksheet>"
    )


def build(rows: Sequence[Dict[str, str]]) -> bytes:
    """行から、根拠対照表.xlsx のバイト列を作る（同じ中身からは同じバイト列）。"""
    parts = [
        ("[Content_Types].xml", input_sheet.CONTENT_TYPES),
        ("_rels/.rels", input_sheet.ROOT_RELS),
        ("xl/workbook.xml", _workbook()),
        ("xl/_rels/workbook.xml.rels", input_sheet.WORKBOOK_RELS),
        ("xl/styles.xml", input_sheet.STYLES),
        ("xl/worksheets/sheet1.xml", _sheet_xml(rows)),
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts:
            data = text.encode("utf-8")
            try:
                ET.fromstring(data)
            except ET.ParseError as e:  # 作り方の誤り。書く前に止める
                raise EvidenceError(f"根拠対照表の中身（{name}）を正しく作れませんでした（{e}）") from e
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return out.getvalue()


def read(blob: bytes) -> List[Dict[str, str]]:
    """根拠対照表.xlsx の行（見出しの行より下で、記述か出典のある行）。読めなければ EvidenceError。"""
    try:
        _parts, _name, grid = input_sheet.read_grid(blob)
    except ValueError as e:
        raise EvidenceError(f"根拠対照表を読めません（{e}）") from e
    head_row = None
    cols: Dict[str, str] = {}
    for r in sorted(grid.rows)[:20]:
        names = {}
        for ref, text in grid.texts.items():
            col, row = _split_ref(ref)
            if row == r and text.strip():
                names[text.strip()] = col
        if "記述" in names and "出典" in names:
            head_row, cols = r, names
            break
    if head_row is None:
        raise EvidenceError("根拠対照表に、見出しの行（「記述」「出典」）がありません")
    out = []
    for r in sorted(grid.rows):
        if r <= head_row:
            continue
        row = {key: grid.texts.get(f"{cols[key]}{r}", "").strip() if key in cols else "" for key in KEYS}
        if row["記述"] or row["出典"]:
            out.append(row)
    return out


def _split_ref(ref: str):
    m = input_sheet._REF.fullmatch(ref)
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def normalize_rows(data: Any) -> List[Dict[str, str]]:
    """道具に渡された行（{"行": [...]} か [...]）を確かめて、そろえる。正しくなければ EvidenceError。"""
    items = data.get("行") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise EvidenceError('行は {"行": [{"記述": "…", "種類": "数字", "書いた場所": "…", "出典": "…"}]} の形で渡してください')
    if len(items) > MAX_ROWS:
        raise EvidenceError(f"行が多すぎます（{len(items)}行。{MAX_ROWS}行まで）")
    out = []
    problems = []
    for k, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"{k}行目が {{ }} の形ではありません")
            continue
        unknown = [key for key in item if key not in KEYS and key != "番号"]
        if unknown:
            problems.append(f"{k}行目に、知らない欄があります（{'、'.join(map(str, unknown))}。使えるのは {'・'.join(KEYS)}）")
            continue
        row = {}
        for key in KEYS:
            value = item.get(key, "")
            if value is None:
                value = ""
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            if not isinstance(value, str):
                problems.append(f"{k}行目の「{key}」は文字で渡してください")
                break
            row[key] = clean_text(value).strip()
        else:
            if not row["記述"]:
                problems.append(f"{k}行目に「記述」（本文に書いた数字・固有名詞・日付など）がありません")
            elif row["種類"] and row["種類"] not in KINDS:
                problems.append(f"{k}行目の「種類」は {'・'.join(KINDS)} のどれかにしてください（いまは「{row['種類']}」）")
            else:
                out.append(row)
    if problems:
        raise EvidenceError("。".join(problems))
    return out


def merged(existing: Optional[Sequence[Dict[str, str]]], new: Sequence[Dict[str, str]], replace: bool) -> List[Dict[str, str]]:
    """前の行に足す（replace なら置き換える）。同じ記述・書いた場所の行は、新しい行で置き換える。"""
    base = [] if replace or not existing else [dict(r) for r in existing]
    for row in new:
        key = (row["記述"], row["書いた場所"])
        for i, old in enumerate(base):
            if (old["記述"], old["書いた場所"]) == key:
                base[i] = dict(row)
                break
        else:
            base.append(dict(row))
    return base


def unsupported(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """出典のない行（根拠のない記述）。"""
    return [r for r in rows if not r.get("出典", "").strip()]


def as_markdown(rows: Sequence[Dict[str, str]]) -> str:
    """審査役に渡す形（表の文字）。"""
    lines = ["| 番号 | 記述 | 種類 | 書いた場所 | 出典 |", "|---|---|---|---|---|"]
    for n, r in enumerate(rows, 1):
        cells = [str(n)] + [r.get(k, "").replace("|", "／").replace("\n", " ") or "（なし）" for k in KEYS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
