"""制度データの正解の下書き（testdata/正解/）が、今のスキーマに合うか（TASKS S6b）。

中身が正しいかは、作者が A2 で確かめる。ここで見るのは形と、S6b で足した欄があることだけ。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest
from jsonschema import Draft202012Validator

from conftest import REPO_ROOT

SEIKAI = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"

# 省力化 第8回の補助の対象になる経費の区分（要領8 p.20–22、応募手引8 p.41）
SHORYOKUKA_8_CATEGORIES = [
    "機械装置・システム構築費",
    "運搬費",
    "技術導入費",
    "知的財産権等関連経費",
    "外注費",
    "専門家経費",
    "クラウドサービス利用費",
]


def walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


@pytest.fixture(scope="module")
def seikai() -> dict:
    return json.loads(SEIKAI.read_text(encoding="utf-8"))


def test_seikai_matches_schema(seikai: dict) -> None:
    schema = json.loads((REPO_ROOT / "schema" / "制度データ.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    found = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(seikai)]
    assert found == []


def test_seikai_sources_point_to_documents(seikai: dict) -> None:
    docs = {d["id"] for d in seikai["資料"]}
    for x in walk(seikai):
        if isinstance(x, dict) and set(x) <= {"資料", "ページ", "終わりのページ"} and "資料" in x:
            assert x["資料"] in docs


def test_seikai_has_eligible_cost_categories(seikai: dict) -> None:
    """S6b で足した欄に、省力化の7つの区分が1件ずつある。"""
    items = seikai["補助の対象になる経費"]
    assert [c["名前"] for c in items] == SHORYOKUKA_8_CATEGORIES
    # 必須の区分は機械装置・システム構築費だけ（要領8 p.20 の表）
    assert {c["名前"] for c in items if c.get("必須か") == "必須"} == {"機械装置・システム構築費"}
    assert all(c.get("必須か") in ("必須", "任意") for c in items)
    # どの区分にも、出典のある定義がある
    for c in items:
        assert c["定義"]["出典"], c["名前"]
    # 作者が確かめるまで、あとから足した件だと分かる印を付ける
    assert all(c.get("注記", "").startswith("［追加分］") for c in items)


def test_seikai_cost_limits_refer_to_categories(seikai: dict) -> None:
    """区分ごとの上限（種類「上限」）のうち、区分1つの件は、補助の対象になる経費の区分を指す。"""
    names = set(SHORYOKUKA_8_CATEGORIES)
    limits = [e for e in seikai["補助の対象にならない経費"] if e["種類"] == "上限"]
    single = [e["経費の区分"] for e in limits if e["経費の区分"] in names or "・" not in e["経費の区分"]]
    assert single and set(single) <= names
