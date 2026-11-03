"""Word（.docx）を、Python の標準のライブラリだけで書く小さな道具（DESIGN 4.6・6章）。

python-docx は C の拡張（lxml）が要り、プラグインに同梱できない（S5）。社長の Mac の /usr/bin/python3（3.9）で、
通信も準備もなしに動かすため、docx の中身（XML を zip にまとめたもの）を直接作る。
扱えるのは、見出し・段落・表・リンクだけ。様式への書き込みには使わない（様式は元のファイルを直す。DESIGN 8章）。

- 同じ中身からは、いつも同じバイト列になる（zip の時刻を固定する）。版の履歴で、変わっていない回を見分けるため。
- 書くときは同じ名前のファイルを置き換える。書きかけの一時ファイルは、成功しても失敗しても残さない。
- XML で使えない文字（PDF から写した改ページなど）は、入れる前に直す（clean_text）。それでも読めない部品が
  できたときは、書く前に DocxError にして、前のファイルをそのまま残す。
"""

from __future__ import annotations

import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
REL_STYLES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
REL_DOCUMENT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
FONT = "游ゴシック"

# 段落の中身：文字だけか、(文字, リンク先) の組を並べたもの
Run = Union[str, Tuple[str, str]]


# XML 1.0 で使えない文字。改ページ（\x0c）と垂直タブ（\x0b）は公募要領の PDF から写した文によく混ざるので、
# 行の区切りにする。ほかの制御文字・￾・￿・サロゲート（str の中では必ず対になっていない）は落とす。
_LINE_BREAKS = re.compile("\r\n|[\r\x0b\x0c]")
_NOT_XML = re.compile("[\x00-\x08\x0e-\x1f￾￿\ud800-\udfff]")


class DocxError(ValueError):
    """書こうとした Word の部品が XML として読めないとき（書く前に止め、前のファイルを残す）。"""


def clean_text(text: str) -> str:
    """Word に入れられる文字だけにする（改ページ・垂直タブは改行に、ほかの使えない文字は落とす）。"""
    return _NOT_XML.sub("", _LINE_BREAKS.sub("\n", str(text)))


def _attr(value: str) -> str:
    return escape(_NOT_XML.sub("", _LINE_BREAKS.sub("", str(value))), {'"': "&quot;"})


def _text_run(text: str, bold: bool = False, style: Optional[str] = None) -> str:
    props = ""
    if bold or style:
        props = "<w:rPr>" + (f'<w:rStyle w:val="{style}"/>' if style else "") + ("<w:b/>" if bold else "") + "</w:rPr>"
    parts = []
    # 改行は w:br にする
    for i, line in enumerate(clean_text(text).split("\n")):
        if i:
            parts.append("<w:br/>")
        parts.append(f'<w:t xml:space="preserve">{escape(line)}</w:t>')
    return f"<w:r>{props}{''.join(parts)}</w:r>"


class Document:
    """見出し・段落・表を順に足し、最後に save() で書く。"""

    def __init__(self) -> None:
        self._body: List[str] = []
        self._links: List[str] = []

    def _link(self, text: str, url: str) -> str:
        self._links.append(url)
        rid = f"rIdLink{len(self._links)}"
        return f'<w:hyperlink r:id="{rid}" w:history="1">{_text_run(text, style="Hyperlink")}</w:hyperlink>'

    def _runs(self, content: Union[Run, Sequence[Run]], bold: bool = False) -> str:
        if isinstance(content, (str, tuple)):
            content = [content]
        out = []
        for item in content:
            if isinstance(item, tuple):
                out.append(self._link(item[0], item[1]))
            else:
                out.append(_text_run(item, bold=bold))
        return "".join(out)

    def _paragraph_xml(self, content: Union[Run, Sequence[Run]], style: Optional[str] = None, bold: bool = False) -> str:
        props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{props}{self._runs(content, bold=bold)}</w:p>"

    def title(self, text: str) -> None:
        self._body.append(self._paragraph_xml(text, "Title"))

    def heading(self, text: str, level: int = 1) -> None:
        self._body.append(self._paragraph_xml(text, f"Heading{level}"))

    def paragraph(self, content: Union[Run, Sequence[Run]], bold: bool = False) -> None:
        self._body.append(self._paragraph_xml(content, bold=bold))

    def table(self, rows: Sequence[Sequence[Union[Run, Sequence[Run]]]], header: bool = True,
              widths: Optional[Sequence[int]] = None) -> None:
        """rows の各セルは、文字か、(文字, リンク先) か、それらの並び（1つの段落。文字の改行は行の区切り）。
        widths は列の幅（twip）。"""
        grid = ""
        if widths:
            grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
        out = [
            '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>' + grid
        ]
        for r, row in enumerate(rows):
            cells = []
            for c, cell in enumerate(row):
                width = f'<w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/></w:tcPr>' if widths else ""
                para = self._paragraph_xml(cell, bold=header and r == 0)
                cells.append(f"<w:tc>{width}{para}</w:tc>")
            # 行をページの境目で分けない。見出しの行は、ページが変わっても繰り返す
            row_props = "<w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if header and r == 0 else "") + "</w:trPr>"
            out.append("<w:tr>" + row_props + "".join(cells) + "</w:tr>")
        out.append("</w:tbl>")
        self._body.append("".join(out))
        # 表の直後に空の段落を置く（Word では表どうしが続くとつながるため）
        self._body.append("<w:p/>")

    # --- 書き出し ---

    def _document_xml(self) -> str:
        sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1418" w:right="1134" w:bottom="1418" w:left="1134" w:header="851" w:footer="992" w:gutter="0"/>'
                "</w:sectPr>")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>'
            + "".join(self._body) + sect + "</w:body></w:document>"
        )

    def _document_rels(self) -> str:
        rels = [f'<Relationship Id="rIdStyles" Type="{REL_STYLES}" Target="styles.xml"/>']
        for i, url in enumerate(self._links, 1):
            rels.append(f'<Relationship Id="rIdLink{i}" Type="{REL_HYPERLINK}" Target="{_attr(url)}" TargetMode="External"/>')
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels) + "</Relationships>"
        )

    def to_bytes(self) -> bytes:
        parts = [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/document.xml", self._document_xml()),
            ("word/_rels/document.xml.rels", self._document_rels()),
            ("word/styles.xml", STYLES),
        ]
        encoded = []
        for name, text in parts:
            # どの部品も、XML として読めることを書く前に確かめる（読めない Word で前のファイルを置き換えない）
            try:
                data = text.encode("utf-8")
                ET.fromstring(data)
            except (UnicodeEncodeError, ET.ParseError) as e:
                raise DocxError(f"Word の中身（{name}）を正しく作れませんでした（{e}）") from e
            encoded.append((name, data))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in encoded:
                info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
        return buffer.getvalue()

    def save(self, path: Union[str, Path]) -> None:
        write_replacing(Path(path), self.to_bytes())


def write_replacing(path: Path, data: bytes) -> None:
    """同じ名前のファイルを、中身ごと置き換える。一時ファイルは隠しファイルにし、必ず片付ける。"""
    tmp = path.with_name(f".{path.name}.書きかけ")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    "</Types>"
)

ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{REL_DOCUMENT}" Target="word/document.xml"/>'
    "</Relationships>"
)


def _style(style_id: str, name: str, size: int, bold: bool = False, based: str = "Normal",
           space_before: int = 0, space_after: int = 0) -> str:
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/>'
        f'<w:basedOn w:val="{based}"/><w:next w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:keepNext/><w:spacing w:before="{space_before}" w:after="{space_after}"/></w:pPr>'
        f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr></w:style>'
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<w:styles xmlns:w="{W_NS}">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    f'<w:rFonts w:ascii="{FONT}" w:eastAsia="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>'
    '<w:sz w:val="21"/><w:lang w:val="ja-JP" w:eastAsia="ja-JP"/>'
    "</w:rPr></w:rPrDefault>"
    '<w:pPrDefault><w:pPr><w:spacing w:after="60" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    "</w:docDefaults>"
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    + _style("Title", "Title", 36, bold=True, space_after=200)
    + _style("Heading1", "heading 1", 28, bold=True, space_before=320, space_after=120)
    + _style("Heading2", "heading 2", 24, bold=True, space_before=240, space_after=80)
    + '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
    '<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>'
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>'
    '<w:tblPr><w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr>'
    "</w:style>"
    '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/>'
    "<w:tblPr><w:tblBorders>"
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
    "</w:tblBorders></w:tblPr></w:style>"
    "</w:styles>"
)
