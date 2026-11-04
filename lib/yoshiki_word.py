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

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import difflib
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


def rebuild_zip(blob: bytes, replacements: Dict[str, bytes]) -> bytes:
    """blob の zip の部品を、同じ順・同じ設定で書き直す。replacements の部品だけ中身を替える。"""
    infos, parts = read_parts(blob)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in infos:
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            new.create_system = info.create_system
            zf.writestr(new, replacements.get(info.filename, parts[info.filename]))
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
    """見出しが、同じ行のほかのセルにあるか、そのセルの表のすぐ前の文字のある段落か。"""
    key = norm(heading)
    row = cell.parent
    if row is not None:
        for other in row.findall(W, "tc"):
            if other is not cell and any(norm(text_of(p)) == key for p in other.findall(W, "p")):
                return True
    table = row.parent if row is not None else None
    if table is None or table.parent is None:
        return False
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


def new_paragraphs(data: bytes, rng: Range, text: str) -> bytes:
    """範囲を置き換える段落のバイト列。"""
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
        body = _run_text(w, line)
        run = (f"<{w}:r>".encode("utf-8") + rpr_bytes + body.encode("utf-8") + f"</{w}:r>".encode("utf-8")) if body else b""
        out.append(f"<{w}:p>".encode("utf-8") + ppr_bytes + (kept if i == 0 else b"") + run + f"</{w}:p>".encode("utf-8"))
    return b"".join(out)


def write_item(blob: bytes, position: Dict, text: str, label: str = "",
               other_positions: Sequence[Tuple[str, Dict]] = ()) -> Tuple[bytes, Dict]:
    """Word のファイル blob の、position の書いてよい範囲に text を書いたファイルのバイト列と、書いたことの要約。

    書いた後に直前の版（blob）と比べ、範囲の外が1か所でも変わっていれば OutsideChange（保存しない）。
    """
    if not clean_text(text).strip():
        raise FormError("書く文が空です")
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
    new_data = xml_spans.splice(data, nodes[0].start, nodes[-1].end, new_paragraphs(data, rng, text))
    new_blob = rebuild_zip(blob, {DOC: new_data})
    positions = [(rng.label, position)] + [(lab, pos) for lab, pos in other_positions if lab != rng.label]
    differences = compare_docx(blob, new_blob, positions)
    if differences:
        raise OutsideChange(differences)
    summary = {"項目": rng.label, "段落": len(clean_text(text).split("\n")), "消した説明の青字の段落": removed_blue,
               "文字数": len(clean_text(text).replace("\n", ""))}
    return new_blob, summary


def item_text(blob: bytes, position: Dict) -> str:
    """書いてよい範囲の今の文字（段落ごとに改行でつなぐ）。"""
    _infos, parts = read_parts(blob)
    root = xml_spans.parse(parts[DOC])
    rng = resolve(root, position)
    return "\n".join(text_of(n) for n in rng.nodes if n.is_(W, "p"))


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
    out = compare_parts(parts_b, parts_a, skip=(DOC,))
    if DOC not in parts_b or DOC not in parts_a:
        out.append(f"本文の部品（{DOC}）がありません")
        return out
    return (out + compare_document(parts_b[DOC], parts_a[DOC], positions))[:MAX_DIFFS]
