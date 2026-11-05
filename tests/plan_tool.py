"""全項目が書けた計画書（testdata/計画書/ の D9）を、会社のフォルダに置くテストの部品（TASKS B16・B19。
test_T9_1.py・test_T8_11.py・test_T8_9.py）。

- 公式の様式（downloads/ の その1・2）に、D9 の本文.json の14項目を lib/yoshiki_word.py の write_item で書く
  （道具と同じ関数。道具を何度も動かさずに済むよう、テストの中で書く）。downloads/ がなければ飛ばす。
- 根拠対照表.xlsx は D9 の根拠対照表.json に、D9 の表に足りない3行（EXTRA_ROWS）を足して、lib/konkyo.py で作る。
- 財務モデルの数字の控え（記録/財務モデルの数字.json）は、D9 の財務モデルの指定から lib/zaimu.py で作る（道具と同じ形）。
- 制度データは、正解（testdata/正解/省力化_第8回.json）に、D9 の書き込む位置を入れたもの。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Dict, List, Optional

import kakunin_tool as kt
import pytest

from lib import konkyo, youken, zaimu
from lib import yoshiki_word as yw

REPO_ROOT = kt.REPO_ROOT
MATERIALS = REPO_ROOT / "testdata" / "計画書" / "材料"
SEIKAI = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
SPEC = MATERIALS / "6_計画を下回る実績" / "財務モデルの指定.json"
NUMBERS = "記録/財務モデルの数字.json"
CORRECT = "1_正しい計画書"
MIXED = "2_食い違いを混ぜた計画書"
NEEDS_ANSWER = "3_社長の答えが要る計画書"

# D9 の根拠対照表に足りない行（本文にあるが表にない数字。出典は回答表・見積書・財務モデルの指定から）
EXTRA_ROWS = [
    {"記述": "2回", "種類": "数字", "書いた場所": "1-1 現状分析", "出典": "社長の答え（2026-11-06）：注文の流れ（回答表 E-05）"},
    {"記述": "2社", "種類": "数字", "書いた場所": "2. 省力化投資の具体的内容（投資全体金額と補助申請金額を含む）",
     "出典": "見積書_つばさ台フードシステム.pdf・見積書_ほしみ機工.pdf"},
    {"記述": "5年間", "種類": "数字", "書いた場所": "3-1 労働生産性と1人当たり給与支給総額等の向上",
     "出典": "財務モデル 計画の年数"},
]


def form_or_skip() -> bytes:
    if not kt.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません（公式資料を取ってから流す）")
    return kt.FORM.read_bytes()


def plan(variant: str = CORRECT) -> dict:
    return json.loads((MATERIALS / variant / "本文.json").read_text(encoding="utf-8"))


def rows(variant: str = CORRECT) -> List[dict]:
    data = json.loads((MATERIALS / variant / "根拠対照表.json").read_text(encoding="utf-8"))
    return data["行"] + copy.deepcopy(EXTRA_ROWS)


def seido_with_positions(variant: str = CORRECT) -> dict:
    seido = json.loads(SEIKAI.read_text(encoding="utf-8"))
    positions = {it["名前"]: it["書き込む位置"] for it in plan(variant)["項目"]}
    for form in seido["様式"]:
        for entry in form["項目"]:
            if entry["名前"] in positions:
                entry["書き込む位置"] = positions[entry["名前"]]
    return seido


def word(form: bytes, items: List[dict]) -> bytes:
    blob = form
    positions = [(it["名前"], it["書き込む位置"]) for it in items]
    for it in items:
        blob, _summary = yw.write_item(blob, it["書き込む位置"], it["本文"], it["名前"], positions)
    return blob


def numbers(spec: Optional[dict] = None) -> dict:
    data = json.loads(SPEC.read_text(encoding="utf-8")) if spec is None else spec
    data = {k: v for k, v in data.items() if k != "説明"}
    parsed = zaimu.parse_spec(data)
    book = zaimu.build(parsed, youken.read_requirements(json.loads(SEIKAI.read_text(encoding="utf-8"))))
    return zaimu.numbers_record(parsed, book, "記録/制度データ/省力化_第8回.json", "2026-11-06 10:00")


def place(env: kt.Env, form: bytes, variant: str = CORRECT, items: Optional[List[dict]] = None,
          evidence: Optional[List[dict]] = None, model: Optional[dict] = None) -> None:
    """会社のフォルダに、制度データ・その1・2.docx・根拠対照表.xlsx・数字の控えを置く。"""
    seido = seido_with_positions(variant)
    (env.folder / kt.SEIDO_IN_FOLDER).write_text(json.dumps(seido, ensure_ascii=False), encoding="utf-8")
    env.put(kt.WORD, word(form, items if items is not None else plan(variant)["項目"]))
    env.put(kt.EVIDENCE, konkyo.build(konkyo.normalize_rows({"行": evidence if evidence is not None else rows(variant)})))
    env.put(NUMBERS, json.dumps(model if model is not None else numbers(), ensure_ascii=False).encode("utf-8"))


def items_with(variant: str, name: str, old: str, new: str) -> List[dict]:
    """本文の1項目の文を差し替えたもの。"""
    out = copy.deepcopy(plan(variant)["項目"])
    hit = [it for it in out if it["名前"] == name]
    assert hit and old in hit[0]["本文"], (name, old)
    hit[0]["本文"] = hit[0]["本文"].replace(old, new, 1)
    return out


def texts(variant: str = CORRECT) -> Dict[str, str]:
    return {it["名前"]: it["本文"] for it in plan(variant)["項目"]}
