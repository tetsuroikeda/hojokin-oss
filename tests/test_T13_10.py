"""T13-10 学んだ内容の一覧（SPEC F13「使い方と見せ方」、DESIGN 10章、TASKS B3）。

合格ライン：一覧を作る → すべての項目に出典と日付。変わった項目に変更の履歴（いつ、何から何に、だれが）。

- 一覧は kiroku の記録の道具（record.py list）。何を・いつ（覚えた日）・どこから（出典）を、すべての項目に出す。
- 変更の履歴は、版の履歴を項目ごとにたどって作る（同じ情報を2か所に持たない。DESIGN 10章）。
  ツールが直した分（応答の終わりの版）と、社長が手で直した分（社長が送ったときの版）を、だれ付きで出す。
- 社長が手で消した項目も「消えた項目」に出る（前の版から戻せる）。
- 版のファイルの形（同期されるフォルダ）でも、同じ入口（lib/history.py）から同じように出る。
"""

from __future__ import annotations

import json
import re

import company_tool as ct
import pytest
import version_tool as vt
from test_kiroku_min import RECORD, RECORD_FILE, record, run, set_today  # noqa: F401
import shutil

import hook_runner as hr

DAY1 = "2026-11-04"
DAY2 = "2026-12-01"
QUESTION = "常時使用する従業員は何人ですか（役員は入れません）。補助の上限と要件の判定に使います"


def make_company(tmp_path, form: str) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき 惣菜", form=form)
    for plugin in (c.env.plugin, c.plugin):
        shutil.copytree(hr.REPO_ROOT / "schema", plugin / "schema")
    set_today(c, DAY1)
    return c


@pytest.mark.parametrize("form", [vt.GIT, vt.FILES])
def test_listing_shows_sources_dates_and_change_history(tmp_path, form) -> None:
    c = make_company(tmp_path, form)
    # 1件目：聞き取りの答えと社長の発言から、事実と書き方の決まりを覚える（応答の終わりに「ツール」の版）
    c.say("従業員は15人です")
    ct.ok(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable",
              "--source", "質問", "--question", QUESTION))
    ct.ok(run(c, RECORD, "add-fact", "--name", "会社名", "--value", "株式会社やまぶき惣菜", "--fixed",
              "--source", "社長の発言", "--utterance", "うちは株式会社やまぶき惣菜です"))
    ct.ok(run(c, RECORD, "add-rule", "--kind", "避けたい言い方", "--content", "「〜を図る」は使わない",
              "--trigger", "この言い方は使わないで", "--source", "社長の発言", "--utterance", "この言い方は使わないで"))
    c.stop()

    # 2件目：社長が「16人になった」と答え、ツールが直す（「ツール」の版）
    set_today(c, DAY2)
    c.say("従業員は16人になりました")
    ct.ok(run(c, RECORD, "update-fact", "--id", "事実-0001", "--value", "16人", "--source", "社長の発言",
              "--utterance", "従業員は16人になりました"))
    c.stop()

    # 社長が記録を手で直す（値を変え、決まりを1つ消す）。次に送ったときに「社長」の版になる
    data = record(c)
    for item in data["項目"]:
        if item["id"] == "事実-0002":
            item["値"] = "株式会社やまぶき惣菜（ヤマブキソウザイ）"
    data["項目"] = [it for it in data["項目"] if it["id"] != "決まり-0001"]
    (c.folder / RECORD_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    c.say("記録を直しておきました")

    text = ct.ok(run(c, RECORD, "list"))
    print(text)
    current = text.split("## 消えた項目")[0]
    item_lines = [line for line in current.splitlines() if re.match(r"^- \[(事実|決まり|不備|採否)-[0-9]{4}\]", line)]
    assert len(item_lines) == 2  # 今ある項目
    for line in item_lines:
        assert "出典：" in line and re.search(r"覚えた日 20[0-9]{2}-[0-9]{2}-[0-9]{2}", line), line

    lines = text.splitlines()
    # ツールが直した：いつ・何から何に・だれ
    i = next(n for n, line in enumerate(lines) if line.startswith("- [事実-0001]"))
    history = [line for line in lines[i + 1:i + 4] if "変更の履歴" in line]
    assert any("ツールが値を「15人」から「16人」に" in line for line in history), history
    assert any("2026年12月1日" in line for line in history), history
    # 社長が手で直した
    j = next(n for n, line in enumerate(lines) if line.startswith("- [事実-0002]"))
    history2 = [line for line in lines[j + 1:j + 4] if "変更の履歴" in line]
    assert any("社長が値を「株式会社やまぶき惣菜」から「株式会社やまぶき惣菜（ヤマブキソウザイ）」に" in line
               for line in history2), history2
    # 社長が消した項目
    assert "## 消えた項目（1件。前の版から戻せます）" in text
    assert any(line.startswith("- [決まり-0001]") and "社長が消した" in line for line in lines)
    # 変わっていない項目には、履歴を添えない（覚えた日・出典は一覧の行にある）
    assert sum("変更の履歴" in line for line in lines) == 2


def test_listing_without_history_still_works(tmp_path) -> None:
    """版がまだない（応答の終わりの前）ときも、一覧は出典と日付つきで出る。"""
    c = make_company(tmp_path, vt.GIT)
    ct.ok(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable",
              "--source", "質問", "--question", QUESTION))
    text = ct.ok(run(c, RECORD, "list"))
    assert "[事実-0001] 従業員の数＝15人（出典：質問" in text and f"覚えた日 {DAY1}" in text
    assert "変更の履歴" not in text
