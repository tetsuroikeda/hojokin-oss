"""T3-3 加点の判定（SPEC F3。TASKS B24）。

SPEC：今日の日付を変えて判定する。
合格ライン：間に合わない加点を「今回は取れない」と判定する。

- 道具の中身（lib/nittei.judge_bonuses）に、制度データの正解（持続化 第20回。仮の正解）と、変えた今日の日付を渡す。
- 間に合わない加点の型（どれも、これから取り始めるとき）：
  1. 基準日（決まった期日）までに満たす決まりで、基準日を過ぎた（経営力向上計画加点：基準日 2026-09-30 までの認定）。
  2. 申請の締切を過ぎた（すべての加点）。
  3. 要る書類の依頼の締切を過ぎた（事業承継加点の様式10 に、依頼の締切を足した写しで確かめる）。
  4. かかる日数から逆算した始める日を過ぎた（会社の記録の「加点の日数」、または制度データに出典つきの日数を足した写し）。
- 間に合うときは「取れる見込み」、日数が資料にない加点は「確かめが要る」（推測しない。DESIGN 14章）。
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

from lib import nittei

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((REPO_ROOT / "testdata" / "正解" / "持続化_第20回.json").read_text(encoding="utf-8"))
DEADLINE = date(2026, 12, 15)


def judged(data, today, facts=()):
    return {b.name: b for b in nittei.judge_bonuses(data, today, DEADLINE, list(facts), 20)}


def test_reference_date_passed_means_not_this_time() -> None:
    """基準日（2026-09-30）までに認定を受ける加点は、11/5 にこれから取り始めても間に合わない。"""
    got = judged(DATA, date(2026, 11, 5))
    b = got["経営力向上計画加点"]
    assert b.judge == nittei.NO == "今回は取れない"
    assert "基準日" in b.reason and "すでに満たしていれば取れます" in b.reason
    assert b.sources == ["参考資料20 p.13"]


def test_before_reference_date_is_in_time() -> None:
    b = judged(DATA, date(2026, 9, 1))["経営力向上計画加点"]
    assert b.judge == nittei.OK and b.due == date(2026, 9, 30)


def test_age_reference_date_is_not_a_deadline_to_act() -> None:
    """事業承継加点の基準日は年齢を数える日（「までに」ではない）。基準日を過ぎても、それだけで「取れない」にしない。"""
    b = judged(DATA, date(2026, 11, 5))["事業承継加点"]
    assert b.judge == nittei.CHECK


def test_after_application_deadline_all_not_this_time() -> None:
    got = judged(DATA, date(2026, 12, 16))
    assert got and all(b.judge == nittei.NO for b in got.values())


def test_required_document_request_deadline_passed() -> None:
    data = copy.deepcopy(DATA)
    doc = next(d for d in data["書類"] if d["名前"] == "事業承継診断票（様式10）")
    doc["依頼の締切"] = {"値": {"種類": "決まった日付", "日時": "2026-12-04"}, "出典": [{"資料": "要領20", "ページ": 29}],
                     "根拠の文": "（テスト用）", "状態": "確認済み"}
    assert judged(data, date(2026, 11, 20))["事業承継加点"].judge == nittei.OK
    b = judged(data, date(2026, 12, 10))["事業承継加点"]
    assert b.judge == nittei.NO and "依頼の締切" in b.reason


def test_days_from_company_record() -> None:
    """会社の記録の「加点の日数」（前に社長に聞いた日数）から逆算する：45日なら、始める日は 2026-10-31。"""
    facts = [{"id": "事実-0002", "種類": "事実", "名前": "加点の日数：事業継続力強化計画策定加点", "値": "45日"}]
    early = judged(DATA, date(2026, 10, 20), facts)["事業継続力強化計画策定加点"]
    assert early.judge == nittei.OK and early.start == date(2026, 10, 31)
    late = judged(DATA, date(2026, 11, 5), facts)["事業継続力強化計画策定加点"]
    assert late.judge == nittei.NO and "2026年10月31日" in late.reason


def test_days_from_seido_data_with_source() -> None:
    data = copy.deepcopy(DATA)
    bonus = next(b for b in data["加点"]["項目"] if b["名前"] == "くるみん・えるぼし加点")
    bonus["かかる日数"] = {"値": {"数": 30, "単位": "日"}, "出典": [{"資料": "要領20", "ページ": 34}],
                        "根拠の文": "（テスト用）", "状態": "確認済み"}
    assert judged(data, date(2026, 11, 1))["くるみん・えるぼし加点"].judge == nittei.OK
    assert judged(data, date(2026, 11, 20))["くるみん・えるぼし加点"].judge == nittei.NO


def test_unknown_days_is_check_not_guess() -> None:
    b = judged(DATA, date(2026, 11, 5))["くるみん・えるぼし加点"]
    assert b.judge == nittei.CHECK and "推測しない" in b.reason


def test_schedule_lists_bonus_preparation_when_in_time() -> None:
    sched = nittei.build_schedule(DATA, date(2026, 9, 1), [], 20)
    assert any(i.kind == "加点" and "経営力向上計画加点" in i.name and i.due == date(2026, 9, 30) for i in sched.items)
    assert "今回は取れない" not in [b.judge for b in sched.bonuses if b.name == "経営力向上計画加点"]
