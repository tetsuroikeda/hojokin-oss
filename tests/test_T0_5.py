"""T0-5 開いたときの情報量（SPEC 共通の要件「開いたときに渡す情報は10,000字以内」、DESIGN 4.7 の5。TASKS B27）。

合格ライン：2つの案件を進めた状態で、開いたときに渡す情報を作る → 10,000字以内。

- 道具で用意した会社のフォルダに、2つの案件を進めた状態（tests/status_tool.py。省力化は事業の完了の後、持続化は
  見積書等の提出の段階。義務の知らせ、依頼、取り直し、書類の変化を含む）を置き、開いたときの hook（hooks.json の
  コマンド）を動かして、渡す情報（additionalContext）の全体の字数を数える。
- 依頼をたくさん足して、期限と作業の部分が長くなっても10,000字以内で、どの段階にも共通の決まりの文は削られずに入る。
- 今の状態の画面と Excel も、開いたときに作り直される。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import hook_runner as hr
import pytest
import status_tool as st
import version_tool as vt
from lib import common_rules, status_view


def company(tmp_path: Path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    for plugin in (c.env.plugin, c.plugin):
        for name in ("schema", "knowledge"):
            if not (plugin / name).exists():
                shutil.copytree(hr.REPO_ROOT / name, plugin / name)
    st.build(c.folder)
    return c


def context(c: vt.Company) -> str:
    out = c.start_raw()
    return out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.slow
def test_T0_5_two_cases_within_10000(tmp_path: Path) -> None:
    c = company(tmp_path)
    text = context(c)
    assert len(text) <= status_view.MAX_CONTEXT == 10000, len(text)
    assert status_view.BRIEF_HEAD in text
    assert common_rules.TEXT.rstrip() in text  # 共通の決まりは削らない
    assert st.CASE_A in text and st.CASE_B in text
    assert status_view.DUTY_HEAD in text
    assert (c.folder / "今の状態.html").is_file() and (c.folder / "今の状態.xlsx").is_file()


@pytest.mark.slow
def test_T0_5_many_tasks_are_cut_within_10000(tmp_path: Path) -> None:
    c = company(tmp_path)
    ledger_path = c.folder / "記録" / "期限の台帳.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for n in range(40):
        ledger["作業"].append({"種類": "依頼", "案件": st.CASE_B, "書類": f"見積書等（相見積を含む）その{n + 2}",
                             "依頼先": f"架空の業者{n + 2}", "状態": "まだ", "頼む人": "社長", "記録した日": "2028-02-05"})
    st.write_json(ledger_path, ledger)
    text = context(c)
    assert len(text) <= 10000, len(text)
    assert common_rules.TEXT.rstrip() in text
    assert status_view.BRIEF_HEAD in text
