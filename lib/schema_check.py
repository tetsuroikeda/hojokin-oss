"""JSON Schema の形の確かめ（社長に見せる日本語の文で返す形。標準のライブラリだけで動く小さな部分。DESIGN 4.1・4.5）。

schema/ にある JSON Schema（draft 2020-12）を、そのまま使って確かめる。社長の Mac の /usr/bin/python3（3.9）で
動かすため、jsonschema（開発用のライブラリ）は使わない。正本は schema/ のファイルだけにし、形を2か所に持たない。

扱うのは、schema/ のファイルで使っている言葉だけ（type、const、enum、pattern、minLength・maxLength、
minimum・maximum、properties、required、additionalProperties、items、minItems・maxItems、$ref（#/$defs/… の形）、
allOf・anyOf・oneOf、if・then・else）。知らない確かめの言葉が出てきたら、黙って飛ばさずに SchemaUnsupported にする
（確かめたつもりで通してしまわないため）。

結果は、社長にも読める日本語の文の一覧で返す（空なら合っている）。場所は「項目[2].出典.ファイル」の形で示す。
"""

from __future__ import annotations

import re
from typing import Any, List

# 確かめに使わない言葉（説明や印）
_ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples", "$defs", "definitions"}
_KEYWORDS = {
    "type", "const", "enum", "pattern", "minLength", "maxLength", "minimum", "maximum",
    "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
    "$ref", "allOf", "anyOf", "oneOf", "if", "then", "else",
}

_TYPE_WORDS = {
    "object": "{ } で囲んだ形",
    "array": "[ ] で囲んだ並び",
    "string": "文字",
    "integer": "整数",
    "number": "数",
    "boolean": "true か false",
    "null": "null",
}


class SchemaUnsupported(ValueError):
    """この小さな確かめでは扱えない言葉が、スキーマにある。"""


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    raise SchemaUnsupported(f"type「{name}」は扱えません")


def _equal(a: Any, b: Any) -> bool:
    """JSON として同じか（true と 1 は別のもの）。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _shown(value: Any) -> str:
    if isinstance(value, str):
        return f"「{value}」"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _where(path: str) -> str:
    return path or "全体"


def _resolve(root: dict, ref: str) -> Any:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise SchemaUnsupported(f"$ref「{ref}」は扱えません（#/$defs/… の形だけ）")
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SchemaUnsupported(f"$ref「{ref}」の先がありません")
        node = node[part]
    return node


def validate(schema: dict, instance: Any) -> List[str]:
    """instance が schema に合うかを確かめ、合わない所の文の一覧を返す（空なら合っている）。"""
    errors: List[str] = []
    _check(schema, instance, schema, "", errors)
    return errors


def _check(node: Any, value: Any, root: dict, path: str, errors: List[str]) -> None:
    if node is True:
        return
    if node is False:
        errors.append(f"{_where(path)}：ここには何も置けません")
        return
    if not isinstance(node, dict):
        raise SchemaUnsupported(f"{_where(path)} のスキーマが {{ }} の形ではありません")
    unknown = set(node) - _KEYWORDS - _ANNOTATIONS
    if unknown:
        raise SchemaUnsupported(f"{_where(path)} の {sorted(unknown)} は扱えません")

    if "$ref" in node:
        _check(_resolve(root, node["$ref"]), value, root, path, errors)

    if "type" in node:
        names = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_is_type(value, n) for n in names):
            wanted = "か".join(_TYPE_WORDS.get(n, n) for n in names)
            errors.append(f"{_where(path)}：{wanted}にしてください")
            return  # 形が違えば、中身は確かめない

    if "const" in node and not _equal(value, node["const"]):
        errors.append(f"{_where(path)}：{_shown(node['const'])} にしてください")
    if "enum" in node and not any(_equal(value, e) for e in node["enum"]):
        choices = "、".join(_shown(e) for e in node["enum"])
        errors.append(f"{_where(path)}：{choices} のどれかにしてください")

    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            errors.append(f"{_where(path)}：空にできません" if node["minLength"] == 1
                          else f"{_where(path)}：{node['minLength']}字以上にしてください")
        if "maxLength" in node and len(value) > node["maxLength"]:
            errors.append(f"{_where(path)}：{node['maxLength']}字までにしてください")
        if "pattern" in node and re.search(node["pattern"], value) is None:
            if node["pattern"] == "^[0-9]{4}-[0-9]{2}-[0-9]{2}$":
                errors.append(f"{_where(path)}：「2026-11-04」の形の日付にしてください（{_shown(value)}）")
            else:
                errors.append(f"{_where(path)}：形が合いません（{_shown(value)}）")

    if _is_type(value, "number"):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{_where(path)}：{node['minimum']} 以上にしてください")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{_where(path)}：{node['maximum']} 以下にしてください")

    if isinstance(value, dict):
        props = node.get("properties") or {}
        for key in node.get("required") or []:
            if key not in value:
                errors.append(f"{_where(path)}：「{key}」がありません")
        extra = node.get("additionalProperties", True)
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if key in props:
                _check(props[key], item, root, child, errors)
            elif extra is False:
                errors.append(f"{_where(path)}：「{key}」は置けない欄です")
            elif isinstance(extra, dict):
                _check(extra, item, root, child, errors)

    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(f"{_where(path)}：{node['minItems']}件以上にしてください")
        if "maxItems" in node and len(value) > node["maxItems"]:
            errors.append(f"{_where(path)}：{node['maxItems']}件までにしてください")
        if "items" in node:
            for i, item in enumerate(value):
                _check(node["items"], item, root, f"{path}[{i}]", errors)

    for sub in node.get("allOf") or []:
        _check(sub, value, root, path, errors)

    if "anyOf" in node:
        if not any(not _errors(sub, value, root, path) for sub in node["anyOf"]):
            errors.append(f"{_where(path)}：どの形にも合いません")

    if "oneOf" in node:
        _one_of(node["oneOf"], value, root, path, errors)

    if "if" in node:
        branch = "then" if not _errors(node["if"], value, root, path) else "else"
        if branch in node:
            _check(node[branch], value, root, path, errors)


def _errors(node: Any, value: Any, root: dict, path: str) -> List[str]:
    found: List[str] = []
    _check(node, value, root, path, found)
    return found


def _one_of(choices: list, value: Any, root: dict, path: str, errors: List[str]) -> None:
    results = [_errors(sub, value, root, path) for sub in choices]
    passed = [i for i, r in enumerate(results) if not r]
    if len(passed) == 1:
        return
    if len(passed) > 1:
        errors.append(f"{_where(path)}：2つ以上の形に合ってしまいます")
        return
    # どれにも合わないときは、「種類」が同じ形の理由を示す（会社の記録の項目は「種類」で形が決まる）
    if isinstance(value, dict) and "種類" in value:
        for sub, found in zip(choices, results):
            target = _resolve(root, sub["$ref"]) if isinstance(sub, dict) and "$ref" in sub else sub
            kind = ((target or {}).get("properties") or {}).get("種類") if isinstance(target, dict) else None
            if isinstance(kind, dict) and "const" in kind and _equal(kind["const"], value["種類"]):
                errors.extend(found)
                return
    errors.append(f"{_where(path)}：どの形にも合いません（「種類」を確かめてください）")
