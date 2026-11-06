"""T8-10 財務モデルの計算（SPEC F8、DESIGN 8.3・8.1。TASKS B13）。

合格ライン：財務モデルを作り、Excel の数式の結果と、計算し直した結果を比べて一致する。合算が既存事業と新事業の
和になり、月次の合計が1年目と合う。数量を2割減らした場合の要件の判定も一致する。

- デモの会社（架空）に近い指定（前提14個、既存事業と新事業2つ、月次の波、省力化の指標）で作る。
- LibreOffice で計算し直すテストは、テストの側でも計算し直し（tests/zaimu_tool.py の recalc）、道具の確かめに頼らない。
  LibreOffice がなければ飛ばす。
- 数量を2割減らした場合は、道具が「まとめ」に置いた判定と、数量の前提を0.8倍にした指定で作り直して LibreOffice で
  計算し直した判定（まとめの B7）が一致するかを見る。
- 省力化指数と投資回収期間は、様式その3（別紙1・別紙3）の数式と同じ計算か（手で計算した値と、応募手引8 p.59 の例）。
- 波3 の気づき #7：基準年度の給与などは、決算書の科目を足し上げる道具（kijun）で出す。足し上げた営業利益が決算書と
  合わなければ断る。
"""

from __future__ import annotations

import copy
import json

import pytest
import zaimu_tool as zt

from lib import youken, zaimu

DEMO = zt.DATA / "指定_デモの会社.json"
PLAN = "計画（5年）"
MONTHLY = "月次（1年目）"
COLS = "BCDEFG"  # 基準年度〜5年目
ROW_KEYS = ("売上", "原材料費", "給与支給総額", "その他の人件費", "減価償却費", "その他の経費")


def demo() -> dict:
    return zt.load(DEMO)


def scaled(spec: dict, factor: float) -> dict:
    out = copy.deepcopy(spec)
    for a in out["前提"]:
        if a["名前"].startswith("数量_"):
            a["値"] = a["値"] * factor
    return out


def book_of(spec: dict) -> zaimu.Book:
    reqs = youken.read_requirements(zt.load(zt.SEIDO))
    return zaimu.build(zaimu.parse_spec(spec), reqs)


# ---------------------------------------------------------------- Python の計算（LibreOffice なし）


def test_totals_are_sums_and_monthly_matches_first_year() -> None:
    s = book_of(demo()).summary
    assert s["シート"] == ["前提", PLAN, MONTHLY] and s["前提の数"] == 14
    for key in ROW_KEYS + ("人件費", "営業利益"):
        for y in range(6):
            parts = sum(s["事業ごと"][b][key][y] for b in ("既存事業", "省力化の増産", "冷凍惣菜"))
            assert s["合算"][key][y] == pytest.approx(parts, rel=1e-12)
    # 冷凍惣菜は2年目から（1年目は0）
    assert s["事業ごと"]["冷凍惣菜"]["売上"][1] == 0 and s["事業ごと"]["冷凍惣菜"]["売上"][2] == 450 * 20000
    for key, v in s["月次の合計と1年目"].items():
        assert v["合計"] == pytest.approx(v["1年目"], rel=1e-12), key
    # 月次の波：売上は重みで分け、12月（重み1.2）は2月（0.95）より多い
    sales = s["月次"]["売上"]
    weights = demo()["月次の波"]
    assert sales[11] == pytest.approx(s["合算"]["売上"][1] * 1.2 / sum(weights))
    assert sales[11] > sales[1]


def test_low_case_is_the_same_as_building_with_80_percent() -> None:
    s = book_of(demo()).summary
    low = s["数量が2割少ない場合"]
    assert low["数量の前提"] == ["数量_増産パック", "数量_冷凍惣菜"] and low["割合"] == 0.8
    again = book_of(scaled(demo(), 0.8)).summary
    assert low["判定"] == again["数値の要件（特例を除く）をすべて満たすか"]
    assert [r["判定"] for r in low["要件ごと"]] == [r["判定"] for r in again["判定した要件"]]
    # 数量が減ると売上が減る（数量の前提に当てている）
    assert again["合算"]["売上"][5] < s["合算"]["売上"][5]


def test_low_case_can_fail_while_plan_meets() -> None:
    """数量に頼る計画では、計画どおりなら満たし、2割少ないと満たさないことがある（それを社長に伝えるための行）。"""
    spec = zt.load(zt.SPEC3)
    spec["前提"][1]["値"] = 30000  # 数量_新商品
    spec["既存事業"] = {"給与支給総額": "基準_給与支給総額*(1+賃上げ率)^年", "原材料費": "基準_原材料費"}
    plan = book_of(spec).summary
    assert plan["数値の要件（特例を除く）をすべて満たすか"] == youken.MEETS
    low = plan["数量が2割少ない場合"]
    again = book_of(scaled(spec, 0.8)).summary
    assert low["判定"] == again["数値の要件（特例を除く）をすべて満たすか"]
    lows = {r["名前"]: r for r in low["要件ごと"]}
    assert lows, low


def test_without_quantity_the_low_case_is_not_judged() -> None:
    spec = zt.load(zt.SPEC3)
    spec["前提"][1]["名前"] = "販売数_新商品"
    spec["新事業"][0]["売上"] = "単価_新商品*販売数_新商品"
    book = book_of(spec)
    assert book.summary["数量が2割少ない場合"] is None
    plan = {s.title: s for s in book.sheets}[PLAN]
    assert plan.cells["A8"].value == zaimu.LOW_LABEL and plan.cells["B8"].value == zaimu.NO_QUANTITY


def test_investment_effect_matches_the_totals() -> None:
    """投資の効果の見え方は、計画の合算から出す（営業利益、営業利益率、増加、浮く時間の人件費相当額）。"""
    s = book_of(demo()).summary
    eff = s["投資の効果の見え方"]
    profit, sales, dep = s["合算"]["営業利益"], s["合算"]["売上"], s["合算"]["減価償却費"]
    assert eff["営業利益"] == pytest.approx(profit)
    assert eff["営業利益率"] == pytest.approx([p / v for p, v in zip(profit, sales)])
    assert eff["営業利益の増加（基準年度から最終年）"] == pytest.approx(profit[5] - profit[0])
    assert eff["減価償却費の増加（基準年度から最終年）"] == pytest.approx(dep[5] - dep[0])
    sh = s["省力化"]
    assert eff["省力化で浮く時間の人件費相当額（1年あたり）"] == pytest.approx(
        sh["削減工数"] * sh["人件費単価"] * sh["年間稼働日数"])


def _effect_spec(sales_growth: float, effect: bool) -> dict:
    """リハーサルと同じ形：売上は伸び率だけ、人件費は賃上げだけ、新しい設備の減価償却費が乗る。
    effect が真なら、省力化で浮いた時間で増産し（数量）、計量の自動化で原材料費の割合が下がる。"""
    spec = demo()
    spec.pop("新事業", None)
    spec["前提"] = [a for a in spec["前提"] if not a["名前"].startswith(("数量_", "単価_"))][:6]
    names = {a["名前"] for a in spec["前提"]}
    assert "賃上げ率" in names
    add = [
        {"名前": "売上の伸び率", "値": sales_growth, "単位": "%", "説明": "試し", "根拠": "試し", "出典": "試し"},
        {"名前": "新設備の取得額", "値": 22500000, "単位": "円", "説明": "試し", "根拠": "試し", "出典": "試し"},
        {"名前": "新設備の耐用年数", "値": 10, "単位": "年", "説明": "試し", "根拠": "試し", "出典": "試し"},
        {"名前": "増産の割合", "値": 0.08 if effect else 0.0, "単位": "%", "説明": "試し", "根拠": "試し", "出典": "試し"},
        {"名前": "原材料のロスの減り", "値": 0.03 if effect else 0.0, "単位": "%", "説明": "試し", "根拠": "試し", "出典": "試し"},
    ]
    spec["前提"] = [a for a in spec["前提"] if a["名前"] not in {x["名前"] for x in add}] + add
    spec["既存事業"] = {
        "売上": "基準_売上*(1+売上の伸び率+増産の割合)^年",
        "原材料費": "基準_原材料費*(1+売上の伸び率+増産の割合)^年*(1-原材料のロスの減り)",
        "給与支給総額": "基準_給与支給総額*(1+賃上げ率)^年",
        "その他の人件費": "基準_その他の人件費*(1+賃上げ率)^年",
        "減価償却費": "基準_減価償却費+新設備の取得額/新設備の耐用年数",
    }
    return spec


def test_investment_effect_warns_when_the_effect_is_not_in_the_profit() -> None:
    """浮いた時間の行き先が損益に入っていない計画では知らせが出て、増産と原価の効果を入れると出ない（11/6 のリハーサル）。"""
    weak = book_of(_effect_spec(0.0, effect=False)).summary["投資の効果の見え方"]
    notes = "\n".join(weak["知らせ"])
    assert "浮いた人手と時間の行き先" in notes
    assert "減価償却費の増加" in notes
    assert weak["営業利益の増加（基準年度から最終年）"] < weak["減価償却費の増加（基準年度から最終年）"]
    strong = book_of(_effect_spec(0.0, effect=True)).summary["投資の効果の見え方"]
    assert strong["知らせ"] == [], strong["知らせ"]
    assert strong["営業利益の増加（基準年度から最終年）"] > weak["営業利益の増加（基準年度から最終年）"]


def test_shoryoku_index_same_as_form() -> None:
    """別紙1：組になった作業（検品 180分 → 120分）は、減った60分だけを削減に数える。"""
    sh = book_of(demo()).summary["省力化"]
    assert sh["削減される業務に要していた時間"] == pytest.approx(36.0)  # (2280-180+60)/60
    assert sh["導入後に発生する業務に要する時間"] == pytest.approx(11.0)  # (780-120)/60
    assert sh["省力化指数"] == pytest.approx(25 / 36)
    assert sh["削減工数"] == pytest.approx(25.0)
    va = book_of(demo()).summary["指標"]["付加価値額"]
    assert sh["増加した付加価値額"] == pytest.approx((va[5] - va[0]) / 5)
    assert sh["投資回収期間"] == pytest.approx(22500000 / (25 * 300 * 1500 + sh["増加した付加価値額"]))
    assert sh["表示"]["省力化指数"] == pytest.approx(0.69)
    assert sh["組になった作業"] == [{"導入前": 5, "導入後": 3}]


def test_payback_formula() -> None:
    """別紙3 の式：投資総額 ÷（削減工数 × 年間稼働日数 × 人件費単価 ＋ 増加した付加価値額）。

    応募手引8 p.59 の例の数（表示は 8.85 年。表示された削減工数 6.5 は丸めた値と見られ、6.5 で計算すると 8.84 になる）。
    """
    years = zaimu.payback_years(110_000_000, 6.5, 260, 2_480, 8_250_000)
    assert years == pytest.approx(110_000_000 / 12_441_200)
    assert youken.round_half_up(years, 2) == pytest.approx(8.84)
    assert zaimu.payback_years(1_000_000, 0, 300, 1_500, 0) is None  # 分母が0
    assert zaimu.payback_years(1_000_000, -1, 300, 1_500, 0) is None  # 負は空


@pytest.mark.parametrize("pairs_after, expected", [
    # 内容は変化しない作業で、時間が増えたとき：導入後に、増えた分だけを数える
    ([{"工程": "検品", "分": 240, "種別": "内容は変化しない作業", "対応する導入前": 2}], (100 / 60, 60 / 60)),
    # 新たに追加される作業だけ：導入前は全部、導入後も全部
    ([{"工程": "見守り", "分": 30, "種別": "新たに追加される作業"}], (280 / 60, 30 / 60)),
])
def test_shoryoku_hours_cases(pairs_after, expected) -> None:
    raw = {"導入前": [{"工程": "計量", "分": 100}, {"工程": "検品", "分": 180}], "導入後": pairs_after,
           "投資総額": 1, "年間稼働日数": 1, "人件費単価": 1}
    sh = zaimu._shoryoku(raw, set())
    assert zaimu.shoryoku_hours(sh) == pytest.approx(expected)


def test_first_match_only_like_the_form() -> None:
    """別紙1 は、対応する導入前の No が同じ導入後の行のうち、最初の行だけを見る（MATCH）。"""
    raw = {"導入前": [{"工程": "検品", "分": 180}],
           "導入後": [{"工程": "見守り", "分": 30, "種別": "内容は変化しない作業", "対応する導入前": 1},
                     {"工程": "検品", "分": 120, "種別": "内容は変化しない作業", "対応する導入前": 1}],
           "投資総額": 1, "年間稼働日数": 1, "人件費単価": 1}
    sh = zaimu._shoryoku(raw, set())
    assert [(b.no, a.no) for b, a in zaimu.shoryoku_pairs(sh)] == [(1, 1)]


@pytest.mark.parametrize("bad, words", [
    ({"種別": "なくなる作業"}, "種別は"),
    ({"種別": "内容は変化しない作業"}, "対応する導入前の作業の番号"),
    ({"種別": "内容は変化しない作業", "対応する導入前": 9}, "対応する導入前の作業の番号"),
    ({"分": -1}, "負の数"),
])
def test_bad_shoryoku_is_refused(bad, words) -> None:
    spec = demo()
    spec["省力化"]["導入後"][0].update(bad)
    with pytest.raises(zaimu.SpecError) as e:
        zaimu.parse_spec(spec)
    assert words in str(e.value)


def test_bad_waves_are_refused() -> None:
    spec = demo()
    spec["月次の波"] = [1] * 11
    with pytest.raises(zaimu.SpecError):
        zaimu.parse_spec(spec)
    spec["月次の波"] = [0] * 12
    with pytest.raises(zaimu.SpecError):
        zaimu.parse_spec(spec)


# ---------------------------------------------------------------- 道具（zaimu_model.py）


def test_tool_reports_low_case_shoryoku_and_writes_numbers(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    text = zt.ok(env.run(folder))
    assert "数量が2割少ない場合（数量_増産パック・数量_冷凍惣菜 を0.8倍）" in text
    assert "省力化指数：0.69" in text and "削減工数：25.00 時間/日" in text and "投資回収期間：" in text
    assert "仮の数（後で確かめる）：人件費単価" in text
    numbers = json.loads((folder / "記録" / "財務モデルの数字.json").read_text(encoding="utf-8"))
    assert numbers["中身"]["省力化"]["削減工数"] == pytest.approx(25.0)
    names = {p["名前"]: p for p in numbers["前提"]}
    assert names["数量_増産パック"]["番号"] == "P-05" and names["数量_増産パック"]["仮"] is True
    assert names["基準_給与支給総額"]["番号"] == "J-03" and names["人件費単価"]["番号"] == "S-03"


def test_tool_keeps_fact_marks_and_check_lists_facts_learned_later(tmp_path) -> None:
    """作ったときの会社の記録の事実の指紋を控えに残し、後で増えた・変わった事実を確かめの注意に挙げる（B37。
    11/6 のリハーサルで、増産の見込みを聞いた後も財務モデルが前年比5%の式のままだった）。"""
    from lib import company_record, kakunin

    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    source = company_record.make_source(folder, "社長の発言", utterance="1日に約3,500パック出している")
    _, old, _ = company_record.add_fact(folder, "1日の出荷", "約3,500パック", True, source)
    zt.ok(env.run(folder))
    numbers = json.loads((folder / "記録" / "財務モデルの数字.json").read_text(encoding="utf-8"))
    assert list(numbers[company_record.FACT_MARKS_KEY]) == [old["id"]]
    assert kakunin.facts_after_model(folder, numbers) == []

    _, new, _ = company_record.add_fact(folder, "増産の見込み", "1日に約500パック増やせる", True, source)
    company_record.update_fact(folder, old["id"], "約3,600パック", source)
    assert kakunin.facts_after_model(folder, numbers) == [f"1日の出荷（{old['id']}）", f"増産の見込み（{new['id']}）"]

    # 指紋のない前の控えは、覚えた日が作った日より後の事実を挙げる
    older = {"作った日時": "2000年1月1日（土）10:00"}
    assert len(kakunin.facts_after_model(folder, older)) == 2
    assert kakunin.facts_after_model(folder, {"作った日時": "2999年1月1日（火）10:00"}) == []
    assert kakunin.facts_after_model(folder, None) == []


BREAKDOWN = {
    "決算書": "決算書 第18期（架空）",
    "行": [
        {"科目": "売上高", "区分": "売上", "金額": 201600000, "出典": "p.2"},
        {"科目": "材料費", "区分": "原材料費", "金額": 82600000, "出典": "p.3"},
        {"科目": "労務費の給与", "区分": "給与支給総額", "金額": 33400000, "出典": "p.3"},
        {"科目": "労務費の法定福利費", "区分": "その他の人件費", "金額": 5000000, "出典": "p.3"},
        {"科目": "水道光熱費", "区分": "その他の経費", "金額": 9800000, "出典": "p.3"},
        {"科目": "消耗品・包材", "区分": "その他の経費", "金額": 8600000, "出典": "p.3"},
        {"科目": "工場の家賃", "区分": "その他の経費", "金額": 4800000, "出典": "p.3"},
        {"科目": "製造の減価償却費", "区分": "減価償却費", "金額": 2800000, "出典": "p.3"},
        {"科目": "修繕費など", "区分": "その他の経費", "金額": 1200000, "出典": "p.3"},
        {"科目": "役員報酬", "区分": "その他の人件費", "金額": 10800000, "出典": "p.4"},
        {"科目": "給料手当", "区分": "給与支給総額", "金額": 8200000, "出典": "p.4"},
        {"科目": "販管の法定福利費", "区分": "その他の人件費", "金額": 2900000, "出典": "p.4"},
        {"科目": "福利厚生費", "区分": "その他の人件費", "金額": 600000, "出典": "p.4"},
        {"科目": "荷造運賃", "区分": "その他の経費", "金額": 7400000, "出典": "p.4"},
        {"科目": "車両費", "区分": "その他の経費", "金額": 3800000, "出典": "p.4"},
        {"科目": "リース料", "区分": "その他の経費", "金額": 2600000, "出典": "p.4"},
        {"科目": "販管の減価償却費", "区分": "減価償却費", "金額": 800000, "出典": "p.4"},
        {"科目": "その他", "区分": "その他の経費", "金額": 11500000, "出典": "p.4"},
    ],
    "営業利益": {"金額": 4800000, "出典": "p.2"},
    "人数": {"役員数": {"値": 2, "根拠": "役員名簿", "出典": "役員名簿（架空）"}},
}


def run_kijun(env: zt.Env, folder, *args: str):
    import subprocess
    import hook_runner as hr
    return subprocess.run(
        [hr.real_python(), "-B", str(env.plugin / zt.SCRIPT), "kijun", "--folder", str(folder), *args],
        env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)}, cwd=env.cwd, capture_output=True,
        timeout=120)


def test_kijun_sums_the_statement_and_fills_the_spec(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    rel = "記録/一時/決算の内訳.json"
    (folder / rel).parent.mkdir(parents=True)
    (folder / rel).write_text(json.dumps(BREAKDOWN, ensure_ascii=False), encoding="utf-8")
    text = zt.ok(run_kijun(env, folder, "--input", rel, "--into", zt.SPEC_IN_FOLDER))
    assert "足し上げた営業利益 4,800,000円 が決算書と一致" in text
    spec = json.loads((folder / zt.SPEC_IN_FOLDER).read_text(encoding="utf-8"))
    base = spec["基準年度"]
    assert base["給与支給総額"]["値"] == 41600000 and "労務費の給与 33,400,000円（p.3）＋給料手当 8,200,000円（p.4）" in base[
        "給与支給総額"]["出典"]
    assert base["その他の人件費"]["値"] == 19300000 and base["その他の経費"]["値"] == 49700000
    assert base["減価償却費"]["値"] == 3600000
    assert base["役員数"]["値"] == 2 and base["常勤従業員数"] == demo()["基準年度"]["常勤従業員数"]  # 渡さない人数は残す
    assert spec["前提"] == demo()["前提"]  # ほかは変えない
    zt.ok(env.run(folder))  # 置き換えた指定で財務モデルが作れる


def test_kijun_refuses_when_profit_does_not_match(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    broken = copy.deepcopy(BREAKDOWN)
    del broken["行"][-1]  # 「その他」11,500,000円が抜けた
    rel = "記録/一時/決算の内訳.json"
    (folder / rel).parent.mkdir(parents=True)
    (folder / rel).write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    before = (folder / zt.SPEC_IN_FOLDER).read_bytes()
    r = run_kijun(env, folder, "--input", rel, "--into", zt.SPEC_IN_FOLDER)
    assert r.returncode == 2
    assert "16,300,000円が、決算書の営業利益 4,800,000円と合いません（差 +11,500,000円）" in zt.out(r)
    assert (folder / zt.SPEC_IN_FOLDER).read_bytes() == before


def test_kijun_input_outside_is_refused(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    outside = tmp_path / "外の内訳.json"
    outside.write_text(json.dumps(BREAKDOWN, ensure_ascii=False), encoding="utf-8")
    r = run_kijun(env, folder, "--input", str(outside))
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)


def run_moji(env: zt.Env, folder, *args: str):
    import subprocess
    import hook_runner as hr
    script = env.plugin / "skills" / "kaku" / "scripts" / "moji.py"
    return subprocess.run([hr.real_python(), "-B", str(script), "--folder", str(folder), *args],
                          env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)}, cwd=env.cwd,
                          capture_output=True, timeout=120)


def test_moji_reads_originals_without_adhoc_code(tmp_path) -> None:
    """原本の Word・Excel・PDF の文字を道具で出す（その場の読み取りのコードを書かないため。波3 の気づき #7）。"""
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    names = zt.REPO_ROOT / "testdata" / "デモの会社" / "書類"
    target = folder / "原本"
    target.mkdir()
    import shutil
    shutil.copyfile(names / "株主名簿.docx", target / "株主名簿.docx")
    shutil.copyfile(names / "決算書_第18期.pdf", target / "決算書.pdf")
    text = zt.ok(run_moji(env, folder, "--file", "原本/株主名簿.docx"))
    assert text.startswith("# 原本/株主名簿.docx") and "株主名簿" in text
    text = zt.ok(run_moji(env, folder, "--file", "原本/決算書.pdf", "--page", "1"))
    assert "--- 1ページ目" in text
    (target / "名簿.xlsx").write_bytes((zt.REPO_ROOT / "testdata" / "会社の資料" / "材料" /
                                         "既存事業の売上と経費_第17期_第18期.xlsx").read_bytes())
    text = zt.ok(run_moji(env, folder, "--file", "原本/名簿.xlsx"))
    assert "--- シート「" in text
    outside = tmp_path / "外.txt"
    outside.write_text("外", encoding="utf-8")
    r = run_moji(env, folder, "--file", str(outside))
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)


# ---------------------------------------------------------------- LibreOffice で計算し直して比べる（slow）


@pytest.mark.slow
def test_T8_10_recalculated_model(tmp_path) -> None:
    soffice = zt.soffice_or_skip()
    env = zt.Env(tmp_path)
    folder = env.company(spec=demo())
    result = zt.ok_json(env.run(folder, "--json", soffice=soffice))
    check = result["計算し直し"]
    assert check["した"] is True and check["食い違い"] == [], check["食い違い"][:5]
    s = result["中身"]

    model = folder / zt.MODEL
    formulas = zt.dump_xlsx(model)
    assert formulas["sheets"] == ["前提", PLAN, MONTHLY]
    lo_all = zt.dump_xlsx(zt.recalc(model, tmp_path / "lo"), data_only=True)["cells"]
    lo, cells = lo_all[PLAN], formulas["cells"][PLAN]

    # Excel の数式の結果（テストの側の計算し直し）が、Python の計算と一致する
    for business in ("既存事業", "省力化の増産", "冷凍惣菜", "合算"):
        head = zt.row_of(cells, "【既存事業】" if business == "既存事業" else (
            "【合算】" if business == "合算" else f"【新事業：{business}】"))
        for i, key in enumerate(("売上", "原材料費")):
            for y, col in enumerate(COLS):
                expected = (s["合算"] if business == "合算" else s["事業ごと"][business])[key][y]
                assert lo[f"{col}{head + 1 + i}"] == pytest.approx(expected, rel=1e-12, abs=1e-6), (business, key, y)
    # 合算は、既存事業と新事業の和（計算し直した値で）
    heads = {b: zt.row_of(cells, h) for b, h in (("既存", "【既存事業】"), ("増産", "【新事業：省力化の増産】"),
                                                 ("冷凍", "【新事業：冷凍惣菜】"), ("合算", "【合算】"))}
    for offset in range(1, 9):  # 売上〜営業利益の8行
        for col in COLS:
            parts = sum(lo[f"{col}{heads[b] + offset}"] for b in ("既存", "増産", "冷凍"))
            assert lo[f"{col}{heads['合算'] + offset}"] == pytest.approx(parts, rel=1e-12, abs=1e-6)
    # 月次の合計は1年目と同じ
    monthly = lo_all[MONTHLY]
    for row in range(4, 10):
        assert monthly[f"N{row}"] == pytest.approx(monthly[f"O{row}"], rel=1e-12, abs=1e-6), row
    assert monthly["M4"] > monthly["C4"]  # 季節の波（12か月目は重み1.2、2か月目は0.95）
    # 省力化の指標
    sh = s["省力化"]
    for label, key in (("省力化指数", "省力化指数"), ("削減工数（時間/日）", "削減工数"), ("投資回収期間（年）", "投資回収期間"),
                       ("増加した付加価値額（円/年）", "増加した付加価値額")):
        assert lo[f"B{zt.row_of(cells, label)}"] == pytest.approx(sh[key], rel=1e-12), label

    # 数量を2割減らした場合：道具の判定（まとめの B8）と、0.8倍の指定で作り直して計算し直した判定（B7）が一致する
    assert lo["A8"] == zaimu.LOW_LABEL and lo["B8"] == s["数量が2割少ない場合"]["判定"]
    env2 = zt.Env(tmp_path / "低い")
    folder2 = env2.company(spec=scaled(demo(), 0.8))
    zt.ok(env2.run(folder2, soffice=soffice))
    lo_low = zt.dump_xlsx(zt.recalc(folder2 / zt.MODEL, tmp_path / "lo_low"), data_only=True)["cells"][PLAN]
    assert lo_low["B7"] == lo["B8"]
    for r in s["数量が2割少ない場合"]["要件ごと"]:
        row = zt.row_of(cells, f"要件：{r['名前']}" + ("（特例を選ぶときだけ）" if r["特例"] else ""))
        assert lo_low[f"H{row}"] == r["判定"], r["名前"]
