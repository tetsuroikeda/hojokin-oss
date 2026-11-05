"""T3-2 逆算日程（SPEC F3。TASKS B24）。

SPEC：今日の日付を固定して日程を作る。
合格ライン：期待する作業と期日の一覧と一致する。

- 道具の中身（lib/nittei.build_schedule）に、制度データの正解（testdata/正解/。作者の確かめ前の仮の正解）と、固定した今日の日付を渡す。
- 期待する一覧は、制度データの日付から、決め方（lib/nittei.py の説明）どおりに手で出したもの。
  - 持続化 第20回（2026-11-05）：締切 2026-12-15 17:00。様式4 は依頼の締切 2026-12-04 まで（目安の日数がまだ分からないので、始める日は出さない）。
    計画書（案）は、様式4 を頼む前に固める（12/4）。登記の証明書は発行から3か月以内なので、取る期間は 9/15〜12/15。
    電子申請は受付開始 11/5 から、締切の3日前（12/12）を目安に終える。様式10 は依頼の締切がないので、申請の締切を期日にする。
  - 会社の記録に「依頼の目安の日数：事業支援計画書（様式4）」が7日とあれば、頼む日は 11/27 になり、計画書（案）もその日までに固める。
  - 省力化 第8回（2026-09-01）：締切 2026-10-16 17:00。依頼の締切のある書類がないので、計画書（案）は、外部に頼む書類の期日（締切）。
- 道具（skills/junbi/scripts/nittei.py）を、保存した状態「書く前」の会社のフォルダで /usr/bin/python3 で動かし、同じ一覧が出ることも見る
  （downloads/ がなければ飛ばす）。
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from lib import nittei

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWER = REPO_ROOT / "testdata" / "正解"
SCRIPT = REPO_ROOT / "skills" / "junbi" / "scripts" / "nittei.py"
FUKUGEN = REPO_ROOT / "evals" / "_lib" / "fukugen.py"


def load(name: str) -> dict:
    return json.loads((ANSWER / name).read_text(encoding="utf-8"))


def rows(sched) -> list:
    return [(i.kind, i.name, i.start.isoformat() if i.start else None, i.due.isoformat() if i.due else None,
             i.conditional) for i in sched.items]


JIZOKUKA_EXPECTED = [
    ("取る", "現在事項全部証明書または履歴事項全部証明書を取る（発行から3か月以内のもの）", "2026-09-15", "2026-12-15", True),
    ("電子申請", "電子申請の入力と提出（締切の直前は混み合うので、早めに出す）", "2026-11-05", "2026-12-12", False),
    ("外部に頼む", "事業支援計画書（様式4）を頼む", None, "2026-12-04", False),
    ("計画書", "計画書（案）を固める", None, "2026-12-04", False),
    ("締切", "公募申請（補助金交付申請を兼ねる）の締切", None, "2026-12-15", False),
    ("外部に頼む", "事業承継診断票（様式10）を頼む", None, "2026-12-15", True),
]


def test_jizokuka_schedule_from_fixed_today() -> None:
    """T3-2：持続化 第20回、今日 2026-11-05。期待する作業と期日の一覧と一致する。"""
    sched = nittei.build_schedule(load("持続化_第20回.json"), date(2026, 11, 5), [], 20)
    assert sched.deadline == date(2026, 12, 15) and sched.deadline_time == "17:00"
    assert rows(sched) == JIZOKUKA_EXPECTED
    assert sched.notes == []
    plan = next(i for i in sched.items if i.kind == "計画書")
    assert "事業支援計画書（様式4）" in plan.note  # 様式4 を頼む前に固める（SPEC F3 の例）
    request = next(i for i in sched.items if i.name.startswith("事業支援計画書"))
    assert "まだ分かりません" in request.note  # 目安の日数を推測で入れない
    assert request.sources == ["要領20 p.3", "要領20 p.22"]


def test_lead_days_from_company_record_move_start_and_plan() -> None:
    """前に社長に聞いた依頼の目安の日数（会社の記録）から、頼む日と計画書を固める日を逆算する。"""
    facts = [{"id": "事実-0001", "種類": "事実", "名前": "依頼の目安の日数：事業支援計画書（様式4）", "値": "7日"}]
    sched = nittei.build_schedule(load("持続化_第20回.json"), date(2026, 11, 5), facts, 20)
    request = next(i for i in sched.items if i.name.startswith("事業支援計画書"))
    assert (request.start, request.due) == (date(2026, 11, 27), date(2026, 12, 4))
    assert "7日" in request.note and "会社の記録" in request.note
    plan = next(i for i in sched.items if i.kind == "計画書")
    assert plan.due == date(2026, 11, 27)
    assert rows(sched)[0][0] == "取る"  # 始める日の早い順


def test_shoryokuka_schedule() -> None:
    sched = nittei.build_schedule(load("省力化_第8回.json"), date(2026, 9, 1), [], 8)
    assert sched.deadline == date(2026, 10, 16)
    got = {(k, n): (s, d) for k, n, s, d, _c in rows(sched)}
    assert got[("締切", "応募申請の締切")] == (None, "2026-10-16")
    assert got[("取る", "履歴事項全部証明書を取る（発行から3か月以内のもの）")] == ("2026-07-16", "2026-10-16")
    assert got[("電子申請", "電子申請の入力と提出（締切の直前は混み合うので、早めに出す）")] == ("2026-09-18", "2026-10-13")
    assert got[("外部に頼む", "金融機関確認書を頼む")] == (None, "2026-10-16")
    assert got[("計画書", "計画書（案）を固める")] == (None, "2026-10-16")
    assert all(i.name != "損益計算書（直近2期分）を頼む" for i in sched.items)  # 自社の書類は頼む作業にしない


def test_past_deadline_is_told() -> None:
    sched = nittei.build_schedule(load("省力化_第8回.json"), date(2026, 11, 5), [], 8)
    assert any("過ぎています" in n for n in sched.notes)
    assert "【期日を過ぎた】応募申請の締切" in nittei.report(sched)


def test_no_stage_means_no_schedule() -> None:
    sched = nittei.build_schedule({"制度": {"名前": "架空"}}, date(2026, 11, 5))
    assert sched.items == [] and sched.notes


@pytest.mark.slow
def test_tool_on_restored_company_folder(tmp_path) -> None:
    """道具を、保存した状態「書く前」（省力化。今日 2026-11-05）で動かす。日程の JSON が lib と同じになる。"""
    if not (REPO_ROOT / "downloads").is_dir() and not (REPO_ROOT.parent / "downloads").is_dir():
        pytest.skip("downloads/ がない")
    folder = tmp_path / "会社"
    folder.mkdir()
    r = subprocess.run(["/usr/bin/python3", "-B", str(FUKUGEN), "書く前", str(folder)], capture_output=True, text=True, timeout=300)
    if r.returncode != 0 and "downloads/ が見つかりません" in r.stderr:
        pytest.skip("downloads/ がない")
    assert r.returncode == 0, r.stderr
    out = subprocess.run(["/usr/bin/python3", "-I", "-B", str(SCRIPT), "--folder", str(folder), "--json"],
                         capture_output=True, text=True, encoding="utf-8", timeout=60,
                         env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert out.returncode == 0, out.stdout + out.stderr
    got = json.loads(out.stdout)
    expected = nittei.build_schedule(load("省力化_第8回.json"), date(2026, 11, 5), [], 9).as_dict()
    assert got["締切"] == expected["締切"] == "2026-10-16"
    assert [(t["作業"], t["期日"]) for t in got["作業"]] == [(t["作業"], t["期日"]) for t in expected["作業"]]
    docs = subprocess.run(["/usr/bin/python3", "-I", "-B", str(SCRIPT), "--folder", str(folder), "--docs"],
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert docs.returncode == 0 and "## 必須（13件）" in docs.stdout


def test_doc_list_matches_seido_data() -> None:
    """書類の一覧（T3-4 の土台）：必須書類が制度データと一致し、任意書類に効く審査項目・加点が付く。"""
    data = load("省力化_第8回.json")
    groups = nittei.doc_list(data)
    required = [d["名前"] for d in data["書類"] if d.get("区分") == "必須" and "応募申請" in (d.get("手続き") or [])]
    assert [r["書類"] for r in groups["必須"]] == required
    assert groups["任意"] and all(r["効く審査項目・加点"] for r in groups["任意"])
