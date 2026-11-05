"""2件目の初稿までの会話を調べる道具（tests/multiturn/nikenme.py）と、保存した状態「1件目を終えた」（TASKS B7）を、
モデルを使わずに確かめる。

- nikenme：初稿を書いた呼び出しの見つけ方、初稿までの質問の数え方、確かめ・聞き直し・新しいことの分け方、
  2件目への反映（T13-6・T13-7・T13-14）の確かめ方、記録あり・なしの比べ方（T13-3 の半分の線）。
- 「1件目を終えた」：1件目で学んだこと（事実・4種類の指摘・「次からも」の答え・社長の Word の手直し）が会社の記録にあり、
  避けたい言い方が文体の確かめに加わる。「今回だけ」の指示は記録にない。2件目（持続化）の準備が済み、今日の日付は
  記録の最後に確かめた日より後（変わりうる情報の確かめが要る形）。「記録なし」は会社の記録が空で、聞き取りの記録もない。
本物の claude -p で2件目を流す確かめは、TASKS B7 の終わりの確かめで行う（利用枠を使うので、ここでは流さない）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import nikenme  # noqa: E402

CASE2 = nikenme.SECOND_CASE


def _conversation(items: list) -> list:
    return [dict(item, 番=n) for n, item in enumerate(items, 1)]


def test_draft_call_is_the_first_write_to_a_form() -> None:
    log = [{"場面": "呼び出し", "番": 1}, {"道具": "Bash", "入力": {"command": "python3 -B x/relevant_records.py --folder ."}},
           {"場面": "呼び出し", "番": 2}, {"道具": "AskUserQuestion", "入力": {}},
           {"場面": "呼び出し", "番": 3},
           {"道具": "Bash", "入力": {"command": 'python3 -B "/p/skills/kaku/scripts/yoshiki.py" sheet --folder . --values a.json'}}]
    assert nikenme.draft_call(log) == 3
    assert nikenme.draft_call(log[:4]) is None


def test_questions_before_the_draft_are_counted_from_both_routes() -> None:
    asked = [{"question": "前回は15人でしたが、変わりましたか？（理由：常時使用する従業員数に書くため）"},
             {"question": "冷凍惣菜はいつから売り始めますか？"}]
    conv = _conversation([
        {"だれ": "社長役", "種類": "発言", "文": "持続化の初稿を書いて"},
        {"だれ": "ツール", "種類": "選択肢の画面", "文": json.dumps(asked, ensure_ascii=False), "呼び出し": 1},
        {"だれ": "ツール", "種類": "応答", "呼び出し": 2,
         "文": "ありがとうございます。\n【質問】\n1. 従業員の数を教えてください（理由：書くため）\n2. ネットショップの費用はいくらですか（理由：経費のため）"},
        {"だれ": "ツール", "種類": "応答", "呼び出し": 3, "文": "初稿を書きました。\n【質問】\n1. 資本金はいくらですか（理由：…）"},
    ])
    got = nikenme.questions(conv, before=3)
    assert [q["経路"] for q in got] == ["選択肢の画面", "選択肢の画面", "【質問】", "【質問】"]
    assert [nikenme.classify(q["問い"]) for q in got] == ["確かめ", "新しいこと", "聞き直し", "新しいこと"]
    assert len(nikenme.questions(conv, before=None)) == 5  # 初稿に届かなければ全部


def test_reflect_checks_what_was_learned_in_the_first_case() -> None:
    good = {
        "経営計画入力：1-1.自社の概要": "当社は、スーパー3社（14店舗）と病院・介護施設に惣菜を届けています。売上は20,160万円です。",
        "経営計画入力：3.自社や自社の提供する商品・サービスの強み・弱み":
            "病院や介護施設の細かい注文を断らないことが強みです。やわらか食や減塩が必要な方の注文に応えます。\n"
            "スーパーには、日替わりで約40品目を少しずつ、短い納期で届けています。",
        "経営計画入力：4-1.経営方針・目標": "冷凍惣菜を売り、1年で1,200万円を目指します。これからも「まちの台所」でいたいと考えています。",
    }
    checks = nikenme.reflect(good)
    assert all(v["合格"] for v in checks.values()), checks
    bad = {
        "経営計画入力：1-1.自社の概要": "株式会社やまぶき惣菜は、惣菜の会社です。やまぶき惣菜は、スーパー14社に届けています。"
                                  "売上は201,600千円です。",
        "経営計画入力：3.自社や自社の提供する商品・サービスの強み・弱み":
            "病院・介護施設ごとのきめ細かな対応と、スーパーの日替わりの注文に応える高齢者向けの惣菜が強みです。",
    }
    failed = {k for k, v in nikenme.reflect(bad).items() if not v["合格"]}
    assert failed == set(checks)


def test_judge_compares_with_and_without_records() -> None:
    body = {"経営計画入力：3.自社や自社の提供する商品・サービスの強み・弱み": "やわらか食の注文に応えます。従業員は15人です。"}
    with_side = {"初稿に届いた": True, "質問の数": 3, "初稿に残った印": 1, "初稿までに要る質問": 4, "聞き直し": 0, "確かめ": 1,
                 "初稿": body}
    # 記録なしは、聞いた質問は少なくても、初稿に【空欄】【仮】が多く残る（仕上げるのに要る質問に数える）
    without = {"初稿に届いた": True, "質問の数": 3, "初稿に残った印": 6, "初稿までに要る質問": 9}
    verdict = nikenme.judge(with_side, without)
    assert verdict["T13-2 二度聞かない"]["合格"]
    assert verdict["T13-3 強み・事実が初稿に入る"]["合格"]
    assert verdict["T13-3 質問の数（なしの半分以下）"]["合格"]
    assert not nikenme.judge(dict(with_side, 初稿までに要る質問=5), without)["T13-3 質問の数（なしの半分以下）"]["合格"]
    assert not nikenme.judge(dict(with_side, 聞き直し=1), None)["T13-2 二度聞かない"]["合格"]
    assert not nikenme.judge(dict(with_side, 確かめ=0), None)["T13-2 二度聞かない"]["合格"], "変わりうる情報を確かめずに使った"


def test_markdown_draft_is_read_when_there_is_no_input_sheet(tmp_path: Path) -> None:
    sheet_dir = tmp_path / "案件" / CASE2 / "1_申請" / "申請書"
    sheet_dir.mkdir(parents=True)
    (sheet_dir / "経営計画_初稿.md").write_text("# 初稿\n\n## 1-1.自社の概要\n\n当社は惣菜の会社です。\n\n## 4-1.経営方針・目標\n\n"
                                            "これからも「まちの台所」でいたい。\n", encoding="utf-8")
    values = nikenme.plan_text(tmp_path)
    assert values == {"Markdown：1-1.自社の概要": "当社は惣菜の会社です。", "Markdown：4-1.経営方針・目標": "これからも「まちの台所」でいたい。"}


# ---------------------------------------------------------------- 保存した状態「1件目を終えた」


def _restore(stage: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent), "LANG": "ja_JP.UTF-8"}
    done = subprocess.run(["bash", str(ROOT / "evals" / "_lib" / "fukugen.sh"), stage, str(folder)], capture_output=True,
                          text=True, encoding="utf-8", env=env, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    return folder


@pytest.fixture(scope="module")
def finished(tmp_path_factory) -> Path:
    if not (ROOT / "downloads").is_dir() and not any((p / "downloads").is_dir() for p in ROOT.parents):
        pytest.skip("downloads/ がありません（公式資料を取ってから流す）")
    return _restore("1件目を終えた", tmp_path_factory.mktemp("nikenme") / "会社")


@pytest.mark.slow
def test_finished_state_has_what_was_learned(finished: Path) -> None:
    from lib import buntai, company_record, history

    data = json.loads((finished / "記録" / "会社の記録.json").read_text(encoding="utf-8"))
    facts = {it["名前"]: it for it in data["項目"] if it["種類"] == "事実"}
    rules = [it for it in data["項目"] if it["種類"] == "書き方の決まり"]
    assert facts["取引先"]["値"].startswith("スーパー3社") and facts["取引先"]["出典"]["種類"] == "社長の発言"
    assert "細かい注文" in facts["強み"]["値"] and facts["従業員の数"]["変わりうる"]
    kinds = {r["区分"] for r in rules}
    assert kinds == {"直した表現", "避けたい言い方", "好む言い方", "書き方の方針", "構成"}
    assert any("まちの台所" in r["内容"] for r in rules) and any("万円" in r["内容"] for r in rules)
    assert not any("やまぶき惣菜" in r["内容"] or "当社" in r["内容"] for r in rules), "「今回だけ」の指示は残さない"
    avoid, keep = buntai.company_phrases(rules)
    assert {"高齢者向け", "きめ細かな対応"} <= set(avoid) and "病院や介護施設の細かい注文を断らないこと" not in avoid
    assert keep == ["やわらか食や減塩が必要な方"]
    settings = json.loads((finished / ".hojokin" / "設定.json").read_text(encoding="utf-8"))
    assert settings["今日の日付"] == "2026-11-20"
    found = company_record.relevant(finished, ["常時使用する従業員数"])
    staff = [f for f in found["事実"] if f["名前"] == "従業員の数"][0]
    assert staff["使う前に確かめる"] and "15人" in staff["確かめ方"]
    assert (finished / "記録" / "制度データ" / "持続化_第20回.json").is_file()
    assert (finished / "案件" / CASE2 / "1_申請" / "申請書").is_dir()
    assert (finished / "案件" / CASE2 / "概要と流れ.docx").is_file()
    questions = json.loads((finished / "記録" / "質問の記録.json").read_text(encoding="utf-8"))["質問"]
    ids = {q["回答表の ID"] for q in questions}
    assert {"I-01", "I-02", "I-06"} <= ids, "1件目の計画書に書いた冷凍惣菜のことは、1件目で聞いている"
    assert not ids & {"I-03", "I-04", "I-05", "I-07", "I-08"}, "2件目だけのことは1件目で聞いていない"
    assert "冷凍惣菜を売る場所" in facts and "冷凍惣菜の売上の目標" not in facts
    from lib import doc_text

    plan = finished / "案件" / "2026_省力化（一般型）第9回" / "1_申請" / "申請書" / "その1・2.docx"
    text = doc_text.word_text(plan)
    assert "病院や介護施設の細かい注文を断らないこと" in text and "きめ細かな対応" not in text
    assert history.pending_changes(finished) == []


@pytest.mark.slow
def test_without_records_the_record_is_empty(tmp_path: Path) -> None:
    if not (ROOT / "downloads").is_dir() and not any((p / "downloads").is_dir() for p in ROOT.parents):
        pytest.skip("downloads/ がありません（公式資料を取ってから流す）")
    folder = _restore("1件目を終えた_記録なし", tmp_path / "会社")
    data = json.loads((folder / "記録" / "会社の記録.json").read_text(encoding="utf-8"))
    assert data["項目"] == []
    assert not (folder / "記録" / "質問の記録.json").exists()
    assert (folder / "案件" / CASE2 / "1_申請" / "申請書").is_dir()


@pytest.mark.skipif(not os.environ.get("HOJOKIN_NIKENME_WITH"), reason="2件目を流した記録（HOJOKIN_NIKENME_WITH）がない")
def test_a_real_run_passes() -> None:
    """本物の claude -p で流した記録を渡したときだけ見る。環境変数は「<--out>:<会社のフォルダ>」（なしの側は _WITHOUT）。"""
    out, folder = os.environ["HOJOKIN_NIKENME_WITH"].split(":", 1)
    with_side = nikenme.summarize(Path(out), Path(folder))
    without_side = None
    if os.environ.get("HOJOKIN_NIKENME_WITHOUT"):
        out2, folder2 = os.environ["HOJOKIN_NIKENME_WITHOUT"].split(":", 1)
        without_side = nikenme.summarize(Path(out2), Path(folder2))
    verdict = nikenme.judge(with_side, without_side)
    assert all(v["合格"] for v in verdict.values()), verdict
