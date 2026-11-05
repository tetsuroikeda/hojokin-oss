"""Excel の様式（省力化の事業計画書 その3 と別紙1〜4 など）の一覧づくり・書き込み・書き込み前後の比べ
（SPEC F8「様式に書式を壊さずに書き込む」T8-1、DESIGN 1.1「書いてよい範囲」・5章・6章。TASKS B14b）。

- 書いてよい範囲：保護したシートの、ロックを外したセル（様式が入力の欄として開けているセル）。様式のファイルの
  中身から決めるので、制度データにセルを書き写さなくても、社長が Excel で開いて保存した後でも同じ物差しで比べられる。
  数式のセル、結合したセルの左上でないセル、保護していないシート（参考の道具・選択肢のシートなど）には書かない。
- 書き込み（write_cells）：シートの XML の、そのセルの <c> のバイトだけを差し替え、ほかの部品はバイトのまま残す
  （openpyxl で保存すると、拡張の条件付き書式・入力規則の一覧・図形などが落ちた。実験 E2）。文字はセルの中に
  直接書く（inlineStr。共有の文字の部品には触れない）。セルの書式の番号（s）は変えない。
- 比べる（compare_xlsx）：直前の版と書いた後を、部品の XML どうしで比べる。書いてよい範囲のセルの <c> だけを除き、
  残りが1か所でも違えば差として返す（シートの構成、書式、余白、結合、数式、入力規則、ヘッダーとフッターは、
  シートの XML とほかの部品の比べに入る）。書く道具は、差があれば保存しない。応答の終わりの hook も同じ物差しで比べる。
- 様式を初めて写すとき（first_copy）だけ、ブックの計算の設定に「開いたときにすべて計算し直す」（fullCalcOnLoad）を
  付ける。書いたセルから計算する数式（省力化指数など）の古い値が、Excel で開いたときに残らないようにするため。

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import difflib
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from lib import input_sheet, xml_spans, yoshiki_word
from lib.docx_min import clean_text
from lib.input_sheet import Grid, S
from lib.yoshiki_word import FormError, OutsideChange

R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
BOOK = "xl/workbook.xml"
_REF = re.compile(r"^([A-Z]{1,3})([0-9]{1,7})$")
MAX_LABEL = 60


def _rel_target(base: str, target: str) -> str:
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def col_index(letters: str) -> int:
    return input_sheet.col_index(letters)


def split_ref(ref: str) -> Tuple[int, int]:
    m = _REF.match(ref)
    if not m:
        raise FormError(f"セルの場所「{ref}」が読めません（例：C6）")
    return col_index(m.group(1)), int(m.group(2))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


class SheetInfo:
    """1つのシート（名前、部品、表、保護、結合、書いてよいセル）。"""

    def __init__(self, name: str, part: str, data: bytes, shared: List[str], unlocked: Set[int]) -> None:
        self.name = name
        self.part = part
        self.grid = Grid(data, shared)
        self.protected = self.grid.root.find(S, "sheetProtection") is not None
        self.merges: List[Tuple[int, int, int, int]] = []
        merge_cells = self.grid.root.find(S, "mergeCells")
        for m in (merge_cells.findall(S, "mergeCell") if merge_cells is not None else []):
            ref = m.attrs.get("ref", "")
            if ":" in ref:
                a, b = ref.split(":", 1)
                (c1, r1), (c2, r2) = split_ref(a), split_ref(b)
                self.merges.append((c1, r1, c2, r2))
        self.inputs: Set[str] = set()
        self.formulas: Set[str] = set()
        for ref, cell in self.grid.cells.items():
            if cell.find(S, "f") is not None:
                self.formulas.add(ref)
                continue
            if not self.protected:
                continue
            try:
                style = int(cell.attrs.get("s", "0"))
            except ValueError:
                continue
            if style in unlocked and self._merge_ok(ref):
                self.inputs.add(ref)

    def _merge_ok(self, ref: str) -> bool:
        c, r = split_ref(ref)
        for c1, r1, c2, r2 in self.merges:
            if c1 <= c <= c2 and r1 <= r <= r2:
                return (c, r) == (c1, r1)
        return True

    def why_not(self, ref: str) -> Optional[str]:
        """そのセルに書けない理由。書けるなら None。"""
        if not self.protected:
            return f"シート「{self.name}」は入力のシートではありません（保護していない参考や選択肢のシート）"
        if ref in self.formulas:
            return f"{self.name}!{ref} は数式のセルです（ほかのセルから計算される）"
        if ref not in self.grid.cells:
            return f"{self.name}!{ref} は様式の入力の欄ではありません"
        if not self._merge_ok(ref):
            return f"{self.name}!{ref} は結合したセルの左上ではありません（結合の左上のセルに書く）"
        if ref not in self.inputs:
            return f"{self.name}!{ref} は様式の入力の欄ではありません（ロックしたセル）"
        return None


class Book:
    def __init__(self, blob: bytes) -> None:
        _infos, self.parts = yoshiki_word.read_parts(blob)
        if BOOK not in self.parts:
            raise FormError("Excel のブックの部品（xl/workbook.xml）がありません")
        shared = input_sheet._shared_strings(self.parts)
        unlocked = unlocked_styles(self.parts)
        self.sheets: List[SheetInfo] = []
        for name, part in sheet_parts(self.parts):
            if part in self.parts:
                try:
                    self.sheets.append(SheetInfo(name, part, self.parts[part], shared, unlocked))
                except (FormError, xml_spans.SpanError):
                    continue  # グラフのシートなど、表でないもの

    def sheet(self, name: str) -> SheetInfo:
        hits = [s for s in self.sheets if s.name == name] or [s for s in self.sheets if _norm(s.name) == _norm(name)]
        if not hits:
            names = "、".join(s.name for s in self.sheets if s.protected)
            raise FormError(f"シート「{name}」がありません（入力のシート：{names}）")
        return hits[0]

    def masks(self) -> Dict[str, Set[str]]:
        return {s.part: set(s.inputs) for s in self.sheets}


def sheet_parts(parts: Dict[str, bytes]) -> List[Tuple[str, str]]:
    """（シートの名前、部品の名前）の並び。"""
    try:
        wb = ET.fromstring(parts[BOOK])
        rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    except (KeyError, ET.ParseError) as e:
        raise FormError(f"Excel のブックを読めません（{e}）") from e
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    sheets = wb.find(f"{{{S}}}sheets")
    for sh in list(sheets) if sheets is not None else []:
        t = target.get(sh.get(f"{{{R}}}id"))
        if t:
            out.append((sh.get("name") or "", _rel_target(BOOK, t)))
    return out


def unlocked_styles(parts: Dict[str, bytes]) -> Set[int]:
    """セルの書式（cellXfs）のうち、ロックを外したものの番号。"""
    try:
        styles = ET.fromstring(parts["xl/styles.xml"])
    except (KeyError, ET.ParseError):
        return set()
    xfs = styles.find(f"{{{S}}}cellXfs")
    out = set()
    for i, xf in enumerate(list(xfs) if xfs is not None else []):
        p = xf.find(f"{{{S}}}protection")
        if p is not None and p.get("locked") in ("0", "false"):
            out.add(i)
    return out


# ---------------------------------------------------------------- 一覧


def outline(blob: bytes) -> List[Dict[str, Any]]:
    """入力のシートごとに、見出しの文字と、書いてよいセル（行の見出しと今の値つき）を並べる。"""
    book = Book(blob)
    out = []
    for sh in book.sheets:
        if not sh.protected or not sh.inputs:
            continue
        labels = []
        by_row: Dict[int, List[Tuple[int, str]]] = {}
        for ref, text in sh.grid.texts.items():
            if ref in sh.inputs or ref in sh.formulas or not text.strip():
                continue
            c, r = split_ref(ref)
            by_row.setdefault(r, []).append((c, text.strip()))
            labels.append({"セル": ref, "文字": _short(text)})
        inputs = []
        for ref in sorted(sh.inputs, key=lambda x: (split_ref(x)[1], split_ref(x)[0])):
            c, r = split_ref(ref)
            left = [t for cc, t in sorted(by_row.get(r, [])) if cc < c]
            entry = {"セル": ref, "行の見出し": _short(left[-1]) if left else ""}
            now = sh.grid.texts.get(ref, "")
            if now.strip():
                entry["今の値"] = _short(now)
            inputs.append(entry)
        labels.sort(key=lambda e: (split_ref(e["セル"])[1], split_ref(e["セル"])[0]))
        out.append({"シート": sh.name, "見出し": labels, "書いてよいセル": inputs,
                    "数式のセル": len(sh.formulas)})
    return out


def _short(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= MAX_LABEL else one[:MAX_LABEL] + "…"


def outline_text(entries: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for e in entries:
        lines.append(f"## シート「{e['シート']}」（書いてよいセル {len(e['書いてよいセル'])}、数式のセル {e['数式のセル']}）")
        lines.append("見出し：")
        for lab in e["見出し"]:
            lines.append(f"  {lab['セル']}「{lab['文字']}」")
        lines.append("書いてよいセル（行の見出し）：")
        rows: Dict[int, List[str]] = {}
        heads: Dict[int, str] = {}
        for cell in e["書いてよいセル"]:
            r = split_ref(cell["セル"])[1]
            shown = cell["セル"] + (f"＝「{cell['今の値']}」" if cell.get("今の値") else "")
            rows.setdefault(r, []).append(shown)
            heads.setdefault(r, cell["行の見出し"])
        for r in sorted(rows):
            lines.append(f"  {r}行目「{heads[r]}」：" + " ".join(rows[r]))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 書く


def _value_kind(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        raise FormError("値は、文字か数にしてください（はい・いいえは「はい」「いいえ」の文字で）")
    if isinstance(value, (int, float)):
        return value
    text = clean_text(str(value))
    return text


def write_cells(blob: bytes, items: Sequence[Dict[str, Any]]) -> Tuple[bytes, Dict[str, Any]]:
    """items（{"シート", "セル", "値"} の並び）を書いたファイルのバイト列と要約。1件でも書けなければ FormError。

    書いた後に直前の版と比べ、書いてよい範囲の外が1か所でも変わっていれば OutsideChange（保存しない）。
    """
    if not items:
        raise FormError("書く値が1つもありません")
    book = Book(blob)
    problems = []
    plan: Dict[str, List[Tuple[str, Any]]] = {}
    seen = set()
    for k, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"{k}件目：形が違います")
            continue
        name, ref = str(item.get("シート") or ""), str(item.get("セル") or "").upper().replace("$", "")
        try:
            sh = book.sheet(name)
            split_ref(ref)
            why = sh.why_not(ref)
            if why:
                raise FormError(why)
            value = _value_kind(item.get("値"))
        except FormError as e:
            problems.append(f"{k}件目（{name}!{ref}）：{e}")
            continue
        if (sh.part, ref) in seen:
            problems.append(f"{k}件目（{name}!{ref}）：同じセルが2回あります")
            continue
        seen.add((sh.part, ref))
        plan.setdefault(sh.part, []).append((ref, value))
    if problems:
        raise FormError("書けない値があります：" + "／".join(problems[:20]))
    replacements = {}
    for part, cells in plan.items():
        sh = next(s for s in book.sheets if s.part == part)
        data = sh.grid.data
        for ref, value in sorted(cells, key=lambda x: sh.grid.cells[x[0]].start, reverse=True):
            cell = sh.grid.cells[ref]
            data = xml_spans.splice(data, cell.start, cell.end, input_sheet._cell_bytes(cell.prefix, ref, cell.attrs, value))
        replacements[part] = data
    new_blob = yoshiki_word.rebuild_zip(blob, replacements)
    differences = compare_xlsx(blob, new_blob)
    if differences:
        raise OutsideChange(differences)
    return new_blob, {"書いたセル": sum(len(v) for v in plan.values()),
                      "シート": [next(s.name for s in book.sheets if s.part == p) for p in plan]}


def cell_value(blob: bytes, sheet: str, ref: str) -> str:
    book = Book(blob)
    return book.sheet(sheet).grid.texts.get(ref.upper(), "")


def first_copy(blob: bytes) -> bytes:
    """公式資料の様式を初めて写すときに、ブックに「開いたときにすべて計算し直す」を付けたもの。"""
    _infos, parts = yoshiki_word.read_parts(blob)
    data = parts.get(BOOK)
    if data is None:
        raise FormError("Excel のブックの部品（xl/workbook.xml）がありません")
    root = xml_spans.parse(data)
    calc = root.find(S, "calcPr")
    if calc is None or "fullCalcOnLoad" in calc.attrs:
        return blob
    tag = calc.start_tag(data)
    closing = b"/>" if tag.endswith(b"/>") else b">"
    new_tag = tag[: -len(closing)].rstrip() + b' fullCalcOnLoad="1"' + closing
    new_data = xml_spans.splice(data, calc.start, calc.start + len(tag), new_tag)
    return yoshiki_word.rebuild_zip(blob, {BOOK: new_data})


# ---------------------------------------------------------------- 比べる


def compare_xlsx(before: bytes, after: bytes) -> List[str]:
    """Excel の様式どうしを比べ、書いてよい範囲（直前の版の、入力のシートのロックを外したセル）の外の差を返す。"""
    try:
        book_b = Book(before)
    except (FormError, xml_spans.SpanError) as e:
        return [f"直前の版を読めません（{e}）"]
    try:
        book_a = Book(after)
    except (FormError, xml_spans.SpanError) as e:
        return [f"書いた後のファイルを読めません（{e}）"]
    names_b = [(s.name, s.part) for s in book_b.sheets]
    names_a = [(s.name, s.part) for s in book_a.sheets]
    if names_b != names_a:
        return ["シートの構成が変わりました（" + "、".join(n for n, _p in names_b) + " → " +
                "、".join(n for n, _p in names_a) + "）"]
    sheet_names = [s.part for s in book_b.sheets]
    out = yoshiki_word.compare_parts(book_b.parts, book_a.parts, skip=tuple(sheet_names))
    for sb, sa in zip(book_b.sheets, book_a.sheets):
        if sb.grid.root.attrs != sa.grid.root.attrs:
            out.append(f"シート「{sb.name}」の根（名前空間の宣言など）が変わりました")
        masked = sorted(sb.inputs)
        for ref in masked:
            cb, ca = sb.grid.cells.get(ref), sa.grid.cells.get(ref)
            if ca is None:
                out.append(f"シート「{sb.name}」のセル {ref} がなくなりました")
                continue
            if cb.attrs.get("s", "0") != ca.attrs.get("s", "0"):
                out.append(f"シート「{sb.name}」のセル {ref} の書式が変わりました")
            if ca.find(S, "f") is not None:
                out.append(f"シート「{sb.name}」のセル {ref} に数式が入りました")
        units_b = input_sheet._units(sb.grid, masked)
        units_a = input_sheet._units(sa.grid, masked)
        sm = difflib.SequenceMatcher(a=[u[1] for u in units_b], b=[u[1] for u in units_a], autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            if op == "replace":
                out.append(f"シート「{sb.name}」で変わった：{'、'.join(u[0] for u in units_b[i1:i2][:3])}")
            elif op == "delete":
                out.append(f"シート「{sb.name}」でなくなった：{'、'.join(u[0] for u in units_b[i1:i2][:3])}")
            else:
                out.append(f"シート「{sb.name}」で増えた：{'、'.join(u[0] for u in units_a[j1:j2][:3])}")
        if len(out) >= yoshiki_word.MAX_DIFFS:
            break
    return out[:yoshiki_word.MAX_DIFFS]
