"""T8-11 財務モデルとの一致（SPEC F8。TASKS B16。DESIGN 8.3「つながり」）。

合格ライン：計画書・様式・入力シートの数字を財務モデルと突き合わせる → 食い違い0件。

- 根拠対照表で出典が財務モデルを指す行（「財務モデル P-07」「財務モデル 合算 売上 5年目」「財務モデル.xlsx
  （労働生産性_5年目）」など）の数字を、数字の控え（記録/財務モデルの数字.json。zaimu_model.py が書く）の値と照らす。
  表に書いた桁で丸めた差を超えれば食い違い。
- 全項目が書けた計画書（D9）は、財務モデルを指す8行がすべて一致する。数字を変えると見つかる。参照の先がないとき、
  数字の控えがないときも見つかる。
- 計画書に書いた数字（本文）・様式（その3 のセル）・入力シート（欄）のどこに書いた数字も、根拠対照表の行で照らす
  （書いた場所はどこでもよい）。
"""

from __future__ import annotations

import copy

import kakunin_tool as kt
import plan_tool as pt
import pytest

from lib import shogo


@pytest.fixture
def env(tmp_path) -> kt.Env:
    return kt.Env(tmp_path)


def test_model_rows_of_the_full_plan_match(env: kt.Env) -> None:
    rows = pt.rows()
    model_rows = [r for r in rows if shogo.model_ref(r["出典"]) is not None]
    assert len(model_rows) >= 8
    pt.place(env, pt.form_or_skip())
    code, report = env.count()
    assert report["財務モデルとの食い違い"] == [] and code == 0


def test_changed_number_is_found(env: kt.Env) -> None:
    items = pt.items_with(pt.CORRECT, "4. 財務計画（資金調達と今後の数値計画）", "240,000千円", "250,000千円")
    rows = pt.rows()
    for r in rows:
        if r["記述"] == "240,000千円":
            r["記述"] = "250,000千円"
    pt.place(env, pt.form_or_skip(), items=items, evidence=rows)
    code, report = env.count()
    assert code == 3
    found = report["財務モデルとの食い違い"]
    assert [f["文字"] for f in found] == ["250,000千円"] and "財務モデルの「売上_5年目」" in found[0]["理由"]


def test_missing_reference_and_missing_numbers_are_found(env: kt.Env) -> None:
    rows = pt.rows()
    for r in rows:
        if r["記述"] == "192円":
            r["出典"] = "財務モデル.xlsx（単価_ない前提）"
    pt.place(env, pt.form_or_skip(), evidence=rows)
    _code, report = env.count()
    assert [f["文字"] for f in report["財務モデルとの食い違い"]] == ["192円"]
    (env.folder / pt.NUMBERS).unlink()
    code, report = env.count()
    assert code == 3 and all("数字の控え" in f["理由"] for f in report["財務モデルとの食い違い"])


# ---------------------------------------------------------------- 参照の書き方（部品）


@pytest.mark.parametrize("source, expected", [
    ("財務モデル P-01", 192.0),
    ("財務モデル.xlsx（単価_パック）", 192.0),
    ("財務モデル J-03", 41600000.0),
    ("財務モデル 合算 売上 基準年度", 201600000.0),
    ("財務モデル.xlsx（売上_基準年度）", 201600000.0),
    ("財務モデル 人数 常勤従業員数 5年目", 15.0),
])
def test_model_value_reference_forms(source: str, expected: float) -> None:
    numbers = pt.numbers()
    value, _unit = shogo.model_value(numbers, shogo.model_ref(source))
    assert value == pytest.approx(expected)


def test_rounding_follows_the_shown_digits() -> None:
    numbers = pt.numbers()
    va = numbers["中身"]["指標"]["付加価値額"][5]
    shown = f"{round(va / 1000):,}千円"
    rows = [{"記述": shown, "出典": "財務モデル 付加価値額 5年目"}]
    assert shogo.model_findings(rows, numbers) == []
    off = [{"記述": f"{round(va / 1000) + 2:,}千円", "出典": "財務モデル 付加価値額 5年目"}]
    assert len(shogo.model_findings(off, numbers)) == 1
    growth = numbers["中身"]["指標"]["労働生産性の伸び"][5]
    assert shogo.model_findings([{"記述": f"{growth:.2f}%", "出典": "財務モデル 労働生産性の伸び 5年目"}], numbers) == []
    rate = [{"記述": "4.1%", "出典": "財務モデル.xlsx（賃上げ率）"}]
    assert shogo.model_findings(rate, numbers) == []  # 率の前提（小数）は百分率で比べる
    assert shogo.model_findings(copy.deepcopy(rate), None)[0][2].startswith("財務モデルの数字の控え")


# ---------------------------------------------------------------- 様式（その3）と入力シートの数（B16 の直し）

FORM3 = kt.REPO_ROOT / "downloads" / "shoryokuka_ippan" / "yoshiki_business_plan_part3_ippan_08.xlsx"
S3 = "【指定様式】事業計画書（その3）"
B4 = "(別紙4）事業計画目標値算出シート"
SCREEN = "事業計画数値"
COLS = "FGHIJK"  # 別紙4 の基準年度〜5年目


def model_cells(numbers: dict) -> list:
    """数字の控えから取った、その3 の入力の欄の値（道具 cells に渡す形）。"""
    s = numbers["中身"]
    out = [{"シート": S3, "セル": "B14", "値": s["計画の年数"]},
           {"シート": S3, "セル": "I19", "値": round(s["指標"]["付加価値額の伸び"][5], 2)},
           {"シート": S3, "セル": "I25", "値": round(s["指標"]["労働生産性の伸び"][5], 2)},
           {"シート": S3, "セル": "I32", "値": round(s["指標"]["1人当たり給与の伸び"][5], 2)}]
    for y, col in enumerate(COLS):
        out.append({"シート": B4, "セル": f"{col}14", "値": round(s["合算"]["売上"][y])})
        out.append({"シート": B4, "セル": f"{col}26", "値": round(s["人数"]["常勤従業員数"][y])})
    return out


def sheet_values(numbers: dict) -> dict:
    sales = numbers["中身"]["合算"]["売上"]
    return {f"売上高（{y}年目計画）": round(sales[y]) for y in range(1, 6)}


def place_forms(env: kt.Env, cells: list, values: dict, evidence=None) -> None:
    if not FORM3.is_file():
        pytest.skip("downloads/ に省力化の様式（その3）がありません")
    from lib import input_sheet
    from lib import yoshiki_excel as ye

    pt.place(env, pt.form_or_skip(), evidence=evidence)
    blob, _summary = ye.write_cells(ye.first_copy(FORM3.read_bytes()), cells)
    env.put(f"{kt.APP_DIR}/その3.xlsx", blob)
    sheet = input_sheet.build(pt.seido_with_positions())
    for field, value in values.items():
        sheet, _s = input_sheet.write_value(sheet, field, value, SCREEN)
    env.put(kt.SHEET, sheet)


def model_places(report: dict) -> list:
    return [f["場所"] for f in report["財務モデルとの食い違い"]]


def test_form3_and_input_sheet_numbers_from_the_model_match(env: kt.Env) -> None:
    numbers = pt.numbers()
    place_forms(env, model_cells(numbers), sheet_values(numbers))
    _code, report = env.count()
    assert report["財務モデルとの食い違い"] == [] and report["食い違い"] == []


def test_shifted_form3_number_is_found(env: kt.Env) -> None:
    numbers = pt.numbers()
    cells = model_cells(numbers)
    for c in cells:
        if c["セル"] == "G14":
            c["値"] += 1_000_000  # 1年目の売上を財務モデルからずらす
    place_forms(env, cells, sheet_values(numbers))
    code, report = env.count()
    assert code == 3 and model_places(report) == [f"その3.xlsx／{B4}!G14"]


def test_shifted_input_sheet_number_is_found(env: kt.Env) -> None:
    numbers = pt.numbers()
    values = sheet_values(numbers)
    values["売上高（3年目計画）"] += 500_000
    place_forms(env, model_cells(numbers), values)
    code, report = env.count()
    assert code == 3 and model_places(report) == [f"{SCREEN}／売上高（3年目計画）"]


def test_example_value_left_in_the_form_is_found(env: kt.Env) -> None:
    """様式に初めから入っている例の値（最終年の年平均成長率 7.48 など）を書き直し忘れても見つかる。"""
    numbers = pt.numbers()
    cells = [c for c in model_cells(numbers) if c["セル"] != "I19"]
    place_forms(env, cells, sheet_values(numbers))
    _code, report = env.count()
    assert f"その3.xlsx／{S3}!I19" in model_places(report)


def test_cell_with_an_evidence_row_is_compared_with_the_row(env: kt.Env) -> None:
    numbers = pt.numbers()
    cells = model_cells(numbers)
    place = f"その3.xlsx／{B4}!F14"
    rows = pt.rows() + [{"記述": "201,600千円", "種類": "数字", "書いた場所": place, "出典": "財務モデル 合算 売上 基準年度"}]
    place_forms(env, cells, sheet_values(numbers), evidence=rows)
    _code, report = env.count()
    assert report["食い違い"] == [] and report["財務モデルとの食い違い"] == []
    for c in cells:
        if c["セル"] == "F14":
            c["値"] = 201_700_000  # セルだけ直して、根拠対照表を直していない
    place_forms(env, cells, sheet_values(numbers), evidence=rows)
    code, report = env.count()
    assert code == 3 and [f["文字"] for f in report["食い違い"]] == ["201,600千円"]


def test_cell_in_model_follows_the_shown_digits() -> None:
    values = [205632000.4, 5.8212, 0.041]
    assert shogo.cell_in_model("205632000", values) and not shogo.cell_in_model("205632002", values)
    assert shogo.cell_in_model("5.82", values) and not shogo.cell_in_model("5.84", values)
    assert shogo.cell_in_model("4.1", shogo.model_number_values(pt.numbers()))  # 率の前提（4.1%）は百分率でも当たる


@pytest.mark.parametrize("text, value", [
    ("-169,440円", -169440.0), ("−1,219,218円", -1219218.0), ("▲3,000円", -3000.0), ("△0.5%", -0.5),
    ("67,364円", 67364.0), ("営業利益は2年目に黒字", 2.0),
])
def test_shown_number_reads_negative_marks(text, value) -> None:
    """数の前の負の印（-・−・▲・△）を負の数として読む（11/6 のリハーサルで、営業利益の赤字の額を
    財務モデルと食い違うと誤って数えた）。"""
    from lib import shogo

    assert shogo.shown_number(text)[0] == value


def test_model_value_reads_beppyo4_rows() -> None:
    """数字の控えの「別紙4」（様式に写す、円に丸めた値）を、出典「財務モデル 別紙4 売上原価 1年目」の形で読み、
    セルの照合の数にも入れる（財務モデルの補助役の指摘。前は別紙4 の売上原価を「財務モデルとの食い違い」と数えるおそれがあった）。"""
    from lib import shogo

    numbers = {"中身": {"別紙4": {"年ごと": {"売上原価": [151333440.0, 160413128.0],
                                              "1人当たり給与支給総額の伸び": [None, 4.0],
                                              "常勤従業員数": [15.0, 15.0]}}}}
    assert shogo.model_value(numbers, "別紙4 売上原価 1年目") == (160413128.0, "円")
    assert shogo.model_value(numbers, "別紙4 1人当たり給与支給総額の伸び 1年目") == (4.0, "%")
    assert shogo.model_value(numbers, "別紙4 常勤従業員数 基準年度") == (15.0, "")
    assert shogo.model_value(numbers, "別紙4 1人当たり給与支給総額の伸び 基準年度") is None
    assert 151333440.0 in shogo.model_number_values(numbers)
