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


# ---------------------------------------------------------------- スケジュールの表（表ごと作る。11/7 の作者の指摘）

SCHEDULE_ITEM = "5. 事業の実施体制とスケジュール"
SCHEDULE_HEADING = "≪事業計画期間にかかるスケジュール≫"
SCHEDULE_TABLE = "t5.r0.c0.t0"
SCHEDULE = {
    "1年目の始め": "2028-04",
    "補助事業実施期間": {"始め": "2027-07", "終わり": "2028-03"},
    "凡例": "●：実施　◎：本番の開始　○：準備・継続",
    "行": [
        {"工程": "1. 要件定義・設計", "作業": "業務の分析と設計", "始め": "2027-07", "終わり": "2027-10"},
        {"工程": "2. 開発", "作業": "機能の開発", "始め": "2027-11", "終わり": "2028-01"},
        {"工程": "2. 開発", "作業": "過去の見積の取り込み", "期間": [{"始め": "2027-11", "終わり": "2027-11"},
                                                         {"始め": "2028-01", "終わり": "2028-01"}]},
        {"工程": "3. 本番", "作業": "使い始め", "始め": "2028-03", "終わり": "2028-03", "印": "◎"},
        {"工程": "4. 運用", "作業": "効果の確かめ", "始め": "2028-04", "終わり": "2033-03", "印": "○"},
    ],
}


def schedule_field(place: str = SCHEDULE_TABLE) -> dict:
    return {"項目": SCHEDULE_ITEM, "欄": "スケジュールの表",
            "書き込む位置": {"見出し": SCHEDULE_HEADING, "場所": place, "範囲": "表"}}


def test_schedule_marks_the_months_and_keeps_the_rest_of_the_form(env: twm.Env, twm_form: bytes) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    spec = put(env, "記録/一時/スケジュール.json", SCHEDULE)
    # 表の書き込む位置がなければ断る（読み取り役に、表を範囲「表」の欄として対応づけさせる）
    r = twm.refused(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", spec))
    assert "スケジュールの表の書き込む位置が見つかりません" in r and not (env.folder / twm.APP).exists()
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": [schedule_field()]})))
    out = twm.ok(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", spec))
    assert "スケジュールの表を作りました（5行。月の欄は 2027年3月〜2028年3月" in out
    blob = (env.folder / twm.APP).read_bytes()
    seido = env.seido()
    form = [f for f in seido["様式"] if f["名前"] == FORM_NAME][0]
    assert yw.compare_docx(twm_form, blob, yw.item_positions(form)) == []
    pos = schedule_field()["書き込む位置"]
    text = yw.item_text(blob, pos)
    assert "1. 要件定義・設計｜業務の分析と設計：2027年7月〜2027年10月●" in text
    assert "2. 開発｜過去の見積の取り込み：2027年11月●、2028年1月●" in text
    assert "3. 本番｜使い始め：2028年3月◎" in text
    assert "4. 運用｜効果の確かめ：事業計画1年目（第1四半期）〜事業計画5年目（第4四半期）○" in text
    _data, root = twm.doc_root(blob)
    tbl = yw.node_at(yw.body_of(root), SCHEDULE_TABLE)
    assert len(tbl.findall(yw.W, "tr")) == 3 + 5  # 見出しの3行と工程の5行（記載例の行は残さない）
    assert not any(yw.blue_state(p) for p in tbl.iter() if p.is_(yw.W, "p"))
    # 空欄に数えず、照合には工程と作業の名前だけを渡す（列の見出しから作った日付は照らさない）
    assert yw.field_label(SCHEDULE_ITEM, "スケジュールの表") not in {
        f.where for f in kakunin.word_findings(blob, twm.APP, seido) if f.kind == kakunin.BLANK}
    texts, _cells = kakunin._texts_of(blob, twm.APP, ".docx", seido)
    named = texts[yw.field_label(SCHEDULE_ITEM, "スケジュールの表")]
    assert "業務の分析と設計" in named and "2027年" not in named


def test_schedule_refuses_dates_in_names_and_more_than_one_page(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": [schedule_field()]})))
    dated = dict(SCHEDULE, 行=[{"工程": "1. 設計", "作業": "設計（2027年7月〜10月）", "始め": "2027-07", "終わり": "2027-10"}])
    r = twm.refused(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", put(env, "記録/一時/スケジュール.json", dated)))
    assert "名前に日付を書かず" in r
    many = dict(SCHEDULE, 行=[{"工程": f"{k}. 工程", "作業": "細かい作業の名前をとても長く書いた行で、二行か三行に折り返すもの",
                              "始め": "2027-07", "終わり": "2027-08"} for k in range(40)])
    r = twm.refused(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", put(env, "記録/一時/スケジュール.json", many)))
    assert "1枚に収まりません" in r
    outside = dict(SCHEDULE, 行=[{"工程": "0. 準備", "作業": "困りごとの話し合い", "始め": "2026-09", "終わり": "2026-09"}])
    r = twm.refused(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", put(env, "記録/一時/スケジュール.json", outside)))
    assert "表の前の準備は、本文に書いてください" in r
    assert not (env.folder / twm.APP).exists()


def test_schedule_merges_cell_fields_into_one_table_field(env: twm.Env, twm_form: bytes) -> None:
    """表のセルを欄ごとに対応づけていた制度データ（11/7 のデモのフォルダ）は、表の欄1つにまとめ直す。
    守りの hook が使う比べ方でも、作り直してなくなったセルの欄は、表の範囲が覆う。"""
    cells = [{"項目": SCHEDULE_ITEM, "欄": f"スケジュール{k}行目（2列目）",
              "書き込む位置": cell(SCHEDULE_HEADING, f"{SCHEDULE_TABLE}.r{k + 2}.c1")} for k in range(1, 19)]
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": cells})))
    before_positions = yw.item_positions([f for f in env.seido()["様式"] if f["名前"] == FORM_NAME][0])
    out = twm.ok(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", put(env, "記録/一時/スケジュール.json", SCHEDULE)))
    assert "制度データの欄を「スケジュールの表」（範囲「表」）1つにまとめました" in out
    entry = [e for f in env.seido()["様式"] if f["名前"] == FORM_NAME for e in f["項目"] if e["名前"] == SCHEDULE_ITEM][0]
    assert [s["名前"] for s in entry["欄"]] == ["スケジュールの表"]
    blob = (env.folder / twm.APP).read_bytes()
    table = (yw.field_label(SCHEDULE_ITEM, "スケジュールの表"), schedule_field()["書き込む位置"])
    assert yw.compare_docx(twm_form, blob, before_positions + [table]) == []
    # 表の範囲がなければ、作り直した表は範囲の外の変化として見つかる
    assert yw.compare_docx(twm_form, blob, before_positions) != []


def test_table_range_still_guards_the_table_settings_and_the_outside(env: twm.Env, twm_form: bytes) -> None:
    """範囲「表」でも、表の設定（tblPr）・列の数・表の前の見出しが変われば、範囲の外の変化として見つかる。
    行と列の幅、セルの中身だけを書いてよいとする（spec-check の指摘。11/7）。"""
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": [schedule_field()]})))
    twm.ok(env.run("schedule", "--item", SCHEDULE_ITEM, "--input", put(env, "記録/一時/スケジュール.json", SCHEDULE)))
    blob = (env.folder / twm.APP).read_bytes()
    form = [f for f in env.seido()["様式"] if f["名前"] == FORM_NAME][0]
    positions = yw.item_positions(form)
    data = yw.read_parts(blob)[1][yw.DOC]
    start = data.index(b"<w:tblGrid>", data.index("≪事業計画期間にかかるスケジュール≫".encode("utf-8")))
    tblpr_end = data.rindex(b"</w:tblPr>", 0, start)

    def changed(new_data: bytes) -> list:
        return yw.compare_docx(blob, yw.rebuild_zip(blob, {yw.DOC: new_data}), positions)

    assert changed(data[:tblpr_end] + b'<w:jc w:val="right"/>' + data[tblpr_end:])  # 表の設定
    assert changed(data[:start + 11] + b'<w:gridCol w:w="300"/>' + data[start + 11:])  # 列の数
    heading = "≪事業計画期間にかかるスケジュール≫".encode("utf-8")
    assert changed(data.replace(heading, "≪スケジュール≫".encode("utf-8"), 1))  # 表の前の見出し
    assert changed(data.replace("補助事業のスケジュール".encode("utf-8"), "スケジュール".encode("utf-8"), 1))  # 外のセル
    # 表の中の文字（印）だけを変えたものは、範囲の中
    assert changed(data.replace("◎".encode("utf-8"), "●".encode("utf-8"), 1)) == []
    # 列の幅の和は、様式の表のまま（本文の幅からはみ出さない。T8-3）
    def grid_sum(doc: bytes) -> int:
        s = doc.index(b"<w:tblGrid>", doc.index(heading))
        return sum(int(x) for x in __import__("re").findall(rb'<w:gridCol w:w="([0-9]+)"', doc[s:doc.index(b"</w:tblGrid>", s)]))
    assert grid_sum(data) == grid_sum(yw.read_parts(twm_form)[1][yw.DOC])


def test_schedule_is_blank_until_made_and_other_tables_cannot_be_a_table_range(env: twm.Env) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": [schedule_field()]})))
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    twm.ok(env.run("write", "--item", "6. 補足事項", "--input", put(env, "記録/一時/書く文.txt", "試しの文。")))
    blob = (env.folder / twm.APP).read_bytes()
    blanks = {f.where for f in kakunin.word_findings(blob, twm.APP, env.seido()) if f.kind == kakunin.BLANK}
    assert yw.field_label(SCHEDULE_ITEM, "スケジュールの表") in blanks  # 見出しの行の文字だけでは書いたことにしない
    other = {"項目": "（1）事業者情報", "欄": "表", "書き込む位置": {"見出し": "（１）事業者情報", "場所": "t0", "範囲": "表"}}
    r = twm.refused(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": [other]})))
    assert "スケジュールの表ではありません" in r


def test_layout_copy_changes_only_fixed_line_heights_and_floating_tables(twm_form: bytes) -> None:
    """PDF の写しの整え：行の高さの固定（exact）と浮いた表（tblpPr）だけを変え、ほかの部品はバイトのまま。"""
    copy = yw.layout_copy(twm_form)
    before, after = yw.read_parts(twm_form)[1], yw.read_parts(copy)[1]
    assert set(before) == set(after)
    assert all(before[n] == after[n] for n in before if n != yw.DOC)
    doc_b, doc_a = before[yw.DOC], after[yw.DOC]
    assert b"tblpPr" in doc_b and b"tblpPr" not in doc_a
    assert b'lineRule="exact"' in doc_b and b'lineRule="exact"' not in doc_a and b'lineRule="atLeast"' not in doc_a
    assert b'w:type="lines"' in doc_b and b'w:type="lines"' not in doc_a  # 行のグリッドにそろえる設定を外す
    # 変わるのは、浮いた表・行の間隔・行のグリッドだけ（文字はそのまま）
    from lib import xml_spans
    assert yw.text_of(xml_spans.parse(doc_a)) == yw.text_of(xml_spans.parse(doc_b))
    import re as _re
    strip = lambda d: _re.sub(rb"<w:tblpPr\b[^>]*/>|<w:spacing\b[^>]*/>|<w:docGrid\b[^>]*/>", b"", d)  # noqa: E731
    assert strip(doc_a) == strip(doc_b)


# ---------------------------------------------------------------- 箇条書き・本文の表・揃え・説明の青字・空の欄（11/7 の作者の指摘）

BULLET_TEXT = (
    "見積に時間がかかる理由は、次の3つです。\n"
    "・図面を読んで形と寸法を拾うのに、1件約20分かかる\n"
    "・材料と外注の値段を調べるのに、1件約15分かかる\n"
    "【表：導入の前と後】\n"
    "|作業|導入の前|導入の後|\n"
    "|---|---|---|\n"
    "|見積1件|75分|15分|\n"
    "|工程の組み直し|90分|20分|\n"
    "表のとおり、見積の時間が大きく減ります。"
)


def test_bullets_tables_and_outside_blue_text(env: twm.Env, twm_form: bytes) -> None:
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", mapping())))
    twm.ok(env.run("write", "--item", "1-2 経営課題", "--input", put(env, "記録/一時/書く文.txt", BULLET_TEXT)))
    blob = (env.folder / twm.APP).read_bytes()
    parts = yw.read_parts(blob)[1]
    # 箇条書きは Word の箇条書き（行頭文字「・」の定義を numbering.xml に足し、段落は番号で指す）
    assert f'w:abstractNumId="{yw.BULLET_NUM_ID}"'.encode() in parts[yw.NUMBERING]
    data, root = twm.doc_root(blob)
    pos = [it["書き込む位置"] for it in plan_items() if it["名前"] == "1-2 経営課題"][0]
    rng = yw.resolve(root, pos)
    numbered = [p for p in yw.range_paragraphs(rng) if any(n.is_(yw.W, "numId") and n.attr(yw.W, "val") == yw.BULLET_NUM_ID
                                                          for n in p.iter())]
    assert [yw.text_of(p) for p in numbered] == ["図面を読んで形と寸法を拾うのに、1件約20分かかる",
                                                 "材料と外注の値段を調べるのに、1件約15分かかる"]
    # 「|」の行は、範囲の中の表になる（区切りの行は表にしない）。表の後の文も範囲に入る
    tables = [n for n in rng.nodes if n.is_(yw.W, "tbl")]
    assert len(tables) == 1 and len(tables[0].findall(yw.W, "tr")) == 3
    # 表は欄の幅に収める（欄の幅が割合のセルで、文書の最後の節〈A4 横〉の幅で作って、右にはみ出した。11/7）
    tbl_w = int(tables[0].find(yw.W, "tblPr").find(yw.W, "tblW").attr(yw.W, "w"))
    grid_w = sum(int(g.attr(yw.W, "w")) for g in tables[0].find(yw.W, "tblGrid").findall(yw.W, "gridCol"))
    assert tbl_w == grid_w <= 11906 - 1440  # A4 縦の本文の幅（左右の余白 720）より狭い
    text = yw.item_text(blob, pos)
    assert "導入の前と後" in text and "見積1件" in text and "15分" in text and text.endswith("見積の時間が大きく減ります。")
    # 範囲の外の説明の青字（題の「記載例」など）も消え、青字でない所は変わらない
    assert "記載例" not in "".join(yw.text_of(p) for p in yw._paragraphs(root))
    form = [f for f in env.seido()["様式"] if f["名前"] == FORM_NAME][0]
    assert yw.compare_docx(twm_form, blob, yw.item_positions(form)) == []
    # 書き直すと、前の表と箇条書きは置き換わる（表は1つのまま）
    twm.ok(env.run("write", "--item", "1-2 経営課題", "--input", put(env, "記録/一時/書く文.txt", BULLET_TEXT)))
    blob2 = (env.folder / twm.APP).read_bytes()
    _d2, root2 = twm.doc_root(blob2)
    assert len([n for n in yw.resolve(root2, pos).nodes if n.is_(yw.W, "tbl")]) == 1
    assert yw.compare_docx(blob, blob2, yw.item_positions(form)) == []


def test_long_lines_in_a_centered_cell_are_justified() -> None:
    """中央揃えの欄（SWOT の表など）に書いた長い行は両端揃えにし、短い見出しは中央のまま。箇条書きは左揃え。"""
    from lib import xml_spans

    data = (f'<w:document xmlns:w="{yw.W}"><w:body><w:tbl><w:tr><w:tc><w:p><w:pPr><w:spacing w:line="260" '
            'w:lineRule="exact"/><w:jc w:val="center"/></w:pPr></w:p></w:tc></w:tr></w:tbl></w:body></w:document>').encode()
    root = xml_spans.parse(data)
    tc = next(n for n in root.iter() if n.is_(yw.W, "tc"))
    rng = yw.Range(tc, 0, len(tc.children), "強み")
    out = yw.new_paragraphs(data, rng, "＜強み＞\n" + "難しい形の部品を1個から短い納期で作れる。" * 2 + "\n・短い箇条", bullets=True)
    paras = [p for p in xml_spans.parse(f'<x xmlns:w="{yw.W}">'.encode() + out + b"</x>").iter() if p.is_(yw.W, "p")]
    jcs = [next((n.attr(yw.W, "val") for n in p.iter() if n.is_(yw.W, "jc")), "") for p in paras]
    assert jcs == ["center", "both", "left"]
    assert b'lineRule="exact"' not in out  # 書いた段落は、行の高さを固定しない
    assert yw.BULLET_NUM_ID.encode() in out


def test_empty_form_boxes_are_blank_and_map_can_add_an_item(env: twm.Env) -> None:
    """どの項目にも対応づけていない空の欄（事業者情報・事業計画名・概要）は空欄に数える。
    制度データにない様式の欄は、"足す": true で項目として足せる。"""
    plan = [{"項目": it["名前"], "書き込む位置": it["書き込む位置"]} for it in plan_items()
            if not it["名前"].startswith(("（2）", "（3）"))]
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", {"様式": FORM_NAME, "対応": plan})))
    twm.ok(env.run("write", "--item", "6. 補足事項", "--input", put(env, "記録/一時/書く文.txt", "試しの文。")))
    blob = (env.folder / twm.APP).read_bytes()
    boxes = kakunin.empty_form_boxes(blob, twm.APP, env.seido())
    assert any(b.startswith("（２）事業計画名") for b in boxes) and any(b.startswith("（３）事業計画の概要") for b in boxes)
    assert "商号又は名称" in boxes
    new = {"様式": FORM_NAME, "対応": [{"項目": "事業計画名（様式の欄）", "足す": True,
                                       "書き込む位置": cell("（２）事業計画名（３０字程度）", "t1.r0.c0")}]}
    r = twm.refused(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", dict(new, 対応=[dict(new["対応"][0], 足す=False)]))))
    assert "項目「事業計画名（様式の欄）」がありません" in r
    twm.ok(env.run("map", "--input", put(env, "記録/一時/様式の対応.json", new)))
    twm.ok(env.run("write", "--item", "事業計画名（様式の欄）", "--input", put(env, "記録/一時/書く文.txt", "見積と工程の仕組みとAIで返事を速くする")))
    blob = (env.folder / twm.APP).read_bytes()
    boxes = kakunin.empty_form_boxes(blob, twm.APP, env.seido())
    assert not any(b.startswith("（２）事業計画名") for b in boxes)


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
