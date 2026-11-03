"""実験 E2b：Excel の様式（事業計画書その3、別紙1〜4）に書き込んで、書式・入力規則・数式が落ちないかを見る。
あわせて、試しの財務モデルの数式を LibreOffice で計算し直し、Python の計算と一致するかを見る。

1. downloads/ の様式の写しの入力欄に、試しの値を書く。書き方は2通り（openpyxl で開いて保存／シートの XML を直接書き換える）。
   書いてよい範囲は、保護したシートの「ロックしないセル」（様式が入力欄として開けてあるセル）とする。
2. 書く前と後を、zip の部品の XML で比べる（openpyxl で読み直したものでは比べない。読むときに落ちる部品が見えなくなるため）。
3. 範囲の外をわざと変えた写しで、比べる道具が差を見つけるかを確かめる（否定の対照）。
4. 試しの財務モデル（新しく作るもの）を openpyxl で作り、LibreOffice で計算し直した値と、Python で計算した値を比べる。
   計算し直しが本当に起きたかは、数式のセルにわざと違う計算済みの値を入れておいて確かめる。
5. XML を直接書いた写しの、計算済みの値が古いまま残るかを、LibreOffice で計算し直した値と比べる。

使い方（出力はリポの外に書く）：
  uv run --no-project --with openpyxl --with lxml python -I experiments/E2/e2b_excel.py --out <リポの外のフォルダ>
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import math
import posixpath
import re
import sys
import warnings
from collections import Counter
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from lxml import etree  # noqa: E402
from openpyxl.formula.translate import Translator  # noqa: E402
from openpyxl.utils.datetime import to_excel  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402

from e2_common import (  # noqa: E402
    EXCEL_FORM,
    convert,
    prepare_out_dir,
    read_parts,
    require_form,
    write_parts,
    write_registry,
)

warnings.simplefilter("ignore")

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
X14 = "{http://schemas.microsoft.com/office/spreadsheetml/2009/9/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

S0 = "【指定様式】事業計画書（その3）"
S1 = "（別紙１）省力化計算シート"
S3 = "（別紙３）投資回収期間計算シート"
S4 = "(別紙4）事業計画目標値算出シート"


# ---------------------------------------------------------------- 書く値（架空。入力規則に合う値）


def kubun4_inputs() -> dict[str, object]:
    """別紙4 の値。3年目の労働生産性が、基準年度のちょうど 1.04^3 倍になるようにする（ROUNDDOWN の境目を見るため）。"""
    officers, staff = 2, 7
    productivity = {"F": 5_000_000, "G": 5_200_000, "H": 5_408_000, "I": 5_624_320, "J": 5_849_293, "K": 6_083_265}
    values: dict[str, object] = {"C4": "3月", "C5": 46661}
    for col, prod in productivity.items():
        added_value = prod * (officers + staff)  # 付加価値額
        labor, dep_old = 30_000_000, 3_000_000
        dep_new = 0 if col == "F" else 4_500_000
        sga = labor + dep_old + dep_new + 10_000_000  # 販管費に人件費と減価償却費を含める
        gross = added_value - labor - dep_old - dep_new + sga  # 売上総利益
        sales = round(gross / 0.4)
        values.update(
            {
                f"{col}14": sales,
                f"{col}15": sales - gross,
                f"{col}17": sga,
                f"{col}19": labor,
                f"{col}21": dep_old,
                f"{col}25": officers,
                f"{col}26": staff,
            }
        )
        if col != "F":
            values[f"{col}22"] = dep_new
    # 給与支給総額：基準年度（E）の1人当たりを800万円にし、3年目（I）をちょうど 1.035^3 倍（8,869,743円）にする
    per_person = {"C": 7_700_000, "D": 7_850_000, "E": 8_000_000, "G": 8_280_000, "H": 8_569_800, "I": 8_869_743, "J": 9_180_184, "K": 9_501_490}
    for col, pay in per_person.items():
        values[f"{col}33"] = pay * staff
        values[f"{col}34"] = staff
    return values


INPUTS: dict[str, dict[str, object]] = {
    S0: {
        "B20": "盛り付けと包装の作業時間が減り、空いた人手で注文を増やす（試しの文）。",
        "I19": 4.12,
        "I25": 4.12,
        "I32": 3.6,
    },
    S1: {
        "C11": "盛り付け",
        "D11": 120,
        "C12": "計量",
        "D12": 90,
        "C13": "包装",
        "D13": 150,
        "I11": "盛り付け（ロボット）",
        "J11": 20,
        "K11": "内容は変化しない作業",
        "L11": 1,
        "I12": "計量（一貫ライン）",
        "J12": 30,
        "K12": "内容は変化しない作業",
        "L12": 2,
        "I13": "画像検査の確認",
        "J13": 15,
        "K13": "新たに追加される作業",
    },
    S3: {"C6": 22_500_000, "H6": 250, "J6": 1_500, "L6": 3_000_000, "C13": "人件費の単価は、パートの時給の平均（試しの文）。"},
    S4: kubun4_inputs(),
}


# ---------------------------------------------------------------- zip の中の読み取り


def xc14n(el) -> bytes:
    """名前空間の宣言の違いに左右されないよう、排他的な C14N でそろえる。"""
    return etree.tostring(el, method="c14n", exclusive=True)


def part_key(data: bytes) -> bytes:
    """部品の中身をそろえた形。C14N 1.0 が通らない部品（相対の名前空間など）は C14N 2.0、XML でなければバイトのまま。"""
    try:
        return xc14n(etree.fromstring(data))
    except etree.C14NError:
        return etree.canonicalize(data.decode("utf-8")).encode("utf-8")
    except etree.XMLSyntaxError:
        return data


def resolve(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def rels_of(parts: dict, part: str) -> list[tuple[str, str]]:
    d, name = posixpath.split(part)
    rel = f"{d}/_rels/{name}.rels"
    if rel not in parts:
        return []
    root = etree.fromstring(parts[rel])
    out = []
    for r in root.findall(PR + "Relationship"):
        target = r.get("Target")
        if r.get("TargetMode") != "External":
            target = resolve(d, target)
        out.append((r.get("Type").rsplit("/", 1)[-1], target, r.get("Id")))
    return out


def sheet_map(parts: dict) -> dict[str, str]:
    """シートの名前 → シートの部品の名前。"""
    wb = etree.fromstring(parts["xl/workbook.xml"])
    rid = {i: t for _, t, i in rels_of(parts, "xl/workbook.xml")}
    return {s.get("name"): rid[s.get(R + "id")] for s in wb.find(M + "sheets")}


def shared_strings(parts: dict) -> list:
    if "xl/sharedStrings.xml" not in parts:
        return []
    return list(etree.fromstring(parts["xl/sharedStrings.xml"]).findall(M + "si"))


BOOL_FONT_PROPS = {"b", "i", "strike", "outline", "shadow", "condense", "extend"}


def norm_style(el):
    """書式の要素の、意味の同じ書き方をそろえる（子の並び、<b/> と <b val="1"/>、塗りの既定値、空の子）。"""
    el = copy.deepcopy(el)
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        local = etree.QName(node).localname
        if local in BOOL_FONT_PROPS and node.get("val") is None:
            node.set("val", "1")
        if local == "patternFill" and node.get("patternType") is None:
            node.set("patternType", "none")
        if node.get("tint") is not None:
            node.set("tint", repr(float(node.get("tint"))))
        if local == "protection":
            # 既定の値（hidden="0"、locked="1"）は書かなくても同じ
            if node.get("hidden") in ("0", "false"):
                del node.attrib["hidden"]
            if node.get("locked") in ("1", "true"):
                del node.attrib["locked"]
    for node in list(el.iter())[::-1]:
        if node is not el and len(node) == 0 and not node.attrib and not (node.text or "").strip():
            node.getparent().remove(node)
    for node in el.iter():
        node[:] = sorted(node, key=lambda ch: (str(ch.tag), xc14n(ch)))
    return xc14n(el)


def style_keys(parts: dict) -> list[bytes]:
    """セルの書式の番号 → 書式の中身（表示形式・フォント・塗り・罫線・配置・保護）。番号を付け直しただけの違いを見分けるため。"""
    styles = etree.fromstring(parts["xl/styles.xml"])

    def listed(tag, child):
        box = styles.find(M + tag)
        return [norm_style(el) for el in box.findall(M + child)] if box is not None else []

    fonts, fills, borders = listed("fonts", "font"), listed("fills", "fill"), listed("borders", "border")
    numfmts = {nf.get("numFmtId"): nf.get("formatCode") for nf in styles.iterfind(f"{M}numFmts/{M}numFmt")}
    keys = []
    for xf in styles.find(M + "cellXfs").findall(M + "xf"):
        nid = xf.get("numFmtId", "0")
        parts_of_key = [
            numfmts.get(nid, f"組み込み{nid}").encode(),
            fonts[int(xf.get("fontId", "0"))] if fonts else b"",
            fills[int(xf.get("fillId", "0"))] if fills else b"",
            borders[int(xf.get("borderId", "0"))] if borders else b"",
            b"".join(norm_style(ch) for ch in xf),
        ]
        keys.append(b"|".join(parts_of_key))
    return keys


def unlocked_styles(parts: dict) -> set[str]:
    styles = etree.fromstring(parts["xl/styles.xml"])
    out = set()
    for i, xf in enumerate(styles.find(M + "cellXfs").findall(M + "xf")):
        prot = xf.find(M + "protection")
        if prot is not None and prot.get("locked") == "0":
            out.add(str(i))
    return out


def writable_cells(parts: dict) -> dict[str, set[str]]:
    """書いてよい範囲：保護したシートの、ロックしないセル。"""
    unlocked = unlocked_styles(parts)
    out = {}
    for name, part in sheet_map(parts).items():
        root = etree.fromstring(parts[part])
        if root.find(M + "sheetProtection") is None:
            out[name] = set()
            continue
        out[name] = {c.get("r") for c in root.iter(M + "c") if c.get("s", "0") in unlocked}
    return out


def content_key(rich) -> bytes:
    """文字のセルの中身（書式つきの文字やふりがなを含む）。共有の文字（si）と、セルの中の文字（is）を同じ形で比べる。"""
    return b"".join(xc14n(ch) for ch in rich)


def cells_of(root, sst: list) -> dict[str, dict]:
    masters = {}
    for c in root.iter(M + "c"):
        f = c.find(M + "f")
        if f is not None and f.get("t") == "shared" and f.get("ref") and f.text:
            masters[f.get("si")] = (c.get("r"), f.text)
    out = {}
    for c in root.iter(M + "c"):
        ref = c.get("r")
        t = c.get("t", "n")
        f, v, inline = c.find(M + "f"), c.find(M + "v"), c.find(M + "is")
        if t == "s" and v is not None:
            val = ("文字", content_key(sst[int(v.text)]))
        elif t == "inlineStr" and inline is not None:
            val = ("文字", content_key(inline))
        elif v is not None:
            val = (t, v.text)
        else:
            val = None
        formula = None
        if f is not None:
            text = f.text
            if f.get("t") == "shared" and not text:
                origin, master = masters[f.get("si")]
                text = Translator("=" + master, origin=origin).translate_formula(ref)[1:]
            formula = (f.get("t") == "array", f.get("ref") if f.get("t") == "array" else None, text)
        out[ref] = {"s": c.get("s", "0"), "val": val, "f": formula, "f_raw": None if f is None else xc14n(f)}
    return out


EMPTY_CELL = {"s": "0", "val": None, "f": None, "f_raw": None}


def drop_space_attr(val):
    """xml:space="preserve" の有無は、全角の空白しかない文字では意味が同じ。"""
    if not val or val[0] != "文字":
        return val
    return ("文字", re.sub(rb' xml:space="preserve"', b"", val[1]))


def text_only(val):
    """ふりがな（rPh・phoneticPr）を除いた中身。"""
    val = drop_space_attr(val)
    if not val or val[0] != "文字":
        return val
    return ("文字", re.sub(rb"<rPh .*?</rPh>|<phoneticPr[^>]*>(</phoneticPr>)?", b"", val[1]))


def multiset_diff(a: list[bytes], b: list[bytes]) -> int:
    ca, cb = Counter(a), Counter(b)
    return sum(((ca - cb) + (cb - ca)).values())


def sheet_categories(root, skeys: list[bytes]) -> dict[str, list[bytes]]:
    """T8-1 の物差しの項目ごとに、シートの部品を取り出す。行の書式は、番号でなく書式の中身で比べる。"""

    def all_of(*paths):
        return [xc14n(el) for p in paths for el in root.iterfind(p)]

    cats = {
        "結合セル": all_of(f"{M}mergeCells/{M}mergeCell"),
        "入力規則": all_of(f"{M}dataValidations/{M}dataValidation", f".//{X14}dataValidation"),
        "条件付き書式": all_of(f"{M}conditionalFormatting", f".//{X14}conditionalFormatting"),
        "列の幅": all_of(f"{M}cols"),
        "印刷の設定とヘッダー・フッター": all_of(
            f"{M}pageMargins", f"{M}pageSetup", f"{M}printOptions", f"{M}headerFooter", f"{M}rowBreaks", f"{M}colBreaks"
        ),
        "シートの保護": all_of(f"{M}sheetProtection"),
        "図形・フォームの部品": all_of(f"{M}drawing", f"{M}legacyDrawing", f"{M}controls"),
    }
    rows = []
    for row in root.iter(M + "row"):
        attrs = {k: v for k, v in row.attrib.items() if k not in ("spans",)}
        if "s" in attrs:
            # 行の書式は customFormat="1" のときだけ効く
            if attrs.get("customFormat") in ("1", "true"):
                attrs["s"] = skeys[int(attrs["s"])].decode("utf-8", errors="replace")
            else:
                del attrs["s"]
        rows.append(json.dumps(sorted(attrs.items()), ensure_ascii=False).encode())
    cats["行の高さ・行の設定"] = rows
    rest = copy.deepcopy(root)
    for tag in (
        "sheetData",
        "mergeCells",
        "dataValidations",
        "conditionalFormatting",
        "cols",
        "pageMargins",
        "pageSetup",
        "printOptions",
        "headerFooter",
        "rowBreaks",
        "colBreaks",
        "sheetProtection",
        "drawing",
        "legacyDrawing",
        "controls",
    ):
        for el in rest.findall(M + tag):
            rest.remove(el)
    ext_lst = rest.find(M + "extLst")
    if ext_lst is not None:
        for ext in list(ext_lst):
            if ext.find(X14 + "dataValidations") is not None or ext.find(X14 + "conditionalFormattings") is not None:
                ext_lst.remove(ext)
    cats["その他のシートの設定"] = [xc14n(rest)]
    return cats


def compare_sheet(name: str, pb: dict, pa: dict, part_b: str, part_a: str, writable: set[str]) -> dict[str, dict]:
    """項目ごとに {数, 例} を返す。"""
    rb, ra = etree.fromstring(pb[part_b]), etree.fromstring(pa[part_a])
    cb, ca = cells_of(rb, shared_strings(pb)), cells_of(ra, shared_strings(pa))
    out: dict[str, dict] = {}

    def add(cat, msg, n=1):
        item = out.setdefault(cat, {"数": 0, "例": []})
        item["数"] += n
        if len(item["例"]) < 4:
            item["例"].append(msg)

    kb, ka = style_keys(pb), style_keys(pa)
    for ref in sorted(set(cb) | set(ca)):
        x, y = cb.get(ref, EMPTY_CELL), ca.get(ref, EMPTY_CELL)
        if x["s"] != y["s"]:
            if kb[int(x["s"])] == ka[int(y["s"])]:
                add("書式の番号だけ（中身は同じ）", ref)
            else:
                add("セルの書式", f"{ref}：書式の番号 {x['s']} → {y['s']}")
        if x["f"] != y["f"]:
            add("数式", f"{ref}：{x['f'][2] if x['f'] else 'なし'} → {y['f'][2] if y['f'] else 'なし'}")
        elif x["f_raw"] != y["f_raw"]:
            add("数式の書き方（中身は同じ）", ref)
        if x["f"] is None and y["f"] is None and x["val"] != y["val"] and ref not in writable:
            if text_only(x["val"]) == text_only(y["val"]):
                add("ふりがなが落ちた（ふだんは見えない）", ref)
            elif drop_space_attr(x["val"]) == drop_space_attr(y["val"]):
                add("文字の書き方だけ（中身は同じ）", ref)
            else:
                add("値（範囲の外）", f"{ref}")
    cats_b, cats_a = sheet_categories(rb, kb), sheet_categories(ra, ka)
    for cat in cats_b:
        n = multiset_diff(cats_b[cat], cats_a[cat])
        if n:
            add(cat, f"前 {len(cats_b[cat])}・後 {len(cats_a[cat])}", n)
    relb = sorted((t, posixpath.basename(p)) for t, p, _ in rels_of(pb, part_b))
    rela = sorted((t, posixpath.basename(p)) for t, p, _ in rels_of(pa, part_a))
    if relb != rela:
        add("つながる部品", f"前 {relb} → 後 {rela}")
    return out


def compare_workbook(pb: dict, pa: dict) -> dict[str, list[str]]:
    wb, wa = etree.fromstring(pb["xl/workbook.xml"]), etree.fromstring(pa["xl/workbook.xml"])
    out: dict[str, list[str]] = {}

    def sheets(w):
        return [(s.get("name"), s.get("state", "visible")) for s in w.find(M + "sheets")]

    def names(w):
        dn = w.find(M + "definedNames")
        return sorted((d.get("name"), d.get("localSheetId", ""), d.text) for d in (dn if dn is not None else []))

    def one(w, tag):
        el = w.find(M + tag)
        return None if el is None else xc14n(el)

    if sheets(wb) != sheets(wa):
        out["シートの構成"] = [f"{sheets(wb)} → {sheets(wa)}"]
    if names(wb) != names(wa):
        out["名前の定義"] = [f"前だけ {sorted(set(names(wb)) - set(names(wa)))}", f"後だけ {sorted(set(names(wa)) - set(names(wb)))}"]
    for tag, cat in (("workbookProtection", "ブックの保護"), ("calcPr", "計算の設定"), ("externalReferences", "外部リンク")):
        if one(wb, tag) != one(wa, tag):
            out[cat] = [f"{one(wb, tag)} → {one(wa, tag)}"]
    return out


SKIP_PARTS = {"xl/workbook.xml", "xl/sharedStrings.xml", "xl/_rels/workbook.xml.rels"}


def compare_parts(pb: dict, pa: dict) -> list[str]:
    """シート・ブック・共有の文字以外の部品を比べる。シートの部品と、そのつながりの部品は上で比べる。"""
    sheets_b, sheets_a = set(sheet_map(pb).values()), set(sheet_map(pa).values())

    def skip(name, sheets):
        if name in SKIP_PARTS or name in sheets:
            return True
        return any(name == f"{posixpath.dirname(s)}/_rels/{posixpath.basename(s)}.rels" for s in sheets)

    out = []
    names_b = {n for n in pb if not skip(n, sheets_b)}
    names_a = {n for n in pa if not skip(n, sheets_a)}
    for name in sorted(names_b - names_a):
        out.append(f"{name}：なくなった")
    for name in sorted(names_a - names_b):
        out.append(f"{name}：増えた")
    for name in sorted(names_b & names_a):
        x, y = pb[name], pa[name]
        if name.endswith((".xml", ".rels", ".vml")):
            if name == "[Content_Types].xml":
                same = sorted(xc14n(c) for c in etree.fromstring(x)) == sorted(xc14n(c) for c in etree.fromstring(y))
            else:
                same = part_key(x) == part_key(y)
        else:
            same = x == y
        if not same:
            out.append(f"{name}：中身が変わった")
    return out


def check(before: Path, after: Path) -> dict:
    pb, pa = read_parts(before), read_parts(after)
    writable = writable_cells(pb)
    mb, ma = sheet_map(pb), sheet_map(pa)
    per_sheet = {}
    for name in mb:
        if name not in ma:
            per_sheet[name] = {"シートの構成": ["シートがなくなった"]}
            continue
        diffs = compare_sheet(name, pb, pa, mb[name], ma[name], writable[name])
        if diffs:
            per_sheet[name] = diffs
    wbd = compare_workbook(pb, pa)
    parts = compare_parts(pb, pa)
    counted = {
        cat: sum(v["数"] for d in per_sheet.values() for c, v in d.items() if c == cat)
        for cat in sorted({c for d in per_sheet.values() for c in d})
    }
    benign = ("数式の書き方（中身は同じ）", "書式の番号だけ（中身は同じ）", "文字の書き方だけ（中身は同じ）")
    total = sum(n for c, n in counted.items() if c not in benign) + sum(len(v) for v in wbd.values()) + len(parts)
    return {"範囲の外の差の数": total, "シートの項目ごとの数": counted, "シートごと": per_sheet, "ブック": wbd, "部品": parts}


# ---------------------------------------------------------------- 書き込み


def col_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def row_number(ref: str) -> int:
    return int("".join(ch for ch in ref if ch.isdigit()))


def set_cell_xml(root, ref: str, value) -> None:
    """シートの XML のセルに値を書く。書式の番号（s）はそのまま。文字はセルの中の文字（inlineStr）にして、共有の文字の部品を触らない。"""
    sheet_data = root.find(M + "sheetData")
    r = row_number(ref)
    row = next((x for x in sheet_data.findall(M + "row") if int(x.get("r")) == r), None)
    if row is None:
        row = sheet_data.makeelement(M + "row", {"r": str(r)})
        later = next((x for x in sheet_data.findall(M + "row") if int(x.get("r")) > r), None)
        later.addprevious(row) if later is not None else sheet_data.append(row)
    c = next((x for x in row.findall(M + "c") if x.get("r") == ref), None)
    if c is None:
        c = row.makeelement(M + "c", {"r": ref})
        later = next((x for x in row.findall(M + "c") if col_index(x.get("r")) > col_index(ref)), None)
        later.addprevious(c) if later is not None else row.append(c)
    if c.find(M + "f") is not None:
        raise RuntimeError(f"{ref} は数式のセルです")
    for child in list(c):
        c.remove(child)
    if isinstance(value, str):
        c.set("t", "inlineStr")
        t = etree.SubElement(etree.SubElement(c, M + "is"), M + "t")
        t.text = value
        t.set(XML_SPACE, "preserve")
    else:
        c.attrib.pop("t", None)
        etree.SubElement(c, M + "v").text = repr(value) if isinstance(value, float) else str(value)


def serialize(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def write_direct(src: Path, dst: Path, inputs: dict, guard: bool = True) -> None:
    parts = read_parts(src)
    smap = sheet_map(parts)
    writable = writable_cells(parts)
    replace = {}
    for name, values in inputs.items():
        root = etree.fromstring(parts[smap[name]])
        for ref, value in values.items():
            if guard and ref not in writable[name]:
                raise RuntimeError(f"{name}!{ref} は書いてよい範囲の外です")
            set_cell_xml(root, ref, value)
        replace[smap[name]] = serialize(root)
    write_parts(src, dst, replace)


def write_openpyxl(src: Path, dst: Path, inputs: dict) -> None:
    wb = openpyxl.load_workbook(src)
    for name, values in inputs.items():
        for ref, value in values.items():
            wb[name][ref].value = value
    wb.save(dst)


# ---------------------------------------------------------------- 否定の対照


def mutate(src: Path, dst: Path, how: str) -> None:
    parts = read_parts(src)
    smap = sheet_map(parts)
    replace = {}

    def sheet(name):
        return etree.fromstring(parts[smap[name]])

    if how == "結合を1つ外す":
        root = sheet(S0)
        mc = root.find(M + "mergeCells")
        mc.remove(mc.find(M + "mergeCell"))
        mc.set("count", str(len(mc)))
        replace[smap[S0]] = serialize(root)
    elif how == "入力規則を1つ消す":
        root = sheet(S1)
        dvs = root.find(M + "dataValidations")
        dvs.remove(dvs.find(M + "dataValidation"))
        dvs.set("count", str(len(dvs)))
        replace[smap[S1]] = serialize(root)
    elif how == "数式を1つ変える":
        root = sheet(S4)
        c = next(c for c in root.iter(M + "c") if c.get("r") == "F16")
        c.find(M + "f").text = "F14+F15"
        replace[smap[S4]] = serialize(root)
    elif how == "ロックしたセル（見出し）に書く":
        root = sheet(S4)
        set_cell_xml(root, "B14", "売上高（変更）")
        replace[smap[S4]] = serialize(root)
    elif how == "拡張の条件付き書式を1つ消す":
        name = "（別紙２）省力化業務プロセス図"
        root = sheet(name)
        cf = next(root.iter(X14 + "conditionalFormatting"))
        cf.getparent().remove(cf)
        replace[smap[name]] = serialize(root)
    elif how == "シートの保護を外す":
        root = sheet(S3)
        root.remove(root.find(M + "sheetProtection"))
        replace[smap[S3]] = serialize(root)
    elif how == "範囲のセルの書式の番号を変える":
        root = sheet(S1)
        c = next(c for c in root.iter(M + "c") if c.get("r") == "C11")
        c.set("s", "0")
        replace[smap[S1]] = serialize(root)
    elif how == "スタイルの文字の大きさを変える":
        styles = etree.fromstring(parts["xl/styles.xml"])
        sz = next(styles.iter(M + "sz"))
        sz.set("val", str(float(sz.get("val")) + 1))
        replace["xl/styles.xml"] = serialize(styles)
    else:
        raise ValueError(how)
    write_parts(src, dst, replace)


MUTATIONS = [
    "結合を1つ外す",
    "入力規則を1つ消す",
    "数式を1つ変える",
    "ロックしたセル（見出し）に書く",
    "拡張の条件付き書式を1つ消す",
    "シートの保護を外す",
    "範囲のセルの書式の番号を変える",
    "スタイルの文字の大きさを変える",
]


# ---------------------------------------------------------------- 試しの財務モデル


def x_round(x: float, d: int) -> float:
    """Excel の ROUND（0.5 は0から遠いほうへ）。"""
    q = Decimal(1).scaleb(-d)
    return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))


def rounddown_naive(x: float, d: int) -> float:
    """そのまま切り捨てる。浮動小数の誤差（3.9999999…）を、そのまま切り捨てる。"""
    k = 10**d
    return math.trunc(x * k) / k


def rounddown_15(x: float, d: int) -> float:
    """有効数字15桁にそろえてから切り捨てる（表計算ソフトに近い扱い）。"""
    q = Decimal(1).scaleb(-d)
    return float(Decimal(f"{x:.15g}").quantize(q, rounding=ROUND_DOWN))


def roundup_15(x: float, d: int) -> float:
    q = Decimal(1).scaleb(-d)
    return float(Decimal(f"{x:.15g}").quantize(q, rounding=ROUND_UP))


ASSUMPTIONS = [
    # 名前, 値, 単位, この数字は何か
    ("単価_冷凍惣菜", 680, "円/個", "冷凍惣菜1個の値段"),
    ("数量_冷凍惣菜_年1", 24_000, "個/年", "1年目に売る数"),
    ("伸び_数量", 0.15, "", "2年目から毎年の数の伸び"),
    ("原価率_冷凍惣菜", 0.42, "", "冷凍惣菜の原材料費の割合"),
    ("既存_売上", 201_600_000, "円", "基準年度の今の事業の売上"),
    ("既存_伸び", 0.02, "", "今の事業の売上の毎年の伸び"),
    ("既存_原価率", 0.6, "", "今の事業の原材料費の割合"),
    ("人数", 9, "人", "役員と常勤の従業員"),
    ("時間_年", 1_800, "時間/人", "1人の1年の働く時間"),
    ("時給", 1_350, "円/時", "基準年度の1時間あたりの給与"),
    ("賃上げ率", 0.035, "", "給与の毎年の伸び"),
    ("法定福利費率", 0.15, "", "給与に対する法定福利費などの割合"),
    ("設備費", 22_500_000, "円", "入れる設備の金額"),
    ("償却年数", 5, "年", "設備の減価償却の年数"),
    ("既存_償却費", 3_000_000, "円/年", "今の設備の減価償却費"),
    ("その他経費", 30_000_000, "円/年", "そのほかの経費"),
    ("境目_基準", 5_000_000, "円", "ROUNDDOWN の境目の試し（基準）"),
    ("境目_3年目", 5_624_320, "円", "境目の試し（基準の 1.04^3 倍）"),
    ("境目2_基準", 8_000_000, "円", "境目の試し2（基準）"),
    ("境目2_3年目", 8_869_743, "円", "境目の試し2（基準のちょうど 1.035^3 倍。Python では 3.4999… になる）"),
]
SEASON = [0.06, 0.06, 0.07, 0.08, 0.08, 0.09, 0.10, 0.10, 0.09, 0.09, 0.09, 0.09]
MONTHS = "BCDEFGHIJKLM"
YEARS = "BCDEFG"  # 基準年度・1〜5年目
SHEET_A, SHEET_P, SHEET_M = "前提", "計画（5年）", "月次（1年目）"
QM = f"'{SHEET_M}'"


def build_model(rounddown) -> tuple[openpyxl.Workbook, dict]:
    """試しの財務モデルを作り、数式と、同じ計算を Python でした値を返す。"""
    wb = openpyxl.Workbook()
    wa = wb.active
    wa.title = SHEET_A
    wa.append(["名前", "値", "単位", "この数字は何か", "根拠"])
    p = {}
    for i, (name, value, unit, desc) in enumerate(ASSUMPTIONS, start=2):
        wa.append([name, value, unit, desc, "試しの値"])
        wb.defined_names[name] = DefinedName(name, attr_text=f"{SHEET_A}!$B${i}")
        p[name] = value
    py: dict[tuple[str, str], object] = {}

    wm = wb.create_sheet(SHEET_M)
    wm["A3"], wm["A4"], wm["A5"], wm["A6"], wm["A7"] = "月", "季節の波", "数量", "売上", "原材料費"

    def put(ws, ref, formula, value):
        ws[ref] = formula
        py[(ws.title, ref)] = value

    for j, col in enumerate(MONTHS):
        wm[f"{col}3"] = f"{j + 1}月"
        wm[f"{col}4"] = SEASON[j]
        q = x_round(p["数量_冷凍惣菜_年1"] * SEASON[j], 0)
        put(wm, f"{col}5", f"=ROUND(数量_冷凍惣菜_年1*{col}4,0)", q)
        put(wm, f"{col}6", f"={col}5*単価_冷凍惣菜", q * p["単価_冷凍惣菜"])
        put(wm, f"{col}7", f"={col}6*原価率_冷凍惣菜", q * p["単価_冷凍惣菜"] * p["原価率_冷凍惣菜"])
    wm["N3"] = "合計"
    for r in (5, 6, 7):
        total = 0.0
        for col in MONTHS:
            total += py[(SHEET_M, f"{col}{r}")]
        put(wm, f"N{r}", f"=SUM(B{r}:M{r})", total)

    wp = wb.create_sheet(SHEET_P)
    labels = {
        3: "年度（基準=0）",
        5: "既存：売上",
        6: "既存：原材料費",
        7: "既存：人件費",
        8: "既存：給与支給総額",
        9: "既存：減価償却費",
        10: "既存：その他",
        11: "既存：営業利益",
        13: "新：売上",
        14: "新：原材料費",
        15: "新：減価償却費",
        16: "新：営業利益",
        18: "合算：売上",
        19: "合算：原材料費",
        20: "合算：人件費",
        21: "合算：給与支給総額",
        22: "合算：減価償却費",
        23: "合算：その他",
        24: "合算：営業利益",
        25: "付加価値額",
        26: "労働生産性",
        27: "1人当たり給与支給総額",
        28: "労働生産性の年平均の伸び（％）",
        29: "給与の年平均の伸び（％）",
        30: "要件（労働生産性 4.0%）",
        31: "要件（給与 3.5%）",
        33: "数量2割減：新の売上",
        34: "数量2割減：付加価値額",
        35: "数量2割減：労働生産性",
        36: "数量2割減：伸び（％）",
        37: "数量2割減：要件",
        39: "境目の試し：伸び（％）",
        40: "境目の試し：要件",
        41: "境目の試し2：伸び（％）",
        42: "境目の試し2：要件",
    }
    for r, label in labels.items():
        wp[f"A{r}"] = label

    def v(r, col):
        return py[(SHEET_P, f"{col}{r}")]

    for n, col in enumerate(YEARS):
        wp[f"{col}3"] = n
        prev = YEARS[n - 1] if n else None
        if n == 0:
            put(wp, f"{col}5", "=既存_売上", float(p["既存_売上"]))
        else:
            put(wp, f"{col}5", f"={prev}5*(1+既存_伸び)", v(5, prev) * (1 + p["既存_伸び"]))
        put(wp, f"{col}6", f"={col}5*既存_原価率", v(5, col) * p["既存_原価率"])
        pay = p["人数"] * p["時間_年"] * p["時給"] * (1 + p["賃上げ率"]) ** n
        put(wp, f"{col}7", f"=人数*時間_年*時給*(1+賃上げ率)^{col}$3*(1+法定福利費率)", pay * (1 + p["法定福利費率"]))
        put(wp, f"{col}8", f"=人数*時間_年*時給*(1+賃上げ率)^{col}$3", pay)
        put(wp, f"{col}9", "=既存_償却費", float(p["既存_償却費"]))
        put(wp, f"{col}10", "=その他経費", float(p["その他経費"]))
        put(wp, f"{col}11", f"={col}5-{col}6-{col}7-{col}9-{col}10", v(5, col) - v(6, col) - v(7, col) - v(9, col) - v(10, col))
        if n == 0:
            put(wp, f"{col}13", "=0", 0.0)
            put(wp, f"{col}14", "=0", 0.0)
            put(wp, f"{col}15", "=0", 0.0)
        elif n == 1:
            put(wp, f"{col}13", f"={QM}!N6", py[(SHEET_M, "N6")])
            put(wp, f"{col}14", f"={QM}!N7", py[(SHEET_M, "N7")])
        else:
            sales = p["単価_冷凍惣菜"] * p["数量_冷凍惣菜_年1"] * (1 + p["伸び_数量"]) ** (n - 1)
            put(wp, f"{col}13", f"=単価_冷凍惣菜*数量_冷凍惣菜_年1*(1+伸び_数量)^({col}$3-1)", sales)
            put(wp, f"{col}14", f"={col}13*原価率_冷凍惣菜", sales * p["原価率_冷凍惣菜"])
        if n:
            put(wp, f"{col}15", "=設備費/償却年数", p["設備費"] / p["償却年数"])
        put(wp, f"{col}16", f"={col}13-{col}14-{col}15", v(13, col) - v(14, col) - v(15, col))
        put(wp, f"{col}18", f"={col}5+{col}13", v(5, col) + v(13, col))
        put(wp, f"{col}19", f"={col}6+{col}14", v(6, col) + v(14, col))
        put(wp, f"{col}20", f"={col}7", v(7, col))
        put(wp, f"{col}21", f"={col}8", v(8, col))
        put(wp, f"{col}22", f"={col}9+{col}15", v(9, col) + v(15, col))
        put(wp, f"{col}23", f"={col}10", v(10, col))
        op = v(18, col) - v(19, col) - v(20, col) - v(22, col) - v(23, col)
        put(wp, f"{col}24", f"={col}18-{col}19-{col}20-{col}22-{col}23", op)
        put(wp, f"{col}25", f"={col}24+{col}20+{col}22", op + v(20, col) + v(22, col))
        put(wp, f"{col}26", f"={col}25/人数", v(25, col) / p["人数"])
        put(wp, f"{col}27", f"={col}21/人数", v(21, col) / p["人数"])
        put(wp, f"{col}33", f"={col}13*0.8", v(13, col) * 0.8)
        put(wp, f"{col}34", f"={col}25-({col}13-{col}14)*0.2", v(25, col) - (v(13, col) - v(14, col)) * 0.2)
        put(wp, f"{col}35", f"={col}34/人数", v(34, col) / p["人数"])
        if n:
            g = rounddown(((v(26, col) / v(26, "B")) ** (1 / n) - 1) * 100, 2)
            put(wp, f"{col}28", f"=ROUNDDOWN((({col}26/$B$26)^(1/{col}$3)-1)*100,2)", g)
            g2 = rounddown(((v(27, col) / v(27, "B")) ** (1 / n) - 1) * 100, 2)
            put(wp, f"{col}29", f"=ROUNDDOWN((({col}27/$B$27)^(1/{col}$3)-1)*100,2)", g2)
            put(wp, f"{col}30", f'=IF({col}28>=4,"満たす","満たさない")', "満たす" if g >= 4 else "満たさない")
            put(wp, f"{col}31", f'=IF({col}29>=3.5,"満たす","満たさない")', "満たす" if g2 >= 3.5 else "満たさない")
            g3 = rounddown(((v(35, col) / v(35, "B")) ** (1 / n) - 1) * 100, 2)
            put(wp, f"{col}36", f"=ROUNDDOWN((({col}35/$B$35)^(1/{col}$3)-1)*100,2)", g3)
            put(wp, f"{col}37", f'=IF({col}36>=4,"満たす","満たさない")', "満たす" if g3 >= 4 else "満たさない")
    b1 = rounddown(((p["境目_3年目"] / p["境目_基準"]) ** (1 / 3) - 1) * 100, 2)
    put(wp, "B39", "=ROUNDDOWN(((境目_3年目/境目_基準)^(1/3)-1)*100,2)", b1)
    put(wp, "B40", '=IF(B39>=4,"満たす","満たさない")', "満たす" if b1 >= 4 else "満たさない")
    b2 = rounddown(((p["境目2_3年目"] / p["境目2_基準"]) ** (1 / 3) - 1) * 100, 2)
    put(wp, "B41", "=ROUNDDOWN(((境目2_3年目/境目2_基準)^(1/3)-1)*100,2)", b2)
    put(wp, "B42", '=IF(B41>=3.5,"満たす","満たさない")', "満たす" if b2 >= 3.5 else "満たさない")
    return wb, py


def inject_stale_values(src: Path, dst: Path, stale: str = "-1") -> int:
    """すべての数式のセルに、わざと違う計算済みの値を入れる（計算し直しが本当に起きたかを見る罠）。"""
    parts = read_parts(src)
    replace = {}
    n = 0
    for part in sheet_map(parts).values():
        root = etree.fromstring(parts[part])
        for c in root.iter(M + "c"):
            if c.find(M + "f") is None:
                continue
            for old in c.findall(M + "v"):
                c.remove(old)
            c.attrib.pop("t", None)
            etree.SubElement(c, M + "v").text = stale
            n += 1
        replace[part] = serialize(root)
    write_parts(src, dst, replace)
    return n


def values_of(path: Path) -> dict[tuple[str, str], object]:
    wb = openpyxl.load_workbook(path, data_only=True)
    return {(ws.title, c.coordinate): c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row}


def same_value(a, b) -> str:
    """'完全' / '誤差' / '違う'。日付は Excel の通し番号にして比べる。"""
    a, b = (to_excel(x) if isinstance(x, (datetime.datetime, datetime.date)) else x for x in (a, b))
    if isinstance(a, str) or isinstance(b, str):
        return "完全" if a == b else "違う"
    if a is None or b is None:
        return "違う"
    if float(a) == float(b):
        return "完全"
    return "誤差" if abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(b))) else "違う"


def compare_values(lo: dict, py: dict) -> dict:
    kinds = Counter()
    worst = 0.0
    wrong = []
    for key, expected in py.items():
        got = lo.get(key)
        kind = same_value(got, expected)
        kinds[kind] += 1
        if kind == "誤差":
            worst = max(worst, abs(float(got) - float(expected)) / max(1.0, abs(float(expected))))
        if kind == "違う":
            wrong.append(f"{key[0]}!{key[1]}：LibreOffice {got!r} / Python {expected!r}")
    return {"数式のセル": len(py), "完全に一致": kinds["完全"], "誤差の範囲で一致": kinds["誤差"], "誤差の最大（相対）": worst, "違う": wrong}


# ---------------------------------------------------------------- 様式の数式（別紙4）を Python でも計算する


def roundup_naive(x: float, d: int) -> float:
    k = 10**d
    return math.copysign(math.ceil(abs(x) * k) / k, x)


def kubun4_python(inputs: dict, rounddown, roundup) -> dict[tuple[str, str], float]:
    """別紙4 の付加価値額・労働生産性・1人当たり給与支給総額と、年平均の伸びを、様式の数式と同じ順で計算する。"""
    out = {}
    cols = "FGHIJK"
    prod = {}

    def g(col, r):
        return float(inputs.get(f"{col}{r}", 0))

    for col in cols:
        added = (g(col, 14) - g(col, 15) - g(col, 17)) + g(col, 19) + (g(col, 21) + g(col, 22))
        out[(S4, f"{col}23")] = added
        x = added / (g(col, 25) + g(col, 26))
        prod[col] = roundup(x, 2) if added < 0 else rounddown(x, 2)
        out[(S4, f"{col}27")] = prod[col]
    pay = {col: rounddown(g(col, 33) / g(col, 34), 2) for col in "CDEGHIJK"}
    pay["F"] = pay["E"]  # F35 は =E35
    for col in "CDEFGHIJK":
        out[(S4, f"{col}35")] = pay[col]
    for n, col in enumerate(cols[1:], start=1):
        out[(S4, f"{col}24")] = rounddown(((out[(S4, f"{col}23")] / out[(S4, "F23")]) ** (1 / n) - 1) * 100, 2)
        out[(S4, f"{col}29")] = rounddown(((prod[col] / prod["F"]) ** (1 / n) - 1) * 100, 2)
        growth = ((pay[col] / pay["F"]) ** (1 / n) - 1) * 100
        out[(S4, f"{col}40")] = rounddown(growth, 2) if pay[col] >= pay["F"] else roundup(growth, 2)
    return out


# ---------------------------------------------------------------- 本体

RECALC_ALWAYS = [
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>'
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="出力先（リポの外）")
    args = ap.parse_args()
    out = prepare_out_dir(args.out)
    report: dict = {}

    form = out / "form.xlsx"
    form.write_bytes(require_form(EXCEL_FORM).read_bytes())
    pf = read_parts(form)
    report["様式"] = {
        "シート": list(sheet_map(pf)),
        "書いてよいセルの数（保護したシートのロックしないセル）": {k: len(v) for k, v in writable_cells(pf).items()},
        "書いたセルの数": {k: len(v) for k, v in INPUTS.items()},
        "部品の数": len(pf),
    }

    # 1・2. 2通りで書いて比べる
    direct = out / "written_direct.xlsx"
    write_direct(form, direct, INPUTS)
    report["XML を直接"] = check(form, direct)
    via_openpyxl = out / "written_openpyxl.xlsx"
    write_openpyxl(form, via_openpyxl, INPUTS)
    report["openpyxl"] = check(form, via_openpyxl)

    # 書いた値が、書いた所に入っているか（XML を直接）
    got = values_of(direct)

    def as_written(x):
        # 日付の表示形式のセルは、openpyxl が日付にして返すので、Excel の通し番号に戻して比べる
        return to_excel(x) if isinstance(x, datetime.datetime) else x

    report["XML を直接"]["書いた値が入っている"] = all(
        as_written(got[(s, r)]) == val for s, vals in INPUTS.items() for r, val in vals.items()
    )

    # 範囲の外に書こうとすると、書く側の守りが止めるか
    try:
        write_direct(form, out / "refused.xlsx", {S4: {"B14": "売上高（変更）"}})
        report["範囲の外への書き込みを書く側が止める"] = False
    except RuntimeError as e:
        report["範囲の外への書き込みを書く側が止める"] = f"止めた（{e}）"

    # 3. 否定の対照
    report["否定の対照"] = []
    for i, how in enumerate(MUTATIONS):
        dst = out / f"mutated_{i}.xlsx"
        mutate(direct, dst, how)
        res = check(direct, dst)
        found = {**res["シートの項目ごとの数"], **{k: len(v) for k, v in res["ブック"].items()}}
        if res["部品"]:
            found["部品"] = res["部品"]
        report["否定の対照"].append({"変え方": how, "見つけた差の数": res["範囲の外の差の数"], "見つけた項目": found})

    # 4. 試しの財務モデル
    profile_default = out / "lo_profile_default"
    profile_recalc = out / "lo_profile_recalc"
    write_registry(profile_recalc, RECALC_ALWAYS)
    wb, py_naive = build_model(rounddown_naive)
    _, py_15 = build_model(rounddown_15)
    model = out / "model.xlsx"
    wb.save(model)
    trap = out / "model_trap.xlsx"
    n_trap = inject_stale_values(model, trap)
    lo_recalc = values_of(convert(trap, "xlsx:Calc Office Open XML", out / "lo_recalc", profile_recalc))
    lo_default_trap = values_of(convert(trap, "xlsx:Calc Office Open XML", out / "lo_default_trap", profile_default))
    lo_default_plain = values_of(convert(model, "xlsx:Calc Office Open XML", out / "lo_default_plain", profile_default))
    report["財務モデル"] = {
        "シート": [SHEET_A, SHEET_M, SHEET_P],
        "前提の数": len(ASSUMPTIONS),
        "名前を付けたセル": len(ASSUMPTIONS),
        "罠を入れた数式のセル": n_trap,
        "計算し直しを常にしたとき：Python（そのまま切り捨て）と比べる": compare_values(lo_recalc, py_naive),
        "計算し直しを常にしたとき：Python（15桁にそろえて切り捨て）と比べる": compare_values(lo_recalc, py_15),
        "既定の設定で、罠のまま残ったセル": sum(1 for k in py_naive if lo_default_trap.get(k) == -1),
        "既定の設定で、計算済みの値のない写し（openpyxl で作ったまま）": compare_values(lo_default_plain, py_15),
        "境目の試し": {
            "B39（1.04^3 倍、3年）": {
                "LibreOffice": lo_recalc.get((SHEET_P, "B39")),
                "Python そのまま": py_naive[(SHEET_P, "B39")],
                "Python 15桁": py_15[(SHEET_P, "B39")],
                "割る前の値（Python）": ((5_624_320 / 5_000_000) ** (1 / 3) - 1) * 100,
            },
            "B41（1.035^3 倍、3年）": {
                "LibreOffice": lo_recalc.get((SHEET_P, "B41")),
                "Python そのまま": py_naive[(SHEET_P, "B41")],
                "Python 15桁": py_15[(SHEET_P, "B41")],
                "割る前の値（Python）": ((8_869_743 / 8_000_000) ** (1 / 3) - 1) * 100,
            },
            "判定 B40・B42（LibreOffice / Python そのまま / Python 15桁）": [
                (lo_recalc.get((SHEET_P, r)), py_naive[(SHEET_P, r)], py_15[(SHEET_P, r)]) for r in ("B40", "B42")
            ],
        },
        "まとめの数字（LibreOffice）": {
            "5年目の合算の売上": lo_recalc.get((SHEET_P, "G18")),
            "5年目の付加価値額": lo_recalc.get((SHEET_P, "G25")),
            "5年目の労働生産性の伸び（％）": lo_recalc.get((SHEET_P, "G28")),
            "月次の売上の合計と1年目の新の売上": [lo_recalc.get((SHEET_M, "N6")), lo_recalc.get((SHEET_P, "C13"))],
        },
    }

    # 5. XML を直接書いた写しの、計算済みの値
    stale = values_of(direct)
    recalced = values_of(convert(direct, "xlsx:Calc Office Open XML", out / "lo_recalc_form", profile_recalc))
    pd = read_parts(direct)
    formula_cells = []
    for name, part in sheet_map(pd).items():
        for c in etree.fromstring(pd[part]).iter(M + "c"):
            if c.find(M + "f") is not None:
                formula_cells.append((name, c.get("r")))
    def stale_cells(values):
        return [
            k
            for k in formula_cells
            if same_value(values.get(k), recalced.get(k)) == "違う" and not (values.get(k) in (None, "") and recalced.get(k) in (None, ""))
        ]

    differ = stale_cells(stale)
    # 案：ブックの計算の設定に fullCalcOnLoad を立てる（workbook.xml の属性が1つ変わる）。既定の設定の LibreOffice が計算し直すかを見る
    full_calc = out / "written_direct_fullcalc.xlsx"
    wbx = etree.fromstring(pd["xl/workbook.xml"])
    wbx.find(M + "calcPr").set("fullCalcOnLoad", "1")
    write_parts(direct, full_calc, {"xl/workbook.xml": serialize(wbx)})
    full_calc_lo = values_of(convert(full_calc, "xlsx:Calc Office Open XML", out / "lo_default_fullcalc", profile_default))
    plain_lo = values_of(convert(direct, "xlsx:Calc Office Open XML", out / "lo_default_form", profile_default))
    key_cells = [(S0, "B8"), (S0, "B39"), (S1, "D3"), (S1, "J3"), (S1, "M3"), (S3, "C3"), (S4, "G24"), (S4, "I29"), (S4, "I40")]
    report["計算済みの値（XML を直接書いた写し）"] = {
        "数式のセル": len(formula_cells),
        "古い値のまま（LibreOffice で計算し直すと変わる）": len(differ),
        "既定の設定の LibreOffice で開いたとき、古い値のまま": len(stale_cells(plain_lo)),
        "fullCalcOnLoad を立てて、既定の設定の LibreOffice で開いたとき、古い値のまま": len(stale_cells(full_calc_lo)),
        "主なセル（書いた写しのまま → 計算し直した値）": {f"{s}!{r}": [stale.get((s, r)), recalced.get((s, r))] for s, r in key_cells},
        "主なセル（既定の設定の LibreOffice で開いた値）": {f"{s}!{r}": plain_lo.get((s, r)) for s, r in key_cells},
        "別紙4 を Python（そのまま切り捨て）でも計算して比べる": compare_values(recalced, kubun4_python(INPUTS[S4], rounddown_naive, roundup_naive)),
        "別紙4 を Python（15桁にそろえて切り捨て）でも計算して比べる": compare_values(recalced, kubun4_python(INPUTS[S4], rounddown_15, roundup_15)),
        "別紙4 の境目 I40（給与 1.035^3 倍、3年）": {
            "LibreOffice": recalced.get((S4, "I40")),
            "割る前の値（Python）": ((8_869_743 / 8_000_000) ** (1 / 3) - 1) * 100,
        },
    }

    (out / "e2b_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
