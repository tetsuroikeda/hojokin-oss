"""財務モデルの、様式（その3 の別紙4）に写す数字と、数量が2割少ない場合の読み方（11/6 のリハーサルの穴1〜3。
SPEC F8・T8-4・T8-10、DESIGN 8.3）。

- 穴1：別紙4 は売上原価と販売費及び一般管理費を分けて求める。決算の内訳の行に「損益の区分」を付けると、kijun が区分ごとの
  売上原価の割合を出して指定に書き、道具が別紙4 の行の並びで売上原価・販管費を出す。丸める前の和は「売上 − 営業利益」と
  合う。本補助金で導入する設備の減価償却費は、指定の式で既存設備の分と分け、売上原価の割合も別にできる。
- 穴2：決算が出ているのは直近期だけ。年度（直近期・補助事業の完了予定・応募の締切）から、締切期・基準年度・経過年数を
  様式と同じ決め方で出す（応募手引8 p.22・p.58 の例）。基準年度は直近期の実績からの式で置き、締切期の⑦⑧と足下の賃上げも
  出す。公式の別紙4 に同じ数字を入れて計算し直すと、経過年数・足下の賃上げ・労働生産性の伸びが道具の値と同じになる。
- 穴3：数量が2割少ない場合は、計画で増やす分にかける。今の数量（実績）まで「数量_」にしていたら判定せず、理由と参考の
  値を示す。売上が減っても原材料費が動かないときは知らせる。
- 架空の会社（リハーサルと同じ数字。tests/test_T8_10.py の BREAKDOWN と同じ決算書）。
"""

from __future__ import annotations

import copy
import json
import re
import zipfile
from datetime import date

import pytest
import zaimu_tool as zt

from lib import youken, zaimu
from test_T8_10 import BREAKDOWN, run_kijun

SEIDO9 = {"数値の要件": zt.load(zt.SEIDO)["数値の要件"],
          "決まった期日": [{"名前": "公募開始日", "日時": {"値": {"日時": "2026-11-04"}, "状態": "確認済み"}},
                         {"名前": "公募締切日", "日時": {"値": {"年月": "2026-12", "旬": "下旬"}, "出典": [{"資料": "スケジュール9"}],
                                                   "状態": "要確認"}}]}
PLAN = "計画（3年）"
SIDE = {"p.3": "売上原価", "p.4": "販管費"}  # BREAKDOWN の出典のページ：p.3 が製造原価報告書、p.4 が販管費の内訳


def breakdown_with_sides() -> dict:
    data = copy.deepcopy(BREAKDOWN)
    for row in data["行"]:
        if row["区分"] != "売上":
            row["損益の区分"] = SIDE[row["出典"]]
    data["売上原価"] = {"金額": 148_200_000, "出典": "p.2"}
    data["販売費及び一般管理費"] = {"金額": 48_600_000, "出典": "p.2"}
    data["人数"] = {k: RECENT[k] for k in ("役員数", "常勤従業員数", "給与を受けた従業員数")}
    return data


def item(value, source="決算書 第18期（架空）"):
    return {"値": value, "根拠": "決算書", "出典": source}


def formula(text, source="会社の記録（架空）"):
    return {"式": text, "根拠": "聞き取り", "出典": source}


RECENT = {"売上": item(201_600_000), "原材料費": item(82_600_000), "給与支給総額": item(41_600_000),
          "その他の人件費": item(19_300_000), "減価償却費": item(3_600_000), "その他の経費": item(49_700_000),
          "役員数": item(2, "役員名簿（架空）"), "常勤従業員数": item(15, "労働者名簿（架空）"),
          "給与を受けた従業員数": item(15, "労働者名簿（架空）")}
SHARES = {"原材料費": item(1), "給与支給総額": item(33_400_000 / 41_600_000), "その他の人件費": item(5_000_000 / 19_300_000),
          "減価償却費": item(2_800_000 / 3_600_000), "その他の経費": item(24_400_000 / 49_700_000)}


def rehearsal_spec(current_in_quantity: bool = True, deadline: str = "2026-12") -> dict:
    """リハーサルの会社の指定（基準年度は第20期＝完了日を含む期。直近期は第18期の決算書）。

    current_in_quantity が真なら、リハーサルの前の指定と同じく、今の出荷パック（実績）に「数量_」を付ける。
    偽なら、今の出荷パックは「数量_」を付けず、計画で増やす分の倍率だけを「数量_」にし、原材料費を売上につなげる。"""
    assumptions = [
        {"名前": "売上の伸び率", "値": 0.05, "単位": "%", "根拠": "聞き取り", "出典": "社長の答え（架空）"},
        {"名前": "賃上げ率", "値": 0.04, "単位": "%", "根拠": "聞き取り", "出典": "社長の答え（架空）"},
        {"名前": "新設備の取得額", "値": 22_500_000, "単位": "円", "根拠": "見積書", "出典": "見積書（架空）"},
        {"名前": "新設備の耐用年数", "値": 10, "単位": "年", "根拠": "聞き取り", "出典": "社長の答え（架空）"},
        {"名前": "単価_惣菜", "値": 250, "単位": "円/パック", "根拠": "聞き取り", "出典": "社長の答え（架空）"},
        {"名前": "固定費_地代家賃", "値": 4_800_000, "単位": "円/年", "根拠": "決算書", "出典": "決算書（架空）"},
        {"名前": "固定費_リース料", "値": 2_600_000, "単位": "円/年", "根拠": "決算書", "出典": "決算書（架空）"},
    ]
    fixed = "固定費_地代家賃+固定費_リース料"
    if current_in_quantity:
        assumptions.append({"名前": "数量_出荷パック", "値": 806_400, "単位": "パック/年", "根拠": "決算書", "出典": "決算書（架空）"})
        sales = "単価_惣菜*数量_出荷パック*(1+売上の伸び率)^年"
        material = "基準_原材料費*(1+売上の伸び率)^年"
        other = f"(基準_その他の経費-({fixed}))*(1+売上の伸び率)^年+{fixed}"
    else:
        assumptions += [
            {"名前": "出荷パック_基準", "値": 806_400, "単位": "パック/年", "根拠": "決算書", "出典": "決算書（架空）"},
            {"名前": "数量_増産の倍率", "値": 1, "単位": "倍", "根拠": "計画どおり", "出典": "前提 売上の伸び率"},
        ]
        sales = "単価_惣菜*出荷パック_基準*(1+数量_増産の倍率*((1+売上の伸び率)^年-1))"
        material = "基準_原材料費*売上/基準_売上"
        other = f"(基準_その他の経費-({fixed}))*売上/基準_売上+{fixed}"
    flat = ("売上", "原材料費", "減価償却費", "その他の経費", "役員数", "常勤従業員数", "給与を受けた従業員数")
    base = {k: formula(f"直近_{k}") for k in flat}
    base.update({k: formula(f"直近_{k}*(1+賃上げ率)^経過年数") for k in ("給与支給総額", "その他の人件費")})
    return {
        "計画の年数": 3,
        "前提": assumptions,
        "年度": {"直近期": "2026-03", "補助事業の完了予定": "2028-01", "応募の締切": deadline},
        "直近期の実績": copy.deepcopy(RECENT),
        "基準年度": base,
        "既存事業": {"売上": sales, "原材料費": material, "給与支給総額": "基準_給与支給総額*(1+賃上げ率)^年",
                 "その他の人件費": "基準_その他の人件費*(1+賃上げ率)^年", "その他の経費": other,
                 "減価償却費": "基準_減価償却費+新設備の取得額/新設備の耐用年数"},
        "本補助金の設備の減価償却費": formula("新設備の取得額/新設備の耐用年数", "前提 新設備の取得額・耐用年数"),
        "売上原価の割合": copy.deepcopy(SHARES),
    }


def book_of(spec: dict) -> zaimu.Book:
    return zaimu.build(zaimu.parse_spec(spec), youken.read_requirements(SEIDO9))


# ---------------------------------------------------------------- 穴2：年度（直近期・締切期・基準年度）


@pytest.mark.parametrize("recent, deadline, completion, closing, base, elapsed", [
    ("2026-03", "2026-12", "2028-01", "2027年3月期", "2028年3月期", 2),  # リハーサル（第9回の締切は2026年12月）
    ("2026-01", "2026-10", "2027-06", "2027年1月期", "2028年1月期", 2),  # 応募手引8 p.22 の例（1月決算）
    ("2026-09", "2026-10", "2027-09", "2027年9月期", "2027年9月期", 1),  # 応募手引8 p.58 の例（9月決算。締切期＝基準年度）
])
def test_timeline_like_the_form(recent, deadline, completion, closing, base, elapsed) -> None:
    spec = zaimu.parse_spec(dict(rehearsal_spec(), **{"年度": {"直近期": recent, "応募の締切": deadline,
                                                            "補助事業の完了予定": completion}}))
    tl = spec.timeline
    assert (tl.label(tl.recent), tl.label(tl.closing), tl.label(tl.base), tl.elapsed) == (
        tl.label(int(recent[:4])), closing, base, elapsed)
    assert tl.label(tl.base + 1) == f"{int(base[:4]) + 1}年{tl.month}月期"  # 1年目は基準年度の翌年度（要領9 p.7（8））
    assert spec.base["給与支給総額"].value == pytest.approx(41_600_000 * 1.04 ** elapsed)


def test_deadline_from_seido_and_note_5() -> None:
    found = zaimu.deadline_from_seido(SEIDO9)
    assert found["値"] == "2026-12" and "公募締切日" in found["出典"] and "要確認" in found["出典"]
    raw = rehearsal_spec()
    del raw["年度"]["応募の締切"]
    filled = zaimu.with_seido_deadline(raw, SEIDO9)
    assert "応募の締切" not in raw["年度"]  # 指定は書き換えない
    assert zaimu.parse_spec(filled).timeline.closing == 2027
    # 締切がなければ、直近期の次の期を締切期とし、そう知らせる
    tl = zaimu.parse_spec(raw).timeline
    assert tl.closing == 2027 and any("応募の締切が分からない" in n for n in tl.notes)
    # 決算が確定していないので前々期の値を使う（別紙4 の注5）：経過年数は様式の直近期から数える
    late = dict(raw, **{"年度": {"直近期": "2025-03", "補助事業の完了予定": "2028-01", "応募の締切": "2026-12"}})
    tl = zaimu.parse_spec(late).timeline
    assert tl.recent == 2026 and tl.recent_actual == 2025 and tl.elapsed == 2 and any("注5" in n for n in tl.notes)


@pytest.mark.parametrize("change, words", [
    (lambda s: s["年度"].update({"直近期": "2024-03"}), "前の期（2026年3月期）ではありません"),
    (lambda s: s["年度"].update({"補助事業の完了予定": "2026-11"}), "応募の締切より前"),
    (lambda s: s.pop("年度"), "「年度」（直近期・補助事業の完了予定）を書いてください"),
    (lambda s: s["基準年度"].update({"売上": formula("直近_売上*(1+売上の伸び率)^年")}), "「年」を使えません"),
    (lambda s: s["基準年度"].update({"売上": formula("直近_ない")}), "「直近_ない」が、前提にも基準年度にもありません"),
    (lambda s: s["前提"].append({"名前": "経過年数", "値": 1}), "道具が使う名前と重なる"),
    (lambda s: s["前提"].append({"名前": "直近_売上", "値": 1}), "道具が使う名前と重なる"),
    (lambda s: s["売上原価の割合"].pop("その他の経費"), "売上原価の割合に、ない区分があります：その他の経費"),
    (lambda s: s["売上原価の割合"].update({"原材料費": item(1.2)}), "0〜1にしてください"),
    (lambda s: s.update({"本補助金の設備の減価償却費": formula("新設備の取得額")}), "合算の減価償却費"),
])
def test_bad_beppyo_spec_is_refused(change, words) -> None:
    spec = rehearsal_spec()
    change(spec)
    with pytest.raises(zaimu.SpecError) as e:
        book_of(spec)
    assert words in str(e.value)


def test_base_year_from_the_recent_year_and_ashimoto() -> None:
    """基準年度（第20期）は直近期（第18期）の実績からの式。締切期（第19期）は同じ式の経過年数を1にしたもの。"""
    book = book_of(rehearsal_spec())
    s = book.summary
    assert s["年度"]["基準年度"] == "2028年3月期" and s["年度"]["経過年数"] == 2
    assert s["年度"]["計画の年"] == ["2029年3月期", "2030年3月期", "2031年3月期"]
    assert s["合算"]["給与支給総額"][0] == pytest.approx(44_994_560) and s["合算"]["その他の人件費"][0] == pytest.approx(20_874_880)
    a = s["別紙4"]["足下の賃上げ"]
    assert a["列"] == ["2026年3月期", "2027年3月期", "2028年3月期"]
    assert a["給与支給総額"] == [41_600_000, 43_264_000, 44_994_560] and a["給与を受けた従業員数"] == [15, 15, 15]
    pp = [youken.pay_per_person(v, 15) for v in a["給与支給総額"]]
    assert a["1人当たり給与支給総額"] == pp and a["伸び"] == youken.growth_pay(pp[2], pp[0], 2)
    # 前提のシート：基準年度の値は数式（直近期の名前と経過年数）、直近期の実績は名前を付けた入力のセル
    pre = {sh.title: sh for sh in book.sheets}["前提"]
    row = book.names["基準_給与支給総額"][1].split("$")[-1]
    assert pre.cells[f"C{row}"].formula == "=(直近_給与支給総額*((1+賃上げ率)^経過年数))" and pre.cells[f"C{row}"].fill is None
    row = book.names["直近_給与支給総額"][1].split("$")[-1]
    assert pre.cells[f"C{row}"].value == 41_600_000 and pre.cells[f"C{row}"].fill == zaimu.FILL_INPUT
    assert pre.cells["C" + book.names["経過年数"][1].split("$")[-1]].value == 2
    # 数字の控え：直近期（R-）と売上原価の割合（G-）にも番号が付き、式で置いた基準年度は式を残す
    numbers = zaimu.numbers_record(zaimu.parse_spec(rehearsal_spec()), book, None, "")
    by_name = {a["名前"]: a for a in numbers["前提"]}
    assert by_name["直近_給与支給総額"]["番号"].startswith("R-") and by_name["原価割合_原材料費"]["番号"].startswith("G-")
    assert by_name["基準_給与支給総額"]["式"] == "直近_給与支給総額*(1+賃上げ率)^経過年数"


# ---------------------------------------------------------------- 穴1：売上原価と販売費及び一般管理費


def test_cost_split_adds_up_to_sales_minus_profit() -> None:
    s = book_of(rehearsal_spec()).summary
    b, t = s["別紙4"], s["合算"]
    assert b["列"] == ["2028年3月期", "2029年3月期", "2030年3月期", "2031年3月期"]
    rows = b["年ごと"]
    for y in range(4):
        assert b["照らし"]["売上原価＋販管費"][y] == pytest.approx(t["売上"][y] - t["営業利益"][y], abs=1e-6)
        assert rows["売上高"][y] - rows["売上原価"][y] - rows["販売費及び一般管理費"][y] == rows["営業利益"][y]
        assert abs(rows["営業利益"][y] - t["営業利益"][y]) <= 1  # 円に丸めた差だけ
        assert rows["既存設備の減価償却費"][y] == 3_600_000
    assert b["照らし"]["合う"] is True
    assert rows["本補助金で導入する設備の減価償却費"] == [None, 2_250_000, 2_250_000, 2_250_000]
    # 基準年度の売上原価：原材料費は全部、給与は 334/416、法定福利費など 50/193、減価償却費 28/36、その他 244/497
    base_cost = (82_600_000 + 44_994_560 * 334 / 416 + 20_874_880 * 50 / 193 + 3_600_000 * 28 / 36 + 49_700_000 * 244 / 497)
    assert rows["売上原価"][0] == youken.round_half_up(base_cost, 0)
    # 様式に円で写した値から様式と同じ計算をした伸び（リハーサル：3年目の1人当たり給与は 3.99% → 4.00%）
    assert rows["労働生産性の伸び"][1:] == s["指標"]["労働生産性の伸び"][1:]
    assert {(d["指標"], d["年"]) for d in b["様式の値と財務モデルの伸びの違い"]} == {("1人当たり給与支給総額の伸び", 3)}


def test_new_equipment_can_have_its_own_cost_share() -> None:
    """製造ラインの減価償却費は、決算書の減価償却費の割合（28/36）ではなく、全部を売上原価にできる。"""
    plain = book_of(rehearsal_spec()).summary["別紙4"]
    spec = rehearsal_spec()
    spec["売上原価の割合"]["本補助金の設備の減価償却費"] = item(1, "見積書（製造ライン。架空）")
    own = book_of(spec).summary["別紙4"]
    assert any("決算書の減価償却費の割合" in n for n in plain["知らせ"])
    assert not any("決算書の減価償却費の割合" in n for n in own["知らせ"])
    moved = youken.round_half_up(2_250_000 * (1 - 28 / 36), 0)
    assert own["年ごと"]["売上原価"][0] == plain["年ごと"]["売上原価"][0]
    for y in (1, 2, 3):
        assert own["年ごと"]["売上原価"][y] - plain["年ごと"]["売上原価"][y] == pytest.approx(moved, abs=1)
        assert own["年ごと"]["営業利益"][y] == plain["年ごと"]["営業利益"][y]  # 営業利益は変わらない
    assert own["照らし"]["合う"] is True


def test_without_beppyo_keys_nothing_changes() -> None:
    """年度などがない指定（今までの指定）では、別紙4 の数字を出さず、計画のシートも今までと同じ。"""
    s = zaimu.build(zaimu.parse_spec(zt.load(zt.SPEC3)), youken.read_requirements(zt.load(zt.SEIDO))).summary
    assert s["別紙4"] is None and s["年度"] is None


def test_kijun_writes_cost_share_and_recent_year(tmp_path) -> None:
    env = zt.Env(tmp_path)
    spec = rehearsal_spec()
    del spec["直近期の実績"], spec["売上原価の割合"]
    folder = env.company(spec=spec, seido=SEIDO9)
    rel = "記録/一時/決算の内訳.json"
    (folder / rel).parent.mkdir(parents=True)
    (folder / rel).write_text(json.dumps(breakdown_with_sides(), ensure_ascii=False), encoding="utf-8")
    text = zt.ok(run_kijun(env, folder, "--input", rel, "--into", zt.SPEC_IN_FOLDER, "--as", "直近期"))
    assert "売上原価の科目の計 148,200,000円、販売費及び一般管理費の科目の計 48,600,000円" in text
    assert "- 給与支給総額：80.29%" in text and "の直近期の実績を置き換えました（売上原価の割合も書きました）" in text
    written = json.loads((folder / zt.SPEC_IN_FOLDER).read_text(encoding="utf-8"))
    assert written["直近期の実績"]["給与支給総額"]["値"] == 41_600_000
    assert written["基準年度"] == spec["基準年度"]  # 基準年度（式）は変えない
    assert written["売上原価の割合"]["原材料費"]["値"] == 1
    assert written["売上原価の割合"]["給与支給総額"]["値"] == pytest.approx(33_400_000 / 41_600_000)
    assert "労務費の給与 33,400,000円" in written["売上原価の割合"]["給与支給総額"]["出典"]
    out = zt.ok(env.run(folder))  # 書いた指定で作れる（応募の締切は指定にある）
    assert "様式（別紙4）に写す数字（円に丸めた値。列は 2028年3月期、2029年3月期、2030年3月期、2031年3月期）" in out
    assert "→ 合う" in out and "足下の賃上げ（2026年3月期、2027年3月期、2028年3月期）" in out


@pytest.mark.parametrize("how, words", [
    ("一部だけ", "損益の区分（売上原価か販管費）が付いていない行があります：販管の減価償却費"),
    ("合計が違う", "決算書の売上原価 148,000,000円と合いません（差 +200,000円）"),
    ("知らない区分", "損益の区分「営業外」は使えません"),
])
def test_kijun_refuses_bad_sides(tmp_path, how, words) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=zt.load(zt.DATA / "指定_デモの会社.json"))
    data = breakdown_with_sides()
    if how == "一部だけ":
        del data["行"][-2]["損益の区分"]
    elif how == "合計が違う":
        data["売上原価"]["金額"] = 148_000_000
    else:
        data["行"][1]["損益の区分"] = "営業外"
    rel = "記録/一時/決算の内訳.json"
    (folder / rel).parent.mkdir(parents=True)
    (folder / rel).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = (folder / zt.SPEC_IN_FOLDER).read_bytes()
    r = run_kijun(env, folder, "--input", rel, "--into", zt.SPEC_IN_FOLDER)
    assert r.returncode == 2 and words in zt.out(r), zt.out(r)
    assert (folder / zt.SPEC_IN_FOLDER).read_bytes() == before


# ---------------------------------------------------------------- 穴3：数量が2割少ない場合


def test_low_case_with_current_volume_in_quantity_is_not_judged() -> None:
    """リハーサルの前の指定：今の出荷パック（実績）に「数量_」を付けていたので、1年目の労働生産性の伸びが −55.55% になった。"""
    low = book_of(rehearsal_spec(current_in_quantity=True)).summary["数量が2割少ない場合"]
    assert low["判定"] == youken.UNJUDGEABLE and low["参考の判定（今の数量まで減らした場合）"] == youken.FAILS
    assert [(c["事業"], c["行"]) for c in low["今の数量まで減らしている行"]] == [("既存事業", "売上")]
    assert low["今の数量まで減らしている行"][0]["数量を0.8倍にした年0の値"] == pytest.approx(201_600_000 * 0.8)
    basic1 = next(r for r in low["要件ごと"] if r["名前"].startswith("労働生産性"))
    assert basic1["年ごと"][0]["伸び"] == -55.55  # 参考の値は隠さない
    assert any("原材料費は減りません" in n for n in low["知らせ"])
    assert [(m["事業"], m["行"]) for m in low["数量を減らすと変わる行"]] == [("既存事業", "売上")]


def test_low_case_on_the_planned_increase_is_judged() -> None:
    """今の数量は「数量_」を付けず、計画で増やす分だけを「数量_」にすると、計画の数字は同じで、2割少ない場合を判定する。"""
    old = book_of(rehearsal_spec(current_in_quantity=True)).summary
    s = book_of(rehearsal_spec(current_in_quantity=False)).summary
    for key in ("売上", "原材料費", "その他の経費", "営業利益"):
        assert s["合算"][key] == pytest.approx(old["合算"][key], rel=1e-12)
    assert s["指標"]["労働生産性の伸び"] == old["指標"]["労働生産性の伸び"]
    low = s["数量が2割少ない場合"]
    assert low["今の数量まで減らしている行"] == [] and "参考の判定（今の数量まで減らした場合）" not in low
    assert low["判定"] == youken.MEETS and not any("原材料費は減りません" in n for n in low["知らせ"])
    sales = low["最後の年"]["売上"]
    assert sales[1] == pytest.approx(201_600_000 * (1 + 0.8 * (1.05 ** 3 - 1)))  # 増やす分だけが2割少ない
    basic1 = next(r for r in low["要件ごと"] if r["名前"].startswith("労働生産性"))
    assert all(p["伸び"] > 4.0 for p in basic1["年ごと"])


def test_demo_company_low_case_is_unchanged() -> None:
    """新事業（導入による増減）の数量だけを「数量_」にした指定は、今までどおり判定する。"""
    s = zaimu.build(zaimu.parse_spec(zt.load(zt.DATA / "指定_デモの会社.json")),
                    youken.read_requirements(zt.load(zt.SEIDO))).summary
    low = s["数量が2割少ない場合"]
    assert low["今の数量まで減らしている行"] == [] and low["判定"] == youken.MEETS


def test_tool_reports_the_low_case_reason(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=rehearsal_spec(current_in_quantity=True), seido=SEIDO9)
    text = zt.ok(env.run(folder))
    assert "（数量_出荷パック を0.8倍）：数値の要件（特例を除く）をすべて満たすか → 判定できない" in text
    assert "参考：今の数量まで減らした場合の判定は「満たさない」" in text
    assert "今の数量（実績）まで「数量_」にしているので、判定しません" in text
    assert "3年目：売上 233,377,200円 → 186,701,760円" in text


# ---------------------------------------------------------------- LibreOffice で計算し直す（slow）


@pytest.mark.slow
def test_beppyo_block_recalculated(tmp_path) -> None:
    soffice = zt.soffice_or_skip()
    env = zt.Env(tmp_path)
    spec = rehearsal_spec()
    spec["売上原価の割合"]["本補助金の設備の減価償却費"] = item(1, "見積書（架空）")
    folder = env.company(spec=spec, seido=SEIDO9)
    result = zt.ok_json(env.run(folder, "--json", soffice=soffice))
    assert result["計算し直し"]["した"] is True and result["計算し直し"]["食い違い"] == []
    b = result["中身"]["別紙4"]
    cells = zt.dump_xlsx(folder / zt.MODEL)["cells"][PLAN]
    lo = zt.dump_xlsx(zt.recalc(folder / zt.MODEL, tmp_path / "lo"), data_only=True)["cells"][PLAN]
    for label, key in (("　売上原価（区分ごとの合算 × 売上原価の割合）", "売上原価"), ("① 営業利益", "営業利益"),
                       ("労働生産性の年平均成長率（％）", "労働生産性の伸び")):
        row = [int(ref[1:]) for ref, v in cells.items() if ref.startswith("A") and v == label][-1]
        for y, col in enumerate("BCDE"):
            if b["年ごと"][key][y] is not None:
                assert lo[f"{col}{row}"] == pytest.approx(b["年ごと"][key][y], abs=1e-6), (key, y)
    row = zt.row_of(cells, "1人当たり給与支給総額の年平均成長率（％。直近期から基準年度まで、経過年数で）")
    assert lo[f"D{row}"] == b["足下の賃上げ"]["伸び"]


# ---------------------------------------------------------------- 公式の別紙4 に同じ数字を入れる（slow）


def fill_kubun4(src, dst, numbers: dict, texts: dict) -> str:
    """公式の別紙4 の入力欄に、数（numbers）と文字（texts。決算月など）を入れた写しを作る。シートの名前を返す。"""
    from test_T8_4 import kubun4_part
    with zipfile.ZipFile(src) as zin:
        parts = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        infos = zin.infolist()
    name, part = kubun4_part(parts)
    xml = parts[part].decode("utf-8")
    for ref, value in list(numbers.items()) + list(texts.items()):
        pattern = re.compile(r'<c r="' + ref + r'"((?:\s+[^>]*?)?)(?:/>|>.*?</c>)', re.DOTALL)
        found = pattern.search(xml)
        assert found, ref
        attrs = re.sub(r'\s+t="[^"]*"', "", found.group(1))
        body = (f' t="inlineStr"><is><t>{value}</t></is></c>' if ref in texts else f"><v>{float(value)!r}</v></c>")
        xml = xml[:found.start()] + f'<c r="{ref}"{attrs}' + body + xml[found.end():]
    parts[part] = xml.encode("utf-8")
    with zipfile.ZipFile(dst, "w") as zout:
        for info in infos:
            zout.writestr(info, parts[info.filename])
    return name


@pytest.mark.slow
def test_same_as_official_form_with_recent_year(tmp_path) -> None:
    """公式の別紙4（第8回。締切は10月）に、道具の別紙4 の数字と決算月・完了予定を入れて計算し直すと、経過年数・足下の
    賃上げ・営業利益・付加価値額・労働生産性と1人当たり給与の伸びが、道具の値と同じになる。"""
    from test_T8_4 import FORM
    if not FORM.is_file():
        pytest.skip("downloads/ に省力化の様式その3 がありません（公式資料を取ってから流す）")
    zt.soffice_or_skip()
    spec = rehearsal_spec(deadline="2026-10")
    s = book_of(spec).summary
    b, rows, a = s["別紙4"], s["別紙4"]["年ごと"], s["別紙4"]["足下の賃上げ"]
    numbers = {}
    for y, col in enumerate("FGHI"):
        numbers.update({f"{col}14": rows["売上高"][y], f"{col}15": rows["売上原価"][y], f"{col}17": rows["販売費及び一般管理費"][y],
                        f"{col}19": rows["人件費"][y], f"{col}21": rows["既存設備の減価償却費"][y],
                        f"{col}25": rows["役員数"][y], f"{col}26": rows["常勤従業員数"][y]})
        if y:
            numbers.update({f"{col}22": rows["本補助金で導入する設備の減価償却費"][y], f"{col}33": rows["給与支給総額"][y],
                            f"{col}34": rows["給与を受けた従業員数"][y]})
    for col, i in (("C", 0), ("D", 1), ("E", 2)):
        numbers.update({f"{col}33": a["給与支給総額"][i], f"{col}34": a["給与を受けた従業員数"][i]})
    numbers["C5"] = (date(2028, 1, 1) - date(1899, 12, 30)).days  # 補助事業完了予定年月（日付の数）
    filled = tmp_path / "form.xlsx"
    sheet = fill_kubun4(FORM, filled, numbers, {"C4": "3月"})
    lo = zt.dump_xlsx(zt.recalc(filled, tmp_path / "lo"), data_only=True)["cells"][sheet]
    assert lo["C6"] == s["年度"]["経過年数"] == 2
    assert lo["E40"] == a["伸び"]
    for y, col in enumerate("FGHI"):
        assert lo[f"{col}18"] == rows["営業利益"][y], y
        assert lo[f"{col}23"] == rows["付加価値額"][y], y
        assert lo[f"{col}27"] == rows["労働生産性"][y], y
        if y:
            assert lo[f"{col}29"] == rows["労働生産性の伸び"][y], y
            assert lo[f"{col}40"] == rows["1人当たり給与支給総額の伸び"][y], y
