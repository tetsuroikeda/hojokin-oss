"""T9-3 文体（数えられるもの）（SPEC F9。TASKS B17。DESIGN 6章・8.2）。

合格ライン（11/7 の作者の決定で直した）：docs/style-criteria.md の A と B で数える → 「要修正」（記号の残り、です・ます調と
である調の混在）0件。会社の記録の避けたい言い方への該当0件。B への該当と、A の「注意」（100字を超える文を含む）・「弱い注意」は、
数えて示すが合否に使わない。A と B が重なる項目は A に従う。

- 文体の基準の表は、そのたびに docs/style-criteria.md から読む（lib/buntai.py）。
- A の要修正と、会社の記録の避けたい言い方を数え、確かめる道具（kakunin.py count）の合否に入れる。
- B の避ける言い回しと100字を超える文は、数えて道具の出力に示すが、合否に入れない。
- 社長が残すと決めた言い回し（会社の記録の「好む言い方」の「」）は数えない。
- A と B が重なる言い回し（「さまざまな」「等」、カタカナ語）は、注意として数え、合否に使わない。
- 全項目が書けた計画書（D9）は、要修正0件・避ける言い回し0件で通る。
"""

from __future__ import annotations

import json

import kakunin_tool as kt
import plan_tool as pt
import pytest

from lib import buntai

CRITERIA = kt.REPO_ROOT / "docs" / "style-criteria.md"


@pytest.fixture(scope="module")
def criteria() -> buntai.Criteria:
    return buntai.load(CRITERIA)


def count(text: str, criteria, avoid=(), keep=()) -> dict:
    return buntai.count({"1-1 現状分析": text}, criteria, avoid, keep)


def test_b_table_is_read_from_the_criteria_file(criteria) -> None:
    phrases = [p for _k, p, _f, _pat in criteria.b_rules]
    assert len(phrases) >= 30
    assert "喫緊の課題" in phrases and "〜することができる" in phrases and "革新的" in phrases
    # 「〇〇等」・かぎかっこの例・2字以下の語は数えない（D9 の check_plans.py と同じ読み方）
    assert not any("〇〇" in p or "「" in p for p in phrases)


def test_long_sentence_is_caution_and_not_failing(criteria) -> None:
    """100字を超える文は、注意として示すが合否に使わない（11/7 の作者の決定）。"""
    got = count("当社は" + "、".join(["惣菜を作り"] * 20) + "、病院と介護施設とスーパーに毎朝届けています。", criteria)
    assert any("100字を超える" in f["基準"] for f in got[buntai.CAUTION]), got
    assert got[buntai.MUST_FIX] == [] and buntai.failing(got) == 0


@pytest.mark.parametrize("text, rule", [
    ("**強み**は、病院ごとの細かい注文に応えることです。", "記号の残り"),
    ("当社は惣菜を作っています。病院に届けている。スーパーにも届けています。", "混在"),
])
def test_must_fix_items_are_counted(criteria, text: str, rule: str) -> None:
    got = count(text, criteria)
    assert any(rule in f["基準"] for f in got[buntai.MUST_FIX]), got
    assert buntai.failing(got) >= 1


@pytest.mark.parametrize("text, phrase", [
    ("人手の確保は喫緊の課題です。", "喫緊の課題"),
    ("機械で注文に対応することができる仕組みにします。", "〜することができる"),
    ("革新的な盛り付けの仕組みを入れます。", "革新的"),
    ("これにより、1日4,500パックの出荷が可能になります。", "これにより〜が可能になります"),
])
def test_b_phrases_are_counted(criteria, text: str, phrase: str) -> None:
    """B の避ける言い回しは数えて示すが、合否に使わない（11/7 の作者の決定）。"""
    got = count(text, criteria)
    assert any(f"「{phrase}」" in f["基準"] for f in got[buntai.B_HIT]), got
    assert buntai.failing(got) == 0


def test_overlap_with_a_is_caution_and_not_failing(criteria) -> None:
    got = count("さまざまな惣菜を作り、ソリューションとして届けます。", criteria)
    assert got[buntai.B_HIT] == [] and buntai.failing(got) == 0
    assert any("さまざまな" in f["基準"] for f in got[buntai.CAUTION])
    assert any("ソリューション" in f["基準"] for f in got[buntai.CAUTION])


def test_caution_and_weak_caution_are_not_failing(criteria) -> None:
    text = ("当社の盛り付け工程は、正社員1人とパート5人が、はかりと手作業で、1つずつ量って盛り付けています。"
            "品質管理体制強化計画を作っています。") * 3
    got = count(text, criteria)
    assert got[buntai.CAUTION] and buntai.failing(got) == 0


def test_company_avoid_and_keep(criteria) -> None:
    rules = [
        {"種類": "書き方の決まり", "区分": "避けたい言い方", "内容": "「お客様の笑顔」とは書かない"},
        {"種類": "書き方の決まり", "区分": "好む言い方", "内容": "「革新的」は社長の言葉なので残す"},
    ]
    avoid, keep = buntai.company_phrases(rules)
    assert avoid == ["お客様の笑顔"] and keep == ["革新的"]
    got = count("お客様の笑顔のために、革新的なラインを入れます。", criteria, avoid, keep)
    assert [f["文字"] for f in got[buntai.COMPANY_HIT]] == ["お客様の笑顔"]
    assert got[buntai.B_HIT] == []  # 社長が残すと決めたものは数えない
    assert buntai.failing(got) == 1


# ---------------------------------------------------------------- 道具（kakunin.py count）で


@pytest.fixture
def env(tmp_path) -> kt.Env:
    return kt.Env(tmp_path)


def test_full_plan_has_no_must_fix_and_no_b(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    code, report = env.count()
    style = report["文体"]
    assert (style["要修正"], style["避ける言い回し"], style["避けたい言い方"]) == ([], [], [])
    assert code == 0


def test_b_phrase_in_the_plan_is_shown_but_does_not_stop_the_check(env: kt.Env) -> None:
    items = pt.items_with(pt.CORRECT, "1-2 経営課題", "。", "。人手の確保は喫緊の課題です。")
    pt.place(env, pt.form_or_skip(), items=items)
    code, report = env.count()
    assert code == 0
    assert [f["場所"] for f in report["文体"]["避ける言い回し"]] == ["1-2 経営課題"]
    text = kt.code(env.tool("count"), 0)
    assert "避ける言い回し 1件" in text and "喫緊の課題" in text and "すぐ手を打つべき課題" in text


def test_company_avoid_phrase_from_the_record_stops_the_check(env: kt.Env) -> None:
    items = pt.items_with(pt.CORRECT, "1-2 経営課題", "。", "。お客様の笑顔を守ります。")
    pt.place(env, pt.form_or_skip(), items=items)
    from lib import company_record

    source = company_record.make_source(env.folder, "社長の発言", utterance="この言い方は使わないで")
    company_record.add_rule(env.folder, "避けたい言い方", "「お客様の笑顔」とは書かない", "この言い方は使わないで", source)
    code, report = env.count()
    assert code == 3 and [f["文字"] for f in report["文体"]["避けたい言い方"]] == ["お客様の笑顔"]
