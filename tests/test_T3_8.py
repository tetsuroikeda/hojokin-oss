"""T3-8 出典の裏取り（SPEC F3。TASKS B25）。

SPEC：出典のページと違う値、そのページにない根拠の文、2回の読み取りで食い違う重要な項目を混ぜた制度データを検査する。
合格ライン：混ぜたものをすべて「要確認」にする。

- 材料は testdata/制度データ/make_materials.py --build（D10）。公募要領の文を含むので、tmp_path に作る（downloads/ がなければ飛ばす）。
  章「1-4 補助対象事業と公募期間」の2回の読み取り（読み取り役が返す形）と、要領8・応募手引8 の資料の本文。
- 製品と同じ道で検査する：1回目と2回目を、それぞれ裏取りの道具（lib/urakadori.run）に通して章ごとの結果に置き、
  まとめる道具（lib/seido_data.merge）で1つの制度データにする。まとめるときに、重要な項目を2回の読み取りで突き合わせる（B25）。
- 混ぜたものの一覧（testdata/制度データ/混ぜたものの一覧.json）の「要確認になるべき場所」8つが、まとめた制度データで要確認になり、
  「確認済みのまま残るべき場所」5つが確認済みのまま残る。2回で食い違う重要な項目は、2回の読み取りの注記に両方の値が出る。
- 2回目を通さないと、2回で食い違う重要な項目（ページの裏取りは通る）は見つからない（突き合わせが効いていることの確かめ）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib import seido_data, urakadori

REPO_ROOT = Path(__file__).resolve().parent.parent
MATERIALS = REPO_ROOT / "testdata" / "制度データ"
ANSWER = json.loads((MATERIALS / "混ぜたものの一覧.json").read_text(encoding="utf-8"))["T3-8"]
DOUBLE = "2回の読み取りで食い違う重要な項目"


def _mm():
    if str(MATERIALS) not in sys.path:
        sys.path.insert(0, str(MATERIALS))
    import make_materials  # noqa: E402

    return make_materials


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mm = _mm()
    if not mm.have_downloads():
        pytest.skip("downloads/ に省力化 第8回の資料がない")
    return mm.build(tmp_path_factory.mktemp("材料"))


def states_by_place(data: dict) -> dict:
    """出典つき値の場所（社長に見せる書き方）→ 状態と注記。"""
    out = {}

    def visit(node, path):
        if isinstance(node, dict) and "値" in node and "状態" in node:
            out[urakadori.readable(path, data)] = (node["状態"], node.get("注記") or "")
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(data, [])
    return out


def run_readings(built, rounds):
    mm = _mm()
    company = built["T3-8"]
    for n in rounds:
        urakadori.run(company, mm.CASE, json.loads(json.dumps(built["読み取り"][n])))
    return seido_data.merge(company, mm.CASE)


def test_all_mixed_values_become_check(built) -> None:
    """T3-8：混ぜたもの（8つ）をすべて要確認にし、混ぜていないもの（5つ）は確認済みのまま。"""
    full, merged = run_readings(built, (1, 2))
    got = states_by_place(full)
    for place in ANSWER["要確認になるべき場所"]:
        assert got[place][0] == "要確認", (place, got[place])
    for place in ANSWER["確認済みのまま残るべき場所"]:
        assert got[place][0] == "確認済み", (place, got[place])
    assert len(ANSWER["要確認になるべき場所"]) == 8 and len(ANSWER["確認済みのまま残るべき場所"]) == 5
    # 2回で食い違う重要な項目は、2回の読み取りの注記に、両方の値が出る
    for v in ANSWER["値"]:
        if v["混ぜ方"] == DOUBLE:
            state, note = got[v["場所"]]
            assert seido_data.DOUBLE_PREFIX in note, (v["場所"], note)
            first = json.dumps(v["1回目の値"], ensure_ascii=False)
            second = json.dumps(v["2回目の値"], ensure_ascii=False)
            assert first in note and second in note, (v["場所"], note)
    assert merged.second_chapters == [ANSWER["章"]]
    assert merged.double_compared >= 5
    assert {w for w, _ in merged.double_diffs} >= {v["場所"] for v in ANSWER["値"] if v["混ぜ方"] == DOUBLE}


def test_without_second_reading_double_mismatch_is_missed(tmp_path_factory) -> None:
    """2回目を通さないと、ページの裏取りを通る「2回で食い違う重要な項目」は確認済みのまま（突き合わせが要る理由）。"""
    mm = _mm()
    if not mm.have_downloads():
        pytest.skip("downloads/ に省力化 第8回の資料がない")
    fresh = mm.build(tmp_path_factory.mktemp("材料_1回目だけ"))
    full, merged = run_readings(fresh, (1,))
    got = states_by_place(full)
    doubles = [v["場所"] for v in ANSWER["値"] if v["混ぜ方"] == DOUBLE]
    assert doubles and all(got[p][0] == "確認済み" for p in doubles)
    assert merged.second_chapters == []
    assert "2回目の読み取り：まだありません" in seido_data.merge_report(mm.CASE, merged, urakadori.Result(), "x.json")


def test_report_lists_double_mismatches(built) -> None:
    mm = _mm()
    full, merged = run_readings(built, (1, 2))
    text = seido_data.merge_report(mm.CASE, merged, urakadori.Result(), "記録/制度データ/省力化_第8回.json")
    assert "2回の読み取りで食い違った値（要確認にしました）" in text
    assert "補助額「従業員6〜20人」の上限" in text


def test_numbers_comparison_ignores_wording() -> None:
    a = {"値": "事業計画期間の毎年、年平均成長率4.0%以上", "状態": "確認済み"}
    b = {"値": "年平均 4.0% 以上（毎年）", "状態": "確認済み"}
    assert seido_data.readings_differ(a, b, False) is None
    c = {"値": "年平均成長率3.5%以上", "状態": "確認済み"}
    assert seido_data.readings_differ(a, c, False)
    assert seido_data.readings_differ({"値": 15000000, "状態": "確認済み"}, {"値": "1,500万円", "状態": "確認済み"}, False) is None
    assert seido_data.readings_differ({"値": None, "状態": "読み取れない"}, {"値": "1/2", "状態": "確認済み"}, False)


def test_missing_in_second_reading_is_check() -> None:
    """1回目にあって、同じ章の2回目にない重要な件（必須書類）も要確認にする。"""
    doc = {"名前": "履歴事項全部証明書", "区分": "必須", "内容": {"値": "発行から3か月以内", "状態": "確認済み", "出典": []}}
    first = {"読み取り": {"章": "書類"}, "制度データ": {"書類": [doc]}}
    second = {"読み取り": {"章": "書類", "回目": 2}, "制度データ": {"書類": []}}
    full = {"書類": [json.loads(json.dumps(doc))]}
    result = seido_data.MergeResult()
    seido_data.compare_readings(full, [first], [second], result)
    assert full["書類"][0]["内容"]["状態"] == "要確認"
    assert "2回目の読み取りに、この件がありません" in full["書類"][0]["内容"]["注記"]
