"""T10-2 模擬画面への入力（SPEC F10、DESIGN 5章・11章。TASKS B29）。T10-3 の残り（操作記録）もここで見る。

合格ライン（SPEC 6章 F10）：
  T10-2：デスクトップアプリで入力と添付をさせた後、模擬画面が記録した値と添付されたファイルを読み取ると、
         入力シートと100%一致（添付するファイルを含む）。文字数の超過0件。
  T10-3 の残り：同じ記録で「提出」ボタンが押されていない。確認・誓約・同意（宣誓を含む）のチェック欄とパスワード欄に
         入力がない。

このファイルは2つを見る。
1. デスクトップでの通しの記録（本物の T10-2）：環境変数 HOJOKIN_T10_2_RECORD に模擬画面の記録のフォルダ
   （`python3 mock/server.py --screens --reset --record-dir <フォルダ>` の <フォルダ>。入力値.json・操作記録.jsonl・
   添付/ がある）、HOJOKIN_T10_2_FOLDER に会社のフォルダ（入力シートと添付する書類の写しがある）を渡すと、記録を
   入力シートと照らす。案件・段階が2つ以上なら HOJOKIN_T10_2_CASE・HOJOKIN_T10_2_STAGE も渡す。渡さなければ飛ばす。
2. 照らす道具そのもの：ブラウザを使わずに、入力シートの値を模擬画面へ送って作った記録（mock/test_server.py の
   やり方）で、一致する記録は通り、1欄違う・添付が1つ欠ける・入力シートにない欄に値がある・添付の中身が違う・
   上限を超える・提出が押された記録は落ちることを確かめる。入力シートは、制度データの正解（省力化 第8回）の
   ツールが入れるすべての欄にデモの会社（架空）の値を書いたもの（tests/t10_2_tool.py）。
   あわせて、名前を正解に合わせた模擬画面を内蔵ブラウザで読んだ結果（tests/data/t10_2/）で、画面入力の道具
   （nyuryoku.py list）が、正解の名前の入力シートの欄をすべて画面の欄に当てられることも見る。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import nyuryoku_tool as nt
import pytest
import t10_2_tool as t2

from lib import page_tree

RECORD = os.environ.get("HOJOKIN_T10_2_RECORD")
FOLDER = os.environ.get("HOJOKIN_T10_2_FOLDER")

# 試しの入力シート（207欄）を作り、模擬画面を動かすので、どれも数秒かかる（開発用の Stop hook では流さない）
pytestmark = pytest.mark.slow


def sheet_rows_of(folder: Path, case: str = None, stage: str = None) -> list:
    """会社のフォルダの入力シートの行（画面入力の道具 nyuryoku.py と同じ読み方）。"""
    tool = nt.script_module()
    case = tool.find_case(Path(folder), case)
    stage = tool.find_stage(Path(folder), case, stage)
    _rel, path = tool.sheet_path(Path(folder), case, stage)
    return tool.read_sheet(path)


@pytest.fixture(scope="module")
def sheet_blob() -> bytes:
    seido = t2.answer()
    return t2.write_sheet(seido, t2.demo_values(seido, nt.CASE, nt.STAGE))


@pytest.fixture
def company(tmp_path, sheet_blob) -> Path:
    return t2.make_company(tmp_path / "会社", sheet=sheet_blob)


def run_mock(record_dir: Path, steps) -> tuple:
    with nt.running_mock(record_dir) as base:
        steps(base)
    return nt.read_mock_record(record_dir)


# ---- 試しの入力シート ----

def test_demo_sheet_fills_every_tool_field(company) -> None:
    """試しの入力シートは、正解のツールが入れるすべての欄に値（当てはまらない欄は「該当なし」）がある。"""
    rows = sheet_rows_of(company)
    tool_rows = [r for r in rows if not r["担当者が入れる"]]
    assert len(rows) == 286 and len(tool_rows) == 207
    assert all(r["値"].strip() for r in tool_rows)
    attach = [r for r in tool_rows if r["種類"] == "添付" and not t2.input_sheet.is_not_applicable(r["値"])]
    assert len(attach) == len(t2.ATTACHMENTS)
    for r in attach:
        assert (company / r["値"]).is_file(), r["値"]


def test_write_values_matches_one_by_one() -> None:
    """まとめて書く道具（lib/input_sheet.write_values）は、1件ずつ書いたときと同じファイルを作り、同じ決まりで断る。"""
    seido = t2.answer()
    values = t2.demo_values(seido, nt.CASE, nt.STAGE)[:15]
    fields = {(s["名前"], f["名前"]): f for s, f in t2.input_sheet.fields_of(seido)}
    blob = t2.input_sheet.build(seido)
    for e in values:
        field = fields[(e["画面"], e["欄"])]
        value = e["値"]
        if field["種類"] == "数字" and not t2.input_sheet.is_not_applicable(value):
            value = t2.input_sheet.parse_number(str(value))
        blob, _ = t2.input_sheet.write_value(blob, e["欄"], value, e["画面"], t2.input_sheet.limit_of(field))
    assert t2.write_sheet(seido, values) == blob
    with pytest.raises(ValueError, match="担当者が画面で入れる欄"):
        t2.input_sheet.write_values(t2.input_sheet.build(seido), [("宣誓事項1", "はい", "宣誓・手引き", None)])
    with pytest.raises(ValueError, match="短くしてください"):
        t2.input_sheet.write_values(t2.input_sheet.build(seido),
                                    [("事業者名（カナ）", "ア" * 11, "基本情報", ("上限", 10))])


# ---- 照らす道具：一致する記録は通る ----

def test_matching_record_passes(company, tmp_path) -> None:
    rows = sheet_rows_of(company)
    record = tmp_path / "記録"
    log, state = run_mock(record, lambda base: t2.fill_mock(base, rows, company))
    problems, counts = t2.t10_2_problems(state, rows, company, record)
    assert problems == []
    assert counts["照らした行"] == 207 and counts["添付で合った行"] == len(t2.ATTACHMENTS)
    assert counts["値で合った行"] >= 100 and counts["文字数の超過"] == 0
    # 同じ記録で、提出は押されておらず、担当者のチェック欄とパスワード欄に入力がない（T10-3 の残り）
    assert nt.t10_3_violations(log, state) == []
    # ツールが入れる欄のある8画面（❷〜❾）で、一時保存を1回ずつ押した
    assert [(e["screen"][0], e["button"]) for e in log if e["event"] == "button"] == [
        (no, "save") for no in "❷❸❹❺❻❼❽❾"]


# ---- 照らす道具：違いを見つける ----

def test_one_wrong_value_is_found(company, tmp_path) -> None:
    rows = sheet_rows_of(company)
    _log, state = run_mock(tmp_path / "記録", lambda base: t2.fill_mock(
        base, rows, company, change={"biz_name": "株式会社やまぶき総菜"}))
    problems, _counts = t2.t10_2_problems(state, rows, company)
    assert len(problems) == 1 and "事業者名（法人名/屋号・商号）" in problems[0], problems


def test_missing_attachment_is_found(company, tmp_path) -> None:
    rows = sheet_rows_of(company)
    _log, state = run_mock(tmp_path / "記録", lambda base: t2.fill_mock(base, rows, company, skip=("【指定様式】役員名簿",)))
    problems, _counts = t2.t10_2_problems(state, rows, company)
    assert len(problems) == 1 and "役員名簿" in problems[0] and "添付がない" in problems[0], problems


def test_extra_value_and_wrong_file_are_found(company, tmp_path) -> None:
    rows = sheet_rows_of(company)

    def steps(base):
        t2.fill_mock(base, rows, company)
        cookie = nt.mock_login(base)
        # 入力シートにない欄（法人番号）に値を入れ、履歴事項全部証明書に別の中身のファイルを添付し直す
        body, headers = t2.multipart({"button": "save", **{k: v for k, v in t2.form_for_screens(
            rows, company)[2]["fields"].items()}, "corp_number": "1234567890123"})
        nt.http(f"{base}/shinsei/2", body, headers, cookie)
        files = dict(t2.form_for_screens(rows, company)[9]["files"])
        files["doc_registry"] = ("履歴事項全部証明書.pdf", b"%PDF-1.4 other")
        body, headers = t2.multipart({"button": "save"}, files)
        nt.http(f"{base}/shinsei/9", body, headers, cookie)

    _log, state = run_mock(tmp_path / "記録", steps)
    problems, _counts = t2.t10_2_problems(state, rows, company)
    assert len(problems) == 2, problems
    assert any("法人番号" in p and "入力シートにない欄" in p for p in problems)
    assert any("履歴事項全部証明書" in p and "中身" in p for p in problems)


def test_over_limit_value_is_counted(company) -> None:
    """上限（目安でないもの）を超える値が画面に入っていたら数える。目安を超えるだけなら落とさない。"""
    rows = sheet_rows_of(company)
    name = next(r for r in rows if r["欄"] == "事業計画名（３０文字程度）")
    fields = {f["id"]: f for f in t2.mock_fields()}
    state = {"fields": {"plan_name": {**fields["plan_name"], "value": name["値"]}}, "files": {}}
    only = [dict(name, 上限=("目安", 10))]
    problems, counts = t2.t10_2_problems(state, only)
    assert problems == [] and counts["目安を超えた行"] == 1
    problems, counts = t2.t10_2_problems(state, [dict(name, 上限=("システムの上限", 10))])
    assert counts["文字数の超過"] == 1 and "上限の10字を超えている" in problems[0]


def test_submit_or_oath_in_the_same_record_is_found(company, tmp_path) -> None:
    rows = sheet_rows_of(company)

    def steps(base):
        t2.fill_mock(base, rows, company)
        cookie = nt.mock_login(base)
        nt.mock_post(base, 3, cookie, {"button": "save", "not_same_corp": "on"})
        nt.mock_post(base, 12, cookie, {"button": "submit"})

    log, state = run_mock(tmp_path / "記録", steps)
    found = nt.t10_3_violations(log, state)
    assert any("提出" in p for p in found) and any("not_same_corp" in p for p in found)


# ---- 画面入力の道具が、正解の名前で模擬画面の欄を見つける ----

def plan_for(rows: list, screen: str, page_file: str) -> dict:
    tool = nt.script_module()
    text = (t2.DATA / page_file).read_text(encoding="utf-8")
    page = page_tree.Page(page_tree.parse(text)["elements"])
    return tool.plan(tool.rows_of_screen(rows, screen), tool.page_controls(page))


def test_nyuryoku_list_finds_every_field_on_renamed_screens(company) -> None:
    """名前を正解に合わせた模擬画面（❸・❽ を内蔵ブラウザで読んだ結果）で、正解の名前の入力シートの欄が、
    すべて画面の欄に当たる。表の中の欄も、見えないラベルの名前で当たる。4つの語を含むラジオボタンは、
    入力シートで担当者の欄なら担当者が入れる欄に、ツールの欄なら入れる欄になる。"""
    rows = sheet_rows_of(company)
    result = plan_for(rows, "要件", "b29_shinsei3.txt")
    assert result["見当たらない"] == [] and result["重なり"] == [] and result["入れられない"] == []
    assert [(e["欄"], e["form_input"]) for e in result["入れる"]] == [
        ("小規模企業者/小規模事業者", True), ("再生事業者", False)]
    person = {e["欄"]: e["ref"] for e in result["担当者が入れる"]}
    assert person["国の他の助成制度との重複確認"] == ["ref_55", "ref_58"]

    result = plan_for(rows, "経費明細・資金調達内訳", "b29_shinsei8.txt")
    assert result["見当たらない"] == [] and result["重なり"] == [] and result["入れられない"] == []
    assert len(result["入れる"]) == 12 and len(result["値がない"]) == 19
    assert [e["名前"] for e in result["画面だけにある"]] == []
    filled = {e["欄"]: (e["ref"], e["form_input"]) for e in result["入れる"]}
    assert filled["補助金申請額の経費内訳 借入金（資金の調達先）"] == ("ref_151", "取引のある信用金庫")
    assert filled["機械装置・システム構築費（（B）補助対象経費（税抜きの額））"] == ("ref_44", "22500000")

    # 正解とは違い、入力シートで「国の他の助成制度との重複確認」をツールの欄にすると、選ぶ項目の番号が出る
    tool_rows = copy.deepcopy(rows)
    for r in tool_rows:
        if r["欄"] == "国の他の助成制度との重複確認":
            r["担当者が入れる"], r["値"] = False, "いいえ"
    result = plan_for(tool_rows, "要件", "b29_shinsei3.txt")
    assert ("国の他の助成制度との重複確認", "ref_58") in [(e["欄"], e["ref"]) for e in result["入れる"]]


# ---- デスクトップでの通しの記録（本物の T10-2） ----

@pytest.mark.skipif(not (RECORD and FOLDER),
                    reason="デスクトップでの通しの記録を HOJOKIN_T10_2_RECORD に、会社のフォルダを HOJOKIN_T10_2_FOLDER に渡すと流れる")
def test_desktop_record_matches_the_input_sheet() -> None:
    record, folder = Path(RECORD), Path(FOLDER)
    rows = sheet_rows_of(folder, os.environ.get("HOJOKIN_T10_2_CASE"), os.environ.get("HOJOKIN_T10_2_STAGE"))
    log, state = nt.read_mock_record(record)
    problems, counts = t2.t10_2_problems(state, rows, folder, record)
    print(json.dumps(counts, ensure_ascii=False))
    for p in problems:
        print("- " + p)
    assert problems == []
    assert counts["文字数の超過"] == 0
    # 空振りでないこと：値で合った行と添付で合った行がある（入力シートの値が空ばかりなら落とす）
    assert counts["値で合った行"] > 0 and counts["添付で合った行"] > 0
    violations = nt.t10_3_violations(log, state)
    for v in violations:
        print("- " + v)
    assert violations == []
