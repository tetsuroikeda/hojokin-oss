"""T2-2 二重受給（SPEC F2。TASKS B23）。

SPEC：省力化と持続化に同じ設備の経費を入れる。
合格ライン：重大な問題として指摘する。

- 道具（skills/sagasu/scripts/kimeru.py nijuu。中身は lib/nijuu.py）を、社長の Mac と同じ /usr/bin/python3（3.9）で動かす。
- 1件目（省力化）の経費は、経費明細（`記録/経費明細.json`。lib/keihi.py の形）に置き、2件目（持続化）の予定の経費は、
  Claude が書く形（`記録/一時/二重受給.json`）で渡す。経費の値は、デモの会社（架空。testdata/デモの会社/回答表.md の H-02・I-03）から。
- 同じ設備（型番が同じ／品名と金額が同じ／同じ見積書の同じ明細）を入れると、重大として指摘し、終了コード1。
- 重ならない経費だけなら、何も指摘せず終了コード0。品名が似ていて金額が違うものは「確かめが要る」（重大ではない）。
- 何も書かない（照らす前後で、会社のフォルダのファイルの一覧と中身が同じ）。会社のフォルダの外のファイルは読まない。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from lib import nijuu

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "sagasu" / "scripts" / "kimeru.py"
SYSTEM_PYTHON = "/usr/bin/python3"
CASE1 = "2026_省力化（一般型）第9回"
CASE2 = "2026_持続化（通常枠）第20回"
QUOTE = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"

# 1件目（省力化）の経費明細。デモの会社の H-02（架空）
LEDGER_ROWS = [
    {"経費の区分": "機械装置・システム構築費", "品名": "盛り付けロボット", "型番": "TFS-MR200", "数量": 2, "単位": "台",
     "単価": 3900000, "金額": 7800000, "根拠": "見積書", "原本": QUOTE, "出典": "", "明細の番号": [1], "状態": "確定"},
    {"経費の区分": "機械装置・システム構築費", "品名": "自動計量機", "型番": "TFS-AW50", "数量": 1, "単位": "台",
     "単価": 3200000, "金額": 3200000, "根拠": "見積書", "原本": QUOTE, "出典": "", "明細の番号": [2], "状態": "確定"},
    {"経費の区分": "機械装置・システム構築費", "品名": "トップシール包装機", "型番": "TFS-TS80", "数量": 1, "単位": "台",
     "単価": 4800000, "金額": 4800000, "根拠": "見積書", "原本": QUOTE, "出典": "", "明細の番号": [3], "状態": "確定"},
]

# 2件目（持続化）の予定の経費。デモの会社の I-03（架空）。重ならない
PLAN_OK = [
    {"品名": "急速冷凍庫", "金額": 1200000},
    {"品名": "ネットショップの作成", "金額": 300000},
    {"品名": "パッケージとロゴのデザイン・チラシ", "金額": 600000},
    {"品名": "食品の展示会への出展", "金額": 500000},
]


def make_company(tmp_path: Path) -> Path:
    folder = tmp_path / "架空の会社"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "記録" / "一時").mkdir(parents=True)
    ledger = {"説明": "経費明細（テスト用の架空の値）", "案件": [
        {"案件": CASE1, "作った日時": "2026-11-05T10:00:00+09:00", "行": LEDGER_ROWS, "合計": {}, "使った見積書": [QUOTE]}]}
    (folder / "記録" / "経費明細.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def write_plan(folder: Path, rows) -> str:
    rel = "記録/一時/二重受給.json"
    (folder / rel).write_text(json.dumps({"案件": CASE2, "行": rows}, ensure_ascii=False), encoding="utf-8")
    return rel


def snapshot(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def run_tool(folder: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SYSTEM_PYTHON, "-I", "-B", str(SCRIPT), "nijuu", "--folder", str(folder), *args],
        capture_output=True, text=True, encoding="utf-8",
        env={"PATH": "/usr/bin:/bin", "HOME": str(folder.parent)}, cwd=folder.parent, timeout=60,
    )


@pytest.mark.parametrize("dup, why", [
    ({"品名": "包装機（トップシール）", "型番": "TFS-TS80", "金額": 4800000}, "型番が同じ"),
    ({"品名": "トップシール包装機", "金額": 4800000}, "品名も金額も同じ"),
    ({"品名": "シール機", "金額": 4800000, "原本": QUOTE, "明細の番号": [3]}, "同じ見積書の同じ明細"),
])
def test_same_equipment_in_both_cases_is_serious(tmp_path, dup, why) -> None:
    """T2-2：省力化と持続化に同じ設備の経費を入れると、重大な問題として指摘する。"""
    folder = make_company(tmp_path)
    rel = write_plan(folder, PLAN_OK + [dup])
    before = snapshot(folder)
    r = run_tool(folder, "--input", rel)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "【重大】同じ経費を2つの補助金に計上しています（1件）" in r.stdout
    assert why in r.stdout
    assert CASE1 in r.stdout and CASE2 in r.stdout
    assert "二重受給" in r.stdout
    assert snapshot(folder) == before  # 何も書かない


def test_no_overlap_means_no_finding(tmp_path) -> None:
    folder = make_company(tmp_path)
    rel = write_plan(folder, PLAN_OK)
    r = run_tool(folder, "--input", rel)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "見つかりませんでした" in r.stdout
    assert "重大" not in r.stdout


def test_similar_name_with_other_amount_is_to_check_not_serious(tmp_path) -> None:
    folder = make_company(tmp_path)
    rel = write_plan(folder, PLAN_OK + [{"品名": "トップシール包装機", "金額": 2500000}])
    r = run_tool(folder, "--input", rel)
    assert r.returncode == 1
    assert "確かめが要るもの（1件）" in r.stdout
    assert "【重大】" not in r.stdout


def test_different_model_numbers_are_not_the_same(tmp_path) -> None:
    folder = make_company(tmp_path)
    rel = write_plan(folder, PLAN_OK + [{"品名": "包装機", "型番": "OTHER-1", "金額": 900000}])
    r = run_tool(folder, "--input", rel)
    assert "【重大】" not in r.stdout


def test_ledger_with_two_cases_is_checked_without_input(tmp_path) -> None:
    """2つの案件の経費明細どうしでも照らす（予定の経費を渡さなくても）。"""
    folder = make_company(tmp_path)
    path = folder / "記録" / "経費明細.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["案件"].append({"案件": CASE2, "行": [dict(LEDGER_ROWS[2], 原本="", 明細の番号=None, 根拠="メモ", 状態="仮")]})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = run_tool(folder)
    assert r.returncode == 1
    assert "【重大】" in r.stdout


def test_one_case_only_says_nothing_to_compare(tmp_path) -> None:
    folder = make_company(tmp_path)
    r = run_tool(folder)
    assert r.returncode == 0
    assert "比べる相手がありません" in r.stdout


def test_input_outside_company_folder_is_refused(tmp_path) -> None:
    folder = make_company(tmp_path)
    outside = tmp_path / "外.json"
    outside.write_text(json.dumps({"案件": CASE2, "行": PLAN_OK}, ensure_ascii=False), encoding="utf-8")
    r = run_tool(folder, "--input", str(outside))
    assert r.returncode == 2
    assert "外を指しています" in r.stdout


def test_not_company_folder_is_refused(tmp_path) -> None:
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    r = run_tool(plain)
    assert r.returncode == 2
    assert list(plain.iterdir()) == []


def test_rule_source_comes_from_seido_data(tmp_path) -> None:
    """重大の指摘に、制度データの「してはいけないこと」（重複の受給）の出典を添える。"""
    folder = make_company(tmp_path)
    seido = json.loads((REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))
    (folder / "記録" / "制度データ").mkdir(parents=True)
    (folder / "記録" / "制度データ" / "省力化_第8回.json").write_text(json.dumps(seido, ensure_ascii=False), encoding="utf-8")
    rel = write_plan(folder, PLAN_OK + [{"品名": "トップシール包装機", "金額": 4800000}])
    r = run_tool(folder, "--input", rel)
    assert r.returncode == 1
    assert "出典：" in r.stdout and "重複" in r.stdout and "要領8 p.14" in r.stdout


def test_similarity_rule() -> None:
    assert nijuu.similar(nijuu.norm("トップシール包装機"), nijuu.norm("包装機（トップシール）"))
    assert not nijuu.similar(nijuu.norm("急速冷凍庫"), nijuu.norm("盛り付けロボット"))
