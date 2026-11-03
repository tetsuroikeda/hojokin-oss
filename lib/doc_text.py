"""公式資料を、ページごとの文字にする（DESIGN 9.2、TASKS M2a）。

- PDF は、同梱の pypdf（lib/vendor/）でページごとの文字を取り出す。
  文字を取り出せないページ（画像だけのページ）は、印を付けて残す（読み取り役にページの画像を渡すため。DESIGN 9.2）。
- 印刷されたページ番号と PDF のページの対応を取る。出典は、いつも印刷された番号で示す（DESIGN 9章の注）。
  各ページの最初と最後の数行にある番号から「PDF のページ − 印刷された番号」（ページのずれ）を数え、
  いちばん多いずれを資料全体のずれとする。多数にならなければ、ずれは「分からない」（None）として、PDF のページで示す。
- Word・Excel・HTML はページがないので、Word と HTML は1つの本文、Excel はシートごとに文字にする（標準のライブラリだけ）。

置き方（`記録/資料の本文/<案件>/<資料の id>/`）：
- `ページの対応.json`：資料の名前・回・ハッシュ・ページのずれと、ページごとの「PDF のページ → 印刷された番号」。
- `ページ_001.txt` …：PDF のページごとの文字。1行目に、資料の名前と、印刷された番号・PDF のページを書く。
- Word・HTML は `本文.txt`、Excel は `シート_01.txt` …。

ここは決まった処理だけをする。どの資料を取るか・どのページを読むかは、Claude（読み取り役）が決める。
"""

from __future__ import annotations

import html.parser
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

# 同梱の pypdf（と typing_extensions）を、社長のパソコンに別の版が入っていても先に使う
VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

INDEX_FILE = "ページの対応.json"
HEADER_END = "\n\n"
# 資料全体のずれと認めるのに要る、番号が合ったページの数（と、番号を見つけたページのうちの割合）
MIN_VOTES = 3
MIN_SHARE = 0.5

PDF_SUFFIXES = (".pdf",)
WORD_SUFFIXES = (".docx",)
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
HTML_SUFFIXES = (".html", ".htm")
SUPPORTED_SUFFIXES = PDF_SUFFIXES + WORD_SUFFIXES + EXCEL_SUFFIXES + HTML_SUFFIXES


class TextError(Exception):
    """資料を文字にできなかった（壊れたファイル、暗号のかかった PDF、扱えない形など）。"""


# ---- ファイルの形ごとの取り出し ----


def pdf_pages(path: Path) -> List[str]:
    """PDF のページごとの文字。"""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except Exception as e:  # 同梱のファイルが欠けた・壊れた
        raise TextError(f"PDF を読む補助プログラム（pypdf）を読み込めませんでした（{type(e).__name__}: {e}）") from e
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise TextError("暗号のかかった PDF です")
        return [(page.extract_text() or "") for page in reader.pages]
    except TextError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError) as e:
        raise TextError(f"PDF を読めませんでした（{type(e).__name__}: {e}）") from e


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    return ElementTree.fromstring(archive.read(name))


MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _word_paragraph(p: ElementTree.Element) -> str:
    """段落の文字。図形の文字は、新しい形（Choice）と古い形（Fallback）の両方に入っているので、Fallback は読まない。"""
    parts: List[str] = []

    def walk(node: ElementTree.Element) -> None:
        for child in node:
            # ルビ（ふりがな、<w:ruby> の中の <w:rt>）は本文ではないので読まない。親の文字（<w:rubyBase>）は読む
            if child.tag in (MC_FALLBACK, W_NS + "rt"):
                continue
            if child.tag == W_NS + "t" and child.text:
                parts.append(child.text)
            elif child.tag == W_NS + "tab":
                parts.append("\t")
            elif child.tag in (W_NS + "br", W_NS + "cr"):
                parts.append("\n")
            walk(child)

    walk(p)
    return "".join(parts)


def _word_block(parent: ElementTree.Element, lines: List[str]) -> None:
    """本文の段落と表を、出てくる順に1行ずつにする。表は、行ごとにセルをタブでつなぐ。"""
    for child in parent:
        if child.tag == W_NS + "p":
            lines.append(_word_paragraph(child))
        elif child.tag == W_NS + "tbl":
            for row in child.iter(W_NS + "tr"):
                cells = []
                for cell in row.findall(W_NS + "tc"):
                    inner: List[str] = []
                    _word_block(cell, inner)
                    cells.append(" ".join(x for x in inner if x.strip()))
                lines.append("\t".join(cells))
        elif child.tag == W_NS + "sdt":
            content = child.find(W_NS + "sdtContent")
            if content is not None:
                _word_block(content, lines)


def word_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            body = _xml(archive, "word/document.xml").find(W_NS + "body")
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as e:
        raise TextError(f"Word のファイルを読めませんでした（{type(e).__name__}: {e}）") from e
    lines: List[str] = []
    if body is not None:
        _word_block(body, lines)
    return "\n".join(lines)


def _excel_string(item: ElementTree.Element) -> str:
    """共有の文字（<si>）か、セルの中の文字（<is>）の本文。

    本文は、直下の <t> と、書式つきの部分（<r>）の <t> だけ。日本語の Excel では、本文の後に
    フリガナ（<rPh> の中の <t>）が続くので、<rPh> は読まない（読むと「事業者名ジギョウシャメイ」になる）。
    """
    parts: List[str] = []
    for child in item:
        if child.tag == S_NS + "t":
            parts.append(child.text or "")
        elif child.tag == S_NS + "r":
            parts.extend(t.text or "" for t in child.findall(S_NS + "t"))
    return "".join(parts)


def excel_sheets(path: Path) -> List[Tuple[str, str]]:
    """Excel のシートごとの（シートの名前、文字）。セルは、行ごとにタブでつなぐ。数式は、残っている値を使う。"""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            shared: List[str] = []
            if "xl/sharedStrings.xml" in names:
                for si in _xml(archive, "xl/sharedStrings.xml").findall(S_NS + "si"):
                    shared.append(_excel_string(si))
            rels = {}
            for rel in _xml(archive, "xl/_rels/workbook.xml.rels").findall(PKG_REL_NS + "Relationship"):
                target = rel.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else "xl/" + target
                rels[rel.get("Id")] = target
            sheets = []
            for sheet in _xml(archive, "xl/workbook.xml").iter(S_NS + "sheet"):
                part = rels.get(sheet.get(R_NS + "id"))
                if not part or part not in names:
                    continue
                rows = []
                for row in _xml(archive, part).iter(S_NS + "row"):
                    cells = []
                    for c in row.findall(S_NS + "c"):
                        kind = c.get("t")
                        if kind == "inlineStr":
                            inline = c.find(S_NS + "is")
                            cells.append(_excel_string(inline) if inline is not None else "")
                            continue
                        v = c.find(S_NS + "v")
                        if v is None or v.text is None:
                            continue
                        if kind == "s":
                            index = int(v.text)
                            cells.append(shared[index] if 0 <= index < len(shared) else "")
                        else:
                            cells.append(v.text)
                    if any(x.strip() for x in cells):
                        rows.append("\t".join(cells))
                sheets.append((sheet.get("name") or "", "\n".join(rows)))
            return sheets
    except (zipfile.BadZipFile, KeyError, ValueError, ElementTree.ParseError, OSError) as e:
        raise TextError(f"Excel のファイルを読めませんでした（{type(e).__name__}: {e}）") from e


class _HTMLText(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article",
             "header", "footer", "dt", "dd", "ul", "ol", "nav", "main", "aside", "caption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_text(path: Path) -> str:
    raw = path.read_bytes()
    match = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    parser = _HTMLText()
    parser.feed(text)
    parser.close()
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


# ---- 印刷されたページ番号 ----

_DASHES = "-‐‑‒–—―ー－"
_STANDALONE = re.compile(
    r"^[%s\s]*(?:[PpＰｐ]\s*\.?\s*)?(\d{1,4})\s*(?:/\s*\d{1,4})?[%s\s]*$" % (_DASHES, _DASHES))
_LEADING = re.compile(r"^(\d{1,4})(?=[^\d\s.,:：/%％年月日時分])")
_TRAILING = re.compile(r"(?<![\d.,:：/])\s*(\d{1,4})$")


def _lines(text: str) -> List[str]:
    return [unicodedata.normalize("NFKC", line).strip() for line in text.splitlines() if line.strip()]


def page_number_candidates(text: str) -> Tuple[List[int], List[int]]:
    """ページの最初の2行と最後の3行から、ページ番号らしい数を探す。

    返すのは（強い候補、弱い候補）。強い候補は、行がその数だけのもの（「12」「- 12 -」「P.12」「12/80」）。
    弱い候補は、行の頭や終わりに文字とつながって出てくる数（「83改訂履歴」「…について 2」）で、
    資料全体のずれと合うときだけ使う。
    """
    lines = _lines(text)
    edge = lines[:2] + lines[-3:] if len(lines) > 5 else lines
    strong, weak = [], []
    for line in edge:
        m = _STANDALONE.match(line)
        if m:
            strong.append(int(m.group(1)))
            continue
        for pattern in (_LEADING, _TRAILING):
            m = pattern.search(line)
            if m:
                weak.append(int(m.group(1)))
    return strong, weak


def _vote(candidates: List[List[int]]) -> Tuple[Optional[int], int, int]:
    """ページごとの候補から、いちばん多い「PDF のページ − 番号」と、その数、番号を見つけたページの数。"""
    votes: Counter = Counter()
    pages_with_numbers = 0
    for index, numbers in enumerate(candidates):
        offsets = {index + 1 - n for n in numbers if n > 0}
        if offsets:
            pages_with_numbers += 1
        votes.update(offsets)
    if not votes:
        return None, 0, 0
    (offset, count), = votes.most_common(1)
    return offset, count, pages_with_numbers


def page_offset(texts: List[str]) -> Tuple[Optional[int], List[Optional[int]], List[bool], List[int]]:
    """資料全体のページのずれと、ページごとの印刷された番号。

    返すのは（ずれ、ページごとの印刷された番号、そのページで番号を見つけたか、番号が合わないページ）。
    ずれが多数にならなければ None で、印刷された番号もすべて None。
    """
    found = [page_number_candidates(t) for t in texts]
    offset = None
    for pool in ([s for s, _w in found], [s + w for s, w in found]):
        candidate, count, pages_with_numbers = _vote(pool)
        if candidate is not None and count >= MIN_VOTES and count >= MIN_SHARE * pages_with_numbers:
            offset = candidate
            break
    printed: List[Optional[int]] = []
    seen: List[bool] = []
    mismatched: List[int] = []
    for index, (strong, weak) in enumerate(found):
        pdf_page = index + 1
        if offset is None or pdf_page - offset < 1:
            printed.append(None)
            seen.append(False)
            continue
        number = pdf_page - offset
        printed.append(number)
        hit = number in strong or number in weak
        seen.append(hit)
        if strong and not hit:
            mismatched.append(pdf_page)
    return offset, printed, seen, mismatched


# ---- 書き出しと読み出し ----


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return "PDF"
    if suffix in WORD_SUFFIXES:
        return "Word"
    if suffix in EXCEL_SUFFIXES:
        return "Excel"
    if suffix in HTML_SUFFIXES:
        return "HTML"
    raise TextError(f"この形のファイル（{path.suffix or '拡張子なし'}）は、文字にできません")


def _header(doc: Dict, where: str) -> str:
    return f"【{doc['名前']}（{doc['公募回']}）／資料 {doc['id']}／{where}】{HEADER_END}"


def write_text(source: Path, out_dir: Path, doc: Dict, relative_source: str = "") -> Dict:
    """source を文字にして out_dir に置き、ページの対応（out_dir/ページの対応.json の中身）を返す。

    doc は、資料の id・名前・公募回・ハッシュを持つ辞書。out_dir の中は、前のものを消して作り直す。
    """
    kind = _kind(source)
    pages: List[Tuple[str, Dict]] = []  # （文字, ページの情報）
    index: Dict = {
        "資料": doc["id"],
        "名前": doc["名前"],
        "公募回": doc["公募回"],
        "ファイル": relative_source or source.name,
        "ハッシュ": doc.get("ハッシュ", ""),
        "種類": kind,
    }
    if kind == "PDF":
        texts = pdf_pages(source)
        offset, printed, seen, mismatched = page_offset(texts)
        index["ページ数"] = len(texts)
        index["ページのずれ"] = offset
        if offset is None:
            index["ページの示し方"] = "印刷されたページ番号が見つからないため、PDF のページで示す"
        else:
            index["ページの示し方"] = f"印刷されたページ番号で示す（PDF のページから {offset} を引いた数）"
        for i, text in enumerate(texts):
            pdf_page = i + 1
            where = f"PDF の {pdf_page} ページ目"
            if printed[i] is not None:
                where = f"印刷されたページ {printed[i]}／" + where
            pages.append((_header(doc, where) + text, {
                "PDFのページ": pdf_page,
                "印刷されたページ": printed[i],
                "番号を見つけた": seen[i],
                "文字数": len(text.strip()),
                "ファイル": f"ページ_{pdf_page:03d}.txt",
            }))
        index["文字を取り出せないページ"] = [p["PDFのページ"] for _t, p in pages if p["文字数"] == 0]
        index["番号が合わないページ"] = mismatched
    elif kind == "Excel":
        sheets = excel_sheets(source)
        index["ページ数"] = len(sheets)
        index["ページのずれ"] = None
        index["ページの示し方"] = "Excel のためページの番号は使わず、シートの名前で示す"
        for i, (name, text) in enumerate(sheets):
            pages.append((_header(doc, f"シート「{name}」") + text, {
                "シート": name, "文字数": len(text.strip()), "ファイル": f"シート_{i + 1:02d}.txt"}))
        index["文字を取り出せないページ"] = []
        index["番号が合わないページ"] = []
    else:
        text = word_text(source) if kind == "Word" else html_text(source)
        index["ページ数"] = 1
        index["ページのずれ"] = None
        index["ページの示し方"] = f"{kind} のためページの番号は使わない"
        pages.append((_header(doc, "本文") + text, {"文字数": len(text.strip()), "ファイル": "本文.txt"}))
        index["文字を取り出せないページ"] = []
        index["番号が合わないページ"] = []
    index["ページ"] = [info for _t, info in pages]

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        if old.is_file():
            old.unlink()
    for text, info in pages:
        (out_dir / info["ファイル"]).write_text(text, encoding="utf-8")
    (out_dir / INDEX_FILE).write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def load_index(doc_dir: Path) -> Dict:
    return json.loads((doc_dir / INDEX_FILE).read_text(encoding="utf-8"))


def _strip_header(text: str) -> str:
    if text.startswith("【"):
        head, sep, rest = text.partition(HEADER_END)
        if sep:
            return rest
    return text


def page_text(doc_dir: Path, printed_page: Optional[int] = None, pdf_page: Optional[int] = None) -> Optional[str]:
    """資料のあるページの文字（1行目の見出しは除く）。ページは、印刷された番号か PDF のページで指す。

    印刷された番号は、資料のずれが分かっているときだけ使える。ずれが分からない資料は、PDF のページで指す
    （出典もそのページで示しているため）。見つからなければ None。M2b の裏取りと、答えの引用の照らしに使う。
    """
    index = load_index(doc_dir)
    for page in index.get("ページ", []):
        if printed_page is not None:
            match = page.get("印刷されたページ") == printed_page
            if index.get("ページのずれ") is None and page.get("PDFのページ") is not None:
                match = page.get("PDFのページ") == printed_page
        elif pdf_page is not None:
            match = page.get("PDFのページ") == pdf_page
        else:
            match = False
        if match:
            return _strip_header((doc_dir / page["ファイル"]).read_text(encoding="utf-8"))
    return None
