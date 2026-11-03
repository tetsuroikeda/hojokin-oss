"""ブラウザの道具がページを読んだ結果（read_page の木）を読む（DESIGN 5章、実験 E1）。

read_page の結果は、1行に1つの部品を、字下げ（空白1つで1段）で親子を表した文で返る。
  label [ref_16]
   checkbox "on" [ref_17] type="checkbox"
   generic "宣誓事項1：…に同意する" [ref_18]
- 部品の番号（ref_N）は、画面ごとに振り直される（実験 E1）。ここで作る控えは、その画面の間だけ使う。
- 欄の名前は、欄そのものではなく、囲むラベルから取る。チェック欄の名前は「on」、ラジオボタンの名前は値、
  選択欄の名前は選んでいる項目になるため（実験 E1）。ラベルに名前がないときは、ラベルの中の文字
  （欄そのものと、その中の部品を除く）をつなぐ。模擬画面（D11a）は、この形になる。
- 番号のない行（option など）は控えに入れない。部品の形でない行（Viewport、Tab Context など）は読み飛ばす。

Python 3.9 の標準のライブラリだけで動く形にする（hooks から使うため）。
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Dict, List, Optional

_LINE = re.compile(
    r'^(?P<indent> *)(?P<role>[a-z][A-Za-z]*)'
    r'(?: "(?P<name>(?:[^"\\]|\\.)*)")?'
    r'(?: \[(?P<ref>ref_\d+)\])?'
    r'(?P<rest>.*)$'
)
_ATTR = re.compile(r'([A-Za-z][\w-]*)="((?:[^"\\]|\\.)*)"')
_TAB = re.compile(r"Executed on tabId:\s*(\S+)")

# 値を入れる欄（クリックや入力の行き先）
CHOICE_ROLES = ("checkbox", "radio", "combobox", "listbox", "switch")
TEXT_ROLES = ("textbox", "searchbox", "spinbutton")
CONTROL_ROLES = CHOICE_ROLES + TEXT_ROLES + ("button", "link", "slider", "menuitem", "option")


def normalize(text: Optional[str]) -> str:
    """名前を比べるための形。NFC にそろえ、続いた空白を1つにし、前後の空白を除く。"""
    if not text:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def response_text(response) -> str:
    """道具の結果（文字・{type, text} の並び・それを JSON にした文字）から、文の部分を取り出す。"""
    if response is None:
        return ""
    if isinstance(response, str):
        stripped = response.strip()
        if stripped[:1] in ("[", "{"):
            try:
                loaded = json.loads(stripped)
            except ValueError:
                return response
            if isinstance(loaded, (list, dict)):
                return response_text(loaded)
        return response
    if isinstance(response, list):
        return "\n".join(response_text(item) for item in response)
    if isinstance(response, dict):
        if isinstance(response.get("text"), str):
            return response["text"]
        for key in ("content", "result", "output"):
            if key in response:
                return response_text(response[key])
    return ""


def parse(text: str) -> dict:
    """read_page の文から、部品の控えを作る。

    返す形：{"tab": 結果に出たタブの番号か None, "elements": {番号: 部品}}
    部品：{"role", "name", "type", "parent"（番号のある一番近い親）, "order"（ページの中の順番）}
    """
    elements: Dict[str, dict] = {}
    stack: List[tuple] = []  # (字下げ, 番号か None)
    tab = None
    order = 0
    for line in text.splitlines():
        found_tab = _TAB.search(line)
        if found_tab:
            tab = found_tab.group(1)
            continue
        m = _LINE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        ref = m.group("ref")
        parent = None
        for _indent, ancestor in reversed(stack):
            if ancestor is not None:
                parent = ancestor
                break
        stack.append((indent, ref))
        if ref is None:
            continue
        attrs = dict(_ATTR.findall(m.group("rest") or ""))
        elements[ref] = {
            "role": m.group("role"),
            "name": m.group("name") or "",
            "type": attrs.get("type", ""),
            "parent": parent,
            "order": order,
        }
        order += 1
    return {"tab": tab, "elements": elements}


class Page:
    """控えた部品を引くための道具。"""

    def __init__(self, elements: Dict[str, dict]):
        self.elements = elements
        self._children: Dict[str, List[str]] = {}
        for ref, element in elements.items():
            parent = element.get("parent")
            if parent:
                self._children.setdefault(parent, []).append(ref)
        for refs in self._children.values():
            refs.sort(key=lambda r: elements[r].get("order", 0))

    def get(self, ref: str) -> Optional[dict]:
        return self.elements.get(ref)

    def ancestors(self, ref: str):
        seen = set()
        current = (self.elements.get(ref) or {}).get("parent")
        while current and current in self.elements and current not in seen:
            seen.add(current)
            yield current
            current = self.elements[current].get("parent")

    def descendants(self, ref: str) -> List[str]:
        result: List[str] = []
        todo = list(self._children.get(ref, []))
        while todo:
            child = todo.pop(0)
            result.append(child)
            todo[0:0] = self._children.get(child, [])
        return result

    def enclosing_label(self, ref: str) -> Optional[str]:
        """ref がラベルならそれ、ラベルの中にあれば一番近いラベル。"""
        element = self.elements.get(ref)
        if element and element["role"] == "label":
            return ref
        for ancestor in self.ancestors(ref):
            if self.elements[ancestor]["role"] == "label":
                return ancestor
        return None

    def controls_in(self, label_ref: str) -> List[str]:
        """ラベルの中の欄（欄の中の部品は除く）。"""
        result = []
        inside_control = set()
        for ref in self.descendants(label_ref):
            if any(a in inside_control for a in self.ancestors(ref)):
                continue
            element = self.elements[ref]
            if element["role"] in CHOICE_ROLES + TEXT_ROLES or element["type"] == "file":
                result.append(ref)
                inside_control.add(ref)
        return result

    def field_name(self, control_ref: str) -> str:
        """欄の名前。囲むラベルの名前か、ラベルの中の文字（欄そのものと、その中の部品を除く）。

        囲むラベルがない欄は、名前が読めないものとして空を返す（欄そのものの名前は、
        チェック欄なら「on」、ラジオボタンなら値、選択欄なら選んでいる項目になるため。実験 E1）。
        """
        label = self.enclosing_label(control_ref)
        if label is None or label == control_ref:
            return ""
        own = normalize(self.elements[label]["name"])
        if own:
            return own
        skip = set([control_ref] + self.descendants(control_ref))
        parts = []
        for ref in self.descendants(label):
            if ref in skip:
                continue
            element = self.elements[ref]
            if element["role"] in CONTROL_ROLES:
                skip.update(self.descendants(ref))
                continue
            if any(a in skip for a in self.ancestors(ref)):
                continue
            name = normalize(element["name"])
            if name:
                parts.append(name)
        return normalize(" ".join(parts))
