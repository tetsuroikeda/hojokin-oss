"""画面入力の道具（skills/nyuryoku/scripts/nyuryoku.py。TASKS M8）。

入力シート.xlsx と、ブラウザの道具がページを読んだ結果（tests/browser_records/ の模擬画面の記録）を突き合わせる。
- sheet：画面ごとの欄の数と、文字数の上限を超える値・書き方の分からないチェック欄の値を数える。
- list：画面の部品の番号と、form_input に渡す値を出す（担当者が入れる欄、画面にない欄も分ける）。
- check：入れた後の画面と入力シートを、文字の欄・選択欄は値で照らし、チェック欄・ラジオボタンは担当者に
  確かめてもらう欄として出す。
- 画面は、hook（PostToolUse）が控えた最後の読み取りか、標準入力の read_page の文から読む。
- /usr/bin/python3（3.9）で動き、会社のフォルダの外は読まない。
"""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import hook_runner as hr
import nyuryoku_tool as nt
import pytest

from lib import input_sheet, yoshiki_word


def run(folder: Path, *args: str, page: str = None, cwd: Path = None) -> subprocess.CompletedProcess:
    stdin = nt.record_text(page).encode("utf-8") if page else b""
    argv = [hr.real_python(), "-B", str(nt.SCRIPT), *args, "--folder", str(folder)]
    if page:
        argv += ["--page", "-"]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent)}
    return subprocess.run(argv, input=stdin, capture_output=True, cwd=str(cwd or folder), env=env, timeout=60)


def run_json(folder: Path, *args: str, page: str = None):
    r = run(folder, *args, "--json", page=page)
    return r.returncode, json.loads(r.stdout.decode("utf-8"))


@pytest.fixture
def folder(tmp_path) -> Path:
    return nt.make_company(tmp_path)


# ---- sheet ----

def test_sheet_counts_screens(folder) -> None:
    r = run(folder, "sheet")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0, out
    assert "1 宣誓・手引き：ツールが入れる欄 0（値がある 0）、担当者が入れる欄 5" in out
    assert "4 加点項目：ツールが入れる欄 15（値がある 9）、担当者が入れる欄 0" in out
    assert "上限を超える値と、書き方の分からない値はありません" in out
    code, data = run_json(folder, "sheet")
    assert code == 0 and data["入れられない"] == []
    assert data["入力シート"] == f"案件/{nt.CASE}/{nt.STAGE}/申請書/入力シート.xlsx"


def _edit_sheet(folder: Path, old: str, new: str) -> None:
    """社長が Excel で入力シートを直したのと同じ形に、シートの文字を書き換える。"""
    path = folder / "案件" / nt.CASE / nt.STAGE / "申請書" / input_sheet.FILE_NAME
    blob = path.read_bytes()
    with zipfile.ZipFile(path) as z:
        sheet = z.read("xl/worksheets/sheet1.xml")
    assert old.encode("utf-8") in sheet
    path.write_bytes(yoshiki_word.rebuild_zip(blob, {"xl/worksheets/sheet1.xml": sheet.replace(
        old.encode("utf-8"), new.encode("utf-8"))}))


def test_sheet_finds_values_over_the_limit_and_unknown_check_values(folder) -> None:
    _edit_sheet(folder, "2512345678", "25123456789")
    # 「値」の列（ツールが入れる欄の書式 s="4"）の「はい」だけを書き換える（「担当者が入れる」の列は変えない）
    _edit_sheet(folder, 's="4" t="inlineStr"><is><t xml:space="preserve">はい<',
                's="4" t="inlineStr"><is><t xml:space="preserve">たぶん<')
    r = run(folder, "sheet")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 4, out
    assert "受付番号（半角10桁）：上限は10字で、値は11字です" in out
    assert "チェック欄の値「たぶん」の意味が分かりません" in out
    # 上限を超える値は、list でも入れる欄に出さない
    code, data = run_json(folder, "list", "--screen", "加点項目", page="m8_shinsei4_before.txt")
    assert code == 4
    assert "受付番号（半角10桁）" in [e["欄"] for e in data["入れられない"]]
    assert "受付番号（半角10桁）" not in [e["欄"] for e in data["入れる"]]


# ---- list ----

EXPECTED_SCREEN4 = [
    ("事業承継又はM&A加点", "ref_26", False),
    ("事業継続力強化計画加点", "ref_31", True),
    ("受付番号（半角10桁）", "ref_35", "2512345678"),
    ("実施期間開始期（年）", "ref_38", "2025"),
    ("実施期間開始期（月）", "ref_53", "4"),
    ("実施期間終期（年）", "ref_57", "2028"),
    ("実施期間終期（月）", "ref_72", "3"),
    ("事業場内最低賃金引き上げ加点", "ref_84", True),
    ("省力化ナビ加点", "ref_96", True),
]


def test_list_gives_refs_and_values_from_the_page(folder) -> None:
    code, data = run_json(folder, "list", "--screen", "加点項目", page="m8_shinsei4_before.txt")
    assert code == 0, data
    assert [(e["欄"], e["ref"], e["form_input"]) for e in data["入れる"]] == EXPECTED_SCREEN4
    assert [e["欄"] for e in data["値がない"]] == [
        "成長加速マッチングサービス加点", "地域別最低賃金引き上げ加点", "えるぼし加点", "くるみん加点",
        "健康経営優良法人加点", "生産性向上支援センター利用加点"]
    assert data["見当たらない"] == [] and data["重なり"] == [] and data["画面だけにある"] == []
    assert data["注意"] == ""
    # 記録した実際の操作（m8_calls.jsonl）は、この一覧の「はい」の欄と値に当たる
    done = {}
    for row in nt.calls():
        op = row["tool_name"].split("__")[-1]
        items = [row["tool_input"]] if op == "form_input" else [a["input"] for a in row["tool_input"].get("actions", [])]
        for item in items if op in ("form_input", "browser_batch") else []:
            done[item["ref"]] = item["value"]
    planned = {e["ref"]: e["form_input"] for e in data["入れる"] if e["form_input"] is not False}
    assert done == planned


def test_list_text_shows_how_to_fill(folder) -> None:
    r = run(folder, "list", "--screen", "❹ 加点項目", page="m8_shinsei4_before.txt")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0, out
    assert "2. 事業継続力強化計画加点（チェック）：ref_31 に form_input で true（チェックを入れる）" in out
    assert '3. 受付番号（半角10桁）（文字）：ref_35 に form_input で "2512345678"' in out
    assert "1. 事業承継又はM&A加点（チェック）：ref_26 に form_input で false（チェックを外す）" in out


def test_list_separates_staff_fields_and_radio(folder) -> None:
    code, data = run_json(folder, "list", "--screen", "要件", page="m8_shinsei3.txt")
    assert code == 0, data
    assert [(e["欄"], e["ref"], e["form_input"]) for e in data["入れる"]] == [
        ("小規模企業者・小規模事業者", "ref_27", True),
        ("再生事業者", "ref_30", False),
        ("国の他の助成制度との重複", "ref_59", True),  # ラジオボタンは、選ぶ項目「いいえ」の番号
    ]
    staff = {e["欄"]: e["ref"] for e in data["担当者が入れる"]}
    assert staff == {"みなし同一法人でないことの確認": ["ref_34"], "みなし大企業でないことの確認": ["ref_38"],
                     "風俗営業等に関する確認": ["ref_42"], "両立支援のひろば": ["ref_50"]}
    assert [e["欄"] for e in data["値がない"]] == ["「両立支援のひろば」の企業データ詳細ページのURL"]


def test_list_oath_screen_has_only_staff_fields(folder) -> None:
    code, data = run_json(folder, "list", "--screen", "宣誓・手引き", page="m8_shinsei1.txt")
    assert code == 0, data
    assert data["入れる"] == []
    assert sorted(e["ref"][0] for e in data["担当者が入れる"]) == ["ref_30", "ref_33", "ref_36", "ref_39", "ref_42"]
    out = run(folder, "list", "--screen", "宣誓・手引き", page="m8_shinsei1.txt").stdout.decode("utf-8")
    assert "ツールが入れる欄はありません" in out and "担当者が入れる（ツールは入れない" in out


def test_list_reports_fields_missing_from_the_page_and_wrong_screen(folder) -> None:
    # ❹ の入力シートを ❸ の画面で突き合わせると、欄が見当たらず、見出しも違う
    code, data = run_json(folder, "list", "--screen", "加点項目", page="m8_shinsei3.txt")
    assert code == 4
    assert {e["欄"] for e in data["見当たらない"]} >= {"事業継続力強化計画加点", "受付番号（半角10桁）"}
    assert "見出しに「加点項目」が見当たりません" in data["注意"]
    # 画面にあって入力シートにない欄も出す（宣誓の欄は担当者が入れる）
    extra = {e["名前"]: e["担当者が入れる"] for e in data["画面だけにある"]}
    assert extra["みなし同一法人でないことの確認：みなし同一法人による申請でないことを宣誓する"] is True


def test_list_uses_the_snapshot_saved_by_the_hook(folder) -> None:
    """標準入力がなければ、PostToolUse の hook が控えた最後の読み取りを使う（一時保存の後は番号がずれる）。"""
    nt.read_screen(folder, "m8_shinsei4_before.txt")
    code, data = run_json(folder, "list", "--screen", "加点項目")
    assert code == 0 and [(e["欄"], e["ref"]) for e in data["入れる"]][:2] == [
        ("事業承継又はM&A加点", "ref_26"), ("事業継続力強化計画加点", "ref_31")]
    nt.read_screen(folder, "m8_shinsei4_saved.txt")
    code, data = run_json(folder, "list", "--screen", "加点項目")
    assert code == 0 and [(e["欄"], e["ref"]) for e in data["入れる"]][:2] == [
        ("事業承継又はM&A加点", "ref_28"), ("事業継続力強化計画加点", "ref_33")]


def test_list_without_snapshot_is_refused(folder) -> None:
    r = run(folder, "list", "--screen", "加点項目")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2 and "画面の控えがありません" in out and "read_page" in out


# ---- check ----

def test_check_after_input_matches(folder) -> None:
    code, data = run_json(folder, "check", "--screen", "加点項目", page="m8_shinsei4_filled.txt")
    assert code == 0, data
    assert [(e["欄"], e["画面の値"]) for e in data["合う"]] == [
        ("受付番号（半角10桁）", "2512345678"), ("実施期間開始期（年）", "2025"), ("実施期間開始期（月）", "4"),
        ("実施期間終期（年）", "2028"), ("実施期間終期（月）", "3")]
    assert data["合わない"] == [] and data["見当たらない"] == []
    assert [(e["欄"], e["確かめること"]) for e in data["担当者に確かめる"]] == [
        ("事業承継又はM&A加点", "チェックが入っていない"), ("事業継続力強化計画加点", "チェックが入っている"),
        ("事業場内最低賃金引き上げ加点", "チェックが入っている"), ("省力化ナビ加点", "チェックが入っている")]
    # 一時保存の後に読み直した画面（番号がずれている）でも合う
    code, data = run_json(folder, "check", "--screen", "加点項目", page="m8_shinsei4_saved.txt")
    assert code == 0 and len(data["合う"]) == 5


def test_check_text_lists_tool_and_staff_fields(folder) -> None:
    r = run(folder, "check", "--screen", "要件", page="m8_shinsei3.txt")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0, out
    assert "担当者に画面で確かめてもらう" in out and "- 国の他の助成制度との重複：「いいえ」が選ばれている" in out
    assert "担当者が入れる欄（ツールは入れていない）" in out and "- みなし大企業でないことの確認" in out


def test_check_before_input_finds_mismatches(folder) -> None:
    code, data = run_json(folder, "check", "--screen", "加点項目", page="m8_shinsei4_before.txt")
    assert code == 4
    assert [(e["欄"], e["画面の値"]) for e in data["合わない"]][:2] == [
        ("受付番号（半角10桁）", ""), ("実施期間開始期（年）", "")]
    r = run(folder, "check", "--screen", "加点項目", page="m8_shinsei4_before.txt")
    assert '- 合わない：受付番号（半角10桁）（ref_35）入力シート "2512345678"、画面 ""' in r.stdout.decode("utf-8")


def test_check_finds_a_wrong_value(folder, tmp_path) -> None:
    folder2 = nt.make_company(tmp_path / "別", values=[v if v[1] != "実施期間終期（年）" else ("加点項目", v[1], "2029")
                                                    for v in nt.SHEET_VALUES])
    code, data = run_json(folder2, "check", "--screen", "加点項目", page="m8_shinsei4_filled.txt")
    assert code == 4
    assert [(e["欄"], e["値"], e["画面の値"]) for e in data["合わない"]] == [("実施期間終期（年）", "2029", "2028")]


# ---- 断るとき ----

def test_refuses_outside_company_folder_and_unknown_screen(folder, tmp_path) -> None:
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    r = run(plain, "sheet")
    assert r.returncode == 2 and ".hojokin/ がありません" in r.stdout.decode("utf-8")
    r = run(folder, "list", "--screen", "経費明細", page="m8_shinsei4_before.txt")
    assert r.returncode == 2 and "画面「経費明細」の欄がありません" in r.stdout.decode("utf-8")
    r = run(folder, "list")
    assert r.returncode == 2 and "引数が違います" in r.stdout.decode("utf-8")


def test_refuses_case_folder_linked_outside(tmp_path) -> None:
    folder = nt.make_company(tmp_path / "会社")
    outside = tmp_path / "外の会社"
    (outside / "9_外の段階" / "申請書").mkdir(parents=True)
    os.rename(folder / "案件" / nt.CASE, tmp_path / "退けた案件")
    os.symlink(outside, folder / "案件" / nt.CASE)
    r = run(folder, "sheet")
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2 and "外を指しています" in out
    assert "9_外の段階" not in out


def test_runs_with_system_python(folder) -> None:
    """lib/ と skills/*/scripts/ は /usr/bin/python3（3.9）で動く（hook_runner.real_python は 3.9 を優先する）。"""
    if not Path("/usr/bin/python3").exists():
        pytest.skip("/usr/bin/python3 がありません")
    r = subprocess.run(["/usr/bin/python3", "-B", str(nt.SCRIPT), "sheet", "--folder", str(folder)],
                       capture_output=True, timeout=60)
    assert r.returncode == 0, r.stdout.decode("utf-8") + r.stderr.decode("utf-8")
    assert not list(nt.SCRIPT.parent.rglob("__pycache__"))
