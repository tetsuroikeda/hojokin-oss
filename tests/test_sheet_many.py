"""入力シートの欄にまとめて書くことと、「該当なし」の扱い（TASKS M12b。省力化の申請画面は欄が200を超えるため）。

- kaku の `yoshiki.py sheet --values -`：標準入力の JSON の欄と値を、1回でまとめて書く。1件でも書けなければ、
  何も書かない（入力シートは前のまま）。書いた後に、はじめの版と比べて書いてよい範囲の外が変わっていない。
- 会社に当てはまらない欄の値「該当なし」：数字の欄にも書ける。確かめの道具は値のある欄として数え、画面入力の道具は
  空の欄と同じく画面に入れない。

材料は tests/data/ の試しの制度データだけを使う（公式資料は使わない）。道具は /usr/bin/python3 で、Claude が Bash で
動かすのと同じく引数で場所を渡して動かす。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import hook_runner as hr
import nyuryoku_tool as nt
import pytest

from lib import input_sheet, kakunin

REPO_ROOT = hr.REPO_ROOT
SEIDO = REPO_ROOT / "tests" / "data" / "yoshiki" / "制度データ_様式と画面.json"
SCRIPT = REPO_ROOT / "skills" / "kaku" / "scripts" / "yoshiki.py"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"
SHEET = f"案件/{CASE}/{STAGE}/申請書/入力シート.xlsx"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    f = tmp_path / "山田 製作所"
    (f / ".hojokin").mkdir(parents=True)
    (f / "記録" / "制度データ").mkdir(parents=True)
    (f / "記録" / "制度データ" / "省力化_第8回.json").write_bytes(SEIDO.read_bytes())
    for sub in ("申請書", "添付する書類"):
        (f / "案件" / CASE / STAGE / sub).mkdir(parents=True)
    return f


def run(folder: Path, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    argv = [hr.real_python(), "-B", str(SCRIPT), "sheet", "--folder", str(folder), *args]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent)}
    return subprocess.run(argv, input=stdin, capture_output=True, cwd=str(folder.parent), env=env, timeout=120)


def values_json(entries) -> bytes:
    return json.dumps({"値": entries}, ensure_ascii=False).encode("utf-8")


def out(r: subprocess.CompletedProcess) -> str:
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return r.stdout.decode("utf-8")


def test_values_are_written_at_once(folder: Path) -> None:
    entries = [
        {"画面": "事業計画名及び作成者情報", "欄": "事業計画名（３０文字程度）", "値": "盛り付けと包装の省力化（試し）"},
        {"欄": "事業計画の概要", "値": "試しの概要"},
        {"画面": "事業計画数値", "欄": "常勤従業員数（基準年度）", "値": "12"},
    ]
    r = run(folder, "--values", "-", stdin=values_json(entries))
    text = out(r)
    assert r.returncode == 0, text
    assert "制度データの申請画面から作り、3件の欄の値を書きました" in text
    blob = (folder / SHEET).read_bytes()
    assert input_sheet.value_of(blob, "事業計画名（３０文字程度）") == "盛り付けと包装の省力化（試し）"
    assert input_sheet.value_of(blob, "事業計画の概要") == "試しの概要"
    assert input_sheet.value_of(blob, "常勤従業員数（基準年度）") == "12"
    # 書いてよい範囲（値の列）の外は、作ったばかりの入力シートと同じ
    fresh = input_sheet.build(json.loads(SEIDO.read_text(encoding="utf-8")))
    assert input_sheet.compare_xlsx(fresh, blob) == []
    # 2回目は、前の値を残して書き足す
    r = run(folder, "--values", "-", stdin=values_json([{"欄": "事業計画の概要", "値": "書き直した概要"}]))
    assert r.returncode == 0, out(r)
    blob2 = (folder / SHEET).read_bytes()
    assert input_sheet.value_of(blob2, "事業計画の概要") == "書き直した概要"
    assert input_sheet.value_of(blob2, "事業計画名（３０文字程度）") == "盛り付けと包装の省力化（試し）"


@pytest.mark.parametrize("bad, reason", [
    ({"欄": "ない欄", "値": "x"}, "欄「ない欄」がありません"),
    ({"欄": "宣誓の確認", "値": "はい"}, "担当者が画面で入れる欄です"),
    ({"欄": "常勤従業員数（基準年度）", "値": "十二人"}, "数でない値"),
    ({"欄": "事業計画の概要", "値": "あ" * 101}, "システムの上限は100字"),
    ({"欄": "事業計画の概要"}, "「欄」と「値」がありません"),
])
def test_one_wrong_entry_writes_nothing(folder: Path, bad: dict, reason: str) -> None:
    entries = [{"欄": "事業計画名（３０文字程度）", "値": "試し"}, bad]
    r = run(folder, "--values", "-", stdin=values_json(entries))
    text = out(r)
    assert r.returncode == 2, text
    assert "前のままです" in text and "2件目" in text and reason in text
    assert not (folder / SHEET).exists()


def test_values_and_field_are_not_used_together(folder: Path) -> None:
    r = run(folder, "--values", "-", "--field", "事業計画の概要", stdin=values_json([{"欄": "事業計画の概要", "値": "x"}]))
    assert r.returncode == 2 and "一緒に使えません" in out(r)
    r = run(folder)
    assert r.returncode == 2 and "--field（1つの欄）か --values（まとめて）" in out(r)


def test_not_applicable_is_written_even_in_a_number_field_and_counts_as_filled(folder: Path) -> None:
    entries = [
        {"欄": "事業計画名（３０文字程度）", "値": "試し"},
        {"欄": "事業計画の概要", "値": "試し"},
        {"欄": "常勤従業員数（基準年度）", "値": "該当なし"},
    ]
    r = run(folder, "--values", "-", stdin=values_json(entries))
    assert r.returncode == 0, out(r)
    blob = (folder / SHEET).read_bytes()
    assert input_sheet.value_of(blob, "常勤従業員数（基準年度）") == input_sheet.NOT_APPLICABLE
    # 1件ずつの書き方でも、数字の欄に「該当なし」を書ける
    r = run(folder, "--field", "常勤従業員数（基準年度）", "--value", "該当なし")
    assert r.returncode == 0, out(r)
    # 確かめの道具は、「該当なし」の欄を空欄に数えない（ツールが入れる欄に、空の欄が残っていない）
    blanks = [f for f in kakunin.sheet_findings(blob, SHEET) if f.kind == kakunin.BLANK]
    assert blanks == []


def test_nyuryoku_does_not_touch_not_applicable_fields(tmp_path: Path) -> None:
    values = tuple(v for v in nt.SHEET_VALUES if v[1] not in ("受付番号（半角10桁）", "事業承継又はM&A加点"))
    values += (("加点項目", "受付番号（半角10桁）", "該当なし"), ("加点項目", "事業承継又はM&A加点", "該当なし"))
    company = nt.make_company(tmp_path, values=values)
    base = [hr.real_python(), "-B", str(nt.SCRIPT)]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(base + ["sheet", "--folder", str(company)], capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout.decode("utf-8")  # チェック欄の「該当なし」も、書き方の分からない値にしない
    r = subprocess.run(base + ["list", "--screen", "加点項目", "--folder", str(company), "--page", "-", "--json"],
                       input=nt.record_text("m8_shinsei4_before.txt").encode("utf-8"), capture_output=True, env=env,
                       timeout=60)
    data = json.loads(r.stdout.decode("utf-8"))
    entered = [e["欄"] for e in data["入れる"]]
    assert "受付番号（半角10桁）" not in entered and "事業承継又はM&A加点" not in entered
    skipped = {e["欄"]: e.get("理由") for e in data["値がない"]}
    assert skipped["受付番号（半角10桁）"] == "該当なし" and skipped["事業承継又はM&A加点"] == "該当なし"
