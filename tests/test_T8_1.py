"""T8-1 書式を壊さない（SPEC F8、DESIGN 5章・6章。TASKS B14b）。

合格ライン：書いてよい範囲の外の変化0件（スタイル、余白、表の行と列、結合セル、数式、入力規則、シートの構成、
ヘッダーとフッター。行を足してよい表に足した行は除く）。範囲の外を変える書き込みは保存されず、直前の版のまま残る。

- Excel の様式（省力化 その3 と別紙1〜4）：書いてよい範囲は、入力のシート（保護したシート）のロックを外したセル。
  道具（yoshiki.py cells）で、その3・別紙1・別紙3・別紙4 の入力の欄に書き、公式の様式と比べて範囲の外の変化0件。
  数式のセル・結合の左上でないセル・保護していないシートへの書き込みは断り、ファイルは前のまま。
- 比べ方が、スタイル・余白・結合・数式・入力規則・シートの構成・ヘッダーとフッター・ロックしたセルの変化を
  見つけること（1つずつ変えて確かめる）。
- 入力シート.xlsx：制度データの申請画面のツールが入れる欄すべてに書き、範囲の外の変化0件。
- Word の様式（その1・2）のすべての項目は tests/test_write_word.py で確かめる。ここでは、Stop hook の戻しを確かめる。
- その場のコードで書き換えたとき：Stop hook が、変わった Word・Excel を同じ物差しで比べ、範囲の外が変わっていたら
  直前の版に戻して Claude に伝える。範囲の中だけの変化（道具で書いたもの）は戻さない。

様式は downloads/ から読み、写しや書いたファイルは tmp_path にだけ作る（リポに入れない）。downloads/ がなければ飛ばす。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

import pytest
import test_write_min as twm
import version_tool as vt

from lib import input_sheet
from lib import yoshiki_excel as ye
from lib import yoshiki_word as yw

REPO_ROOT = twm.REPO_ROOT
FORM3 = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "yoshiki_business_plan_part3_ippan_08.xlsx"
SEIKAI = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
PLAN = REPO_ROOT / "testdata" / "計画書" / "材料" / "1_正しい計画書" / "本文.json"
OFFICIAL3 = f"案件/{twm.CASE}/公式資料/事業計画書 その3_第8回.xlsx"
APP3 = f"案件/{twm.CASE}/{twm.STAGE}/申請書/その3.xlsx"

S3 = "【指定様式】事業計画書（その3）"
B1 = "（別紙１）省力化計算シート"
B3 = "（別紙３）投資回収期間計算シート"
B4 = "(別紙4）事業計画目標値算出シート"

VALUES = [
    {"シート": S3, "セル": "B3", "値": "株式会社やまぶき惣菜（架空）"},
    {"シート": S3, "セル": "B14", "値": 5},
    {"シート": S3, "セル": "B20", "値": "付加価値額は、機械で空いた人手で増やす売上から計算した（試しの文）。"},
    {"シート": S3, "セル": "I19", "値": 6.12},
    {"シート": B1, "セル": "C11", "値": "計量"}, {"シート": B1, "セル": "D11", "値": 540},
    {"シート": B1, "セル": "C12", "値": "盛り付け"}, {"シート": B1, "セル": "D12", "値": 900},
    {"シート": B1, "セル": "C13", "値": "検品"}, {"シート": B1, "セル": "D13", "値": 180},
    {"シート": B1, "セル": "I11", "値": "ラインの見守り"}, {"シート": B1, "セル": "J11", "値": 360},
    {"シート": B1, "セル": "K11", "値": "新たに追加される作業"},
    {"シート": B1, "セル": "I12", "値": "検品"}, {"シート": B1, "セル": "J12", "値": 120},
    {"シート": B1, "セル": "K12", "値": "内容は変化しない作業"}, {"シート": B1, "セル": "L12", "値": 3},
    {"シート": B3, "セル": "C6", "値": 22500000}, {"シート": B3, "セル": "H6", "値": 300},
    {"シート": B3, "セル": "J6", "値": 1500}, {"シート": B3, "セル": "L6", "値": 2100000},
    {"シート": B3, "セル": "C13", "値": "増加した付加価値額は、5年目と基準年度の差を5で割った（試しの文）。"},
    {"シート": B4, "セル": "C4", "値": "3月"},
    {"シート": B4, "セル": "F14", "値": 201600000}, {"シート": B4, "セル": "G14", "値": 205632000},
]


@pytest.fixture(scope="module")
def form3() -> bytes:
    if not FORM3.is_file():
        pytest.skip("downloads/ に省力化の様式（その3）がありません（公式資料を取ってから流す）")
    return FORM3.read_bytes()


class Env(twm.Env):
    """test_write_min の会社のフォルダに、その3 の公式資料を足したもの。"""

    def __init__(self, tmp_path: Path, form: bytes, form3: bytes) -> None:
        super().__init__(tmp_path, form)
        (self.folder / OFFICIAL3).write_bytes(form3)
        (self.folder / OFFICIAL3).chmod(0o444)
        listed = self.folder / "記録" / "資料の本文" / twm.CASE / "資料の一覧.json"
        listed.write_text(json.dumps({"案件": twm.CASE, "置き場所": {
            "Wordその1・2": {"ファイル": twm.OFFICIAL}, "Excelその3": {"ファイル": OFFICIAL3}}}, ensure_ascii=False),
            encoding="utf-8")

    def put(self, rel: str, data) -> str:
        target = self.folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return rel


@pytest.fixture
def env(tmp_path: Path, form3: bytes) -> Env:
    if not twm.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません")
    return Env(tmp_path, twm.FORM.read_bytes(), form3)


# ---------------------------------------------------------------- Excel の様式（その3）


def test_input_cells_are_the_unlocked_cells_of_protected_sheets(form3: bytes) -> None:
    book = ye.Book(form3)
    by = {s.name: s for s in book.sheets}
    assert by[B1].protected and {"C11", "D11", "I40", "L40"} <= by[B1].inputs and "M3" not in by[B1].inputs
    assert "M3" in by[B1].formulas and "C3" in by[B3].formulas
    assert {"C6", "H6", "J6", "L6", "C13"} <= by[B3].inputs and "D13" not in by[B3].inputs  # C13:M19 の結合の左上だけ
    assert not by["選択肢"].protected and not by["選択肢"].inputs
    entries = {e["シート"]: e for e in ye.outline(form3)}
    assert set(entries) == {S3, B1, "（別紙２）省力化業務プロセス図", B3, B4}
    assert any(c["セル"] == "C6" for c in entries[B3]["書いてよいセル"])


def test_cells_tool_writes_every_kind_of_input_and_keeps_the_form(env: Env, form3: bytes) -> None:
    text = twm.ok(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": VALUES})))
    assert f"{APP3} に、公式資料の様式から写して作り" in text and f"{len(VALUES)}個のセル" in text
    blob = (env.folder / APP3).read_bytes()
    base = ye.first_copy(form3)
    assert ye.compare_xlsx(base, blob) == []  # 範囲の外の変化0件
    for v in VALUES:
        assert ye.cell_value(blob, v["シート"], v["セル"]) == (str(v["値"]) if not isinstance(v["値"], str) else v["値"])
    # 写すときだけ、開いたときに計算し直す設定を付ける。ほかの部品はバイトのまま
    parts_b, parts_a = twm.parts_of(form3), twm.parts_of(blob)
    assert b'fullCalcOnLoad="1"' in parts_a[ye.BOOK] and b"fullCalcOnLoad" not in parts_b[ye.BOOK]
    changed = sorted(n for n in parts_b if parts_b[n] != parts_a.get(n))
    # 書いたシート（1・2・4・6）と、数式の値を計算し直したシート（LibreOffice があるとき）だけが変わる
    assert {"xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml",
            "xl/worksheets/sheet4.xml", "xl/worksheets/sheet6.xml"} <= set(changed)
    assert all(n == "xl/workbook.xml" or n.startswith("xl/worksheets/sheet") for n in changed), changed
    # 2回目は前の値を置き換え、ほかのセルは残る
    twm.ok(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": [{"シート": B3, "セル": "H6", "値": 280}]})))
    blob2 = (env.folder / APP3).read_bytes()
    assert ye.cell_value(blob2, B3, "H6") == "280" and ye.cell_value(blob2, B3, "C6") == "22500000"
    assert ye.compare_xlsx(blob, blob2) == []


@pytest.mark.parametrize("bad, words", [
    ({"シート": B1, "セル": "M3", "値": 0.7}, "数式のセル"),
    ({"シート": B3, "セル": "D13", "値": "x"}, "結合したセルの左上ではありません"),
    ({"シート": "選択肢", "セル": "A1", "値": "x"}, "入力のシートではありません"),
    ({"シート": B3, "セル": "B3", "値": "x"}, "入力の欄ではありません"),
    ({"シート": "別紙9", "セル": "A1", "値": "x"}, "シート「別紙9」がありません"),
    ({"シート": B3, "セル": "C6", "値": True}, "文字か数"),
])
def test_writes_outside_the_range_are_refused_and_nothing_changes(env: Env, bad, words) -> None:
    twm.ok(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": VALUES[:3]})))
    before = (env.folder / APP3).read_bytes()
    r = twm.refused(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": [VALUES[4], bad]})))
    assert words in r and "前のままです" in r
    assert (env.folder / APP3).read_bytes() == before  # 1件でも書けなければ、ほかの値も書かない


def test_first_write_refused_makes_no_file(env: Env) -> None:
    twm.refused(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": [{"シート": B1, "セル": "M3", "値": 1}]})))
    assert not (env.folder / APP3).exists()


def _replace_part(blob: bytes, name: str, old: bytes, new: bytes) -> bytes:
    parts = twm.parts_of(blob)
    assert old in parts[name], (name, old)
    return yw.rebuild_zip(blob, {name: parts[name].replace(old, new, 1)})


def _sub_part(blob: bytes, name: str, pattern: bytes, new: bytes) -> bytes:
    parts = twm.parts_of(blob)
    data, n = re.subn(pattern, new, parts[name], count=1)
    assert n == 1, (name, pattern)
    return yw.rebuild_zip(blob, {name: data})


TAMPERS = {
    "スタイル": lambda b: _sub_part(b, "xl/styles.xml", rb'<sz val="[0-9.]+"/>', b'<sz val="30"/>'),
    "余白": lambda b: _sub_part(b, "xl/worksheets/sheet4.xml", rb'<pageMargins left="[0-9.]+"', b'<pageMargins left="2.5"'),
    "結合セル": lambda b: _replace_part(b, "xl/worksheets/sheet4.xml", b'<mergeCell ref="C13:M19"/>', b'<mergeCell ref="C13:H19"/>'),
    "数式": lambda b: _sub_part(b, "xl/worksheets/sheet2.xml", rb"<f>IF\(D3=0", b"<f>IF(D3=1"),
    "入力規則": lambda b: _sub_part(b, "xl/worksheets/sheet2.xml", rb'<dataValidation type="list"', b'<dataValidation type="whole"'),
    "シートの構成": lambda b: _sub_part(b, "xl/workbook.xml", '<sheet name="選択肢"[^>]*/>'.encode("utf-8"), b""),
    "ヘッダーとフッター": lambda b: _sub_part(b, "xl/worksheets/sheet4.xml", rb"</worksheet>",
                                       b"<headerFooter><oddHeader>&amp;Ctest</oddHeader></headerFooter></worksheet>"),
    "ロックしたセル": lambda b: _sub_part(b, "xl/worksheets/sheet4.xml", rb'(<c r="B3" [^>]*>)<v>[0-9]+</v>', rb'\1<v>0</v>'),
    "行の高さ": lambda b: _sub_part(b, "xl/worksheets/sheet2.xml", rb'<row r="11" ', b'<row r="11" ht="40" customHeight="1" '),
}


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_compare_finds_each_kind_of_outside_change(form3: bytes, name: str) -> None:
    base = ye.first_copy(form3)
    written, _summary = ye.write_cells(base, VALUES)
    try:
        tampered = TAMPERS[name](written)
    except AssertionError:
        pytest.skip(f"この様式には「{name}」を変える場所がありません")
    found = ye.compare_xlsx(written, tampered)
    assert found, name


def test_values_inside_the_range_are_not_differences(form3: bytes) -> None:
    base = ye.first_copy(form3)
    written, _summary = ye.write_cells(base, VALUES)
    again, _summary = ye.write_cells(written, [{"シート": B3, "セル": "C6", "値": 1}])
    assert ye.compare_xlsx(written, again) == []


# ---------------------------------------------------------------- 入力シート（すべての欄）


def test_input_sheet_every_tool_field_is_written_inside_the_range(env: Env) -> None:
    seido = json.loads(SEIKAI.read_text(encoding="utf-8"))
    (env.folder / twm.SEIDO_IN_FOLDER).write_text(json.dumps(seido, ensure_ascii=False), encoding="utf-8")
    values: List[dict] = []
    for screen, field in input_sheet.fields_of(seido):
        if field.get("担当者が入れる"):
            continue
        kind = field.get("種類")
        values.append({"画面": screen["名前"], "欄": field["名前"],
                       "値": 1 if kind == "数字" else ("該当なし" if kind in ("チェック", "選択", "ファイル") else "試し")})
    assert len(values) > 150
    twm.ok(env.run("sheet", "--values", env.put("記録/一時/入力シートの値.json", {"値": values})))
    blob = (env.folder / twm.SHEET).read_bytes()
    made = input_sheet.build(seido)
    assert input_sheet.compare_xlsx(made, blob) == []
    _parts, _name, grid = input_sheet.read_grid(blob)
    _head, cols = grid.header()
    empty = [f for r, _s, f, staff in grid.field_rows() if not staff
             and not grid.texts.get(f"{cols[input_sheet.HEAD_VALUE]}{r}", "").strip()]
    assert empty == []


# ---------------------------------------------------------------- その場のコードで書き換えたとき（Stop hook）


def _company_with_application(tmp_path: Path, form: bytes, form3: bytes) -> vt.Company:
    c = vt.Company(tmp_path)
    seido = json.loads(SEIKAI.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    positions = {it["名前"]: it["書き込む位置"] for it in plan["項目"]}
    for f in seido["様式"]:
        for e in f["項目"]:
            if e["名前"] in positions:
                e["書き込む位置"] = positions[e["名前"]]
    c.write("記録/制度データ/省力化_第8回.json", json.dumps(seido, ensure_ascii=False))
    c.write(f"{vt.APPLICATION}/その3.xlsx", ye.first_copy(form3))
    c.write(f"{vt.APPLICATION}/その1・2.docx", form)
    c.stop()  # 道具が作ったものとして、版に残す
    return c


@pytest.mark.slow
def test_stop_hook_reverts_outside_changes_made_by_adhoc_code(tmp_path: Path, form3: bytes) -> None:
    if not twm.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません")
    form = twm.FORM.read_bytes()
    c = _company_with_application(tmp_path, form, form3)
    xlsx = c.folder / vt.APPLICATION / "その3.xlsx"
    docx = c.folder / vt.APPLICATION / "その1・2.docx"

    # 範囲の中だけの変化（道具で書いたのと同じ）は戻さない
    inside, _s = ye.write_cells(xlsx.read_bytes(), VALUES)
    xlsx.write_bytes(inside)
    keiei = {"見出し": "１‐2経営課題", "場所": "t4.r2.c0.p0", "範囲": "見出しの後"}
    word_inside, _s = yw.write_item(docx.read_bytes(), keiei, "人手が足りない（試しの文）。", "1-2 経営課題")
    docx.write_bytes(word_inside)
    out = c.stop()
    assert not (out and "直前の版に戻しました" in json.dumps(out, ensure_ascii=False))
    assert xlsx.read_bytes() == inside and docx.read_bytes() == word_inside

    # その場のコードで、数式と様式の文を書き換えた → 直前の版に戻して伝える
    xlsx.write_bytes(TAMPERS["数式"](inside))
    docx.write_bytes(_sub_part(word_inside, yw.DOC, "商号又は名称".encode("utf-8"), "会社の名前".encode("utf-8")))
    out = c.stop()
    reason = out["reason"] if out and out.get("decision") == "block" else ""
    assert "その3.xlsx が、書いてよい範囲の外まで変わっていました" in reason
    assert "その1・2.docx が、書いてよい範囲の外まで変わっていました" in reason
    assert "yoshiki.py" in reason
    assert xlsx.read_bytes() == inside and docx.read_bytes() == word_inside
    # 戻したので、書き換えた中身は版に残らない
    assert c.stop() is None or "直前の版に戻しました" not in json.dumps(c.stop(), ensure_ascii=False)

    # 道具が作り直す Excel（根拠対照表.xlsx。保護したシートがない）は、中身が変わっても戻さない
    from lib import konkyo
    evidence = c.folder / vt.APPLICATION / "根拠対照表.xlsx"
    row = {"記述": "15人", "種類": "数字", "書いた場所": "1-1 現状分析", "出典": "回答表 C-01"}
    evidence.write_bytes(konkyo.build([row]))
    c.stop()
    second = konkyo.build([row, dict(row, 記述="2008年4月1日", 種類="日付")])
    evidence.write_bytes(second)
    out = c.stop()
    assert not (out and "根拠対照表.xlsx が、書いてよい範囲" in json.dumps(out, ensure_ascii=False))
    assert evidence.read_bytes() == second


# ---------------------------------------------------------------- 数式のセルの値の保存（11/6 のリハーサルの不具合）


def test_cells_tool_stores_formula_values(env: Env, form3: bytes) -> None:
    """書いた後に、数式のセルの値を LibreOffice で計算し直して保存する。数式と書式はそのまま（範囲の外の変化0件）。
    リハーサルでは、省力化指数（その3!B8）・業務時間の合計（別紙1!D3）・投資回収期間が 0 のまま残り、審査役が要修正にした。"""
    from zaimu_tool import soffice_or_skip

    soffice_or_skip()
    text = twm.ok(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": VALUES})))
    assert "数式のセル（省力化指数・投資回収期間・伸び率など）の値を、LibreOffice で計算し直して保存しました" in text
    blob = (env.folder / APP3).read_bytes()
    assert ye.compare_xlsx(ye.first_copy(form3), blob) == []
    before_h, after_h = float(ye.cell_value(blob, B1, "D3")), float(ye.cell_value(blob, B1, "J3"))  # 時間（式は分÷60）
    assert before_h > after_h > 0  # 前は 0 のまま残っていた
    assert abs(float(ye.cell_value(blob, B1, "M3")) - (before_h - after_h) / before_h) < 1e-9  # 省力化指数
    assert ye.cell_value(blob, S3, "B8") == ye.cell_value(blob, B1, "M3")  # その3 の省力化指数は別紙1 から
    # 数式はそのまま残る（値だけを替えた）
    sheet = twm.parts_of(blob)["xl/worksheets/sheet1.xml"]
    assert sheet.count(b"<f") == twm.parts_of(form3)["xl/worksheets/sheet1.xml"].count(b"<f")
    # recalc は、値の同じセルは書き換えない（もう一度動かしても変わらない）
    twm.ok(env.run("recalc", "--file", "その3.xlsx"))
    assert (env.folder / APP3).read_bytes() == blob


def test_cells_tool_writes_to_the_form_given_by_source(env: Env, form3: bytes) -> None:
    """--source に その3 以外の Excel の様式を渡すと、その様式の名前の申請書に書く（前は その3.xlsx に決め打ちだった）。
    書き先がもうあって、渡した様式とシートの構成が違えば断る。"""
    other = f"案件/{twm.CASE}/公式資料/【指定様式】試しの確認書_第9回.xlsx"
    (env.folder / other).write_bytes(form3)
    text = twm.ok(env.run("cells", "--source", other, "--input",
                          env.put("記録/一時/確認書の値.json", {"値": [{"シート": B3, "セル": "H6", "値": 250}]}), "--soffice", "/nonexistent"))
    made = f"案件/{twm.CASE}/{twm.STAGE}/申請書/試しの確認書.xlsx"
    assert f"{made} に、公式資料の様式から写して作り" in text
    assert "計算し直せませんでした" in text  # LibreOffice がないときは、値を前のまま残したと伝える
    assert not (env.folder / APP3).exists()
    # 書き先と様式の構成が違うときは断る
    (env.folder / f"案件/{twm.CASE}/{twm.STAGE}/申請書/別の.xlsx").write_bytes(twm.FORM.read_bytes())
    r = env.run("cells", "--source", other, "--file", "別の.xlsx", "--input", "記録/一時/確認書の値.json")
    assert r.returncode != 0
