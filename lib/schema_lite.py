"""JSON Schema（2020-12）のうち、このプラグインのスキーマが使う決まりだけで、形を確かめる（TASKS M2b）。

社長の Mac の /usr/bin/python3（3.9）で、通信なしに動かすため、jsonschema は同梱しない
（jsonschema が使う部品に、Python だけで書かれていないものがある。DESIGN 4.1）。

扱う決まり：$ref（同じスキーマの中だけ）、type、enum、const、required、properties、additionalProperties、
items、minItems、minLength、minimum、maximum、pattern、allOf、anyOf、oneOf、not、if・then・else。
説明のための決まり（title、description など）は読まない。
ほかの決まりがスキーマに出てきたら、黙って通さずに SchemaError で止める（スキーマを広げたときに気づくため）。
jsonschema と同じ判定になることは、tests/test_urakadori.py で確かめる。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

CHECKED = {
    "$ref", "type", "enum", "const", "required", "properties", "additionalProperties", "items",
    "minItems", "minLength", "minimum", "maximum", "pattern", "allOf", "anyOf", "oneOf", "not",
    "if", "then", "else",
}
NOT_CHECKED = {"$schema", "$defs", "$id", "$comment", "title", "description", "examples", "default"}

Path_ = List[Union[str, int]]


class SchemaError(ValueError):
    """スキーマそのものが、ここで扱えない形をしている。"""


def path_label(path: Path_) -> str:
    """場所の書き方。例：補助額[0].上限.値（いちばん外側は「（全体）」）。"""
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out or "（全体）"


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if kind == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if kind == "number":
        return isinstance(value, (int, float))
    raise SchemaError(f"type の「{kind}」は扱えません")


def _same(a: Any, b: Any) -> bool:
    """JSON としての同じ（true と 1 は違う。1 と 1.0 は同じ）。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


_TYPE_NAMES = {"object": "{ } の形", "array": "[ ] の並び", "string": "文字", "integer": "整数",
               "number": "数", "boolean": "true か false", "null": "null"}


class Validator:
    """root（スキーマ全体）で、値の形を確かめる。"""

    def __init__(self, root: Dict) -> None:
        self.root = root
        self._check_keywords(root)

    # ---- スキーマの確かめ ----

    def _check_keywords(self, node: Any) -> None:
        if isinstance(node, list):
            for x in node:
                self._check_keywords(x)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key not in CHECKED and key not in NOT_CHECKED:
                raise SchemaError(f"スキーマの決まり「{key}」は、この道具では扱えません")
            if key in ("properties", "$defs"):
                for sub in value.values():
                    self._check_keywords(sub)
            elif key in ("enum", "const", "required", "description", "title", "examples", "default"):
                continue
            else:
                self._check_keywords(value)

    def resolve(self, ref: str) -> Dict:
        if not ref.startswith("#"):
            raise SchemaError(f"ほかのファイルを指す $ref（{ref}）は扱えません")
        node: Any = self.root
        for part in [p for p in ref[1:].split("/") if p]:
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise SchemaError(f"$ref の先（{ref}）がスキーマにありません")
            node = node[part]
        return node

    # ---- 値の確かめ ----

    def errors(self, value: Any, schema: Optional[Dict] = None, path: Optional[Path_] = None) -> List[str]:
        """形の誤り（「場所：理由」の文）の一覧。空なら形が合っている。"""
        return self._errors(value, self.root if schema is None else schema, list(path or []))

    def _errors(self, value: Any, schema: Any, path: Path_) -> List[str]:
        if schema is True or schema == {}:
            return []
        if schema is False:
            return [f"{path_label(path)}：ここには何も置けません"]
        out: List[str] = []
        where = path_label(path)
        if "$ref" in schema:
            out += self._errors(value, self.resolve(schema["$ref"]), path)
        if "type" in schema:
            kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_type_ok(value, k) for k in kinds):
                names = "か".join(_TYPE_NAMES.get(k, k) for k in kinds)
                return out + [f"{where}：{names}で書いてください"]
        if "enum" in schema and not any(_same(value, x) for x in schema["enum"]):
            choices = "・".join(str(x) for x in schema["enum"])
            out.append(f"{where}：{choices} のどれかで書いてください（今は {value!r}）")
        if "const" in schema and not _same(value, schema["const"]):
            out.append(f"{where}：{schema['const']!r} でなければなりません（今は {value!r}）")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append(f"{where}：空にできません" if schema["minLength"] == 1
                           else f"{where}：{schema['minLength']}字以上で書いてください")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append(f"{where}：書き方が決まりと合いません（{value!r}。決まり：{schema['pattern']}）")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append(f"{where}：{schema['minimum']} 以上の数にしてください（今は {value}）")
            if "maximum" in schema and value > schema["maximum"]:
                out.append(f"{where}：{schema['maximum']} 以下の数にしてください（今は {value}）")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append(f"{where}：{schema['minItems']}件以上が要ります（今は {len(value)}件）")
            if "items" in schema:
                for i, item in enumerate(value):
                    out += self._errors(item, schema["items"], path + [i])
        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    out.append(f"{where}：「{key}」がありません")
            props = schema.get("properties", {})
            for key, item in value.items():
                if key in props:
                    out += self._errors(item, props[key], path + [key])
                elif "additionalProperties" in schema:
                    extra = schema["additionalProperties"]
                    if extra is False:
                        out.append(f"{path_label(path + [key])}：この場所に「{key}」は置けません")
                    elif extra is not True:
                        out += self._errors(item, extra, path + [key])
        for sub in schema.get("allOf", []):
            out += self._errors(value, sub, path)
        if "anyOf" in schema:
            results = [self._errors(value, sub, path) for sub in schema["anyOf"]]
            if all(results):
                out += self._closest(where, results, "どの形にも合いません")
        if "oneOf" in schema:
            results = [self._errors(value, sub, path) for sub in schema["oneOf"]]
            passed = sum(1 for r in results if not r)
            if passed == 0:
                out += self._closest(where, results, "どの形にも合いません")
            elif passed > 1:
                out.append(f"{where}：形が1つに決まりません（{passed}つの形に合います）")
        if "not" in schema and not self._errors(value, schema["not"], path):
            out.append(f"{where}：この形にはできません（例：その状態では置けない欄があります）")
        if "if" in schema:
            branch = "then" if not self._errors(value, schema["if"], path) else "else"
            if branch in schema:
                out += self._errors(value, schema[branch], path)
        return out

    @staticmethod
    def _closest(where: str, results: List[List[str]], message: str) -> List[str]:
        """どの形にも合わないとき、誤りがいちばん少ない形の誤りを添える。"""
        best = min(results, key=len)
        return [f"{where}：{message}（いちばん近い形との違い：{'／'.join(best[:3])}）"]
