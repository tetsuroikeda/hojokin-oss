"""T9-1 事実の照合（SPEC F9。TASKS B16。DESIGN 6章・8.1）。

合格ライン：本文の数字・固有名詞・日付を根拠対照表と突き合わせる → 根拠なし0件、食い違い0件。本文に出典の書き込み0件。

- 全項目が書けた計画書（D9 の正しい計画書。tests/plan_tool.py）を、公式の様式に書いて確かめる道具（kakunin.py count）に
  かける。根拠なし・食い違い・本文の出典が0件で、コードの確かめが通る。
- 1つずつ崩して、道具が見つけることを確かめる：表にない数字・日付・固有名詞（根拠なし）、表の記述が本文にない
  （食い違い）、本文に書いた出典（「出典：」「p.3」「回答表」など）。
- 聞き取りと違う記述を混ぜた計画書（D9 の2）は、表の出典が回答表の ID のままなので、コードの確かめは通る
  （審査役が見つけるもの。T9-2）。
"""

from __future__ import annotations

import kakunin_tool as kt
import plan_tool as pt
import pytest

from lib import shogo


@pytest.fixture
def env(tmp_path) -> kt.Env:
    return kt.Env(tmp_path)


def kinds(report: dict) -> dict:
    return {k: report[k] for k in ("根拠なし", "食い違い", "本文の出典")}


def test_full_plan_passes(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    code, report = env.count()
    assert kinds(report) == {"根拠なし": [], "食い違い": [], "本文の出典": []}, report
    assert report["財務モデルとの食い違い"] == []
    assert code == 0 and report["通った"]


@pytest.mark.parametrize("item, old, new, words", [
    ("1-1 現状分析", "介護施設11か所", "介護施設12か所", "12か所"),  # 数字
    ("2-1 設備導入による業務プロセスや配置のビフォーアフター", "。", "。2027年9月に入れ替えます。", "2027年9月"),  # 日付
    ("6. 補足事項", "。", "。株式会社あおば商事とも話しています。", "株式会社あおば商事"),  # 固有名詞
])
def test_fact_not_in_the_table_is_found(env: kt.Env, item, old, new, words) -> None:
    pt.place(env, pt.form_or_skip(), items=pt.items_with(pt.CORRECT, item, old, new))
    code, report = env.count()
    assert code == 3
    found = [f for f in report["根拠なし"] if f["場所"] == item]
    assert any(words in f["文字"] for f in found), report["根拠なし"]


def test_table_row_not_in_the_text_is_a_mismatch(env: kt.Env) -> None:
    # 本文の「介護施設11か所」を直したのに、表を直していない
    items = pt.items_with(pt.CORRECT, "1-1 現状分析", "介護施設11か所", "介護施設")
    pt.place(env, pt.form_or_skip(), items=items)
    code, report = env.count()
    assert code == 3
    assert [f["文字"] for f in report["食い違い"]] == ["介護施設11か所"]


@pytest.mark.parametrize("citation", ["（出典：決算書 第18期 p.3）", "（回答表 E-01）", "（社長の答え、2026年11月6日）",
                                      "（見積書_つばさ台フードシステム.pdf 1ページ）"])
def test_citation_in_the_text_is_found(env: kt.Env, citation: str) -> None:
    items = pt.items_with(pt.CORRECT, "1-1 現状分析", "201,600千円", "201,600千円" + citation)
    rows = pt.rows()
    if "2026年11月6日" in citation:
        rows.append({"記述": "2026年11月6日", "種類": "日付", "書いた場所": "1-1 現状分析", "出典": "社長の答え（2026-11-06）"})
    pt.place(env, pt.form_or_skip(), items=items, evidence=rows)
    code, report = env.count()
    assert code == 3
    assert len(report["本文の出典"]) >= 1 and report["本文の出典"][0]["場所"] == "1-1 現状分析"


def test_facts_learned_after_the_model_are_noted_but_do_not_stop(env: kt.Env) -> None:
    """財務モデルを作った後に会社の記録に増えた事実は、注意に挙げる。完成は止めない（B37。11/6 のリハーサル）。"""
    import json

    from lib import company_record

    model = pt.numbers()
    model[company_record.FACT_MARKS_KEY] = {}  # 作ったときは、会社の記録に事実がなかった
    pt.place(env, pt.form_or_skip(), model=model)
    code, report = env.count()
    assert code == 0 and not any("財務モデルを作った後" in n for n in report["注意"])

    source = company_record.make_source(env.folder, "社長の発言", utterance="3年目までに1日約500パック増やす")
    _, fact, _ = company_record.add_fact(env.folder, "増産の見込み", "3年目までに1日約500パック増やす", True, source)
    code, report = env.count()
    notes = [n for n in report["注意"] if "財務モデルを作った後" in n]
    assert code == 0 and len(notes) == 1 and f"増産の見込み（{fact['id']}）" in notes[0], json.dumps(report["注意"], ensure_ascii=False)


def test_mixed_plan_passes_the_code_check(env: kt.Env) -> None:
    """聞き取りと食い違う記述は、表の出典が正しい計画書と同じなので、コードでは見つからない（審査役が見る。T9-2）。"""
    pt.place(env, pt.form_or_skip(), variant=pt.MIXED)
    code, report = env.count()
    assert kinds(report) == {"根拠なし": [], "食い違い": [], "本文の出典": []}, report
    assert code == 0


# ---------------------------------------------------------------- 部品（様式なしでも流せる）


def test_facts_finds_numbers_dates_and_companies() -> None:
    text = "2026年3月期の売上は201,600千円で、1日に約3,500パックを出す。株式会社つばさ台フードシステムに頼む。4.0%伸びる。"
    found = shogo.facts(text)
    assert ("日付", "2026年3月期") in found and ("数字", "201,600千円") in found
    assert ("数字", "約3,500パック") in found and ("数字", "4.0%") in found
    assert ("固有名詞", "株式会社つばさ台フードシステム") in found
    assert ("数字", "1日") not in found  # 「1日に」は単位の1つ分を言うだけ


def test_oku_amounts_and_fractions_are_read_as_written() -> None:
    """「2億4,160万円」は1つの数として取り、財務モデルの値と照らせる。「3分の1」の「分」は時間として取らない（B37）。"""
    found = shogo.facts("売上は2億160万円から2億4,160万円に増える。増産分を毎年3分の1ずつ足す。1日延べ2,280分。")
    assert ("数字", "2億160万円") in found and ("数字", "2億4,160万円") in found
    assert ("数字", "4,160万円") not in found and ("数字", "3分") not in found
    assert ("数字", "2,280分") in found
    assert shogo.shown_number("2億4,160万円") == (241600000.0, 5000.0, "円")
    assert shogo.shown_number("554万円") == (5540000.0, 5000.0, "円")


def test_covered_ignores_about_and_commas() -> None:
    assert shogo.covered("約3,500パック", ["約3500パック"]) and shogo.covered("3,500パック", [shogo.norm("約3,500パック")])
    assert not shogo.covered("3,600パック", [shogo.norm("約3,500パック")])


def test_citations() -> None:
    assert shogo.citations("売上は伸びた（出典：決算書）。")
    assert shogo.citations("要領8 p.12 にある")
    assert not shogo.citations("決算書の数字をもとに、売上の計画を立てた。")
