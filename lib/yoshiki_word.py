"""Word の様式（省力化の事業計画書 その1・2 など）の一覧づくり・書き込み・書き込み前後の構造の比較
（SPEC F8「様式に書式を壊さずに書き込む」T8-1、DESIGN 1.1「書いてよい範囲」・5章・6章・9.1。TASKS M6）。

- 一覧（outline）：様式の表・セル・文字のある段落を、場所の名前付きで並べる。読み取り役は、この一覧を見て、
  制度データの様式の項目を書き込む位置に対応づける（DESIGN 9.1）。
- 書き込み（write_item）：word/document.xml の、書いてよい範囲のバイトだけを差し替える。ほかの部品はバイトのまま残す。
  ElementTree で読み直して書き出すと名前空間の宣言が落ちるため（lib/xml_spans.py の冒頭の試し）。
  説明の青字（様式が「削除の上」と求める説明の文。色 0070C0）は、書いてよい範囲に含めて消す（S0 で決めた）。
- 比べる（compare_docx）：直前の版と、書いた後を、zip の部品の XML どうしで比べる（DESIGN 5章。ライブラリで読み直した
  ものでは比べない）。書いてよい範囲を前と後の両方で覆い、残りが1か所でも違えば差として返す。書く道具は、差が
  あれば保存しない。

場所の名前（一覧と、制度データの「書き込む位置」の「場所」で使う。数は0から）
- 本文のすぐ下の表は t0, t1 …、段落は p0, p1 …（表と段落は別々に数える）。
- 表の中は、行 r、セル c で続ける：t4.r2.c0 は、本文の5つ目の表の3行目の1つ目のセル。
- セルの中の段落・表も同じく続ける：t4.r2.c0.p0、t4.r0.c0.t0.r6.c1。

書き込む位置（制度データの 様式[].項目[].書き込む位置。形は M6 で決めた仮の形）
- {"見出し": "１‐2経営課題", "場所": "t4.r2.c0.p0", "範囲": "見出しの後"}
  見出しの段落の後から、そのセルの終わり（セルの中に表があれば、その手前）までの段落。見出しの段落は、セルの中に
  あること。見出しは文字で探し（全角・半角と空白の違いは見ない）、様式の中に1つだけならそれを、2つ以上なら場所で
  指したものを使う。
- {"見出し": "（２）事業計画名（３０字程度）", "場所": "t1.r0.c0", "範囲": "セル"}
  そのセルの段落すべて（セルの中に表があれば、その手前まで）。見出しは、同じ行のほかのセルの文字か、そのセルの
  表のすぐ前にある文字のある段落であること。

書く文の書式：書いてよい範囲の空の段落（なければ最初の段落）の段落の書式を写す。文字の書式は、その段落の印の書式から、
色（w:color）と変更履歴の印を除いたものにする（実験 E2：印の書式をそのまま写すと、補足事項の行で書いた文字が青になった）。
新しい段落には、Word の段落の番号（w14:paraId など）を付けない（同じ番号が2つあると、Word が修復を求めることがある）。

図表と写真（TASKS B33。図は lib/zuhyo.py が作る）：書く文の「図を置く行」（【図：前後比較】など）は、その図の段落にする。
図の幅は、書いてよい範囲のセルの幅（とページの本文の幅）に収め、高さは縦横の比を保つ（T8-3「余白からはみ出さない」）。
画像は word/media/hojokin_zu_<中身のハッシュ>.png に置き、関係（rIdHojokinZu…）と種類の登録を足す。書き直して使われなく
なった、この道具の画像と関係は片付ける。範囲の外の比較では、この道具の画像・関係と、png・jpeg の種類の登録だけを差に数えない。

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import difflib
import hashlib
import io
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape, quoteattr

from lib import xml_spans
from lib.docx_min import clean_text
from lib.xml_spans import Node

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
DOC = "word/document.xml"
CONTENT_TYPES = "[Content_Types].xml"

AFTER_HEADING = "見出しの後"
CELL = "セル"
KINDS = (AFTER_HEADING, CELL)

# 様式の説明の青字（その1・2 の冒頭に「説明の青字は削除の上」とある）
EXPLANATION_COLORS = ("0070C0",)
# 範囲の段落を消しても残す印（対になる相手が範囲の外にあるとき、片方だけ消すと壊れるため）
KEEP_MARKS = ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "permStart", "permEnd",
              "moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")
# 書く文字の書式から除くもの（色と、変更履歴の印）
DROP_FROM_RUN = ("color", "ins", "del", "moveFrom", "moveTo", "rPrChange")
# 写した段落の書式から除くもの（節の区切りと、変更履歴の印）
DROP_FROM_PARAGRAPH = ("sectPr", "pPrChange")
EXPANDED = ("tbl", "tr", "tc")
MAX_SHOWN = 80
MAX_DIFFS = 20


# 表の欄を持つ項目（「（1）事業者情報」の商号又は名称など）の欄の名前の区切り（TASKS B14a）
FIELD_SEP = "：欄："

# 図表と写真（TASKS B33）
RELS = "word/_rels/document.xml.rels"
FIGURE_REL_PREFIX = "rIdHojokinZu"
FIGURE_MEDIA_PREFIX = "word/media/hojokin_zu_"
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU_PER_TWIP = 635
CELL_MARGIN = 108          # セルの左右の余白の既定（twip）
MAX_FIGURE_EMU = 5760000   # 図の幅の上限 16cm
MAX_PHOTO_EMU = 4320000    # 写真の幅と高さの上限 12cm
FALLBACK_WIDTH = 9638      # 幅が分からないときの本文の幅（A4、左右の余白 20mm）
_FIGURE_RELS = re.compile(rb'<Relationship\b[^>]*\bId="' + FIGURE_REL_PREFIX.encode() + rb'[0-9a-f]+"[^>]*/>')
_IMAGE_DEFAULTS = re.compile(rb'<Default\b[^>]*\bExtension="(?:png|jpeg)"[^>]*/>', re.I)


def field_label(item: str, field: str) -> str:
    return f"{item}{FIELD_SEP}{field}"


def item_positions(form: Dict) -> List[Tuple[str, Dict]]:
    """様式の項目と、項目の「欄」の、対応づけた書き込む位置（名前, 位置）。欄の名前は「項目：欄：欄の名前」。

    表の欄を持つ項目は、制度データの項目に `"欄": [{"名前": "商号又は名称", "書き込む位置": {…}}]` を持つ。
    """
    out = []
    for entry in form.get("項目") or [] if isinstance(form, dict) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("名前"))
        pos = entry.get("書き込む位置")
        if isinstance(pos, dict) and pos.get("範囲"):
            out.append((name, pos))
        for sub in entry.get("欄") or []:
            spos = sub.get("書き込む位置") if isinstance(sub, dict) else None
            if isinstance(spos, dict) and spos.get("範囲"):
                out.append((field_label(name, str(sub.get("名前"))), spos))
    return out


class FormError(ValueError):
    """様式を読めない、書き込む位置が見つからない・正しくない。"""


class OutsideChange(ValueError):
    """書くと、書いてよい範囲の外が変わる（保存しない）。differences に差の一覧。"""

    def __init__(self, differences: List[str]) -> None:
        super().__init__("書いてよい範囲の外が変わります")
        self.differences = differences


# ---------------------------------------------------------------- zip の部品


def read_parts(blob: bytes) -> Tuple[List[zipfile.ZipInfo], Dict[str, bytes]]:
    """zip の部品の一覧と中身。読めなければ FormError。"""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            parts = {info.filename: zf.read(info) for info in infos}
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError) as e:
        raise FormError(f"Word・Excel のファイルとして読めません（{e}）") from e
    return infos, parts


def rebuild_zip(blob: bytes, replacements: Dict[str, bytes], additions: Optional[Dict[str, bytes]] = None,
                removals: Sequence[str] = ()) -> bytes:
    """blob の zip の部品を、同じ順・同じ設定で書き直す。replacements の部品だけ中身を替える。
    additions の部品は終わりに足し（図の画像）、removals の部品は書かない（使われなくなった図の画像）。"""
    infos, parts = read_parts(blob)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in infos:
            if info.filename in removals:
                continue
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            new.create_system = info.create_system
            zf.writestr(new, replacements.get(info.filename, parts[info.filename]))
        for name, data in sorted((additions or {}).items()):
            if name in parts:
                continue
            new = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            new.compress_type = zipfile.ZIP_STORED  # 画像は縮まないので、そのまま入れる
            new.external_attr = 0o644 << 16
            zf.writestr(new, data)
    return out.getvalue()


# ---------------------------------------------------------------- 段落の文字と色


def _skipped(node: Node) -> bool:
    """互換のための代わりの絵（mc:Fallback）と、消した文字・フィールドの式の中は数えない。"""
    return node.is_(MC, "Fallback") or (node.uri == W and node.local in ("delText", "instrText"))


def text_of(node: Node) -> str:
    out: List[str] = []

    def walk(n: Node) -> None:
        if _skipped(n):
            return
        if n.uri == W:
            if n.local == "t":
                out.append(n.text)
            elif n.local == "tab":
                out.append("\t")
            elif n.local in ("br", "cr"):
                out.append("\n")
        for c in n.children:
            walk(c)

    walk(node)
    return "".join(out)


def _runs(node: Node) -> Iterator[Node]:
    if _skipped(node):
        return
    if node.is_(W, "r"):
        yield node
        return
    for c in node.children:
        yield from _runs(c)


def run_color(run: Node) -> str:
    rpr = run.find(W, "rPr")
    color = rpr.find(W, "color") if rpr is not None else None
    value = color.attr(W, "val") if color is not None else None
    return (value or "").upper()


def blue_state(p: Node) -> str:
    """段落の文字のうち、説明の青字がどれだけか（「全部」「一部」「」）。"""
    colored = [run_color(r) in EXPLANATION_COLORS for r in _runs(p) if text_of(r).strip()]
    if not colored or not any(colored):
        return ""
    return "全部" if all(colored) else "一部"


def has_drawing(p: Node) -> bool:
    return any(n.uri == W and n.local in ("drawing", "pict", "object") for n in p.iter())


def norm(text: str) -> str:
    """見出しを比べる形（全角・半角をそろえ、空白をすべて除く）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


# ---------------------------------------------------------------- 場所の名前


def body_of(root: Node) -> Node:
    body = root.find(W, "body")
    if body is None or not root.is_(W, "document"):
        raise FormError("Word の本文（w:body）が見つかりません")
    return body


_LETTER = {"tbl": "t", "p": "p", "tr": "r", "tc": "c"}
_LOCAL = {v: k for k, v in _LETTER.items()}


def path_of(node: Node) -> str:
    parts: List[str] = []
    n: Optional[Node] = node
    while n is not None and not n.is_(W, "body"):
        if n.uri != W or n.local not in _LETTER or n.parent is None:
            raise FormError("場所の名前を付けられない所です")
        same = [c for c in n.parent.children if c.is_(W, n.local)]
        parts.append(f"{_LETTER[n.local]}{same.index(n)}")
        n = n.parent
    return ".".join(reversed(parts))


def node_at(body: Node, place: str) -> Optional[Node]:
    """場所の名前（t4.r2.c0.p0 など）の要素。なければ None。"""
    node = body
    for token in str(place).split("."):
        m = re.fullmatch(r"([tprc])([0-9]+)", token.strip())
        if m is None:
            return None
        same = node.findall(W, _LOCAL[m.group(1)])
        k = int(m.group(2))
        if k >= len(same):
            return None
        node = same[k]
    return node if node is not body else None


# ---------------------------------------------------------------- 一覧


def _shown(text: str) -> str:
    text = text.replace("\n", " ").replace("\t", " ")
    return text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN] + "…"


def _merge(tc: Node) -> str:
    pr = tc.find(W, "tcPr")
    if pr is None:
        return ""
    out = []
    span = pr.find(W, "gridSpan")
    if span is not None and (span.attr(W, "val") or "1") != "1":
        out.append(f"横に{span.attr(W, 'val')}つ分")
    vmerge = pr.find(W, "vMerge")
    if vmerge is not None:
        out.append("縦の結合の始まり" if vmerge.attr(W, "val") == "restart" else "縦の結合の続き")
    return "・".join(out)


def outline(root: Node) -> List[Dict]:
    """表・セル・文字のある段落の一覧（空の段落は、セルの段落の数にだけ数える）。"""
    entries: List[Dict] = []

    def walk(container: Node, depth: int) -> None:
        for child in container.children:
            if child.is_(W, "p"):
                text = text_of(child)
                if not text.strip():
                    continue
                entry = {"場所": path_of(child), "種類": "段落", "文字": _shown(text.strip()), "深さ": depth}
                blue = blue_state(child)
                if blue:
                    entry["説明の青字"] = blue
                entries.append(entry)
            elif child.is_(W, "tbl"):
                rows = child.findall(W, "tr")
                entries.append({"場所": path_of(child), "種類": "表", "行": len(rows),
                                "列": [len(r.findall(W, "tc")) for r in rows], "深さ": depth})
                for tr in rows:
                    for tc in tr.findall(W, "tc"):
                        paras = tc.findall(W, "p")
                        filled = [text_of(p).strip() for p in paras if text_of(p).strip()]
                        entry = {"場所": path_of(tc), "種類": "セル", "段落": len(paras),
                                 "空": not filled, "深さ": depth + 1}
                        merge = _merge(tc)
                        if merge:
                            entry["結合"] = merge
                        entries.append(entry)
                        walk(tc, depth + 2)

    walk(body_of(root), 0)
    return entries


def outline_text(entries: Sequence[Dict]) -> str:
    lines = []
    for e in entries:
        pad = "  " * e["深さ"]
        if e["種類"] == "表":
            lines.append(f"{pad}{e['場所']} 表（{e['行']}行。行ごとのセルの数 {e['列']}）")
        elif e["種類"] == "セル":
            extra = f"、{e['結合']}" if e.get("結合") else ""
            lines.append(f"{pad}{e['場所']} セル（段落{e['段落']}{'、空' if e['空'] else ''}{extra}）")
        else:
            blue = f"【説明の青字：{e['説明の青字']}】" if e.get("説明の青字") else ""
            lines.append(f"{pad}{e['場所']} 段落{blue}「{e['文字']}」")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 書き込む位置と、書いてよい範囲


class Range:
    """container の子の [start, end) が書いてよい範囲。"""

    def __init__(self, container: Node, start: int, end: int, label: str) -> None:
        self.container = container
        self.start = start
        self.end = end
        self.label = label

    @property
    def nodes(self) -> List[Node]:
        return self.container.children[self.start:self.end]


def _paragraphs(root: Node) -> List[Node]:
    out: List[Node] = []

    def walk(n: Node) -> None:
        if _skipped(n):
            return
        if n.is_(W, "p"):
            out.append(n)
        for c in n.children:
            walk(c)

    walk(body_of(root))
    return out


def find_heading(root: Node, heading: str, place: Optional[str] = None) -> Node:
    key = norm(heading)
    if not key:
        raise FormError("見出しが空です")
    found = [p for p in _paragraphs(root) if norm(text_of(p)) == key]
    if place:
        node = node_at(body_of(root), place)
        if node is not None and node in found:
            return node
    if len(found) == 1:
        return found[0]
    if not found:
        raise FormError(f"見出し「{heading}」の段落が、様式にありません")
    raise FormError(f"見出し「{heading}」の段落が様式に{len(found)}つあり、場所（{place or 'なし'}）で決められません")


def _until_table(children: List[Node], start: int) -> int:
    end = start
    while end < len(children) and not children[end].is_(W, "tbl"):
        end += 1
    return end


def _heading_near_cell(cell: Node, heading: str) -> bool:
    """見出しが、同じ行のほかのセルにあるか、同じ列の1行目のセル（列の見出し）にあるか、
    そのセルの表のすぐ前の文字のある段落か。列の見出しは、役割分担の表（役職／氏名／担当内容…）のように、
    見出しの行の下の行に書く表のため（11/7 のリハーサル）。"""
    key = norm(heading)
    row = cell.parent
    if row is not None:
        for other in row.findall(W, "tc"):
            if other is not cell and any(norm(text_of(p)) == key for p in other.findall(W, "p")):
                return True
    table = row.parent if row is not None else None
    if table is None or table.parent is None:
        return False
    rows = table.findall(W, "tr")
    if rows and row is not rows[0]:
        cells, top = row.findall(W, "tc"), rows[0].findall(W, "tc")
        k = cells.index(cell)
        if len(top) == len(cells) and k < len(top) and any(norm(text_of(p)) == key for p in top[k].findall(W, "p")):
            return True
    siblings = table.parent.children
    for node in reversed(siblings[:siblings.index(table)]):
        if node.is_(W, "p") and text_of(node).strip():
            return norm(text_of(node)) == key
        if node.is_(W, "tbl"):
            return False
    return False


def resolve(root: Node, position: Dict, label: str = "") -> Range:
    """書き込む位置から、書いてよい範囲を決める。決められなければ FormError。"""
    if not isinstance(position, dict):
        raise FormError("書き込む位置が { } の形ではありません")
    kind = position.get("範囲")
    heading = position.get("見出し")
    place = position.get("場所")
    label = label or str(heading)
    if kind not in KINDS:
        raise FormError(f"書き込む位置の「範囲」は {'・'.join(KINDS)} のどれかにしてください（いまは {kind!r}）")
    if not isinstance(heading, str) or not heading.strip():
        raise FormError("書き込む位置に「見出し」（様式の文字のまま）がありません")
    if place is not None and not isinstance(place, str):
        raise FormError("書き込む位置の「場所」は文字にしてください（例：t4.r2.c0.p0）")
    if kind == AFTER_HEADING:
        node = find_heading(root, heading, place)
        cell = node.parent
        if cell is None or not cell.is_(W, "tc"):
            raise FormError(f"見出し「{heading}」の段落が表のセルの中にありません（「見出しの後」はセルの中の見出しに使う）")
        children = cell.children
        start = children.index(node) + 1
        end = _until_table(children, start)
    else:
        if not place:
            raise FormError("「セル」の書き込む位置には、セルの「場所」（例：t1.r0.c0）が要ります")
        cell = node_at(body_of(root), place)
        if cell is None or not cell.is_(W, "tc"):
            raise FormError(f"場所 {place} は、様式のセルではありません")
        if not _heading_near_cell(cell, heading):
            raise FormError(f"場所 {place} のセルの近く（同じ行か、表のすぐ前）に、見出し「{heading}」がありません")
        children = cell.children
        start = 0
        while start < len(children) and children[start].is_(W, "tcPr"):
            start += 1
        end = _until_table(children, start)
    rng = Range(cell, start, end, label)
    if not any(n.is_(W, "p") for n in rng.nodes):
        raise FormError(f"「{label}」の書いてよい範囲に段落がありません")
    return rng


def check_position(root: Node, position: Dict, label: str = "") -> Dict:
    """読み取り役の対応づけを確かめ、制度データに書く形にそろえる。正しくなければ FormError。"""
    rng = resolve(root, position, label)
    out = {"見出し": position["見出し"], "範囲": position["範囲"]}
    if position["範囲"] == AFTER_HEADING:
        heading = rng.container.children[rng.start - 1]
        out["場所"] = path_of(heading)
    else:
        out["場所"] = position["場所"]
    for key, value in position.items():
        if key not in out:
            out[key] = value
    return out


# ---------------------------------------------------------------- 書く


def _clean_props(data: bytes, node: Node, drop: Sequence[str], rpr_drop: Sequence[str] = ()) -> bytes:
    """要素 node の写し。drop の子（W の名前空間）を除き、rPr の子は rpr_drop を除く。"""
    if node.tag_end == node.end:  # 空の要素（<w:pPr/>）
        return node.raw(data)
    out = [node.start_tag(data)]
    for child in node.children:
        if child.uri == W and child.local in drop:
            continue
        if child.is_(W, "rPr") and rpr_drop:
            out.append(_clean_props(data, child, rpr_drop))
        else:
            out.append(child.raw(data))
    out.append(f"</{node.name}>".encode("utf-8"))
    return b"".join(out)


def _template(paragraphs: List[Node]) -> Node:
    for p in paragraphs:
        if not text_of(p).strip() and not has_drawing(p):
            return p
    for p in paragraphs:
        if blue_state(p) != "全部":
            return p
    return paragraphs[0]


def _field_balance(nodes: Sequence[Node]) -> int:
    balance = 0
    for top in nodes:
        for n in top.iter():
            if n.is_(W, "fldChar"):
                kind = n.attr(W, "fldCharType")
                balance += 1 if kind == "begin" else (-1 if kind == "end" else 0)
    return balance


def _kept_marks(data: bytes, nodes: Sequence[Node]) -> bytes:
    out = []
    for top in nodes:
        for n in top.iter():
            if n.uri == W and n.local in KEEP_MARKS:
                out.append(n.raw(data))
    return b"".join(out)


def _run_text(w: str, line: str) -> str:
    pieces = []
    for i, part in enumerate(line.split("\t")):
        if i:
            pieces.append(f"<{w}:tab/>")
        if part:
            pieces.append(f'<{w}:t xml:space="preserve">{escape(part)}</{w}:t>')
    return "".join(pieces)


class Placed:
    """図を置く行に入れる絵の、Word の中での形（関係の番号、部品の名前、大きさ、図の番号）。"""

    def __init__(self, figure, rid: str, media: str, cx: int, cy: int, docpr: int) -> None:
        self.figure, self.rid, self.media, self.cx, self.cy, self.docpr = figure, rid, media, cx, cy, docpr


def _figure_paragraph(w: str, placed: Placed, kept: bytes) -> bytes:
    """図の段落。行の高さを固定した段落の書式を写すと絵が切れるので、書式は写さず、中央に置く。"""
    title = quoteattr(placed.figure.title)
    name = quoteattr(f"図 {placed.docpr}")
    inline = (
        f'<wp:inline xmlns:wp="{NS_WP}" distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{placed.cx}" cy="{placed.cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{placed.docpr}" name={name} descr={title}/>'
        f'<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="{NS_A}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic xmlns:a="{NS_A}"><a:graphicData uri="{NS_PIC}"><pic:pic xmlns:pic="{NS_PIC}">'
        f'<pic:nvPicPr><pic:cNvPr id="{placed.docpr}" name={name} descr={title}/><pic:cNvPicPr><a:picLocks noChangeAspect="1"/>'
        f'</pic:cNvPicPr></pic:nvPicPr><pic:blipFill><a:blip xmlns:r="{NS_R}" r:embed="{placed.rid}"/>'
        f'<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{placed.cx}" cy="{placed.cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        f'</pic:pic></a:graphicData></a:graphic></wp:inline>'
    )
    ppr = (f'<{w}:pPr><{w}:spacing {w}:before="60" {w}:after="60" {w}:line="240" {w}:lineRule="auto"/>'
           f'<{w}:ind {w}:left="0" {w}:right="0" {w}:firstLine="0"/><{w}:jc {w}:val="center"/></{w}:pPr>')
    return (f"<{w}:p>{ppr}".encode("utf-8") + kept
            + f"<{w}:r><{w}:drawing>{inline}</{w}:drawing></{w}:r></{w}:p>".encode("utf-8"))


def new_paragraphs(data: bytes, rng: Range, text: str, placed: Optional[Dict[str, Placed]] = None) -> bytes:
    """範囲を置き換える段落のバイト列。placed の行（図を置く行）は、図の段落にする。"""
    placed = placed or {}
    nodes = rng.nodes
    paragraphs = [n for n in nodes if n.is_(W, "p")]
    template = _template(paragraphs)
    w = template.prefix
    ppr = template.find(W, "pPr")
    ppr_bytes = _clean_props(data, ppr, DROP_FROM_PARAGRAPH, DROP_FROM_RUN) if ppr is not None else b""
    mark = ppr.find(W, "rPr") if ppr is not None else None
    rpr_bytes = _clean_props(data, mark, DROP_FROM_RUN) if mark is not None else b""
    kept = _kept_marks(data, nodes)
    lines = clean_text(text).split("\n")
    out = []
    for i, line in enumerate(lines):
        if line.strip() in placed:
            out.append(_figure_paragraph(w, placed[line.strip()], kept if i == 0 else b""))
            continue
        body = _run_text(w, line)
        run = (f"<{w}:r>".encode("utf-8") + rpr_bytes + body.encode("utf-8") + f"</{w}:r>".encode("utf-8")) if body else b""
        out.append(f"<{w}:p>".encode("utf-8") + ppr_bytes + (kept if i == 0 else b"") + run + f"</{w}:p>".encode("utf-8"))
    return b"".join(out)


# ---------------------------------------------------------------- 図表と写真の置き場所と大きさ


def _twips(node: Optional[Node], name: str) -> Optional[int]:
    if node is None:
        return None
    value = node.attr(W, name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def available_width(root: Node, rng: Range) -> int:
    """図を置ける幅（twip）。セルの幅から左右の余白を引いたものと、ページの本文の幅の、小さいほう。"""
    page = FALLBACK_WIDTH
    body = body_of(root)
    sect = next((c for c in reversed(body.children) if c.is_(W, "sectPr")), None)
    if sect is not None:
        size, margin = sect.find(W, "pgSz"), sect.find(W, "pgMar")
        sw, left, right = _twips(size, "w"), _twips(margin, "left"), _twips(margin, "right")
        if sw and left is not None and right is not None and sw - left - right > 0:
            page = sw - left - right
    cell = rng.container
    width = page
    if cell.is_(W, "tc"):
        tcpr = cell.find(W, "tcPr")
        tcw = tcpr.find(W, "tcW") if tcpr is not None else None
        if tcw is not None and (tcw.attr(W, "type") in (None, "dxa")):
            w = _twips(tcw, "w")
            if w:
                mar = tcpr.find(W, "tcMar")
                lm = _twips(mar.find(W, "left") if mar is not None else None, "w")
                rm = _twips(mar.find(W, "right") if mar is not None else None, "w")
                width = min(page, w - (CELL_MARGIN if lm is None else lm) - (CELL_MARGIN if rm is None else rm))
    return max(width, 1000)


def _docpr_ids(data: bytes) -> List[int]:
    return [int(m) for m in re.findall(rb'<(?:\w+:)?docPr\b[^>]*?\bid="(\d+)"', data)]


def place_figures(data: bytes, root: Node, rng: Range, text: str, figures: Dict) -> Dict[str, Placed]:
    """書く文の図を置く行ごとに、関係の番号・部品の名前・大きさ（EMU）・図の番号を決める。"""
    width_emu = available_width(root, rng) * EMU_PER_TWIP
    next_id = max(_docpr_ids(data) + [0]) + 1
    out: Dict[str, Placed] = {}
    for line in clean_text(text).split("\n"):
        key = line.strip()
        if key not in figures or key in out:
            continue
        fig = figures[key]
        digest = hashlib.sha1(fig.data).hexdigest()[:12]
        ext = "jpeg" if fig.kind == "jpeg" else "png"
        cx = min(width_emu, MAX_PHOTO_EMU if fig.photo else MAX_FIGURE_EMU)
        cy = int(cx * fig.height_px / max(fig.width_px, 1))
        if fig.photo and cy > MAX_PHOTO_EMU:  # 縦長の写真は、高さで収める
            cx, cy = int(MAX_PHOTO_EMU * fig.width_px / max(fig.height_px, 1)), MAX_PHOTO_EMU
        out[key] = Placed(fig, FIGURE_REL_PREFIX + digest, f"{FIGURE_MEDIA_PREFIX}{digest}.{ext}", cx, cy, next_id)
        next_id += 1
    return out


def figure_text(p: Node) -> str:
    """段落の中の絵の代わりの文（「［図：題］」）。絵がなければ空（審査役に渡す本文で、図があることを示すため）。"""
    out = []
    for n in p.iter():
        if n.local == "docPr" and n.uri == NS_WP:
            descr = n.attrs.get("descr")
            out.append(f"［図：{descr}］" if descr else "［図］")
    return "".join(out)


def _with_figure_parts(parts: Dict[str, bytes], new_doc: bytes, placed: Dict[str, Placed]
                       ) -> Tuple[Dict[str, bytes], Dict[str, bytes], List[str]]:
    """（差し替える部品、足す部品、消す部品）。使われなくなった、この道具の画像と関係は片付ける。"""
    rels = parts.get(RELS)
    if rels is None and placed:
        raise FormError(f"Word の関係の部品（{RELS}）がないので、図を入れられません")
    used = set(re.findall(rb'embed="(' + FIGURE_REL_PREFIX.encode() + rb'[0-9a-f]+)"', new_doc))
    replace: Dict[str, bytes] = {}
    add: Dict[str, bytes] = {}
    remove: List[str] = []
    if rels is not None:
        new_rels = _FIGURE_RELS.sub(lambda m: m.group(0) if re.search(rb'Id="([^"]+)"', m.group(0)).group(1) in used
                                    else b"", rels)
        have = set(re.findall(rb'Id="(' + FIGURE_REL_PREFIX.encode() + rb'[0-9a-f]+)"', new_rels))
        additions = []
        for p in placed.values():
            if p.rid.encode() not in have:
                additions.append(f'<Relationship Id="{p.rid}" Type="{REL_IMAGE}" '
                                 f'Target="{p.media[len("word/"):]}"/>'.encode("utf-8"))
                have.add(p.rid.encode())
                add[p.media] = p.figure.data
        if additions:
            m = re.search(rb"</(?:\w+:)?Relationships>\s*$", new_rels)
            if m is None:
                raise FormError(f"Word の関係の部品（{RELS}）の形が想定と違うので、図を入れられません")
            new_rels = new_rels[:m.start()] + b"".join(additions) + new_rels[m.start():]
        if new_rels != rels:
            replace[RELS] = new_rels
        kept_targets = {f"word/{t.decode()}" for t in re.findall(rb'Target="(media/hojokin_zu_[^"]+)"', new_rels)}
        remove = [name for name in parts if name.startswith(FIGURE_MEDIA_PREFIX) and name not in kept_targets]
    types = parts.get(CONTENT_TYPES)
    if types is not None and placed:
        new_types = types
        for ext in sorted({p.media.rsplit(".", 1)[1] for p in placed.values()}):
            if not re.search(rb'<Default\b[^>]*\bExtension="' + ext.encode() + rb'"', new_types, re.I):
                m = re.search(rb"<(?:\w+:)?Types\b[^>]*>", new_types)
                if m is None:
                    raise FormError("Word の種類の部品の形が想定と違うので、図を入れられません")
                default = f'<Default Extension="{ext}" ContentType="image/{ext}"/>'.encode("utf-8")
                new_types = new_types[:m.end()] + default + new_types[m.end():]
        if new_types != types:
            replace[CONTENT_TYPES] = new_types
    return replace, add, remove


FIGURE_LINE = re.compile(r"^\s*【(図|写真)：.+】\s*$")


def write_item(blob: bytes, position: Dict, text: str, label: str = "",
               other_positions: Sequence[Tuple[str, Dict]] = (), figures: Optional[Dict] = None) -> Tuple[bytes, Dict]:
    """Word のファイル blob の、position の書いてよい範囲に text を書いたファイルのバイト列と、書いたことの要約。

    figures は、図を置く行 → 絵（lib/zuhyo.py の Figure）。書いた後に直前の版（blob）と比べ、範囲の外が1か所でも
    変わっていれば OutsideChange（保存しない）。
    """
    if not clean_text(text).strip():
        raise FormError("書く文が空です")
    figures = figures or {}
    missing = [ln.strip() for ln in clean_text(text).split("\n") if FIGURE_LINE.match(ln) and ln.strip() not in figures]
    if missing:
        raise FormError(f"図を置く行（{'、'.join(missing)}）の図がありません。書きません")
    _infos, parts = read_parts(blob)
    if DOC not in parts:
        raise FormError(f"Word の本文の部品（{DOC}）がありません")
    data = parts[DOC]
    root = xml_spans.parse(data)
    rng = resolve(root, position, label)
    nodes = rng.nodes
    if _field_balance(nodes) != 0:
        raise FormError(f"「{rng.label}」の書いてよい範囲に、範囲の外へまたがるフィールドがあります。書きません")
    removed_blue = sum(1 for n in nodes if n.is_(W, "p") and blue_state(n))
    placed = place_figures(data, root, rng, text, figures)
    new_data = xml_spans.splice(data, nodes[0].start, nodes[-1].end, new_paragraphs(data, rng, text, placed))
    replace, add, remove = _with_figure_parts(parts, new_data, placed)
    replace[DOC] = new_data
    # 足す・消す部品（図の画像）があるときだけ渡す（図のない書き込みは、前と同じ呼び方のまま）
    extra = {k: v for k, v in (("additions", add), ("removals", remove)) if v}
    new_blob = rebuild_zip(blob, replace, **extra)
    positions = [(rng.label, position)] + [(lab, pos) for lab, pos in other_positions if lab != rng.label]
    differences = compare_docx(blob, new_blob, positions)
    if differences:
        raise OutsideChange(differences)
    text_lines = [ln for ln in clean_text(text).split("\n") if ln.strip() not in placed]
    summary = {"項目": rng.label, "段落": len(clean_text(text).split("\n")), "消した説明の青字の段落": removed_blue,
               "文字数": len("".join(text_lines)), "図": [p.figure.title for p in placed.values()],
               "図の幅（cm）": [round(p.cx / 360000, 1) for p in placed.values()]}
    return new_blob, summary


def item_text(blob: bytes, position: Dict) -> str:
    """書いてよい範囲の今の文字（段落ごとに改行でつなぐ）。"""
    _infos, parts = read_parts(blob)
    root = xml_spans.parse(parts[DOC])
    rng = resolve(root, position)
    return "\n".join(text_of(n) or figure_text(n) for n in rng.nodes if n.is_(W, "p"))


# ---------------------------------------------------------------- 比べる


def _canonical(text: bytes) -> Optional[str]:
    try:
        return ET.canonicalize(xml_data=text.decode("utf-8"), rewrite_prefixes=True)
    except (ET.ParseError, UnicodeDecodeError, ValueError):
        return None


def _same_xml_part(name: str, x: bytes, y: bytes) -> bool:
    if x == y:
        return True
    if not name.endswith((".xml", ".rels")):
        return False
    if name == CONTENT_TYPES:
        # 子の並びに意味がない部品は、子の集まりとして比べる
        try:
            kids = [sorted(ET.canonicalize(xml_data=ET.tostring(c, encoding="unicode")) for c in ET.fromstring(d))
                    for d in (x, y)]
        except ET.ParseError:
            return False
        return kids[0] == kids[1]
    a, b = _canonical(x), _canonical(y)
    return a is not None and a == b


def compare_parts(before: Dict[str, bytes], after: Dict[str, bytes], skip: Sequence[str]) -> List[str]:
    out = []
    for name in sorted(set(before) | set(after)):
        if name in skip:
            continue
        if name not in after:
            out.append(f"部品 {name} がなくなりました")
        elif name not in before:
            out.append(f"部品 {name} が増えました")
        elif not _same_xml_part(name, before[name], after[name]):
            out.append(f"部品 {name} が変わりました")
    return out


def _decls(root: Node) -> Dict[str, str]:
    return {k: v for k, v in root.attrs.items() if k == "xmlns" or k.startswith("xmlns:")}


def _unit_canonical(raw: bytes, decls: Dict[str, str]) -> Optional[str]:
    attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in sorted(decls.items()))
    return _canonical(f"<_比べる {attrs}>".encode("utf-8") + raw + "</_比べる>".encode("utf-8"))


def _label(unit: Tuple[str, Optional[Node], bytes]) -> str:
    """差を示すときの、単位の名前（場所と、文字の頭）。"""
    kind, node, _key = unit
    if node is None:
        return kind
    try:
        where = path_of(node) or node.name
    except FormError:
        where = node.name
    text = text_of(node).strip() if kind == "" else ""
    shown = f"{where}「{_shown(text)[:24]}」" if text else where
    return shown + kind


def _units(root: Node, data: bytes, masks: Dict[int, Range]) -> List[Tuple[str, Optional[Node], bytes]]:
    """比べる単位（表は行・セルまで開く）。書いてよい範囲は、範囲ごとに1つの印にする。
    単位は（種類、要素、比べる中身）。名前は差を示すときだけ作る（_label）。"""
    out: List[Tuple[str, Optional[Node], bytes]] = []

    def walk(node: Node) -> None:
        mask = masks.get(id(node))
        children = node.children
        i = 0
        while i <= len(children):
            if mask is not None and i == mask.start:
                out.append((f"書いてよい範囲「{mask.label}」", None, f"範囲:{mask.label}".encode("utf-8")))
                if mask.end > i:
                    i = mask.end
                    continue
            if i == len(children):
                break
            child = children[i]
            if child.uri == W and (child.local in EXPANDED or child.local == "body"):
                attrs = sorted(child.attrs.items())
                out.append((" の設定", child, f"<{child.name} {attrs}>".encode("utf-8")))
                walk(child)
                out.append((" の終わり", child, f"</{child.name}>".encode("utf-8")))
            else:
                out.append(("", child, child.raw(data)))
            i += 1

    walk(root)
    return out


def compare_document(before: bytes, after: bytes, positions: Sequence[Tuple[str, Dict]]) -> List[str]:
    """word/document.xml どうしを、書いてよい範囲を覆って比べる。差の説明の一覧を返す。"""
    try:
        root_b = xml_spans.parse(before)
    except xml_spans.SpanError as e:
        return [f"直前の版の本文（{DOC}）を読めません（{e}）"]
    try:
        root_a = xml_spans.parse(after)
    except xml_spans.SpanError as e:
        return [f"書いた後の本文（{DOC}）が XML として読めません（{e}）"]
    out: List[str] = []
    if root_b.name != root_a.name or root_b.attrs != root_a.attrs:
        out.append("文書の根（名前空間の宣言など）が変わりました")
    masks_b: Dict[int, Range] = {}
    masks_a: Dict[int, Range] = {}
    for label, position in positions:
        got = []
        for root in (root_b, root_a):
            try:
                got.append(resolve(root, position, label))
            except FormError:
                got.append(None)
        if got[0] is None and got[1] is None:
            continue
        if got[0] is None or got[1] is None:
            out.append(f"書いてよい範囲「{label}」の目印（見出しやセル）が、{'書いた後' if got[1] is None else '直前の版'}に見つかりません")
            continue
        masks_b[id(got[0].container)] = got[0]
        masks_a[id(got[1].container)] = got[1]
    units_b = _units(root_b, before, masks_b)
    units_a = _units(root_a, after, masks_a)
    decls_b, decls_a = _decls(root_b), _decls(root_a)
    keys_b, keys_a = [u[2] for u in units_b], [u[2] for u in units_a]
    if keys_b == keys_a:
        return out
    sm = difflib.SequenceMatcher(a=keys_b, b=keys_a, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            pairs = zip(units_b[i1:i2], units_a[j1:j2])
            if all(x[1] is not None and y[1] is not None and _unit_canonical(x[2], decls_b) is not None
                   and _unit_canonical(x[2], decls_b) == _unit_canonical(y[2], decls_a) for x, y in pairs):
                continue  # 書き方だけが違い、中身は同じ
        if op == "replace":
            out.append(f"変わった：{'、'.join(_label(u) for u in units_b[i1:i2][:3])}")
        elif op == "delete":
            out.append(f"なくなった：{'、'.join(_label(u) for u in units_b[i1:i2][:3])}")
        else:
            out.append(f"増えた：{'、'.join(_label(u) for u in units_a[j1:j2][:3])}")
    return out[:MAX_DIFFS]


def _without_figures(parts: Dict[str, bytes]) -> Dict[str, bytes]:
    """比べる前に、この道具が足す・片付ける図の部品（画像、関係、png・jpeg の種類の登録）を除く。
    図の段落そのものは書いてよい範囲の中にあり、範囲の比べ方で覆う。"""
    out = {}
    for name, data in parts.items():
        if name.startswith(FIGURE_MEDIA_PREFIX):
            continue
        if name == RELS:
            data = _FIGURE_RELS.sub(b"", data)
        elif name == CONTENT_TYPES:
            data = _IMAGE_DEFAULTS.sub(b"", data)
        out[name] = data
    return out


def compare_docx(before: bytes, after: bytes, positions: Sequence[Tuple[str, Dict]]) -> List[str]:
    """Word のファイルどうしを比べ、書いてよい範囲の外の差の一覧を返す（0件なら空）。"""
    try:
        _i, parts_b = read_parts(before)
    except FormError as e:
        return [f"直前の版を読めません（{e}）"]
    try:
        _i, parts_a = read_parts(after)
    except FormError as e:
        return [f"書いた後のファイルを読めません（{e}）"]
    out = compare_parts(_without_figures(parts_b), _without_figures(parts_a), skip=(DOC,))
    if DOC not in parts_b or DOC not in parts_a:
        out.append(f"本文の部品（{DOC}）がありません")
        return out
    return (out + compare_document(parts_b[DOC], parts_a[DOC], positions))[:MAX_DIFFS]
