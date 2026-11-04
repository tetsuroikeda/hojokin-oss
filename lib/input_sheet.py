"""入力シート.xlsx（申請画面と同じ項目名・順番・文字数の上限の表）を作り、決まった範囲の欄に値を書き、書く前と後を
比べる（SPEC F8「ツールが作る書類も、一度作った後は決まった範囲だけを書き換える」・F10、DESIGN 1.1「書いてよい範囲」・
4.5・5章。TASKS M6）。

- 作る（build）：制度データの「申請画面」の画面と欄から、1つのシート「入力シート」を作る。ツールが一から作る Excel
  なので、標準のライブラリで zip と XML を作る（同梱の openpyxl も使えるが、バイトが毎回同じになり、版の履歴で
  変わっていない回を見分けやすいので、こちらにした）。
- 書いてよい範囲（このひな形で決める。DESIGN 1.1）：見出しの行（「欄」「値」「担当者が入れる」の並ぶ行）より下で、
  欄の名前があり、「担当者が入れる」が「はい」でない行の、「値」の列のセル。範囲の中で変わってよいのは値だけで、
  セルの書式の番号（s）は変えない。範囲は、ファイルの中身（見出しの行と各行の文字）から決めるので、社長が Excel で
  開いて保存した後でも同じ物差しで比べられる。
- 書く（write_value）：様式と同じく、シートの XML のそのセルのバイトだけを差し替え、ほかはバイトのまま残す。文字は
  セルの中に直接書く（inlineStr。共有の文字の部品には触れない）。書いた後に直前の版と比べ、範囲の外が1か所でも
  変わっていれば保存しない（lib/yoshiki_word.OutsideChange）。

ひな形の列（M6 の仮の形。T10-1・T10-4（支援者の欄の案内）は M8 などで足す）
  画面の順番｜画面｜欄｜種類｜上限｜担当者が入れる｜値｜値の出どころ

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import difflib
import io
import posixpath
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape, quoteattr

from lib import xml_spans, yoshiki_word
from lib.docx_min import FIXED_ZIP_TIME, clean_text
from lib.xml_spans import Node
from lib.yoshiki_word import FormError, OutsideChange

FILE_NAME = "入力シート.xlsx"
SHEET_NAME = "入力シート"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

COLUMNS = (
    ("画面の順番", 10), ("画面", 24), ("欄", 36), ("種類", 8), ("上限", 18), ("担当者が入れる", 14), ("値", 50),
    ("値の出どころ", 36),
)
HEAD_FIELD, HEAD_VALUE, HEAD_STAFF, HEAD_SCREEN = "欄", "値", "担当者が入れる", "画面"
YES, NO = "はい", "いいえ"
HEADER_ROW = 2
NO_FIELDS = "この画面の欄は、まだ制度データにありません"
# セルの書式の番号（styles.xml の cellXfs の順）
ST_TITLE, ST_HEAD, ST_TEXT, ST_TOOL, ST_STAFF = 1, 2, 3, 4, 5
HARD_LIMITS = ("上限", "システムの上限")


# ---------------------------------------------------------------- 作る


def col_letter(index: int) -> str:
    """1 → A。"""
    out = ""
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _inline(ref: str, style: int, text: str) -> str:
    text = clean_text(text)
    if text == "":
        return f'<c r="{ref}" s="{style}"/>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _number(ref: str, style: int, value: Any) -> str:
    return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'


def limit_of(field: Dict) -> Optional[Tuple[str, int]]:
    """欄の上限（種類、文字数）。なければ None。"""
    limit = field.get("上限")
    value = limit.get("値") if isinstance(limit, dict) and "状態" in limit else limit
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return ("上限", value)
    if isinstance(value, dict) and isinstance(value.get("文字数"), int) and value.get("種類") != "なし":
        return (str(value.get("種類") or "上限"), value["文字数"])
    return None


def limit_text(field: Dict) -> str:
    limit = limit_of(field)
    if limit is None:
        return ""
    kind, chars = limit
    return f"{chars}字（{kind}）"


def _screens(seido: Dict) -> List[Dict]:
    screens = (seido.get("申請画面") or {}).get("画面") if isinstance(seido, dict) else None
    if not isinstance(screens, list):
        raise FormError("制度データに「申請画面」の「画面」の並びがありません")
    return sorted((s for s in screens if isinstance(s, dict)), key=lambda s: s.get("順番") or 0)


def fields_of(seido: Dict) -> List[Tuple[Dict, Dict]]:
    """（画面、欄）の並び。"""
    return [(s, f) for s in _screens(seido) for f in (s.get("欄") or []) if isinstance(f, dict)]


def _title(seido: Dict) -> str:
    sd = seido.get("制度") or {}
    name = str(sd.get("名前") or "")
    frame = f"（{sd['枠']}）" if sd.get("枠") else ""
    return (f"入力シート：{name}{frame} {sd.get('公募回') or ''}".strip()
            + "（申請画面と同じ順に並べています。黄色の「値」はツールが入れ、灰色の「値」は担当者が画面で入れます）")


def sheet_xml(seido: Dict) -> str:
    rows = [f'<row r="1">{_inline("A1", ST_TITLE, _title(seido))}</row>']
    head = "".join(_inline(f"{col_letter(i)}{HEADER_ROW}", ST_HEAD, name) for i, (name, _w) in enumerate(COLUMNS, 1))
    rows.append(f'<row r="{HEADER_ROW}">{head}</row>')
    r = HEADER_ROW
    for screen in _screens(seido):
        fields = [f for f in (screen.get("欄") or []) if isinstance(f, dict)]
        order = screen.get("順番")
        name = str(screen.get("名前") or "")
        if not fields:
            r += 1
            cells = [_number(f"A{r}", ST_TEXT, int(order)) if isinstance(order, int) else _inline(f"A{r}", ST_TEXT, ""),
                     _inline(f"B{r}", ST_TEXT, name)]
            cells += [_inline(f"{col_letter(i)}{r}", ST_TEXT, "") for i in range(3, 8)]
            cells.append(_inline(f"H{r}", ST_TEXT, NO_FIELDS))
            rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            continue
        for field in fields:
            r += 1
            staff = field.get("担当者が入れる") is True
            cells = [
                _number(f"A{r}", ST_TEXT, int(order)) if isinstance(order, int) else _inline(f"A{r}", ST_TEXT, ""),
                _inline(f"B{r}", ST_TEXT, name),
                _inline(f"C{r}", ST_TEXT, str(field.get("名前") or "")),
                _inline(f"D{r}", ST_TEXT, str(field.get("種類") or "")),
                _inline(f"E{r}", ST_TEXT, limit_text(field)),
                _inline(f"F{r}", ST_TEXT, YES if staff else NO),
                _inline(f"G{r}", ST_STAFF if staff else ST_TOOL, ""),
                _inline(f"H{r}", ST_TEXT, str(field.get("値の出どころ") or "")),
            ]
            rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, (_n, w) in enumerate(COLUMNS, 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{S}" xmlns:r="{R}">'
        '<sheetViews><sheetView workbookViewId="0">'
        f'<pane ySplit="{HEADER_ROW}" topLeftCell="A{HEADER_ROW + 1}" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18"/>'
        f"<cols>{cols}</cols>"
        f"<sheetData>{''.join(rows)}</sheetData>"
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>'
        "</worksheet>"
    )


_FONT = '<sz val="11"/><name val="游ゴシック"/><family val="2"/><charset val="128"/>'
_BORDER = "".join(f'<{s} style="thin"><color auto="1"/></{s}>' for s in ("left", "right", "top", "bottom"))
_WRAP = '<alignment vertical="top" wrapText="1"/>'
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<styleSheet xmlns="{S}">'
    f'<fonts count="2"><font>{_FONT}</font><font><b/>{_FONT}</font></fonts>'
    '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>'
    "</fills>"
    f'<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border>{_BORDER}<diagonal/></border>'
    "</borders>"
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>'
    f'<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1">{_WRAP}</xf>'
    f'<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1">{_WRAP}</xf>'
    f'<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1">{_WRAP}</xf>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)
WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<workbook xmlns="{S}" xmlns:r="{R}"><bookViews><workbookView/></bookViews>'
    f'<sheets><sheet name="{SHEET_NAME}" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<Relationships xmlns="{PKG_REL}">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    "</Relationships>"
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<Relationships xmlns="{PKG_REL}">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)


def build(seido: Dict) -> bytes:
    """制度データの申請画面から、入力シート.xlsx のバイト列を作る（同じ中身からは同じバイト列）。"""
    parts = [
        ("[Content_Types].xml", CONTENT_TYPES),
        ("_rels/.rels", ROOT_RELS),
        ("xl/workbook.xml", WORKBOOK),
        ("xl/_rels/workbook.xml.rels", WORKBOOK_RELS),
        ("xl/styles.xml", STYLES),
        ("xl/worksheets/sheet1.xml", sheet_xml(seido)),
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts:
            data = text.encode("utf-8")
            try:
                ET.fromstring(data)
            except ET.ParseError as e:  # 作り方の誤り。書く前に止める
                raise FormError(f"入力シートの中身（{name}）を正しく作れませんでした（{e}）") from e
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return out.getvalue()


# ---------------------------------------------------------------- 読む


def _rel_target(base: str, target: str) -> str:
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def sheet_part(parts: Dict[str, bytes]) -> str:
    """1つ目のシートの部品の名前（xl/worksheets/sheet1.xml など）。"""
    try:
        rels = ET.fromstring(parts["_rels/.rels"])
        book = next(r.get("Target") for r in rels if r.get("Type", "").endswith("/officeDocument"))
        book = _rel_target("", book)
        wb = ET.fromstring(parts[book])
        sheet = wb.find(f"{{{S}}}sheets/{{{S}}}sheet")
        rid = sheet.get(f"{{{R}}}id")
        book_rels_name = posixpath.join(posixpath.dirname(book), "_rels", posixpath.basename(book) + ".rels")
        book_rels = ET.fromstring(parts[book_rels_name])
        target = next(r.get("Target") for r in book_rels if r.get("Id") == rid)
        return _rel_target(book, target)
    except (KeyError, StopIteration, AttributeError, ET.ParseError) as e:
        raise FormError(f"入力シートのシートが見つかりません（{e}）") from e


def _shared_strings(parts: Dict[str, bytes]) -> List[str]:
    name = next((n for n in parts if n.endswith("sharedStrings.xml")), None)
    if name is None:
        return []
    root = ET.fromstring(parts[name])
    out = []
    for si in root.findall(f"{{{S}}}si"):
        # ふりがな（rPh）の中の文字は数えない
        pieces = []
        for child in si:
            if child.tag == f"{{{S}}}t":
                pieces.append(child.text or "")
            elif child.tag == f"{{{S}}}r":
                t = child.find(f"{{{S}}}t")
                pieces.append((t.text or "") if t is not None else "")
        out.append("".join(pieces))
    return out


def _cell_text(cell: Node, shared: List[str]) -> str:
    kind = cell.attrs.get("t")
    if kind == "inlineStr":
        is_ = cell.find(S, "is")
        if is_ is None:
            return ""
        return "".join(n.text for n in is_.iter() if n.is_(S, "t") and not any(a.is_(S, "rPh") for a in n.ancestors()))
    v = cell.find(S, "v")
    text = v.text if v is not None else ""
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return ""
    return text


_REF = re.compile(r"([A-Z]+)([0-9]+)")


class Grid:
    """シートの行とセル（場所付き）。"""

    def __init__(self, data: bytes, shared: List[str]) -> None:
        self.data = data
        self.root = xml_spans.parse(data)
        if not self.root.is_(S, "worksheet"):
            raise FormError("入力シートのシートの形が違います")
        self.sheet_data = self.root.find(S, "sheetData")
        if self.sheet_data is None:
            raise FormError("入力シートに表（sheetData）がありません")
        self.rows: Dict[int, Node] = {}
        self.cells: Dict[str, Node] = {}
        self.texts: Dict[str, str] = {}
        for row in self.sheet_data.findall(S, "row"):
            try:
                self.rows[int(row.attrs.get("r", "0"))] = row
            except ValueError:
                continue
            for c in row.findall(S, "c"):
                ref = c.attrs.get("r", "")
                if _REF.fullmatch(ref):
                    self.cells[ref] = c
                    self.texts[ref] = _cell_text(c, shared)

    def header(self) -> Tuple[int, Dict[str, str]]:
        """見出しの行の番号と、見出しの名前 → 列。"""
        for r in sorted(self.rows)[:20]:
            names = {}
            for ref, text in self.texts.items():
                m = _REF.fullmatch(ref)
                if m and int(m.group(2)) == r and text.strip():
                    names[text.strip()] = m.group(1)
            if all(h in names for h in (HEAD_FIELD, HEAD_VALUE, HEAD_STAFF)):
                return r, names
        raise FormError("入力シートに、見出しの行（「欄」「値」「担当者が入れる」）がありません")

    def field_rows(self) -> List[Tuple[int, str, str, bool]]:
        """（行、画面、欄、担当者が入れるか）の並び。"""
        head, cols = self.header()
        out = []
        for r in sorted(self.rows):
            if r <= head:
                continue
            field = self.texts.get(f"{cols[HEAD_FIELD]}{r}", "").strip()
            if not field:
                continue
            screen = self.texts.get(f"{cols[HEAD_SCREEN]}{r}", "").strip() if HEAD_SCREEN in cols else ""
            staff = self.texts.get(f"{cols[HEAD_STAFF]}{r}", "").strip() == YES
            out.append((r, screen, field, staff))
        return out

    def range_refs(self) -> List[str]:
        """書いてよい範囲のセル（担当者が入れる欄でない行の、値の列）。"""
        _head, cols = self.header()
        return [f"{cols[HEAD_VALUE]}{r}" for r, _s, _f, staff in self.field_rows() if not staff]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def read_grid(blob: bytes) -> Tuple[Dict[str, bytes], str, Grid]:
    _infos, parts = yoshiki_word.read_parts(blob)
    name = sheet_part(parts)
    if name not in parts:
        raise FormError(f"入力シートのシートの部品（{name}）がありません")
    return parts, name, Grid(parts[name], _shared_strings(parts))


def value_of(blob: bytes, field: str, screen: Optional[str] = None) -> str:
    _parts, _name, grid = read_grid(blob)
    r = _find_row(grid, field, screen)
    _head, cols = grid.header()
    return grid.texts.get(f"{cols[HEAD_VALUE]}{r}", "")


# ---------------------------------------------------------------- 書く


def _find_row(grid: Grid, field: str, screen: Optional[str]) -> int:
    rows = [(r, s, f, staff) for r, s, f, staff in grid.field_rows()
            if _norm(f) == _norm(field) and (not screen or _norm(s) == _norm(screen))]
    if not rows:
        raise FormError(f"入力シートに欄「{field}」がありません")
    if len(rows) > 1:
        raise FormError(f"入力シートに欄「{field}」が{len(rows)}つあります。画面の名前も渡してください")
    return rows[0][0]


def _cell_bytes(prefix: str, ref: str, attrs: Dict[str, str], value: Any) -> bytes:
    name = f"{prefix}:c" if prefix else "c"
    keep = {k: v for k, v in attrs.items() if k not in ("r", "t")}
    head = f'<{name} r="{ref}"' + "".join(f" {k}={quoteattr(v)}" for k, v in keep.items())
    v_name = f"{prefix}:v" if prefix else "v"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{head}><{v_name}>{value!r}</{v_name}></{name}>".encode("utf-8")
    is_name, t_name = (f"{prefix}:is", f"{prefix}:t") if prefix else ("is", "t")
    text = escape(clean_text(str(value)))
    return (f'{head} t="inlineStr"><{is_name}><{t_name} xml:space="preserve">{text}</{t_name}></{is_name}></{name}>'
            .encode("utf-8"))


def parse_number(text: str) -> Any:
    raw = unicodedata.normalize("NFKC", str(text)).replace(",", "").strip()
    if re.fullmatch(r"-?[0-9]+", raw):
        return int(raw)
    if re.fullmatch(r"-?[0-9]+\.[0-9]+", raw):
        return float(raw)
    raise FormError(f"数字の欄に、数でない値（{text}）は書けません")


def write_value(blob: bytes, field: str, value: Any, screen: Optional[str] = None,
                limit: Optional[Tuple[str, int]] = None) -> Tuple[bytes, Dict]:
    """入力シート blob の欄 field の「値」に value を書いたファイルのバイト列と、書いたことの要約。

    担当者が入れる欄、上限（目安でないもの）を超える文字は書かない（FormError）。範囲の外が変われば OutsideChange。
    """
    parts, name, grid = read_grid(blob)
    r = _find_row(grid, field, screen)
    staff = next(s for row, _sc, _f, s in grid.field_rows() if row == r)
    if staff:
        raise FormError(f"欄「{field}」は、担当者が画面で入れる欄です。ツールは入れません")
    _head, cols = grid.header()
    ref = f"{cols[HEAD_VALUE]}{r}"
    note = ""
    if isinstance(value, str):
        chars = len(clean_text(value))
        if limit is not None and chars > limit[1]:
            if limit[0] in HARD_LIMITS:
                raise FormError(f"欄「{field}」の{limit[0]}は{limit[1]}字で、書こうとした値は{chars}字です。短くしてください")
            note = f"{limit[0]}の{limit[1]}字を超えています（{chars}字）"
    data = grid.data
    cell = grid.cells.get(ref)
    row = grid.rows[r]
    if cell is not None:
        new_data = xml_spans.splice(data, cell.start, cell.end, _cell_bytes(cell.prefix, ref, cell.attrs, value))
    else:
        new_cell = _cell_bytes(row.prefix, ref, {}, value)
        later = [c for c in row.findall(S, "c") if _REF.fullmatch(c.attrs.get("r", ""))
                 and col_index(_REF.fullmatch(c.attrs["r"]).group(1)) > col_index(cols[HEAD_VALUE])]
        if later:
            new_data = xml_spans.splice(data, later[0].start, later[0].start, new_cell)
        elif row.tag_end == row.end:  # <row r="5"/>
            start_tag = row.start_tag(data)
            opened = start_tag[:-2].rstrip() + b">"
            new_data = xml_spans.splice(data, row.start, row.end, opened + new_cell + f"</{row.name}>".encode("utf-8"))
        else:
            close = data.rfind(b"</", row.start, row.end)
            new_data = xml_spans.splice(data, close, close, new_cell)
    new_blob = yoshiki_word.rebuild_zip(blob, {name: new_data})
    differences = compare_xlsx(blob, new_blob)
    if differences:
        raise OutsideChange(differences)
    summary = {"欄": field, "セル": ref, "値": value}
    if note:
        summary["注意"] = note
    return new_blob, summary


# ---------------------------------------------------------------- 比べる


def _units(grid: Grid, masked: Sequence[str]) -> List[Tuple[str, bytes]]:
    out: List[Tuple[str, bytes]] = []
    data = grid.data
    for child in grid.root.children:
        if child is grid.sheet_data:
            out.append(("表（sheetData）の設定", str(sorted(child.attrs.items())).encode("utf-8")))
            for row in child.children:
                if not row.is_(S, "row"):
                    out.append((row.name, row.raw(data)))
                    continue
                out.append((f"{row.attrs.get('r', '?')}行目の設定", str(sorted(row.attrs.items())).encode("utf-8")))
                for c in row.children:
                    ref = c.attrs.get("r", "")
                    if c.is_(S, "c") and ref in masked:
                        continue
                    out.append((f"セル {ref or c.name}", c.raw(data)))
                out.append((f"{row.attrs.get('r', '?')}行目の終わり", b"</row>"))
        else:
            out.append((child.name, child.raw(data)))
    return out


def compare_xlsx(before: bytes, after: bytes) -> List[str]:
    """入力シートどうしを比べ、書いてよい範囲（値の列）の外の差の一覧を返す（0件なら空）。"""
    try:
        parts_b, name_b, grid_b = read_grid(before)
    except (FormError, xml_spans.SpanError) as e:
        return [f"直前の版を読めません（{e}）"]
    try:
        parts_a, name_a, grid_a = read_grid(after)
    except (FormError, xml_spans.SpanError) as e:
        return [f"書いた後のファイルを読めません（{e}）"]
    if name_a != name_b:
        return [f"シートの部品が変わりました（{name_b} → {name_a}）"]
    out = yoshiki_word.compare_parts(parts_b, parts_a, skip=(name_b,))
    if grid_b.root.attrs != grid_a.root.attrs:
        out.append("シートの根（名前空間の宣言など）が変わりました")
    masked = grid_b.range_refs()
    for ref in masked:
        cb, ca = grid_b.cells.get(ref), grid_a.cells.get(ref)
        sb = cb.attrs.get("s", "0") if cb is not None else "0"
        sa = ca.attrs.get("s", "0") if ca is not None else "0"
        if sb != sa:
            out.append(f"セル {ref} の書式が変わりました")
    units_b, units_a = _units(grid_b, masked), _units(grid_a, masked)
    sm =difflib.SequenceMatcher(a=[u[1] for u in units_b], b=[u[1] for u in units_a], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace":
            out.append(f"変わった：{'、'.join(u[0] for u in units_b[i1:i2][:3])}")
        elif op == "delete":
            out.append(f"なくなった：{'、'.join(u[0] for u in units_b[i1:i2][:3])}")
        else:
            out.append(f"増えた：{'、'.join(u[0] for u in units_a[j1:j2][:3])}")
    return out[:yoshiki_word.MAX_DIFFS]
