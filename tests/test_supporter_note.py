"""入力シートの支援者の欄の案内（SPEC 2.3・F10「入力シートの支援者の欄には 2.3 の案内を添える」、T10-4 の道具の部分。
DESIGN 14章「支援者の欄の案内」。TASKS B29）。

- 入力シートを作る道具（lib/input_sheet.py の build）は、支援者の欄の行の「案内」の列に、SPEC 2.3 の案内を入れる。
  支援者の欄は、省力化（第8回の正解）なら ❺ の事業計画書作成支援者情報の9欄、持続化（第20回の正解）なら
  第三者からのアドバイスの4欄。ほかの欄（アンケートの「支援機関からの情報」、生産性向上支援センターの加点など）には
  入れない。案内の列は書いてよい範囲の外で、値を書いても変わらない。
- kaku の yoshiki.py sheet は、入力シートを書いた後に、この案内を出す（Claude が社長に伝える。振る舞いは
  evals/T10-4-支援者の欄/ で見る）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import hook_runner as hr

from lib import input_sheet

REPO = hr.REPO_ROOT
SCRIPT = REPO / "skills" / "kaku" / "scripts" / "yoshiki.py"
NOTE = "このツールは支援者には当たりません。人の支援者がいる場合は正直に書いてください。"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"


def answer(name: str) -> dict:
    return json.loads((REPO / "testdata" / "正解" / f"{name}.json").read_text(encoding="utf-8"))


def test_note_is_the_spec_text() -> None:
    assert input_sheet.SUPPORTER_NOTE == NOTE
    spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
    assert "「" + NOTE.rstrip("。") + "」" in spec


def test_supporter_rows_get_the_note() -> None:
    notes = input_sheet.notes_of(input_sheet.build(answer("省力化_第8回")))
    assert [(s, f) for s, f, _n in notes] == [("事業計画名及び作成者情報", f) for f in (
        "事業計画書作成に支援者は関与していない", "支援機関名", "支援報酬（予定）額", "契約期間", "支援担当者部署名",
        "支援担当者名", "支援者連絡先電話番号", "支援者メールアドレス", "認定経営革新等支援機関ID")]
    assert {n for _s, _f, n in notes} == {NOTE}
    notes = input_sheet.notes_of(input_sheet.build(answer("持続化_第20回")))
    assert [f for _s, f, _n in notes] == ["商工会・商工会議所以外からのアドバイスの有無", "アドバイス料の有無",
                                         "アドバイス料の金額", "アドバイス者名"]


def test_note_stays_when_values_are_written() -> None:
    """案内の列は書いてよい範囲の外。値を書いても案内は変わらず、範囲の外の差も出ない。"""
    blob = input_sheet.build(answer("省力化_第8回"))
    written, _ = input_sheet.write_value(blob, "事業計画書作成に支援者は関与していない", "はい", "事業計画名及び作成者情報")
    assert input_sheet.notes_of(written) == input_sheet.notes_of(blob)
    assert input_sheet.compare_xlsx(blob, written) == []
    # 案内は、値（G 列）と値の出どころ（H 列）の後ろの I 列
    _parts, _name, grid = input_sheet.read_grid(written)
    assert grid.header()[1][input_sheet.HEAD_NOTE] == "I"


def test_yoshiki_sheet_prints_the_note(tmp_path) -> None:
    folder = tmp_path / "やまぶき惣菜"
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "記録" / "制度データ").mkdir(parents=True)
    (folder / "記録" / "制度データ" / "省力化_第8回.json").write_text(
        json.dumps(answer("省力化_第8回"), ensure_ascii=False), encoding="utf-8")
    (folder / "案件" / CASE / STAGE / "申請書").mkdir(parents=True)
    argv = [hr.real_python(), "-B", str(SCRIPT), "sheet", "--folder", str(folder), "--screen", "事業計画名及び作成者情報",
            "--field", "事業計画書作成に支援者は関与していない", "--value", "はい"]
    r = subprocess.run(argv, capture_output=True, cwd=str(tmp_path), env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                       timeout=120)
    text = r.stdout.decode("utf-8")
    assert r.returncode == 0, text + r.stderr.decode("utf-8")
    assert f"入力シートの「案内」の列に「{NOTE}」と入れてあります" in text
    assert "「事業計画書作成に支援者は関与していない」など9欄" in text
    sheet = folder / "案件" / CASE / STAGE / "申請書" / input_sheet.FILE_NAME
    assert len(input_sheet.notes_of(sheet.read_bytes())) == 9
