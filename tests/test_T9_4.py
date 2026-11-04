"""T9-4 仮の印と空欄（SPEC F9。自動。方法：完成した申請書を見る。合格ライン：仮の印0件、空欄0件）。TASKS M7。

- 仮の印と空欄は、文章では決まった形（【仮：…】、【空欄：…】）で書き、コードで数える（DESIGN 6章）。
  財務モデルの前提のような数字の欄は、隣の「状態」の欄が「仮」の行を数える。
- 空欄には、印のほかに、まだ何も書いていない所も数える（仮の形。TASKS M7 の質問）：書き込む位置を対応づけた様式の
  項目で、説明の青字のほかに文字がないもの、入力シートのツールが入れる欄で、値が空のもの。
- 完成の記録は、仮の印と空欄が0件のときだけ残る（DESIGN 8章）。そのうえで、完成の記録にある版の申請書を、
  道具の読み方に頼らずに見て（zip の中の XML の文字）、仮の印0件・空欄0件を確かめる。

道具は /usr/bin/python3 で、hook は hooks.json のコマンドから動かす（tests/kakunin_tool.py）。
公式の様式を使うテストは downloads/ がなければ飛ばす（写しや書いたファイルは tmp_path にだけ作る）。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import kakunin_tool as kt
import pytest

from lib import input_sheet, shinsa_result


@pytest.fixture
def env(tmp_path: Path) -> kt.Env:
    return kt.Env(tmp_path)


def places_of(report: dict, kind: str) -> list:
    return [(f["ファイル"], f["場所"]) for f in report[kind]]


# ---------------------------------------------------------------- 数え方


def test_marks_in_word_are_counted_by_item(env: kt.Env) -> None:
    env.trial_application({
        # 印が Word の中で別々の文字の区切り（run）に分かれていても数える。全角・半角の「：」も、「：」のない形も
        "1-1 現状分析": ["受注は月【仮：650】件に増えた。", ["断った注文は", "【空", "欄：件数", "】", "件"]],
        "1-2 経営課題": ["【仮】盛り付けは4人で行う。【 仮 : 繁忙期は11月】", "【空欄】"],
        # 6. 補足事項は書いていない（説明の青字だけ）
    }, extra=["【仮：様式の項目の外に書いた印】"])
    env.evidence(kt.GOOD_EVIDENCE)
    code, report = env.count()
    assert code == 3 and not report["通った"]
    assert places_of(report, "仮の印") == [
        (kt.WORD, "1-1 現状分析"), (kt.WORD, "1-2 経営課題"), (kt.WORD, "1-2 経営課題"), (kt.WORD, "p1")]
    assert [f["文字"] for f in report["仮の印"]][:2] == ["【仮:650】", "【仮】"]
    assert places_of(report, "空欄") == [(kt.WORD, "1-1 現状分析"), (kt.WORD, "1-2 経営課題"), (kt.WORD, "6. 補足事項")]
    assert report["空欄"][2]["文字"] == "（まだ何も書いていない項目）"
    text = kt.code(env.tool("count"), 3)
    assert "仮の印 4件、空欄 3件" in text
    assert f"{kt.WORD}（6. 補足事項）：（まだ何も書いていない項目）" in text


def test_words_that_only_look_like_marks_are_not_counted(env: kt.Env) -> None:
    env.trial_application({
        "1-1 現状分析": ["【仮説】を立てて検証した。【仮称】冷凍惣菜の新しい品目。", "仮の数字は使っていない。"],
        "1-2 経営課題": ["空欄のまま出さないよう、社長が確かめた。【空欄の多い書類】は使わない。"],
        "6. 補足事項": ["特になし。"],
    }, sheet_values=kt.GOOD_SHEET)
    env.evidence(kt.GOOD_EVIDENCE)
    code, report = env.count()
    assert (report["仮の印"], report["空欄"]) == ([], [])
    assert code == 0 and report["通った"]


def test_marks_in_sheets_model_and_text_files(env: kt.Env) -> None:
    env.trial_application(kt.GOOD_BODIES,
                          sheet_values={"事業計画名（３０文字程度）": "【仮：自動化で断らない工場】",
                                        "常勤従業員数（基準年度）": "7"},  # 事業計画の概要は空のまま
                          model=[("単価_冷凍惣菜", ""), ("数量_冷凍惣菜", "仮"), ("賃上げ率", "仮")])
    env.put(f"{kt.APP_DIR}/下書き.md", "# 下書き\n導入は【空欄：導入の月】に終える。\n".encode("utf-8"))
    env.evidence(kt.GOOD_EVIDENCE)
    code, report = env.count()
    assert code == 3
    assert places_of(report, "仮の印") == [
        (kt.SHEET, "入力シート!G4"), (kt.MODEL, "前提!H6"), (kt.MODEL, "前提!H7")]
    assert report["仮の印"][0]["文字"] == "【仮:自動化で断らない工場】"
    assert report["仮の印"][1]["文字"] == "「状態」が仮（数量_冷凍惣菜）"
    assert places_of(report, "空欄") == [
        (f"{kt.APP_DIR}/下書き.md", "2行目"), (kt.SHEET, "事業計画名及び作成者情報／事業計画の概要")]
    # 担当者が入れる欄（宣誓の確認）は、空でも数えない
    assert not any("宣誓" in f["場所"] for f in report["空欄"])


# ---------------------------------------------------------------- 完成した申請書を見る


def assert_no_marks_by_reading_files(env: kt.Env, files: dict) -> None:
    """道具の読み方に頼らずに、完成の記録にある版の申請書を見る：仮の印0件、空欄0件。"""
    for rel, sha in files.items():
        path = env.folder / rel
        assert shinsa_result.sha256_file(path) == sha, rel  # 今のファイルが、完成にした版のまま
        if path.suffix in (".docx", ".xlsx"):
            text = unicodedata.normalize("NFKC", kt.all_xml_text(path.read_bytes()))
        else:
            text = unicodedata.normalize("NFKC", path.read_text(encoding="utf-8"))
        for mark in ("【仮", "【 仮", "【空欄", "【 空欄"):
            assert mark not in text, (rel, mark)
    blob = (env.folder / kt.SHEET).read_bytes()
    _parts, _name, grid = input_sheet.read_grid(blob)
    _head, cols = grid.header()
    for r, screen, field, staff in grid.field_rows():
        if not staff:
            assert grid.texts.get(f"{cols['値']}{r}", "").strip(), (screen, field)  # ツールが入れる欄に空欄がない
    if kt.MODEL in files:
        # 財務モデルの「状態」の欄に「仮」がない（文字だけのセルが「仮」のものがない）
        for name, data in kt.zip_parts((env.folder / kt.MODEL).read_bytes()).items():
            if name.endswith(".xml"):
                assert "<t>仮</t>" not in data.decode("utf-8"), name


def finish(env: kt.Env) -> dict:
    """審査役に渡し、審査役の報告（要修正0件）を hook が保存し、完成にする。完成の記録の1件を返す。"""
    kt.ok(env.tool("prepare"))
    number = env.note()["確かめの番号"]
    env.subagent_stop(kt.report_json(number, [kt.finding("助言", "図を1つ足すと読みやすい")]))
    assert "完成にしました" in kt.ok(env.tool("finish"))
    return env.completion()["記録"][-1]


def test_completed_application_has_no_provisional_marks_or_blanks(env: kt.Env) -> None:
    # 仮の印と空欄の残った申請書は、完成にならない（審査役にも渡さない）
    env.trial_application({**kt.GOOD_BODIES, "1-2 経営課題": ["盛り付けは【仮：4人】で行う。", "【空欄：断った注文の件数】"]},
                          sheet_values={"事業計画名（３０文字程度）": "盛り付けの自動化", "常勤従業員数（基準年度）": "7"},
                          model=[("単価_冷凍惣菜", ""), ("数量_冷凍惣菜", "仮")])
    env.evidence(kt.GOOD_EVIDENCE)
    code, report = env.count()
    assert (len(report["仮の印"]), len(report["空欄"])) == (2, 2)
    text = kt.code(env.tool("finish"), 3)
    assert "仮の印 2件、空欄 2件" in text
    assert kt.code(env.tool("prepare"), 3)
    assert not (env.folder / kt.COMPLETION).exists()

    # 社長に聞いて埋めた（仮の印を外し、空欄に答えを入れた）
    env.put(kt.WORD, kt.make_docx(kt.GOOD_BODIES))
    kt.ok(env.yoshiki("sheet", "--field", "事業計画の概要", "--value", "盛り付け機を入れ、断っていた注文を受ける。"))
    env.put(kt.MODEL, kt.make_model_xlsx([("単価_冷凍惣菜", ""), ("数量_冷凍惣菜", "")]))
    code, report = env.count()
    assert code == 0 and (report["仮の印"], report["空欄"]) == ([], [])

    entry = finish(env)
    assert entry["コードの確かめ"]["仮の印"] == 0 and entry["コードの確かめ"]["空欄"] == 0
    assert set(entry["ファイルのハッシュ"]) == {kt.WORD, kt.SHEET, kt.EVIDENCE, kt.MODEL}
    # 完成した申請書を見る：仮の印0件、空欄0件
    assert_no_marks_by_reading_files(env, entry["ファイルのハッシュ"])
    code, report = env.count()
    assert code == 0 and (report["仮の印"], report["空欄"]) == ([], [])


def test_a_mark_added_after_completion_is_found_and_not_completed(env: kt.Env) -> None:
    env.trial_application(kt.GOOD_BODIES, sheet_values=kt.GOOD_SHEET)
    env.evidence(kt.GOOD_EVIDENCE)
    entry = finish(env)
    # 完成の後に仮の印を足した版は、完成の記録の版ではなく、数えると見つかり、完成にならない
    env.put(kt.WORD, kt.make_docx({**kt.GOOD_BODIES, "6. 補足事項": ["【仮：来年度に2台目を検討】"]}))
    assert shinsa_result.sha256_file(env.folder / kt.WORD) != entry["ファイルのハッシュ"][kt.WORD]
    code, report = env.count()
    assert code == 3 and places_of(report, "仮の印") == [(kt.WORD, "6. 補足事項")]
    text = kt.code(env.tool("finish"), 3)
    assert "仮の印 1件" in text
    assert len(env.completion()["記録"]) == 1


@pytest.mark.slow
def test_completed_official_form_has_no_marks(env: kt.Env) -> None:
    """公式の様式（その1・2）に、M6 の書く道具で書いた申請書でも、完成した版の仮の印0件・空欄0件を確かめる。"""
    if not kt.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません（公式資料を取ってから流す）")
    env.official_form(kt.FORM.read_bytes())

    def write(item: str, text: str) -> None:
        kt.ok(env.yoshiki("write", "--item", item, stdin=text.encode("utf-8")))

    write("（２）事業計画名", "盛り付けの自動化で受注を断らない工場にする")
    write("1-2 経営課題", "盛り付けを【仮：4人】の手作業で行っている。\n繁忙期は断る注文が月30件ある。")
    for field, value in kt.GOOD_SHEET.items():
        kt.ok(env.yoshiki("sheet", "--field", field, "--value", value))
    env.evidence(kt.GOOD_EVIDENCE)
    code, report = env.count()
    assert code == 3
    assert places_of(report, "仮の印") == [(kt.WORD, "1-2 経営課題")]
    assert places_of(report, "空欄") == [(kt.WORD, "6. 補足事項")]  # 補足事項は、説明の青字のほかに何もない

    write("1-2 経営課題", "盛り付けを4人の手作業で行っている。\n繁忙期は断る注文が月30件ある。")
    write("6. 補足事項", "特になし。")
    code, report = env.count()
    assert code == 0, json.dumps(report, ensure_ascii=False)
    entry = finish(env)
    assert_no_marks_by_reading_files(env, entry["ファイルのハッシュ"])
