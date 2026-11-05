"""Word の様式（その1・2）のすべての項目に書き、PDF にする（TASKS B14a。SPEC F8「様式に書式を壊さずに書き込む」、
DESIGN 1.1・5章・6章・9.1）。

- その1・2 の項目は、正解の制度データ（testdata/正解/省力化_第8回.json）の「事業計画書（その1・その2）」の16項目。
  14項目は文の項目（書き込む位置は testdata/計画書/ の D9 と同じ）、「（1）事業者情報」と「1. 事業者の概要」は
  表の欄を持つ項目で、欄ごとに書き込む位置を対応づける（`"欄": [{"名前", "書き込む位置"}]`）。
- 対応づけは map（読み取り役が返す形）で入れ、書くのは write（欄は --field）。すべて書いた後に、公式資料の様式と
  比べて、書いてよい範囲の外の変化が0件であること、書いてよい範囲に書いた文があること、空欄がないことを確かめる。
- PDF にする（pdf）：段階の「添付する書類」に写しを作り、元の Word は変えない。LibreOffice がなければ飛ばす。

様式は downloads/ から読み、写しや書いたファイルは tmp_path にだけ作る（リポに入れない）。downloads/ がなければ飛ばす。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
import test_write_min as twm

from lib import kakunin
from lib import yoshiki_word as yw

REPO_ROOT = twm.REPO_ROOT
SEIKAI = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
PLAN = REPO_ROOT / "testdata" / "計画書" / "材料" / "1_正しい計画書" / "本文.json"
FORM_NAME = "事業計画書（その1・その2）"
PDF = f"案件/{twm.CASE}/{twm.STAGE}/添付する書類/その1・2.pdf"


def cell(heading: str, place: str) -> Dict[str, str]:
    return {"見出し": heading, "場所": place, "範囲": "セル"}


INNER = "t4.r0.c0.t0"
YEARS = (("2023年度", "c1"), ("2024年度", "c2"), ("2025年度", "c3"))
FIELDS: Dict[str, List[Tuple[str, Dict[str, str], str]]] = {
    "（1）事業者情報": [
        ("商号又は名称", cell("商号又は名称", "t0.r0.c1"), "株式会社やまぶき惣菜（架空）"),
        ("代表者役職・氏名", cell("代表者役職・氏名", "t0.r2.c1"), "代表取締役　沢村 宏之（架空）"),
        ("本社所在地", cell("本社所在地", "t0.r3.c1"), "東京都大田区（架空の番地）"),
        ("業種", cell("業種", "t0.r4.c1"), "食品製造業（惣菜製造業）"),
        ("設立年月日", cell("設立年月日", "t0.r5.c1"), "2008年4月1日"),
        ("役員数／従業員数（常勤）", cell("役員数／従業員数（常勤）", "t0.r6.c1"), "2人／15人"),
        ("ホームページURL", cell("ホームページURL", "t0.r7.c1"), "https://www.example.com/"),
    ],
    "1. 事業者の概要（現状分析・経営課題）": [
        ("事業者名", cell("事業者名", f"{INNER}.r0.c1"), "株式会社やまぶき惣菜（架空）"),
        ("経営理念", cell("経営理念", f"{INNER}.r1.c1"), "毎日の食事を、病院・介護施設・家庭に安心して届ける（試しの文）。"),
        ("経営戦略", cell("経営戦略", f"{INNER}.r2.c1"), "細かい注文に応える品ぞろえを、少ない人手でも保つ（試しの文）。"),
        ("事業コンセプト", cell("事業コンセプト", f"{INNER}.r3.c1"), "近くの病院・介護施設とスーパーに、日替わりの惣菜を届ける（試しの文）。"),
        ("事業内容", cell("事業内容", f"{INNER}.r4.c1"),
         "①商品・サービスの具体的内容と価格：煮物・焼き物など1日約40品目（試しの文）。\n"
         "②競合に対する差別化・強み、セールスポイント：やわらか食などの細かい注文に応える（試しの文）。\n"
         "③事業者の製品やサービスが顧客に提供できている価値：施設の調理の手間を減らす（試しの文）。"),
        ("長期的なビジョン", cell("長期的なビジョン", f"{INNER}.r5.c1"), "5年後に冷凍惣菜を2本目の柱にする（試しの文）。"),
    ] + [
        (f"{row}（{year}）", cell(row, f"{INNER}.r{r}.{c}"), value)
        for row, r, values in (("売上金額", 7, ("186,400千円", "194,800千円", "201,600千円")),
                               ("売上総利益", 8, ("48,900千円", "51,300千円", "53,400千円")),
                               ("営業利益", 9, ("3,100千円", "3,900千円", "4,800千円")),
                               ("従業員数", 10, ("14人", "15人", "15人")))
        for (year, c), value in zip(YEARS, values)
    ],
}


def plan_items() -> List[dict]:
    return json.loads(PLAN.read_text(encoding="utf-8"))["項目"]


def make_env(tmp_path: Path, form: bytes) -> twm.Env:
    env = twm.Env(tmp_path, form)
    seido = json.loads(SEIKAI.read_text(encoding="utf-8"))
    (env.folder / twm.SEIDO_IN_FOLDER).write_text(json.dumps(seido, ensure_ascii=False, indent=2), encoding="utf-8")
    return env


def mapping() -> dict:
    pairs = [{"項目": it["名前"], "書き込む位置": it["書き込む位置"]} for it in plan_items()]
    for item, fields in FIELDS.items():
        pairs += [{"項目": item, "欄": name, "書き込む位置": pos} for name, pos, _text in fields]
    return {"様式": FORM_NAME, "対応": pairs}


def put(env: twm.Env, rel: str, data) -> str:
    target = env.folder / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    target.write_text(text, encoding="utf-8")
    return rel


def write_all(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    for it in plan_items():
        twm.ok(env.run("write", "--item", it["名前"], "--input", put(env, "記録/一時/書く文.txt", it["本文"])))
    for item, fields in FIELDS.items():
        for name, _pos, text in fields:
            done = twm.ok(env.run("write", "--item", item, "--field", name,
                                  "--input", put(env, "記録/一時/書く文.txt", text)))
            assert f"「{yw.field_label(item, name)}」を書きました" in done


@pytest.fixture
def env(tmp_path: Path, twm_form: bytes) -> twm.Env:
    return make_env(tmp_path, twm_form)


@pytest.fixture(scope="module")
def twm_form() -> bytes:
    if not twm.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません（公式資料を取ってから流す）")
    return twm.FORM.read_bytes()


# ---------------------------------------------------------------- すべての項目


def test_every_item_of_the_form_is_mapped() -> None:
    """正解の制度データの その1・2 の16項目すべてに、文の書き込む位置か、表の欄がある（このテストの対応づけで）。"""
    seido = json.loads(SEIKAI.read_text(encoding="utf-8"))
    form = [f for f in seido["様式"] if f["名前"] == FORM_NAME][0]
    names = [e["名前"] for e in form["項目"]]
    covered = {it["名前"] for it in plan_items()} | set(FIELDS)
    assert len(names) == 16 and set(names) == covered


@pytest.mark.slow
def test_write_all_items_and_fields_keeps_the_form(env: twm.Env, twm_form: bytes) -> None:
    write_all(env)
    seido = env.seido()
    form = [f for f in seido["様式"] if f["名前"] == FORM_NAME][0]
    entries = {e["名前"]: e for e in form["項目"]}
    for item, fields in FIELDS.items():
        assert [s["名前"] for s in entries[item]["欄"]] == [n for n, _p, _t in fields]
        assert "書き込む位置" not in entries[item]
    positions = yw.item_positions(form)
    assert len(positions) == 14 + sum(len(v) for v in FIELDS.values())

    blob = (env.folder / twm.APP).read_bytes()
    # 書いてよい範囲の外は、公式資料の様式から1か所も変わっていない
    assert yw.compare_docx(twm_form, blob, positions) == []
    # 書いた文が、その範囲にある（欄も）
    for it in plan_items():
        assert yw.item_text(blob, it["書き込む位置"]).replace("\n", "") == it["本文"].replace("\n", "")
    for item, fields in FIELDS.items():
        for _name, pos, text in fields:
            assert yw.item_text(blob, pos) == text
    # 空欄（まだ何も書いていない項目・欄）はない。説明の青字は書いた範囲から消えた
    findings = kakunin.word_findings(blob, twm.APP, seido)
    assert [f for f in findings if f.kind == kakunin.BLANK] == []
    _data, root = twm.doc_root(blob)
    blue_left = [p for p in yw._paragraphs(root) if yw.blue_state(p)]
    _data0, root0 = twm.doc_root(twm_form)
    assert len(blue_left) < len([p for p in yw._paragraphs(root0) if yw.blue_state(p)])


def test_field_needs_field_option_and_known_name(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    text = put(env, "記録/一時/書く文.txt", "株式会社やまぶき惣菜（架空）")
    r = twm.refused(env.run("write", "--item", "（1）事業者情報", "--input", text))
    assert "表の欄ごとに書きます。--field" in r
    r = twm.refused(env.run("write", "--item", "（1）事業者情報", "--field", "資本金", "--input", text))
    assert "欄「資本金」がありません" in r and "商号又は名称" in r
    assert not (env.folder / twm.APP).exists()


def test_map_refuses_a_field_whose_heading_is_not_in_the_row(env: twm.Env) -> None:
    bad = {"様式": FORM_NAME, "対応": [{"項目": "（1）事業者情報", "欄": "業種", "書き込む位置": cell("業種", "t0.r3.c1")}]}
    before = (env.folder / twm.SEIDO_IN_FOLDER).read_bytes()
    r = twm.refused(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", bad)))
    assert "（1）事業者情報：欄：業種" in r
    assert (env.folder / twm.SEIDO_IN_FOLDER).read_bytes() == before


def test_unwritten_field_is_counted_as_blank(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    twm.ok(env.run("write", "--item", "（1）事業者情報", "--field", "商号又は名称",
                   "--input", put(env, "記録/一時/書く文.txt", "株式会社やまぶき惣菜（架空）")))
    blob = (env.folder / twm.APP).read_bytes()
    blanks = {f.where for f in kakunin.word_findings(blob, twm.APP, env.seido()) if f.kind == kakunin.BLANK}
    assert yw.field_label("（1）事業者情報", "業種") in blanks
    assert yw.field_label("（1）事業者情報", "商号又は名称") not in blanks


# ---------------------------------------------------------------- PDF


def test_pdf_without_libreoffice_is_refused(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    twm.ok(env.run("write", "--item", "6. 補足事項", "--input", put(env, "記録/一時/書く文.txt", "試しの文。")))
    r = twm.refused(env.run("pdf", "--soffice", str(env.root / "ない" / "soffice")))
    assert "LibreOffice が見つからないので" in r and not (env.folder / PDF).exists()


def test_pdf_needs_the_word_file(env: twm.Env) -> None:
    r = twm.refused(env.run("pdf", "--soffice", "/bin/sh"))
    assert "まだありません" in r


@pytest.mark.slow
def test_pdf_is_a_copy_and_the_word_is_unchanged(env: twm.Env) -> None:
    soffice = __import__("zaimu_tool").soffice_or_skip()
    write_all(env)
    word = (env.folder / twm.APP).read_bytes()
    text = twm.ok(env.run("pdf", "--soffice", soffice))
    assert f"{PDF} に、その1・2.docx を PDF にした写しを作りました" in text
    data = (env.folder / PDF).read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 10_000
    assert (env.folder / twm.APP).read_bytes() == word  # 元の Word は変えない
    assert not (env.folder / ".hojokin" / "一時" / "PDF").exists()  # 作業の場所は残さない
    # 作り直しても1つのファイル（同じ名前で置き換える）
    twm.ok(env.run("pdf", "--soffice", soffice))
    assert sorted(p.name for p in (env.folder / PDF).parent.iterdir()) == ["その1・2.pdf"]
