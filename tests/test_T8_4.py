"""T8-4 数値の要件の計算（SPEC F8）。方法「計算し直した結果と比べる」、合格ライン「一致し、要件の判定が正しい」。

TASKS M5：数値の要件（労働生産性、給与支給総額）を、制度データにある定義で判定する。判定は様式（別紙4）の数式と
同じ計算で行い、基準との差が0.01ポイント未満なら社長に知らせる（DESIGN 8.3。11/3 に作者が決めた）。

合格ラインの確かめ方
- 「一致し」：
  - 道具が作った財務モデル.xlsx を、テストの側で LibreOffice（計算し直しは「常に」）で計算し直し、補助金の指標と
    要件の判定の行が、道具の出した Python の計算と一致する（test_recalculated_values_match_python）。
    道具そのものも、数式のセルをすべて照らして「一致」と報告する。計算済みの値を持たないファイルなので、値が入れば
    計算し直しが本当に起きたと分かる。
  - 公式の様式（その3 の別紙4。downloads/ から写す）に同じ数字を入れて LibreOffice で計算し直すと、労働生産性・
    1人当たり給与支給総額とそれぞれの年平均成長率が、道具の値と一致する（test_same_as_official_form）。
- 「要件の判定が正しい」：
  - 基準の数（4.0%・3.5%）と、いつの値で比べるか（毎年・終了時点）は、制度データから読む。制度データの基準を
    変えると、プログラムを変えずに判定が変わる（test_requirements_are_read_from_seido、test_threshold_comes_from_seido）。
  - 伸びと判定が、テストの側で Decimal で計算し直した別紙4 の式の答えと合う（test_judgment_matches_hand_calculation）。
  - ちょうど基準の計画（800万円 → 3年後 8,869,743円）は、別紙4 と同じく 3.49%（満たさない）と判定し、境目として
    知らせる。基準との差が0.01ポイント未満の計画は、満たす・満たさないのどちらでも知らせ、0.01ポイント以上なら知らせない
    （test_boundary_*）。
"""

from __future__ import annotations

import re
import zipfile
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import zaimu_tool as zt

from lib import youken, zaimu

FORM = zt.REPO_ROOT / "downloads" / "shoryokuka_ippan" / "yoshiki_business_plan_part3_ippan_08.xlsx"


def build(spec: dict, seido: dict = None) -> zaimu.Book:
    reqs = youken.read_requirements(zt.load(zt.SEIDO) if seido is None else seido)
    return zaimu.build(zaimu.parse_spec(spec), reqs)


def judged(book: zaimu.Book) -> dict:
    return {r["名前"]: r for r in book.summary["判定した要件"]}


BASIC1 = "労働生産性の年平均成長率（基本要件①）"
BASIC2 = "1人当たり給与支給総額の年平均成長率（基本要件②）"
SPECIAL = "大幅賃上げ特例：1人当たり給与支給総額の年平均成長率"


# ---------------------------------------------------------------- 要件の定義は制度データから読む


def test_requirements_are_read_from_seido() -> None:
    reqs = {r.name: r for r in youken.read_requirements(zt.load(zt.SEIDO))}
    r1, r2, sp = reqs[BASIC1], reqs[BASIC2], reqs[SPECIAL]
    assert (r1.indicator, r1.threshold, r1.when, r1.optional) == (youken.PRODUCTIVITY, Decimal("4.0"), "毎年", False)
    assert (r2.indicator, r2.threshold, r2.when, r2.optional) == (youken.PAY, Decimal("3.5"), "終了時点", False)
    # 基本の数・上乗せの数・合計の数の3つが書かれた基準は、「合計で」の後の数と比べる。特例を選ぶときだけの要件
    assert (sp.indicator, sp.threshold, sp.when, sp.optional) == (youken.PAY, Decimal("6.0"), "終了時点", True)
    assert r1.source_text() == "要領8 p.10" and r2.source_text() == "要領8 p.11"
    # 財務モデルの数字で判定しないもの・基準の数がないものは、理由を付けて判定しない（推測しない）
    skipped = {name: r.skip_reason for name, r in reqs.items() if not r.judged}
    assert set(skipped) == {
        "事業計画期間の年数", "事業場内最低賃金（基本要件③）", "一般事業主行動計画の公表の対象となる従業員数（基本要件④）",
        "付加価値額の増加（その他の要件③）", "最低賃金引き上げ特例：地域別最低賃金近くで雇用している従業員の割合",
    }
    assert all(skipped.values())
    assert "%以上" in skipped["付加価値額の増加（その他の要件③）"]


def test_requirements_need_a_clear_threshold_and_time() -> None:
    """数が2つ以上で「合計で」もない、いつ比べるかが書いていない、基準が読み取れない、は判定しない。"""
    seido = {"数値の要件": [
        {"名前": "労働生産性の伸び", "基準": {"値": "毎年 3.0%以上、または 4.0%以上", "状態": "要確認", "出典": [], "根拠の文": "x"}},
        {"名前": "労働生産性の伸び2", "基準": {"値": "4.0%以上", "状態": "確認済み", "出典": [], "根拠の文": "x"}},
        {"名前": "1人当たり給与支給総額の伸び", "基準": {"値": None, "状態": "読み取れない", "理由": "x"}},
    ]}
    reqs = youken.read_requirements(seido)
    assert [r.judged for r in reqs] == [False, False, False]
    assert "2つ以上" in reqs[0].skip_reason
    assert "いつ" in reqs[1].skip_reason
    assert "読み取れて" in reqs[2].skip_reason
    with pytest.raises(youken.YoukenError):
        youken.read_requirements({"制度": {}})


def test_total_threshold_is_the_number_after_gokei_de() -> None:
    """数が2つ以上でも「合計で」があれば、その後の数と比べる（制度データの書き方に頼らず、分かれ道を確かめる）。"""
    seido = {"数値の要件": [
        {"名前": "（特例）1人当たり給与支給総額の伸び", "基準": {
            "値": "終了時点で、2.0%以上に 1.5%以上を足し、合計で 3.5%以上", "状態": "確認済み", "出典": [], "根拠の文": "x"}},
        {"名前": "1人当たり給与支給総額の伸び", "基準": {
            "値": "終了時点で、2.0%以上に 1.5%以上を足す", "状態": "確認済み", "出典": [], "根拠の文": "x"}},
    ]}
    total, without = youken.read_requirements(seido)
    assert (total.judged, total.threshold, total.when, total.optional) == (True, Decimal("3.5"), "終了時点", True)
    assert not without.judged and "2つ以上" in without.skip_reason


def test_threshold_comes_from_seido() -> None:
    """制度データの基準を書き換えると、プログラムを変えずに判定と Excel の式が変わる（全角の ％ や数字も読む）。"""
    spec = zt.load(zt.SPEC3)
    before = judged(build(spec))
    assert before[BASIC1]["判定"] == youken.MEETS  # 5年目 4.24%
    assert before[BASIC2]["判定"] == youken.MEETS  # 5年目 3.99%

    seido = zt.load(zt.SEIDO)
    for item in seido["数値の要件"]:
        if item["名前"] == BASIC1:
            item["基準"]["値"] = item["基準"]["値"].replace("4.0％", "４．５％")
        if item["名前"] == BASIC2:
            item["基準"]["値"] = item["基準"]["値"].replace("3.5%", "4.0%")
    book = build(spec, seido)
    after = judged(book)
    assert after[BASIC1]["基準"] == "4.5%以上"
    assert [p["判定"] for p in after[BASIC1]["年ごと"]] == [youken.MEETS] * 4 + [youken.FAILS]
    assert after[BASIC1]["判定"] == youken.FAILS
    assert after[BASIC2]["判定"] == youken.FAILS  # 3.99 < 4.0
    plan = book.sheets[1]
    formulas = [c.formula for c in plan.cells.values() if c.formula and ">=" in c.formula and "ISNUMBER" in c.formula]
    assert any(">=4.5," in f for f in formulas) and any(">=4.0," in f for f in formulas)
    assert not any(">=3.5," in f for f in formulas)


# ---------------------------------------------------------------- 別紙4 の式を、テストの側で Decimal で計算し直す


def d_rounddown(x: Decimal, digits: int = 2) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_DOWN)


def d_roundup(x: Decimal, digits: int = 2) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_UP)


def d_growth(value: Decimal, base: Decimal, n: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 40
        return ((value / base) ** (Decimal(1) / Decimal(n)) - 1) * 100


def hand_indicators(spec: dict) -> dict:
    """指定の3つの前提の計画（既存事業の給与だけが伸び、新事業は売上だけ）を、別紙4 の式で計算する。"""
    p = {a["名前"]: Decimal(str(a["値"])) for a in spec["前提"]}
    base = {k: Decimal(str(v["値"] if isinstance(v, dict) else v)) for k, v in spec["基準年度"].items()}
    n = spec["計画の年数"]
    workers = base["役員数"] + base["常勤従業員数"]
    out = {"労働生産性": [], "1人当たり給与": [], "労働生産性の伸び": [None], "1人当たり給与の伸び": [None]}
    for y in range(n + 1):
        sales = base["売上"] + (p["単価_新商品"] * p["数量_新商品"] if y >= 1 else 0)
        # 付加価値額 ＝ 営業利益＋人件費＋減価償却費 ＝ 売上 − 原材料費 − その他の経費
        va = sales - base["原材料費"] - base["その他の経費"]
        pay = base["給与支給総額"] * (1 + p["賃上げ率"]) ** y
        out["労働生産性"].append(d_rounddown(va / workers))
        out["1人当たり給与"].append(d_rounddown(pay / base["給与を受けた従業員数"]))
    for y in range(1, n + 1):
        out["労働生産性の伸び"].append(d_rounddown(d_growth(out["労働生産性"][y], out["労働生産性"][0], y)))
        g = d_growth(out["1人当たり給与"][y], out["1人当たり給与"][0], y)
        out["1人当たり給与の伸び"].append(d_rounddown(g) if g >= 0 else d_roundup(g))
    return out


@pytest.mark.parametrize("wage", [0.04, 0.02, 0.06])
def test_judgment_matches_hand_calculation(wage) -> None:
    """伸びと判定が、Decimal で計算し直した別紙4 の式の答えと合う（賃上げ率を変えて、満たす・満たさないの両方）。"""
    spec = zt.load(zt.SPEC3)
    for a in spec["前提"]:
        if a["名前"] == "賃上げ率":
            a["値"] = wage
    book = build(spec)
    hand = hand_indicators(spec)
    ind = book.summary["指標"]
    for key in ("労働生産性", "1人当たり給与"):
        assert [Decimal(str(v)) for v in ind[key]] == hand[key], key
    for key in ("労働生産性の伸び", "1人当たり給与の伸び"):
        assert [None] + [Decimal(str(v)) for v in ind[key][1:]] == hand[key], key
    res = judged(book)
    n = spec["計画の年数"]
    expect1 = [youken.MEETS if g >= Decimal("4.0") else youken.FAILS for g in hand["労働生産性の伸び"][1:]]
    assert [p["判定"] for p in res[BASIC1]["年ごと"]] == expect1
    assert [p["年"] for p in res[BASIC1]["年ごと"]] == list(range(1, n + 1))  # 毎年
    last = hand["1人当たり給与の伸び"][n]
    assert [p["年"] for p in res[BASIC2]["年ごと"]] == [n]  # 計画期間の終わり
    assert res[BASIC2]["判定"] == (youken.MEETS if last >= Decimal("3.5") else youken.FAILS)
    assert res[SPECIAL]["判定"] == (youken.MEETS if last >= Decimal("6.0") else youken.FAILS)
    # まとめは、特例を除いた要件で決める
    basic = [res[BASIC1]["判定"], res[BASIC2]["判定"]]
    assert book.summary["数値の要件（特例を除く）をすべて満たすか"] == (
        youken.MEETS if basic == [youken.MEETS] * 2 else youken.FAILS)
    if wage == 0.02:
        assert res[BASIC2]["判定"] == youken.FAILS
    if wage == 0.06:
        assert res[BASIC2]["判定"] == youken.MEETS


# ---------------------------------------------------------------- 境目（基準との差が0.01ポイント未満）


def test_boundary_exact_plan_is_349_and_is_flagged() -> None:
    """ちょうど 3.5% の計画は、別紙4 と同じく 3.49%（満たさない）。境目として知らせる（実験 E2b、DESIGN 8.3）。"""
    book = build(zt.boundary_spec())
    res = judged(book)[BASIC2]
    (year,) = res["年ごと"]
    assert year["年"] == 3
    assert year["伸び"] == 3.49
    assert year["判定"] == youken.FAILS and res["判定"] == youken.FAILS
    assert year["境目"] is True and res["境目"] is True
    plan = book.sheets[1]
    near_cells = [c for c in plan.cells.values() if c.formula and "ROUND(ABS(" in c.formula and "-3.5)" in c.formula]
    assert [c.py for c in near_cells] == [youken.NEAR]
    assert any(c.py == "あり（計画の数字を少し上げることを勧めます）" for c in plan.cells.values())


def one_year_pay(pay_after: int) -> dict:
    """1年の計画で、1人当たり給与が 1,000,000円 → pay_after 円になる。"""
    spec = zt.boundary_spec(years=1, pay_at_end=pay_after)
    spec["基準年度"]["給与支給総額"] = 1_000_000
    return spec


@pytest.mark.parametrize("pay_after, growth, verdict, near", [
    (1_035_000, 3.49, youken.FAILS, True),    # ちょうど 3.5%（浮動小数で 3.4999…）→ 切り捨てで 3.49
    (1_035_001, 3.50, youken.MEETS, True),    # 3.5001%：満たすが、差が0.01ポイント未満
    (1_035_050, 3.50, youken.MEETS, True),    # 3.505%
    (1_034_950, 3.49, youken.FAILS, True),    # 3.495%：満たさないが、差が0.01ポイント未満
    (1_034_850, 3.48, youken.FAILS, False),   # 3.485%：差が0.015ポイント
    (1_035_250, 3.52, youken.MEETS, False),   # 3.525%：差が0.025ポイント
    (1_035_200, 3.51, youken.MEETS, False),   # ちょうど 3.52%（浮動小数で 3.5199…）→ 3.51。差は0.01ポイントちょうどで知らせない
    (1_040_000, 4.00, youken.MEETS, False),
])
def test_boundary_cases(pay_after, growth, verdict, near) -> None:
    res = judged(build(one_year_pay(pay_after)))[BASIC2]
    (year,) = res["年ごと"]
    assert (year["伸び"], year["判定"], year["境目"]) == (growth, verdict, near)
    raw = year["切り捨てる前"]
    assert abs(raw - (pay_after / 1_000_000 - 1) * 100) < 1e-9


def test_near_check_is_strict_less_than() -> None:
    """差が0.01ポイントちょうどは知らせない（「未満」）。小数第9位で丸めてから比べる。"""
    t = Decimal("3.5")
    assert youken.is_near(3.5, t) and youken.is_near(3.491, t) and youken.is_near(3.5099999, t)
    assert not youken.is_near(3.49, t) and not youken.is_near(3.51, t) and not youken.is_near(3.48, t)
    assert not youken.is_near(None, t)


def test_rounding_like_spreadsheet() -> None:
    """切り捨ては有効数字15桁にそろえてから（0.29×100 が 28.999… でも 0.29 のまま）。0 に近いほうへ切り捨てる。"""
    assert youken.rounddown(0.29, 2) == 0.29
    assert youken.rounddown(-1.239, 2) == -1.23 and youken.roundup(-1.231, 2) == -1.24
    assert youken.rounddown(3.499999999999992, 2) == 3.49  # 実験 E2b の値（LibreOffice も 3.49）
    assert youken.rounddown(4.0000000000000036, 2) == 4.0
    assert youken.productivity(-10.005, 1) == -10.01 and youken.productivity(10.005, 1) == 10.0
    assert youken.growth_pay(90, 100, 1) == -10.0 and youken.growth_plain(0, 0, 1) is None


def test_compare_finds_a_different_value() -> None:
    """照らす部品は、値の違い・空のまま・文字の違いを見つける（否定の対照）。"""
    expected = {("計画（5年）", "C10"): 1.0, ("計画（5年）", "C11"): "満たす", ("計画（5年）", "C12"): 3.49}
    assert zaimu.compare(expected, dict(expected)) == []
    got = {("計画（5年）", "C10"): 1.0001, ("計画（5年）", "C11"): "満たさない"}
    wrong = zaimu.compare(expected, got)
    assert len(wrong) == 3 and any("C12" in w and "None" in w for w in wrong)


# ---------------------------------------------------------------- LibreOffice で計算し直して比べる（slow）


@pytest.mark.slow
def test_recalculated_values_match_python(tmp_path) -> None:
    soffice = zt.soffice_or_skip()
    env = zt.Env(tmp_path)
    folder = env.company()
    result = zt.ok_json(env.run(folder, "--json", soffice=soffice))
    check = result["計算し直し"]
    assert check["した"] is True and check["食い違い"] == [] and check["数式のセル"] > 200
    model = folder / zt.MODEL

    # 道具が置いたファイルは計算済みの値を持たない（値が入れば、計算し直しが起きたと分かる）
    raw = zt.dump_xlsx(model, data_only=True)
    plan_title = "計画（5年）"
    formulas = zt.dump_xlsx(model)["cells"][plan_title]
    assert all(raw["cells"][plan_title].get(ref) is None for ref, v in formulas.items() if str(v).startswith("="))

    # テストの側で計算し直し、指標と判定の行を、道具の出した値と比べる
    lo = zt.dump_xlsx(zt.recalc(model, tmp_path / "lo"), data_only=True)["cells"][plan_title]
    s = result["中身"]
    cols = "BCDEFG"
    labels = {
        "労働生産性": "労働生産性（付加価値額÷労働者数）",
        "労働生産性の伸び": "労働生産性の年平均成長率（％）",
        "1人当たり給与": "1人当たり給与支給総額（給与支給総額÷給与を受けた従業員数）",
        "1人当たり給与の伸び": "1人当たり給与支給総額の年平均成長率（％）",
        "付加価値額": "付加価値額（営業利益＋人件費＋減価償却費）",
    }
    for key, label in labels.items():
        r = zt.row_of(formulas, label)
        for y, col in enumerate(cols):
            expected = s["指標"][key][y]
            if expected is None:
                continue
            assert lo.get(f"{col}{r}") == pytest.approx(expected, rel=1e-12, abs=1e-9), (key, y)
    hand = hand_indicators(zt.load(zt.SPEC3))
    for key in ("労働生産性の伸び", "1人当たり給与の伸び"):
        r = zt.row_of(formulas, labels[key])
        assert [Decimal(str(lo[f"{col}{r}"])) for col in cols[1:]] == hand[key][1:]
    for name in (BASIC1, BASIC2):
        r = zt.row_of(formulas, f"要件：{name}")
        res = {x["名前"]: x for x in s["判定した要件"]}[name]
        for p in res["年ごと"]:
            assert lo[f"{cols[p['年']]}{r}"] == p["判定"]
        assert lo[f"H{r}"] == res["判定"] == youken.MEETS
    assert lo["B7"] == youken.MEETS
    # 月次の合計は、計画の1年目と同じ
    monthly = zt.dump_xlsx(zt.recalc(model, tmp_path / "lo2"), data_only=True)["cells"]["月次（1年目）"]
    for row in range(4, 10):
        assert monthly[f"N{row}"] == pytest.approx(monthly[f"O{row}"], abs=1e-6)


@pytest.mark.slow
def test_boundary_plan_recalculated(tmp_path) -> None:
    """ちょうど 3.5% の計画を、LibreOffice で計算し直しても 3.49（満たさない）と境目になる。道具の報告にも出る。"""
    soffice = zt.soffice_or_skip()
    env = zt.Env(tmp_path)
    folder = env.company(spec=zt.boundary_spec())
    r = env.run(folder, soffice=soffice)
    text = zt.ok(r)
    assert "すべて Python の計算と一致しました" in text
    assert "3年目 3.49%（境目）" in text
    assert "基準の 3.5%以上との差が0.01ポイント未満です" in text
    assert "計画の数字を少し上げることを勧めてください" in text
    formulas = zt.dump_xlsx(folder / zt.MODEL)["cells"]["計画（3年）"]
    lo = zt.dump_xlsx(zt.recalc(folder / zt.MODEL, tmp_path / "lo"), data_only=True)["cells"]["計画（3年）"]
    g = zt.row_of(formulas, "1人当たり給与支給総額の年平均成長率（％）")
    assert lo[f"E{g}"] == 3.49
    jr = zt.row_of(formulas, f"要件：{BASIC2}")
    assert lo[f"E{jr}"] == youken.FAILS and lo[f"E{jr + 1}"] == youken.NEAR and lo[f"F{jr + 1}"] == "境目あり"
    assert lo["B7"] == youken.FAILS and lo["D7"].startswith("あり")


@pytest.mark.slow
@pytest.mark.parametrize("pay_after", [1_035_000, 1_035_200, 1_034_950, 1_035_001])
def test_float_edge_plans_match_libreoffice(tmp_path, pay_after) -> None:
    """浮動小数の誤差で切り捨てが1つ下に落ちる計画（ちょうど 3.5%・3.52%）や、境目の計画でも、Python の計算と
    LibreOffice の計算し直しが、数式のセルのすべてで一致する（判定と境目の行を含む）。"""
    soffice = zt.soffice_or_skip()
    env = zt.Env(tmp_path)
    folder = env.company(spec=one_year_pay(pay_after))
    result = zt.ok_json(env.run(folder, "--json", soffice=soffice))
    assert result["計算し直し"]["した"] is True and result["計算し直し"]["食い違い"] == []
    expected = {(1_035_000, "伸び"): 3.49, (1_035_200, "伸び"): 3.51, (1_034_950, "伸び"): 3.49, (1_035_001, "伸び"): 3.50}
    res = {x["名前"]: x for x in result["中身"]["判定した要件"]}[BASIC2]
    assert res["年ごと"][0]["伸び"] == expected[(pay_after, "伸び")]


# ---------------------------------------------------------------- 公式の様式（別紙4）で計算し直して比べる（slow）

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def kubun4_part(parts: dict) -> tuple:
    """別紙4（事業計画目標値算出シート）のシートの名前と、部品の名前。"""
    wb = ET.fromstring(parts["xl/workbook.xml"])
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(parts["xl/_rels/workbook.xml.rels"]).iter(PREL + "Relationship")}
    for sheet in wb.iter(S + "sheet"):
        name = sheet.get("name")
        if "事業計画目標値算出シート" in name and "入力" not in name:
            target = rels[sheet.get(REL + "id")].lstrip("/")
            return name, target if target.startswith("xl/") else "xl/" + target
    raise AssertionError("別紙4 のシートが見つかりません")


def fill_form(src: Path, dst: Path, values: dict) -> str:
    """別紙4 の入力欄（もとは0の入ったセル）に数を入れた写しを作る。シートの名前を返す。"""
    with zipfile.ZipFile(src) as zin:
        parts = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        infos = zin.infolist()
    name, part = kubun4_part(parts)
    xml = parts[part].decode("utf-8")
    for ref, value in values.items():
        pattern = re.compile(r'<c r="' + ref + r'"((?:\s+[^>]*?)?)(?:/>|>.*?</c>)', re.DOTALL)
        found = pattern.search(xml)
        assert found, ref
        attrs = re.sub(r'\s+t="[^"]*"', "", found.group(1))
        xml = xml[:found.start()] + f'<c r="{ref}"{attrs}><v>{float(value)!r}</v></c>' + xml[found.end():]
    parts[part] = xml.encode("utf-8")
    with zipfile.ZipFile(dst, "w") as zout:
        for info in infos:
            zout.writestr(info, parts[info.filename])
    return name


def form_inputs(summary: dict) -> dict:
    """財務モデルの数字を、別紙4 の入力欄（F=基準年度、G〜K=1〜5年目）に割り当てる。"""
    t, people = summary["合算"], summary["人数"]
    n = summary["計画の年数"]
    values = {}
    for y, col in enumerate("FGHIJK"):
        k = min(y, n)  # 計画が5年より短いときは、最後の年を繰り返す（比べるのは計画の年だけ）
        costs = t["原材料費"][k] + t["人件費"][k] + t["減価償却費"][k] + t["その他の経費"][k]
        values.update({
            f"{col}14": t["売上"][k], f"{col}15": costs, f"{col}17": 0, f"{col}19": t["人件費"][k],
            f"{col}21": t["減価償却費"][k], f"{col}25": people["役員数"][k], f"{col}26": people["常勤従業員数"][k],
        })
        if y:
            values.update({f"{col}22": 0, f"{col}33": t["給与支給総額"][k], f"{col}34": people["給与を受けた従業員数"][k]})
    values.update({"E33": t["給与支給総額"][0], "E34": people["給与を受けた従業員数"][0]})
    return values


@pytest.mark.slow
@pytest.mark.parametrize("case", ["前提3つ", "境目"])
def test_same_as_official_form(tmp_path, case) -> None:
    """公式の別紙4 に同じ数字を入れて計算し直すと、労働生産性・1人当たり給与と伸びが、道具の値と同じになる。"""
    if not FORM.is_file():
        pytest.skip("downloads/ に省力化の様式その3 がありません（公式資料を取ってから流す）")
    zt.soffice_or_skip()
    spec = zt.load(zt.SPEC3) if case == "前提3つ" else zt.boundary_spec()
    book = build(spec)
    s = book.summary
    filled = tmp_path / "form.xlsx"
    sheet = fill_form(FORM, filled, form_inputs(s))
    lo = zt.dump_xlsx(zt.recalc(filled, tmp_path / "lo"), data_only=True)["cells"][sheet]
    n = s["計画の年数"]
    ind = s["指標"]
    for y, col in enumerate("FGHIJK"[: n + 1]):
        assert lo[f"{col}23"] == pytest.approx(ind["付加価値額"][y], rel=1e-12), y
        assert lo[f"{col}27"] == ind["労働生産性"][y], y
        assert lo[f"{col}35"] == ind["1人当たり給与"][y], y
        if y:
            assert lo[f"{col}24"] == ind["付加価値額の伸び"][y], y
            assert lo[f"{col}29"] == ind["労働生産性の伸び"][y], y
            assert lo[f"{col}40"] == ind["1人当たり給与の伸び"][y], y
    if case == "境目":
        assert lo["I40"] == 3.49 == ind["1人当たり給与の伸び"][3]
        assert judged(book)[BASIC2]["判定"] == youken.FAILS


def test_form_inputs_cover_the_kubun4_rows() -> None:
    """別紙4 に入れる数の割り当て（遅いテストの準備）が、財務モデルの合算と人数から作られる。"""
    s = build(zt.load(zt.SPEC3)).summary
    values = form_inputs(s)
    assert values["F14"] == 120_000_000 and values["G14"] == 132_000_000
    assert values["E33"] == 30_000_000 and values["F25"] == 2 and values["F26"] == 8
    assert values["G15"] == pytest.approx(48_000_000 + s["合算"]["人件費"][1] + 3_000_000 + 20_000_000)
    assert values["G33"] == pytest.approx(30_000_000 * 1.04) and values["G34"] == 8
