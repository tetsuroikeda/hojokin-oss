"""T3-7 制度データの作成の、正解との突き合わせ（SPEC F3。TASKS B25）。

SPEC：省力化と持続化の制度データを作り、正解と突き合わせる。期間中は、Claude が作った仮の正解で照らす（作者の確かめは後）。
合格ライン：照らす項目の一致率100%（仮）。すべてに出典ページ。読み取れない項目は空けたまま示す。正解に含めた資料どうしの食い違いを、すべて示す。

このファイルは2つを見る。
1. 突き合わせの道具（tests/seido_compare.py）が正しく数えるか：正解どうしは100%で、値や件を変えた写しでは、その所だけが外れる。
   読み取れない値に値を入れたもの、出典を消したもの、資料どうしの食い違いを消したものも見つける。
2. 振る舞い（eval の T3-7。保存した状態「制度データの前」から、第8回の資料で制度データを作る）で残した出力の突き合わせ：
   環境変数 HOJOKIN_T3_7_KEPT に、eval が残した会社のフォルダ（`記録/制度データ/省力化_第8回.json` があるもの）を渡すと、
   正解（testdata/正解/省力化_第8回.json）と突き合わせ、合格ラインで合否を出す。渡さなければ飛ばす（DESIGN 11章）。
   持続化 第20回の制度データの eval は、期間中は作っていない（作業の報告に書いた）。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

import seido_compare as sc

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWERS = REPO_ROOT / "testdata" / "正解"


def load(name: str) -> dict:
    return json.loads((ANSWERS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["省力化_第8回.json", "持続化_第20回.json"])
def test_answer_against_itself_is_full_match(name) -> None:
    answer = load(name)
    rep = sc.compare(copy.deepcopy(answer), answer)
    assert rep.points and rep.rate == 1.0, sc.summary(rep)
    assert not rep.missing_conflicts and not rep.filled_unreadable
    cats = set(rep.by_category())
    assert {"必須書類", "締切", "要件", "審査項目", "加点", "様式", "補助額", "審査の段階", "手続きの段階",
            "採択後の書類", "補助の対象にならない経費"} <= cats


def test_changed_values_and_missing_items_are_found() -> None:
    answer = load("省力化_第8回.json")
    got = copy.deepcopy(answer)
    got["補助額"][1]["上限"]["値"] = 18000000                       # 値を変えた
    got["決まった期日"] = [d for d in got["決まった期日"] if "締切" not in d["名前"]]  # 締切を落とした
    got["書類"] = [d for d in got["書類"] if d["名前"] != "履歴事項全部証明書"]  # 必須書類を落とした
    got["数値の要件"][0]["基準"]["値"] = "事業計画期間の毎年、年平均成長率3.0%以上"  # 数を変えた
    got["補助額"][0]["補助率"]["値"] = "1／2"                          # 書き方だけ違う（全角の／）は合う
    rep = sc.compare(got, answer)
    missed = {p.where for p in rep.misses()}
    assert any("従業員6〜20人" in w and "上限" in w for w in missed)
    assert any(w.startswith("決まった期日「締切」") for w in missed)
    assert "書類「履歴事項全部証明書」" in missed
    assert any("労働生産性" in w and "基準" in w for w in missed)
    assert not any("従業員5人以下" in w and "補助率" in w for w in missed)
    assert rep.rate < 1.0


def test_wording_differences_are_not_misses() -> None:
    answer = load("省力化_第8回.json")
    got = copy.deepcopy(answer)
    got["数値の要件"][0]["基準"]["値"] = "毎年、基準年度比で年平均 4.0 % 以上（3〜5年の事業計画期間）"
    got["審査項目"][0]["名前"] = "補助対象事業としての適格性（書面審査）"
    rep = sc.compare(got, answer)
    assert rep.rate == 1.0, sc.summary(rep)


def test_unreadable_with_value_unsourced_and_missing_conflict_are_reported() -> None:
    answer = load("省力化_第8回.json")
    got = copy.deepcopy(answer)
    got["加点"]["区分ごとの上限"]["値"] = 3              # 読み取れないのに値を入れた
    got["補助額"][0]["上限"]["出典"] = []                 # 出典を消した
    got["資料どうしの食い違い"] = got["資料どうしの食い違い"][1:]  # 食い違いを1つ消した
    rep = sc.compare(got, answer)
    assert rep.filled_unreadable and rep.unsourced
    assert rep.missing_conflicts == [answer["資料どうしの食い違い"][0]["項目"]]


def test_kept_eval_output_matches_answer() -> None:
    """eval（T3-7）で残した会社のフォルダの制度データを、正解と突き合わせる（HOJOKIN_T3_7_KEPT。なければ飛ばす）。"""
    kept = os.environ.get("HOJOKIN_T3_7_KEPT")
    if not kept:
        pytest.skip("HOJOKIN_T3_7_KEPT に、eval が残した会社のフォルダを渡すと流れる")
    path = Path(kept) / "記録" / "制度データ" / "省力化_第8回.json"
    got = json.loads(path.read_text(encoding="utf-8"))
    rep = sc.compare(got, load("省力化_第8回.json"))
    print(sc.summary(rep))
    assert rep.rate == 1.0, sc.summary(rep)  # 一致率100%（仮）
    assert not rep.unsourced, rep.unsourced[:10]
    assert not rep.filled_unreadable, rep.filled_unreadable[:10]
    assert not rep.missing_conflicts, rep.missing_conflicts
