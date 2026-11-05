"""T4-2 引用の照合（SPEC F4。TASKS B26）。

SPEC：そのページにない引用を付けた答えを混ぜて検査する。
合格ライン：混ぜたものをすべて見つける。

- 材料は testdata/制度データ/make_materials.py --build（D10）の T4-2（答え6つ。うち3つに、示したページにない引用を混ぜた）。
  公募要領の文を含むので tmp_path に作る（downloads/ がなければ飛ばす）。資料の本文（要領8・応募手引8）と資料の一覧も、そこにある。
- 製品と同じ道で照らす：Stop の hook（hooks/stop.py の quote_notes → hooks/inyou_hooks.py）に、最後の応答として答えを渡す。
  混ぜた答え（4・5・6）はすべて「見つかりませんでした」と返り、混ぜていない答え（1・2・3）は何も返らない。
- 6つを1つの応答にまとめても、混ぜた3つだけが並ぶ。外れたら応答を終わらせずに答え直させ（decision: block）、
  Stop の hook で続けているとき（stop_hook_active）は、知らせるだけにする（止めない。止め続けないため）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MATERIALS = REPO_ROOT / "testdata" / "制度データ"
HOOKS = REPO_ROOT / "hooks"
KEY = json.loads((MATERIALS / "混ぜたものの一覧.json").read_text(encoding="utf-8"))["T4-2"]
NOT_FOUND = "答えの引用が、示した資料のページに見つかりませんでした"


def _import(name: str, where: Path):
    if str(where) not in sys.path:
        sys.path.insert(0, str(where))
    return __import__(name)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mm = _import("make_materials", MATERIALS)
    if not mm.have_downloads():
        pytest.skip("downloads/ に省力化 第8回の資料がない")
    base = tmp_path_factory.mktemp("材料")
    out = mm.build(base)
    company = base / "T4-2" / "会社"
    (company / ".hojokin").mkdir(exist_ok=True)
    return company, out["T4-2"]


def stop_notes(company: Path, message: str):
    stop = _import("stop", HOOKS)
    return stop.quote_notes({"last_assistant_message": message, "stop_hook_active": False}, company)


def test_mixed_quotes_are_all_found(built) -> None:
    """T4-2：混ぜた答え（4・5・6）をすべて見つけ、混ぜていない答え（1・2・3）は通す。"""
    company, answers = built
    for a in answers:
        got = stop_notes(company, a["答え"])
        if a["番"] in KEY["混ぜた答え"]:
            assert got and NOT_FOUND in got[0], (a["番"], a["答え"])
            page = KEY["示したページ"][str(a["番"])]["ページ"]
            assert f"p.{page}）" in got[0]
        else:
            assert got == [], (a["番"], got)
    assert sorted(KEY["混ぜた答え"]) == [4, 5, 6] and sorted(KEY["混ぜていない答え"]) == [1, 2, 3]


def test_one_message_with_all_answers_lists_only_mixed(built) -> None:
    company, answers = built
    message = "\n\n".join(f"問{a['番']}：{a['答え']}" for a in answers)
    got = stop_notes(company, message)
    assert len(got) == 1
    listed = [line for line in got[0].split("\n") if line.startswith("- ")]
    assert len(listed) == 3
    for a in answers:
        quote = a["引用"]["文"]
        shown = quote if len(quote) <= 40 else quote[:38] + "…"
        assert (f"「{shown}」" in got[0]) == (a["番"] in KEY["混ぜた答え"])


def test_block_then_only_notice_when_stop_hook_active(built) -> None:
    """外れたら応答を終わらせずに答え直させ、Stop の hook で続けているときは知らせるだけにする。"""
    company, answers = built
    originals_hooks = _import("originals_hooks", HOOKS)
    bad = next(a for a in answers if a["番"] == 4)
    notes = stop_notes(company, bad["答え"])
    first = originals_hooks.stop({"stop_hook_active": False}, company, notes, None)
    assert first["decision"] == "block" and NOT_FOUND in first["reason"]
    again = originals_hooks.stop({"stop_hook_active": True}, company, notes, None)
    assert "decision" not in again and NOT_FOUND in again["systemMessage"]


def test_quotes_without_source_or_unknown_source_are_not_checked(built) -> None:
    company, _answers = built
    assert stop_notes(company, "これは「どの資料にもない架空の長い文です」という例です。") == []
    assert stop_notes(company, "ウェブのページ p.3「どの資料にもない架空の長い文です」") == []
    assert stop_notes(company, "公募要領（第8回）p.9「要確認」") == []  # 短い語は照らさない


def test_ellipsis_quote_and_source_after_quote(built) -> None:
    """「…」で区切った引用は、切れ端がどれもそのページにあればよい。資料名とページが引用の後ろにある書き方も照らす。"""
    company, answers = built
    good = next(a for a in answers if a["番"] == 1)
    quote = good["引用"]["文"]
    half = len(quote) // 2
    cut = quote[:max(4, half - 2)] + "…" + quote[half + 2:]
    assert stop_notes(company, f"答えです。「{cut}」（公募要領（第8回）p.9）") == []
    assert stop_notes(company, f"答えです。「{quote}」（要領8 p.10）")  # ページを違えると見つける


def test_hook_does_not_fail_without_text_folder(tmp_path) -> None:
    (tmp_path / ".hojokin").mkdir()
    assert stop_notes(tmp_path, "公募要領（第8回）p.9「どの資料にもない架空の長い文です」") == []
    assert stop_notes(tmp_path, "") == []
