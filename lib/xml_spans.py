"""XML のバイト列を、要素ごとの場所（何バイト目から何バイト目まで）を持つ軽い木にする（TASKS M6、DESIGN 4.1・5章）。

様式の Word・Excel は、ファイルの中の XML を直接書き換え、書いてよい範囲の外はバイトのまま残す（DESIGN 5章）。
標準のライブラリの ElementTree で読み直して書き出すと、名前空間の宣言が落ちる。

- M6 の小さな試し（省力化 第8回の その1・2 の word/document.xml）：ElementTree で読んで書き出すと、根の宣言 36 個が
  10 個になり、接頭辞が ns0・ns1 … に変わった。根の mc:Ignorable が指す w15・w16se などの宣言もなくなった。
  Word は、mc:Ignorable の接頭辞が宣言されていない文書を開くときに修復を求めるおそれがある（DESIGN 4.1）。
- そこで、書く道具は元のバイト列の一部だけを差し替える。そのための場所を、標準のライブラリの expat で取る。
  expat は、開始タグの「<」の場所を返す。終わりの場所は、終了タグなら「</…>」の「>」の後、空の要素（<a/>）なら
  開始タグの「>」の後とする。

/usr/bin/python3（3.9）で動く。標準のライブラリだけを使う。
"""

from __future__ import annotations

import re
import xml.parsers.expat
from typing import Dict, Iterator, List, Optional

XML_NS = "http://www.w3.org/XML/1998/namespace"

# 開始タグ（属性の値の中の「>」に惑わされないよう、引用符の中は飛ばす）
_START_TAG = re.compile(rb"""<[^\s/>]+(?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*/?>""")


class SpanError(ValueError):
    """XML として読めない。"""


class Node:
    """要素1つ。start・end は、元のバイト列の中の場所（end は含まない）。"""

    __slots__ = ("name", "uri", "local", "attrs", "ns", "start", "tag_end", "end", "children", "parent", "texts")

    def __init__(self, name: str, uri: str, local: str, attrs: Dict[str, str], ns: Dict[str, str], start: int,
                 tag_end: int, parent: Optional["Node"]) -> None:
        self.name = name
        self.uri = uri
        self.local = local
        self.attrs = attrs
        self.ns = ns
        self.start = start
        self.tag_end = tag_end
        self.end = tag_end
        self.children: List[Node] = []
        self.parent = parent
        self.texts: List[str] = []

    @property
    def prefix(self) -> str:
        return self.name.split(":", 1)[0] if ":" in self.name else ""

    @property
    def text(self) -> str:
        """この要素のすぐ中にある文字（子の要素の中の文字は含まない）。"""
        return "".join(self.texts)

    def is_(self, uri: str, local: str) -> bool:
        return self.uri == uri and self.local == local

    def attr(self, uri: str, local: str) -> Optional[str]:
        """名前空間 uri・名前 local の属性の値。"""
        for name, value in self.attrs.items():
            if ":" in name:
                prefix, name_local = name.split(":", 1)
                if prefix == "xmlns":
                    continue
                name_uri = XML_NS if prefix == "xml" else self.ns.get(prefix, "")
            else:
                name_local, name_uri = name, ""
            if name_uri == uri and name_local == local:
                return value
        return None

    def find(self, uri: str, local: str) -> Optional["Node"]:
        return next((c for c in self.children if c.is_(uri, local)), None)

    def findall(self, uri: str, local: str) -> List["Node"]:
        return [c for c in self.children if c.is_(uri, local)]

    def iter(self) -> Iterator["Node"]:
        yield self
        for c in self.children:
            yield from c.iter()

    def ancestors(self) -> Iterator["Node"]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def raw(self, data: bytes) -> bytes:
        return data[self.start:self.end]

    def start_tag(self, data: bytes) -> bytes:
        return data[self.start:self.tag_end]


def parse(data: bytes) -> Node:
    """data（XML のバイト列）を読み、根の要素を返す。読めなければ SpanError。"""
    parser = xml.parsers.expat.ParserCreate()
    stack: List[Node] = []
    roots: List[Node] = []
    ns_stack: List[Dict[str, str]] = [{"xml": XML_NS}]

    def start(name: str, attrs: Dict[str, str]) -> None:
        index = parser.CurrentByteIndex
        m = _START_TAG.match(data, index)
        if m is None:
            raise SpanError(f"{index} バイト目の開始タグを読めません")
        ns = ns_stack[-1]
        declared = {k: v for k, v in attrs.items() if k == "xmlns" or k.startswith("xmlns:")}
        if declared:
            ns = dict(ns)
            for k, v in declared.items():
                ns["" if k == "xmlns" else k[6:]] = v
        ns_stack.append(ns)
        prefix, local = name.split(":", 1) if ":" in name else ("", name)
        node = Node(name, ns.get(prefix, ""), local, attrs, ns, index, m.end(), stack[-1] if stack else None)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def end(name: str) -> None:
        node = stack.pop()
        ns_stack.pop()
        if data[node.tag_end - 2:node.tag_end] == b"/>":
            node.end = node.tag_end
        else:
            close = data.find(b">", parser.CurrentByteIndex)
            if close < 0:
                raise SpanError(f"{name} の終了タグを読めません")
            node.end = close + 1

    def chars(text: str) -> None:
        if stack:
            stack[-1].texts.append(text)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(data, True)
    except xml.parsers.expat.ExpatError as e:
        raise SpanError(f"XML として読めません（{e}）") from e
    if len(roots) != 1:
        raise SpanError("根の要素が1つではありません")
    return roots[0]


def splice(data: bytes, start: int, end: int, new: bytes) -> bytes:
    """data の start から end（含まない）を new に差し替えたバイト列。"""
    return data[:start] + new + data[end:]
