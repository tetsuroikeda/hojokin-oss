"""実験 E2a：Word の様式（事業計画書その1・2）に書き込んで、書式が壊れないかを見る。

1. downloads/ の様式の写しに試しの文を書く。書き方は2通り（python-docx で開いて保存／document.xml だけを直接書き換える）。
2. 書く前と後を、zip の部品の XML で比べる。書いてよい範囲（仮に決めたもの。下の RANGE_*）を覆ってから C14N で比べる。
3. 範囲の外をわざと変えた写しで、比べる道具が差を見つけるかを確かめる（否定の対照）。
4. LibreOffice で PDF にし、ページ数・向き・フォントを見る。
5. 社長が手で直した写しを4通り作り、直した箇所を取り出せるかを見る。

使い方（出力はリポの外に書く）：
  uv run --no-project --with python-docx --with lxml --with pypdf \
    python -I experiments/E2/e2a_word.py --out <リポの外のフォルダ>
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docx  # noqa: E402
from lxml import etree  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from e2_common import (  # noqa: E402
    WORD_FORM,
    convert,
    font_replacement_items,
    is_xml_part,
    prepare_out_dir,
    read_parts,
    require_form,
    write_parts,
    write_registry,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOC = "word/document.xml"

# 本文の表の順番：0 事業者情報、1 事業計画名、2 事業計画の概要、3 機械装置等、4 その1・2の本体（12行）、5 スケジュール
# 書いてよい範囲（仮）。製品では制度データの「書き込む位置」で決める（DESIGN 9章）
# - 表のセル全体の段落：事業者情報の右の列（□の選択肢がある2行目を除く）と、表1〜3の1セル
# - その1・2の本体の各行：見出しの段落の直後から、次の空でない段落（青字の説明など）の手前まで
RANGE_CELLS = [(0, r, 1) for r in (0, 2, 3, 4, 5, 6, 7)] + [(1, 0, 0), (2, 0, 0), (3, 0, 0)]
RANGE_SLOTS = [(4, r, 0) for r in range(12)]

# 試しの文（架空の会社。testdata/デモの会社 の社名を使う）
CELL_TEXTS = {
    (0, 0, 1): ["株式会社やまぶき惣菜（架空）"],
    (0, 2, 1): ["代表取締役（試しの値）"],
    (0, 3, 1): ["東京都大田区（試しの値）"],
    (0, 4, 1): ["食品製造業（惣菜）"],
    (0, 5, 1): ["（試しの値）"],
    (0, 6, 1): ["2人／7人"],
    (0, 7, 1): ["（なし）"],
    (1, 0, 0): ["盛り付けから包装までをつなぐ省力化ラインで多品種の惣菜を短納期で届ける"],
    (2, 0, 0): [
        "盛り付け・計量・包装が手作業で、人手不足が受注の上限になっている。"
        "画像検査つきの一貫ラインを入れて作業時間を減らし、空いた人手で病院・介護施設向けの細かい注文を増やす。"
    ],
    (3, 0, 0): ["盛り付けロボット一式　12,000千円（試しの値）", "画像検査つき計量包装機　10,500千円（試しの値）"],
}
SLOT_TEXTS = {
    0: ["当社は惣菜を作り、スーパーと病院・介護施設に届けている（試しの文）。", "直近3期の売上と利益は、下の表のとおりである（試しの文）。"],
    1: [
        "強みは、病院・介護施設ごとの細かい注文に、多品種・小ロット・短納期で応えられることである（試しの文）。"
        "一方で、盛り付け・計量・包装・検品はほとんどが手作業で、繁忙期には残業が増え、断る注文も出ている。"
        "この段落は、セルの中で行が折り返されるかを見るために、わざと長くしている。"
        "折り返しても、表の幅や余白は変わらないはずである。",
        "取引先は、日替わりの注文を前日の夕方に決めることが多い（試しの文）。",
    ],
    2: ["人手が足りず、注文を受けられる量に上限がある（試しの文）。"],
    4: ["盛り付けロボットと、画像検査つきの計量包装機を入れる（試しの文）。", "投資の総額は22,500千円（税抜。試しの値）である。"],
    8: ["空いた人手を新しい注文に回し、労働生産性と給与を上げる（試しの文）。"],
    11: ["補足はない（試しの文）。"],
}

# この Mac に入っていないフォントの置き換え先（Mac に初めから入っているフォントか、入っている BIZ UDPゴシック）
FONT_REPLACEMENTS = {
    "BIZ UD明朝 Medium": "Hiragino Mincho ProN",
    "BIZ UDゴシック": "BIZ UDPGothic",
    "ＭＳ Ｐゴシック": "Hiragino Sans",
    "ＭＳ ゴシック": "Hiragino Sans",
    "メイリオ": "Hiragino Sans",
}

# 手直しの試しで変える言い回し（SLOT_TEXTS[1] の1つ目の段落の中）
EDIT_OLD = "断る注文も出ている"
EDIT_NEW = "やむなく断る注文も月に数件ある"


# ---------------------------------------------------------------- 書き込み


def text_of(el) -> str:
    """段落などの文字。変更履歴で消した文字（w:delText）と、互換のための代わりの絵（mc:Fallback）の中は数えない。"""
    out = []
    for node in el.iter(W + "t", W + "tab", W + "br", MC + "Fallback"):
        if any(a.tag == MC + "Fallback" for a in node.iterancestors()) or node.tag == MC + "Fallback":
            continue
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        else:
            out.append("\n")
    return "".join(out)


def is_empty_paragraph(el) -> bool:
    if el.tag != W + "p":
        return False
    if text_of(el):
        return False
    return not any(True for _ in el.iter(W + "drawing", W + "pict", W + "object"))


def run_props(p):
    """段落の印の書式（w:pPr/w:rPr）を、書く run の書式として写す。Word で空の段落に打ったときと同じ。"""
    ppr = p.find(W + "pPr")
    mark = ppr.find(W + "rPr") if ppr is not None else None
    if mark is None:
        return None
    rpr = copy.deepcopy(mark)
    for child in list(rpr):
        if child.tag in (W + "ins", W + "del", W + "moveFrom", W + "moveTo"):
            rpr.remove(child)
    return rpr


def make_run(parent, text: str, rpr):
    r = parent.makeelement(W + "r", {})
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = etree.SubElement(r, W + "t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    return r


def write_paragraphs(p, texts: list[str]) -> list:
    """空の段落 p に1つ目の文を書き、残りは p の段落の書式を写した段落を後ろに足して書く。"""
    if not is_empty_paragraph(p):
        raise RuntimeError(f"空でない段落に書こうとしました：{text_of(p)[:30]}")
    template = copy.deepcopy(p)
    for child in list(template):
        if child.tag != W + "pPr":
            template.remove(child)
    rpr = run_props(p)
    p.append(make_run(p, texts[0], rpr))
    written = [p]
    prev = p
    for text in texts[1:]:
        q = copy.deepcopy(template)
        q.append(make_run(q, text, rpr))
        prev.addnext(q)
        written.append(q)
        prev = q
    return written


def cell(body, t: int, r: int, c: int):
    return body.findall(W + "tbl")[t].findall(W + "tr")[r].findall(W + "tc")[c]


def fill(body) -> list:
    written = []
    for (t, r, c), texts in CELL_TEXTS.items():
        written += write_paragraphs(cell(body, t, r, c).findall(W + "p")[0], texts)
    for r, texts in SLOT_TEXTS.items():
        tc = cell(body, 4, r, 0)
        children = [ch for ch in tc if ch.tag != W + "tcPr"]
        # 見出しの段落の直後の空の段落に書く
        written += write_paragraphs(children[1], texts)
    return written


def describe_written(written) -> list[dict]:
    rows = []
    for p in written:
        rpr = p.find(W + "r/" + W + "rPr")
        color = rpr.find(W + "color").get(W + "val") if rpr is not None and rpr.find(W + "color") is not None else "（段落の書式のまま）"
        size = rpr.find(W + "sz").get(W + "val") if rpr is not None and rpr.find(W + "sz") is not None else "（段落の書式のまま）"
        fonts = rpr.find(W + "rFonts") if rpr is not None else None
        font = fonts.get(W + "eastAsia") or fonts.get(W + "ascii") if fonts is not None else "（段落の書式のまま）"
        rows.append({"文の頭": text_of(p)[:16], "色": color, "大きさ": size, "フォント": font})
    return rows


def write_with_python_docx(src: Path, dst: Path) -> list[dict]:
    d = docx.Document(str(src))
    written = fill(d.element.body)
    info = describe_written(written)
    d.save(str(dst))
    return info


def write_direct(src: Path, dst: Path) -> list[dict]:
    parts = read_parts(src)
    root = etree.fromstring(parts[DOC])
    written = fill(root.find(W + "body"))
    info = describe_written(written)
    write_parts(src, dst, {DOC: serialize(root)})
    return info


def serialize(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# ---------------------------------------------------------------- 構造の比較


def c14n(el) -> bytes:
    return etree.tostring(el, method="c14n")


def c14n_bytes(data: bytes) -> bytes:
    try:
        return etree.tostring(etree.fromstring(data), method="c14n")
    except etree.C14NError:
        # 相対の名前空間などで C14N 1.0 が通らない部品は、C14N 2.0 でそろえる
        return etree.canonicalize(data.decode("utf-8")).encode("utf-8")


def mask_ranges(body_before, body_after):
    """書いてよい範囲を、前と後の両方で印（MASK）に置き換えた写しを返す。範囲の終わりが見つからなければ問題として返す。"""
    b = copy.deepcopy(body_before)
    a = copy.deepcopy(body_after)
    problems = []
    for k, (t, r, c) in enumerate(RANGE_CELLS):
        for body in (b, a):
            tc = cell(body, t, r, c)
            ps = tc.findall(W + "p")
            if not ps:
                continue
            ps[0].addprevious(tc.makeelement("MASK", {"n": f"cell{k}"}))
            for p in ps:
                tc.remove(p)
    for k, (t, r, c) in enumerate(RANGE_SLOTS):
        tc_b, tc_a = cell(b, t, r, c), cell(a, t, r, c)
        kids_b, kids_a = list(tc_b), list(tc_a)
        head = next(i for i, ch in enumerate(kids_b) if ch.tag == W + "p")
        end_b = next((i for i in range(head + 1, len(kids_b)) if not is_empty_paragraph(kids_b[i])), len(kids_b))
        if end_b < len(kids_b):
            anchor = c14n(kids_b[end_b])
            end_a = next((i for i in range(head + 1, len(kids_a)) if c14n(kids_a[i]) == anchor), None)
        else:
            end_a = len(kids_a)
        if end_a is None:
            problems.append(f"表{t} {r}行目：書いてよい範囲の終わり（{text_of(kids_b[end_b])[:20]}）が、書いた後に見つかりません")
            continue
        for tc, kids, end in ((tc_b, kids_b, end_b), (tc_a, kids_a, end_a)):
            kids[head].addnext(tc.makeelement("MASK", {"n": f"slot{k}"}))
            for ch in kids[head + 1 : end]:
                tc.remove(ch)
    return b, a, problems


EXPAND = {W + "tbl", W + "tr", W + "tc"}


def flatten(el, path: str = "body"):
    """表は行・セルまで開き、段落・表の設定・節の設定などを1つずつの単位にする。"""
    counts: dict[str, int] = {}
    for ch in el:
        tag = etree.QName(ch).localname if isinstance(ch.tag, str) else "?"
        counts[tag] = counts.get(tag, 0) + 1
        label = f"{path}/{tag}[{counts[tag]}]"
        if ch.tag in EXPAND:
            yield from flatten(ch, label)
        else:
            yield label, c14n(ch), text_of(ch)[:24]


def compare_document(parts_before: dict, parts_after: dict) -> dict:
    body_b = etree.fromstring(parts_before[DOC]).find(W + "body")
    body_a = etree.fromstring(parts_after[DOC]).find(W + "body")
    mb, ma, problems = mask_ranges(body_b, body_a)
    ub, ua = list(flatten(mb)), list(flatten(ma))
    sm = difflib.SequenceMatcher(a=[u[1] for u in ub], b=[u[1] for u in ua], autojunk=False)
    diffs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        diffs.append(
            {
                "種類": {"replace": "変わった", "delete": "なくなった", "insert": "増えた"}[op],
                "前": [f"{u[0]} 「{u[2]}」" for u in ub[i1:i2]],
                "後": [f"{u[0]} 「{u[2]}」" for u in ua[j1:j2]],
            }
        )
    # 文書の根（名前空間の宣言など）と、本文の外（節の設定は body の中なので上で比べている）
    root_b = etree.fromstring(parts_before[DOC])
    root_a = etree.fromstring(parts_after[DOC])
    for root in (root_b, root_a):
        root.remove(root.find(W + "body"))
    if c14n(root_b) != c14n(root_a):
        diffs.append({"種類": "変わった", "前": ["document の根"], "後": ["document の根"]})
    return {"単位の数": [len(ub), len(ua)], "差": diffs, "範囲の問題": problems}


def same_entries(x: bytes, y: bytes) -> bool:
    """[Content_Types].xml のように、子の並びに意味がない部品を、子の集まりとして比べる。"""
    kids = [sorted(c14n(ch) for ch in etree.fromstring(d)) for d in (x, y)]
    return kids[0] == kids[1]


def compare_parts(parts_before: dict, parts_after: dict) -> tuple[list[str], list[str]]:
    """document.xml 以外の部品を比べる。XML は C14N、ほかはバイトで比べる。差と、数えない注記を返す。"""
    out, notes = [], []
    for name in sorted(set(parts_before) | set(parts_after)):
        if name == DOC:
            continue
        if name not in parts_after:
            out.append(f"{name}：なくなった")
        elif name not in parts_before:
            out.append(f"{name}：増えた")
        else:
            x, y = parts_before[name], parts_after[name]
            same = c14n_bytes(x) == c14n_bytes(y) if is_xml_part(name) else x == y
            if same:
                continue
            if name == "[Content_Types].xml" and same_entries(x, y):
                notes.append(f"{name}：並びだけ変わった（中身の集まりは同じなので数えない）")
            else:
                out.append(f"{name}：中身が変わった")
    return out, notes


def structure_summary(parts: dict) -> dict:
    """T8-1 の物差しの項目ごとの数（範囲を覆わずに数える。書き込みで変わってはいけないもの）。"""
    root = etree.fromstring(parts[DOC])
    body = root.find(W + "body")
    tables = body.findall(W + "tbl")

    def h(name):
        return hashlib.sha256(c14n_bytes(parts[name])).hexdigest()[:10] if name in parts else "なし"

    sections = []
    for sect in root.iter(W + "sectPr"):
        pgsz, pgmar = sect.find(W + "pgSz"), sect.find(W + "pgMar")
        sections.append(
            {
                "用紙": f"{pgsz.get(W + 'w')}x{pgsz.get(W + 'h')} {pgsz.get(W + 'orient') or 'portrait'}",
                "余白": ",".join(f"{etree.QName(k).localname}={v}" for k, v in sorted(pgmar.attrib.items())),
                "ヘッダーの参照": len(sect.findall(W + "headerReference")),
                "フッターの参照": len(sect.findall(W + "footerReference")),
            }
        )
    return {
        "表の数（入れ子を含む）": len(list(body.iter(W + "tbl"))),
        "本文の表ごとの行の数": [len(t.findall(W + "tr")) for t in tables],
        "本文の表ごとのセルの数": [sum(len(tr.findall(W + "tc")) for tr in t.findall(W + "tr")) for t in tables],
        "横の結合（gridSpan）": len(list(body.iter(W + "gridSpan"))),
        "縦の結合（vMerge）": len(list(body.iter(W + "vMerge"))),
        "列の幅（tblGrid）": hashlib.sha256(b"".join(c14n(g) for g in body.iter(W + "tblGrid"))).hexdigest()[:10],
        "節": sections,
        "スタイル（styles.xml）": h("word/styles.xml"),
        "段落番号（numbering.xml）": h("word/numbering.xml"),
        "ヘッダー（header1.xml）": h("word/header1.xml"),
        "設定（settings.xml）": h("word/settings.xml"),
    }


def check(name: str, parts_before: dict, parts_after: dict) -> dict:
    doc = compare_document(parts_before, parts_after)
    others, notes = compare_parts(parts_before, parts_after)
    total = len(doc["差"]) + len(others) + len(doc["範囲の問題"])
    return {"名前": name, "範囲の外の差の数": total, "document.xml": doc, "ほかの部品": others, "注記": notes}


# ---------------------------------------------------------------- 否定の対照（範囲の外をわざと変える）


def mutate(src: Path, dst: Path, how: str) -> None:
    parts = read_parts(src)
    root = etree.fromstring(parts[DOC])
    body = root.find(W + "body")
    replace = {}
    if how == "余白を変える":
        pgmar = next(root.iter(W + "pgMar"))
        pgmar.set(W + "left", str(int(pgmar.get(W + "left")) + 100))
    elif how == "青字の説明を1文字変える":
        tc = cell(body, 4, 0, 0)
        p = next(p for p in tc.findall(W + "p") if text_of(p).startswith("※"))
        t = next(t for t in p.iter(W + "t") if t.text)
        t.text = "＊" + t.text[1:]
    elif how == "表に行を足す":
        tbl = body.findall(W + "tbl")[0]
        tbl.append(copy.deepcopy(tbl.findall(W + "tr")[-1]))
    elif how == "範囲の外のセル（□の選択肢）に書く":
        p = cell(body, 0, 1, 1).findall(W + "p")[0]
        p.append(make_run(p, "■", None))
    elif how == "説明の後ろ（範囲の外）に段落を足す":
        tc = cell(body, 4, 0, 0)
        p = next(p for p in tc.findall(W + "p") if text_of(p).startswith("※"))
        q = copy.deepcopy(p)
        p.addnext(q)
    elif how == "スタイルの文字の大きさを変える":
        styles = etree.fromstring(parts["word/styles.xml"])
        sz = next(styles.iter(W + "sz"))
        sz.set(W + "val", str(int(sz.get(W + "val")) + 2))
        replace["word/styles.xml"] = serialize(styles)
    else:
        raise ValueError(how)
    replace[DOC] = serialize(root)
    write_parts(src, dst, replace)


MUTATIONS = [
    "余白を変える",
    "青字の説明を1文字変える",
    "表に行を足す",
    "範囲の外のセル（□の選択肢）に書く",
    "説明の後ろ（範囲の外）に段落を足す",
    "スタイルの文字の大きさを変える",
]


# ---------------------------------------------------------------- PDF


def pdf_info(path: Path) -> dict:
    reader = PdfReader(str(path))
    pages = []
    fonts: set[str] = set()
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        pages.append("縦" if h >= w else "横")
        res = page.get("/Resources")
        font_dict = res.get_object().get("/Font") if res else None
        if font_dict:
            for ref in font_dict.get_object().values():
                fonts.add(str(ref.get_object().get("/BaseFont")))
    return {"ページ数": len(reader.pages), "向き": "".join(pages), "フォント": sorted({f.split("+")[-1] for f in fonts})}


def requested_fonts(path: Path) -> list[str]:
    """Word が求めるフォントの名前（多い順）。"""
    counts: dict[str, int] = {}
    for name, data in read_parts(path).items():
        if name.startswith("word/") and name.endswith(".xml"):
            for font in re.findall(rb'w:eastAsia="([^"]+)"', data):
                key = font.decode("utf-8")
                counts[key] = counts.get(key, 0) + 1
    return [f"{k}（{v}）" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def installed_font_files(pattern: str) -> list[str]:
    found = []
    for base in (Path("/Library/Fonts"), Path.home() / "Library/Fonts", Path("/System/Library/Fonts")):
        if base.is_dir():
            found += [p.name for p in base.rglob("*") if pattern.lower() in p.name.lower()]
    return sorted(found)


# ---------------------------------------------------------------- 手直しの取り出し


def items_of(path: Path) -> list[tuple[str, str]]:
    """文書を（項目の名前, 段落の文字）の並びにする。項目の名前は、見出し・左の列・直前の本文の段落から取る。"""
    root = etree.fromstring(read_parts(path)[DOC])
    body = root.find(W + "body")
    out: list[tuple[str, str]] = []
    last_heading = "（先頭）"

    def walk_cell(tc, label):
        for ch in tc:
            if ch.tag == W + "p":
                out.append((label, text_of(ch)))
            elif ch.tag == W + "tbl":
                for p in ch.iter(W + "p"):
                    out.append((label, text_of(p)))

    for el in body:
        if el.tag == W + "p":
            text = text_of(el)
            out.append(("本文", text))
            if text.strip():
                last_heading = text.strip()[:30]
        elif el.tag == W + "tbl":
            rows = el.findall(W + "tr")
            n_cells = sum(len(tr.findall(W + "tc")) for tr in rows)
            for tr in rows:
                tcs = tr.findall(W + "tc")
                for i, tc in enumerate(tcs):
                    if n_cells == 1:
                        label = last_heading
                    elif len(tcs) >= 2 and i > 0:
                        label = text_of(tcs[0]).strip()[:30] or last_heading
                    else:
                        first = next((text_of(p).strip() for p in tc.findall(W + "p") if text_of(p).strip()), "")
                        label = first[:30] or last_heading
                    walk_cell(tc, label)
    return out


def normalize(text: str) -> str:
    """タブ・改行・\xa0・続いた空白の違いは、言い回しの直しとみなさない（LibreOffice で保存し直すと変わるため）。"""
    text = text.replace("\t", "").replace("\n", "").replace("\r", "").replace("\xa0", " ")
    return re.sub(r" +", " ", text).strip()


def extract_edits(base: Path, edited: Path, normalized: bool) -> list[dict]:
    """前の版と手で直した版の差を、項目ごとに取り出す。normalized なら、空の段落と、normalize でそろう違いを数えない。"""

    def grouped(path):
        g: dict[str, list[str]] = {}
        for label, text in items_of(path):
            if normalized:
                text = normalize(text)
                if not text.strip():
                    continue
            g.setdefault(label, []).append(text)
        return g

    gb, ge = grouped(base), grouped(edited)
    edits = []
    for label in list(dict.fromkeys(list(gb) + list(ge))):
        xb, xe = gb.get(label, []), ge.get(label, [])
        sm = difflib.SequenceMatcher(a=xb, b=xe, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            item = {"項目": label, "前": xb[i1:i2], "後": xe[j1:j2]}
            if op == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
                cs = difflib.SequenceMatcher(a=xb[i1], b=xe[j1], autojunk=False)
                item["変わった所"] = [
                    f"「{xb[i1][a1:a2]}」→「{xe[j1][b1:b2]}」" for o, a1, a2, b1, b2 in cs.get_opcodes() if o != "equal"
                ]
            edits.append(item)
    return edits


def target_paragraph(body):
    tc = cell(body, 4, 1, 0)
    return next(p for p in tc.findall(W + "p") if EDIT_OLD in text_of(p))


def edit_like_word(src: Path, dst: Path) -> None:
    """Word で直したときのように、run を分け、rsid・proofErr・_GoBack の印を足して、言い回しを1か所変える。"""
    parts = read_parts(src)
    root = etree.fromstring(parts[DOC])
    p = target_paragraph(root.find(W + "body"))
    text = text_of(p)
    rpr = p.find(W + "r/" + W + "rPr")
    head, tail = text.split(EDIT_OLD, 1)
    for r in p.findall(W + "r"):
        p.remove(r)
    p.set(W + "rsidR", "00A1B2C3")
    p.set(W + "rsidRDefault", "00A1B2C3")
    pieces = [head[:10], head[10:], EDIT_NEW, tail]
    for i, piece in enumerate(pieces):
        if i == 2:
            p.append(p.makeelement(W + "proofErr", {W + "type": "spellStart"}))
            p.append(p.makeelement(W + "bookmarkStart", {W + "id": "0", W + "name": "_GoBack"}))
        r = make_run(p, piece, rpr)
        r.set(W + "rsidR", f"00D4E5F{i}")
        p.append(r)
        if i == 2:
            p.append(p.makeelement(W + "bookmarkEnd", {W + "id": "0"}))
            p.append(p.makeelement(W + "proofErr", {W + "type": "spellEnd"}))
    write_parts(src, dst, {DOC: serialize(root)})


def edit_simple(src: Path, dst: Path) -> None:
    parts = read_parts(src)
    root = etree.fromstring(parts[DOC])
    p = target_paragraph(root.find(W + "body"))
    t = next(t for t in p.iter(W + "t") if t.text and EDIT_OLD in t.text)
    t.text = t.text.replace(EDIT_OLD, EDIT_NEW, 1)
    write_parts(src, dst, {DOC: serialize(root)})


def edit_tracked(src: Path, dst: Path) -> None:
    """変更履歴を残したまま直した版（w:del と w:ins）。"""
    parts = read_parts(src)
    root = etree.fromstring(parts[DOC])
    p = target_paragraph(root.find(W + "body"))
    text = text_of(p)
    rpr = p.find(W + "r/" + W + "rPr")
    head, tail = text.split(EDIT_OLD, 1)
    for r in p.findall(W + "r"):
        p.remove(r)
    attrs = {W + "author": "社長（試し）", W + "date": "2026-11-03T10:00:00Z"}
    p.append(make_run(p, head, rpr))
    d = etree.SubElement(p, W + "del", {W + "id": "901", **attrs})
    dr = make_run(d, "", rpr)
    dr.remove(dr.find(W + "t"))
    dt = etree.SubElement(dr, W + "delText")
    dt.text = EDIT_OLD
    d.append(dr)
    ins = etree.SubElement(p, W + "ins", {W + "id": "902", **attrs})
    ins.append(make_run(ins, EDIT_NEW, rpr))
    p.append(make_run(p, tail, rpr))
    write_parts(src, dst, {DOC: serialize(root)})


# ---------------------------------------------------------------- 本体


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="出力先（リポの外）")
    args = ap.parse_args()
    out = prepare_out_dir(args.out)
    profile = out / "lo_profile"
    report: dict = {}

    form = out / "form.docx"
    form.write_bytes(require_form(WORD_FORM).read_bytes())
    parts_form = read_parts(form)
    report["様式の構造"] = structure_summary(parts_form)

    # 1・2. 2通りで書いて比べる
    results = {}
    for method, writer in (("python-docx", write_with_python_docx), ("XML を直接", write_direct)):
        dst = out / f"written_{'docx' if method == 'python-docx' else 'direct'}.docx"
        written = writer(form, dst)
        parts_w = read_parts(dst)
        res = check(method, parts_form, parts_w)
        res["書いた段落の書式"] = written
        res["書いた後の構造"] = structure_summary(parts_w)
        res["構造の数が様式と同じ"] = res["書いた後の構造"] == report["様式の構造"]
        results[method] = res
    report["書き込み"] = results

    # 3. 否定の対照（XML を直接書いた写しを、さらに範囲の外で変える）
    base = out / "written_direct.docx"
    parts_base = read_parts(base)
    negatives = []
    for how in MUTATIONS:
        dst = out / f"mutated_{MUTATIONS.index(how)}.docx"
        mutate(base, dst, how)
        res = check(how, parts_base, read_parts(dst))
        negatives.append(
            {
                "変え方": how,
                "見つけた差の数": res["範囲の外の差の数"],
                "見つけた差": [d["前"][:2] + ["→"] + d["後"][:2] for d in res["document.xml"]["差"]][:3] + res["ほかの部品"],
            }
        )
    report["否定の対照"] = negatives

    # 4. PDF
    pdf_dir = out / "pdf"
    report["PDF"] = {
        "Word が求めるフォント": requested_fonts(form),
        "この Mac に入っている BIZ UD のフォント": installed_font_files("BIZUD"),
    }
    for name, src in (("様式のまま", form), ("書いた後（python-docx）", out / "written_docx.docx"), ("書いた後（XML を直接）", base)):
        pdf = convert(src, "pdf", pdf_dir, profile)
        report["PDF"][name] = pdf_info(pdf)
    # 入っていないフォントの置き換えが、変換のたびに変わるかを見る
    report["PDF"]["同じ写しを3回変換"] = [pdf_info(convert(base, "pdf", pdf_dir / f"again{i}", profile)) for i in range(3)]
    # 置き換え表を固定したプロフィールなら、毎回同じになるかを見る
    fixed = out / "lo_profile_fonts"
    write_registry(fixed, font_replacement_items(FONT_REPLACEMENTS))
    report["PDF"]["置き換え表を固定して3回変換"] = {
        "置き換え表": FONT_REPLACEMENTS,
        "様式のまま": [pdf_info(convert(form, "pdf", pdf_dir / f"fixed_form{i}", fixed)) for i in range(3)],
        "書いた後": [pdf_info(convert(base, "pdf", pdf_dir / f"fixed{i}", fixed)) for i in range(3)],
    }

    # 5. 手直しの取り出し
    edits_dir = out / "edits"
    edits_dir.mkdir(exist_ok=True)
    lo_dir = edits_dir / "lo"
    v1 = edits_dir / "v1_word_like.docx"
    edit_like_word(base, v1)
    v2 = convert(base, "docx:MS Word 2007 XML", lo_dir / "v2", profile)
    v3_pre = edits_dir / "v3_edited.docx"
    edit_simple(base, v3_pre)
    v3 = convert(v3_pre, "docx:MS Word 2007 XML", lo_dir / "v3", profile)
    v4 = edits_dir / "v4_tracked.docx"
    edit_tracked(base, v4)
    variants = [
        ("(i) run を分け rsid・proofErr を足して1か所直した", v1, 1),
        ("(ii) 直さずに LibreOffice で保存し直した", v2, 0),
        ("(iii) 1か所直して LibreOffice で保存し直した", v3, 1),
        ("(iv) 変更履歴を残して1か所直した", v4, 1),
    ]
    report["手直しの取り出し"] = []
    for name, path, expected in variants:
        raw = extract_edits(base, path, normalized=False)
        norm = extract_edits(base, path, normalized=True)
        report["手直しの取り出し"].append(
            {"版": name, "見込みの件数": expected, "そのまま比べた件数": len(raw), "そろえて比べた件数": len(norm), "そのまま": raw[:6], "そろえて": norm}
        )

    (out / "e2a_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
