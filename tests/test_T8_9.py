"""T8-9 分量（上限と目安。自動の部分）と、書く → 確かめる → 直すの繰り返しと打ち切り（SPEC F8・F9、DESIGN 8章。TASKS B19）。

T8-9 の合格ライン（自動の部分）：上限の超過0件。目安の範囲内。目安がない項目（上限だけの項目を含む）の
「足りない」「長すぎる」0件は、審査役が見る（evals/T8-8-T8-9-筋立てと分量）。

- 文字数：様式の項目に「上限」があれば超えたら、「目安」があれば目安の半分から2割増しまで（仮）を外れたら、
  確かめる道具（kakunin.py count）が止める。全項目が書けた計画書（D9）は通る。
- 打ち切り（SPEC F9・DESIGN 8章「途中でやめて社長に返す条件」）：審査役の結果に社長の答えが要る指摘があれば、
  審査役を呼び直させない（prepare が止める）。社長に返すまでに審査役を3回より多く呼ばせない。同じ指摘が2回続いたら
  止める。コードの確かめを直す繰り返しが5回を超えたら止める。社長の答え（質問の記録の新しい答え）の後は数え直す。
- 審査役の結果のそろい具合（文体の C・審査項目と加点項目・4つの段・分量。B18）と、完成の記録が、切れ目と
  「足りない」「長すぎる」のある結果では残らないこと。
- 質問の記録の hook（B15）：【質問】を Stop で読み取り、案件・段階・1回の数・理由を付けて残し、次の発言を答えにする。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import kakunin_tool as kt
import plan_tool as pt
import pytest

from lib import kakunin, shinsa_result


@pytest.fixture
def env(tmp_path) -> kt.Env:
    return kt.Env(tmp_path)


# ---------------------------------------------------------------- 文字数（上限と目安）


def seido_with(limits: dict) -> dict:
    return {"様式": [{"名前": "様式", "項目": [{"名前": k, "分量の上限": {"値": v}} for k, v in limits.items()]}]}


def test_length_limits_and_targets() -> None:
    seido = seido_with({"名前": {"種類": "目安", "文字数": 30}, "概要": {"種類": "上限", "文字数": 100},
                        "本文": {"種類": "なし"}})
    texts = {"名前": "あ" * 30, "概要": "い" * 100, "本文": "う" * 5000}
    assert kakunin.length_findings(texts, seido) == []  # 目安ちょうど、上限ちょうど、目安も上限もない項目
    texts = {"名前": "あ" * 37, "概要": "い" * 101}
    found = {f["場所"]: f for f in kakunin.length_findings(texts, seido)}
    assert found["概要"]["理由"] == "上限の100字を1字超えています"
    assert "目安の30字程度から外れています（37字）" == found["名前"]["理由"]
    assert kakunin.length_findings({"名前": "あ" * 14}, seido)  # 半分より短い
    assert kakunin.length_findings({"名前": "あ" * 15}, seido) == []
    assert kakunin.char_count("  1行目\n2行目  \n") == 6  # 改行と行の頭・終わりの空白は数えない


def test_full_plan_passes_lengths(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    code, report = env.count()
    assert report["文字数"] == [] and code == 0


def test_too_long_plan_name_stops_the_check(env: kt.Env) -> None:
    name = pt.plan()["項目"][0]
    assert name["名前"] == "（2）事業計画名"
    items = pt.items_with(pt.CORRECT, "（2）事業計画名", name["本文"], name["本文"] + "で、病院と介護施設とスーパーの注文を断らない")
    rows = pt.rows()
    pt.place(env, pt.form_or_skip(), items=items, evidence=rows)
    code, report = env.count()
    assert code == 3 and [f["場所"] for f in report["文字数"]] == ["（2）事業計画名"]
    assert "目安 30字（15〜36字）" in kt.code(env.tool("count"), 3)


# ---------------------------------------------------------------- 打ち切り


def review_once(env: kt.Env, findings, **extra) -> str:
    """prepare → 審査役の報告を hook で保存 → result。確かめの番号を返す。"""
    text = kt.ok(env.tool("prepare"))
    number = text.split("確かめの番号：")[1].split()[0]
    env.subagent_stop(kt.report_json(number, findings, **extra))
    env.tool("result")
    return number


def must_fix(where: str) -> dict:
    return kt.finding("要修正", f"{where}の試しの指摘", where=where)


def test_three_reviews_then_return(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    for n, where in enumerate(("1-1 現状分析", "1-2 経営課題", "6. 補足事項"), start=1):
        assert review_once(env, [must_fix(where)]) == f"確かめ-{n:04d}"
    r = env.tool("prepare")
    text = kt.out(r)
    assert r.returncode == 3 and "審査役を3回呼んでも、要修正が残っています" in text and "社長に返します" in text
    assert not (env.folder / kt.RESULTS / "確かめ-0004.json").exists()


def test_owner_answer_needed_stops_at_once_and_answer_resets(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    ask = dict(kt.finding("要確認", "取引が決まっているかが分からない", where="3. 新たな付加価値"),
               社長に聞くこと="2027年10月からの取引は、本当に決まっていますか")
    review_once(env, [must_fix("1-1 現状分析"), ask])
    text = kt.out(env.tool("result"))
    assert "社長の答えや判断が要るものがあります" in text and "社長に聞くこと：2027年10月からの取引" in text
    r = env.tool("prepare")
    assert r.returncode == 3 and "審査役を呼び直さずに" in kt.out(r)
    # 社長が答えた（質問の記録に新しい答え）→ 数え直して、また呼べる
    later = (datetime.now() + timedelta(days=400)).isoformat(timespec="seconds")
    log = {"質問": [{"番号": "質問-0001", "問い": "取引は決まっていますか", "理由": "計画の数字の元", "答え": "まだ決まっていない",
                    "答えた時刻": later, "経路": "【質問】"}]}
    env.put(kakunin.QUESTION_LOG, json.dumps(log, ensure_ascii=False).encode("utf-8"))
    assert kt.ok(env.tool("prepare")).count("確かめの番号：確かめ-0002") == 1


def test_same_finding_twice_returns(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    review_once(env, [must_fix("1-2 経営課題")])
    review_once(env, [must_fix("1-2 経営課題")])
    r = env.tool("prepare")
    assert r.returncode == 3 and "同じ指摘が2回続きました" in kt.out(r)


def test_code_fix_loop_over_five_returns(env: kt.Env) -> None:
    items = pt.items_with(pt.CORRECT, "1-2 経営課題", "。", "。【空欄：断った注文の件数】")
    pt.place(env, pt.form_or_skip(), items=items)
    for _ in range(5):
        kt.code(env.tool("count"), 3)
    text = kt.code(env.tool("count"), 3)
    assert "コードの確かめを直して確かめ直す繰り返しが5回を超えました" in text
    r = env.tool("prepare")
    assert r.returncode == 3 and "5回を超えました" in kt.out(r)


def test_completion_needs_no_gaps_and_no_length_problems(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    flow = {"段": {"現状と目標": ["1-1 現状分析"], "課題": ["1-2 経営課題"], "解決策": ["2. 省力化投資"], "効果": ["2-2"]},
            "切れ目": [{"場所": "1-2 → 2-2", "内容": "残業の課題に効果がない"}]}
    review_once(env, [], 筋立て=flow, 分量=[{"項目": "4. 財務計画（資金調達と今後の数値計画）", "判定": "足りない", "理由": "推移がない"}])
    text = kt.code(env.tool("finish"), 3)
    assert "切れ目 1件" in text and "足りない・長すぎる項目が 1件" in text
    flow["切れ目"] = []
    review_once(env, [], 筋立て=flow, 分量=[{"項目": "4. 財務計画（資金調達と今後の数値計画）", "判定": "足りる", "理由": "…"}])
    assert "完成にしました" in kt.ok(env.tool("finish"))
    entry = env.completion()["記録"][-1]
    full = entry["審査役の結果のそろい具合"]
    assert full["4つの段"] == "4/4" and full["切れ目"] == 0 and full["足りない・長すぎる"] == 0


def test_length_verdict_on_an_item_not_given_does_not_stop_completion(env: kt.Env) -> None:
    """「足りない」「長すぎる」は、分母と同じ項目（計画書の本文で渡した、目安のない項目）の中だけで数える（B19 の直し）。"""
    pt.place(env, pt.form_or_skip())
    flow = {"段": {"現状と目標": ["1-1 現状分析"], "課題": ["1-2 経営課題"], "解決策": ["2. 省力化投資"], "効果": ["2-2"]},
            "切れ目": []}
    not_given = "算定根拠 ①付加価値額（最終年の年平均成長率を含む）"  # その3 の項目。本文で渡していない
    review_once(env, [], 筋立て=flow, 分量=[{"項目": not_given, "判定": "足りない", "理由": "その3 がない"},
                                         {"項目": "1-1 現状分析", "判定": "足りる", "理由": "…"}])
    full = json.loads((env.folder / kt.RESULTS / "確かめ-0001.json").read_text(encoding="utf-8"))["そろい具合"]
    assert full["足りない・長すぎる"] == 0 and full["渡していない項目への分量の判定"] == [not_given]
    assert "完成にしました" in kt.ok(env.tool("finish"))


def test_completeness_counts_against_what_was_given(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    kt.ok(env.tool("prepare"))
    seido = json.loads((env.folder / kt.PACKAGE / "制度データの抜き出し.json").read_text(encoding="utf-8"))
    names = [x["名前"] for x in seido["審査項目"]] + [x["名前"] for x in seido["加点"]["項目"]]
    parsed = {"文体C": [{"番号": n, "観点": "…", "判定": "可", "理由": "…"} for n in range(1, 13)],
              "審査項目": [{"名前": n, "点数": 3, "理由": "…"} for n in names[:5]],
              "加点項目": [{"名前": n, "点数": 0, "理由": "申請しない"} for n in names[5:]]}
    full = shinsa_result.completeness(env.folder, parsed)
    assert full["文体の基準C"] == "12/12" and full["審査項目と加点項目"] == f"{len(names)}/{len(names)}"
    parsed["文体C"] = parsed["文体C"][:11]
    parsed["加点項目"] = parsed["加点項目"][1:]
    full = shinsa_result.completeness(env.folder, parsed)
    assert full["判定と理由のない観点"] == [12] and full["点数と理由のない項目"] == [names[5]] and not full["そろった"]


# ---------------------------------------------------------------- 質問の記録の hook（B15）


def test_question_hook_records_text_questions_and_answers(env: kt.Env) -> None:
    pt.place(env, pt.form_or_skip())
    message = ("下書きを書きました。\n\n【質問】\n1. 盛り付けの延べ時間は1日何時間ですか。（理由：省力化の効果の元になるため）\n"
               "2. 去年のクレームは何件ですか。（理由：課題の大きさを数で示すため）\n")
    env.hook("Stop", {"stop_hook_active": False, "last_assistant_message": message})
    log = json.loads((env.folder / kakunin.QUESTION_LOG).read_text(encoding="utf-8"))["質問"]
    assert [(e["案件"], e["段階"], e["同じ回の数"], e["経路"]) for e in log] == [(kt.CASE, kt.STAGE, 2, "【質問】")] * 2
    assert log[0]["理由"] == "省力化の効果の元になるため" and "答え" not in log[0]
    env.hook("Stop", {"stop_hook_active": True, "last_assistant_message": message})  # 同じ応答の終わりは二重に残さない
    assert len(json.loads((env.folder / kakunin.QUESTION_LOG).read_text(encoding="utf-8"))["質問"]) == 2
    env.hook("UserPromptSubmit", {"prompt": "1日に延べ38時間くらい。クレームは7件"})
    log = json.loads((env.folder / kakunin.QUESTION_LOG).read_text(encoding="utf-8"))["質問"]
    assert all(e["答え"] == "1日に延べ38時間くらい。クレームは7件" and e["答えた時刻"] for e in log)
    env.hook("PostToolUse", {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{
        "question": "従業員は今も15人ですか（理由：前回の値を使うため）", "header": "人数",
        "options": [{"label": "はい"}, {"label": "分からない"}], "multiSelect": False}]},
        "tool_response": {"answers": {"従業員は今も15人ですか（理由：前回の値を使うため）": "はい"}}}, match="AskUserQuestion")
    last = json.loads((env.folder / kakunin.QUESTION_LOG).read_text(encoding="utf-8"))["質問"][-1]
    assert (last["経路"], last["答え"], last["理由"], last["同じ回の数"]) == ("選択肢の画面", "はい", "前回の値を使うため", 1)
