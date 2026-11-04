"""最小限の財務モデル（TASKS M5。DESIGN 8.3、SPEC F8「財務モデル」）。

- 前提3つだけの財務モデルを作る。シートは3つ（前提・計画（5年）・月次（1年目））。前提と基準年度の実績のセルに
  名前を付け、計画は名前を使った数式で書く。決まっていない前提は「状態」に「仮」と書き、色を付ける。
- 会社のフォルダでなければ何もしない。指定が正しくなければ作らない（前提は20個まで）。
- 会社のフォルダの外は読まない・書かない（lib/places.py。財務モデル.xlsx・作業の場所の別名も断る）。
- 計算し直した結果が Python と食い違えば置かない（終了コード3）。LibreOffice がなければ確かめずに置き、そう伝える。
- 作業の途中のファイルは残さない。プラグインの場所に __pycache__ を書かない。同梱の openpyxl で、
  /usr/bin/python3（3.9）で動く。
LibreOffice で計算し直して比べる確かめは tests/test_T8_4.py にある。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import hook_runner as hr
import pytest
import zaimu_tool as zt

from lib import youken, zaimu

PLAN = "計画（5年）"


def fake_soffice(env: zt.Env, body: str) -> str:
    """LibreOffice の代わりのスクリプト（計算し直さずに写すだけ、または失敗する）。"""
    path = env.root / "fake" / "soffice"
    path.parent.mkdir()
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


COPY_ONLY = r"""
out=""; prev=""; last=""
for a in "$@"; do
  if [ "$prev" = "--outdir" ]; then out="$a"; fi
  prev="$a"; last="$a"
done
/bin/cp "$last" "$out/"
"""


# ---------------------------------------------------------------- 作る


def test_builds_three_sheets_with_named_cells_and_formulas(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    before = env.outside()
    text = zt.ok(env.run(folder))
    assert "財務モデル.xlsx を作りました（シート：前提・計画（5年）・月次（1年目）。前提 3 個、計画 5 年）。" in text
    assert "LibreOffice が見つからないので、計算し直しの確かめはしていません" in text
    assert "労働生産性の年平均成長率（基本要件①）：満たす（基準 4.0%以上・毎年。要領8 p.10）" in text
    assert "仮の前提（後で確かめる）：数量_新商品" in text
    assert env.outside() == before
    assert not list(env.plugin.rglob("__pycache__"))

    book = zt.dump_xlsx(folder / zt.MODEL)
    assert book["sheets"] == ["前提", PLAN, "月次（1年目）"]
    pre = book["cells"]["前提"]
    # 前提は3つ（P-01〜P-03）。基準年度の実績は別の表（J-01〜）
    assert [v for ref, v in sorted(pre.items()) if ref.startswith("A") and str(v).startswith("P-")] == [
        "P-01", "P-02", "P-03"]
    names = book["names"]
    assert set(names) == {"単価_新商品", "数量_新商品", "賃上げ率"} | {"基準_" + k for k in zaimu.BASE_KEYS}
    for name, place in names.items():
        sheet, ref = place.split("!")
        assert sheet == "'前提'" and ref.startswith("$C$")
        row = ref.replace("$C$", "")
        assert pre[f"B{row}"] == name
        assert book["fills"]["前提"][f"C{row}"] == zaimu.FILL_INPUT  # 社長が書き換えてよい値
    row = names["数量_新商品"].split("$")[-1]
    assert pre[f"H{row}"] == "仮" and book["fills"]["前提"][f"H{row}"] == zaimu.FILL_PROVISIONAL
    assert book["formats"]["前提"]["C" + names["賃上げ率"].split("$")[-1]] == "0.0%"

    plan = book["cells"][PLAN]
    pay = zt.row_of(plan, "【既存事業】") + 4  # 売上・原材料費・人件費・うち給与支給総額
    assert plan[f"A{pay}"] == "　うち給与支給総額（全月分の給与を受けた従業員）"
    assert plan[f"B{pay}"] == "=基準_給与支給総額"
    assert plan[f"C{pay}"] == "=(基準_給与支給総額*((1+賃上げ率)^C$10))"
    sales = zt.row_of(plan, "【新事業：新しい商品】") + 1
    assert plan[f"C{sales}"] == "=(単価_新商品*数量_新商品)"
    assert plan[f"B{sales}"] == 0  # 新事業は1年目から
    formulas = [v for v in plan.values() if isinstance(v, str) and v.startswith("=")]
    assert len(formulas) > 150
    # 数式だけで、計算済みの値は持たない（Excel・LibreOffice が開くときに計算する）
    raw = zt.dump_xlsx(folder / zt.MODEL, data_only=True)["cells"][PLAN]
    assert all(raw.get(ref) is None for ref, v in plan.items() if isinstance(v, str) and v.startswith("="))
    monthly = book["cells"]["月次（1年目）"]
    assert monthly["B4"] == "='計画（5年）'!C33/12" and monthly["N4"] == "=SUM(B4:M4)"
    # 作業の途中のファイルは残さない
    assert not (folder / ".hojokin" / "一時" / "財務モデル").exists()


def test_json_report_sums_and_requirements(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    result = zt.ok_json(env.run(folder, "--json"))
    assert result["置いた"] is True and result["計算し直し"]["した"] is False
    assert result["制度データ"] == zt.SEIDO_IN_FOLDER
    s = result["中身"]
    assert s["前提の数"] == 3 and s["計画の年数"] == 5
    # 合算は既存事業と新事業の和。月次の合計は1年目と同じ
    for key in ("売上", "人件費", "営業利益"):
        for y in range(6):
            assert s["合算"][key][y] == pytest.approx(s["事業ごと"]["既存事業"][key][y] + s["事業ごと"]["新しい商品"][key][y])
    for v in s["月次の合計と1年目"].values():
        assert v["合計"] == pytest.approx(v["1年目"], abs=1e-6)
    assert s["数値の要件（特例を除く）をすべて満たすか"] == youken.MEETS
    assert [r["名前"] for r in s["判定した要件"]] == [
        "労働生産性の年平均成長率（基本要件①）", "1人当たり給与支給総額の年平均成長率（基本要件②）",
        "大幅賃上げ特例：1人当たり給与支給総額の年平均成長率"]


def test_spec_from_stdin_and_seido_option(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(seido=False)
    other = folder / "記録" / "別の場所" / "制度.json"
    other.parent.mkdir(parents=True)
    other.write_text(zt.SEIDO.read_text(encoding="utf-8"), encoding="utf-8")
    r = env.run(folder, "--spec", "-", "--seido", "記録/別の場所/制度.json", "--json",
                stdin=zt.SPEC3.read_bytes())
    result = zt.ok_json(r)
    assert result["制度データ"] == "記録/別の場所/制度.json"
    assert len(result["中身"]["判定した要件"]) == 3


def test_without_seido_builds_but_does_not_judge(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(seido=False)
    text = zt.ok(env.run(folder))
    assert "制度データがないので、数値の要件は判定していません" in text
    assert (folder / zt.MODEL).is_file()


def test_refuses_two_seido_files(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    (folder / "記録" / "制度データ" / "持続化_第20回.json").write_text("{}", encoding="utf-8")
    r = env.run(folder)
    assert r.returncode == 2 and "--seido" in zt.out(r)
    assert not (folder / zt.MODEL).exists()


def test_replace_needed_when_model_exists(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    zt.ok(env.run(folder))
    first = (folder / zt.MODEL).read_bytes()
    r = env.run(folder)
    assert r.returncode == 2 and "--replace" in zt.out(r)
    assert (folder / zt.MODEL).read_bytes() == first
    spec = zt.load(zt.SPEC3)
    spec["前提"][1]["値"] = 24000
    (folder / zt.SPEC_IN_FOLDER).write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    result = zt.ok_json(env.run(folder, "--replace", "--json"))
    assert result["中身"]["合算"]["売上"][1] == 144_000_000
    assert (folder / zt.MODEL).read_bytes() != first


# ---------------------------------------------------------------- 作らない


def test_not_a_company_folder(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = tmp_path / "ふつうのフォルダ"
    folder.mkdir()
    (folder / "記録").mkdir()
    (folder / zt.SPEC_IN_FOLDER).write_text(zt.SPEC3.read_text(encoding="utf-8"), encoding="utf-8")
    before = hr.snapshot(folder)
    r = env.run(folder)
    assert r.returncode == 2 and "会社のフォルダではありません" in zt.out(r)
    assert hr.snapshot(folder) == before


def broken(spec: dict, how: str) -> dict:
    if how == "前提が21個":
        spec["前提"] = spec["前提"] + [{"名前": f"前提{i}", "値": i} for i in range(18)]
    elif how == "知らない名前":
        spec["新事業"][0]["売上"] = "単価_新商品*数量_ない"
    elif how == "セルの場所に見える名前":
        spec["前提"][0]["名前"] = "AB12"
    elif how == "0で割る":
        spec["新事業"][0]["原材料費"] = "売上/(数量_新商品-12000)"
    elif how == "基準年度が足りない":
        del spec["基準年度"]["減価償却費"]
    elif how == "式がぐるぐる回る":
        spec["新事業"][0]["原材料費"] = "その他の経費*0.1"
        spec["新事業"][0]["その他の経費"] = "原材料費*0.1"
    elif how == "使えない書き方":
        spec["新事業"][0]["売上"] = "__import__('os')"
    elif how == "労働者が0人":
        spec["人数"] = {"常勤従業員数": "0", "役員数": "0"}
    elif how == "名前が重なる":
        spec["前提"][1]["名前"] = "単価_新商品"
    return spec


@pytest.mark.parametrize("how, words", [
    ("前提が21個", "20 個まで"),
    ("知らない名前", "「数量_ない」が、前提にも基準年度にもありません"),
    ("セルの場所に見える名前", "セルの場所や関数と紛れる"),
    ("0で割る", "0 で割っています"),
    ("基準年度が足りない", "ない項目があります：減価償却費"),
    ("式がぐるぐる回る", "ぐるぐる回っています"),
    ("使えない書き方", "使えない書き方"),
    ("労働者が0人", "労働者数（役員＋常勤従業員）が0以下"),
    ("名前が重なる", "2つあります"),
])
def test_bad_spec_is_refused(tmp_path, how, words) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(spec=broken(zt.load(zt.SPEC3), how))
    r = env.run(folder)
    assert r.returncode == 2, zt.out(r)
    assert words in zt.out(r)
    assert "財務モデル.xlsx は作っていません" in zt.out(r)
    assert not (folder / zt.MODEL).exists()
    assert not (folder / ".hojokin" / "一時" / "財務モデル").exists()


def test_twenty_assumptions_are_allowed() -> None:
    spec = zt.load(zt.SPEC3)
    spec["前提"] = spec["前提"] + [{"名前": f"前提{i}", "値": i} for i in range(17)]
    assert len(zaimu.parse_spec(spec).assumptions) == 20


def test_excel_and_python_precedence_agree() -> None:
    """Excel と Python の演算の優先順位の違い（-2^2 など）は、かっこで消す。"""
    names = {"a"}
    e = zaimu.Expr.parse("-a^2+2^3^2", "試し", names, ())
    # Excel だけなら -a^2 は (-a)^2、2^3^2 は (2^3)^2 になる。Python の読み方どおりに、かっこを付けて書く
    assert e.excel(lambda n: n) == "=((-(a^2))+(2^(3^2)))"
    assert e.value(lambda n: 3.0) == -(3.0 ** 2) + 2 ** 9


# ---------------------------------------------------------------- 会社のフォルダの外


def test_spec_or_seido_outside_is_refused(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    outside = tmp_path / "外" / "指定.json"
    outside.parent.mkdir()
    outside.write_text(zt.SPEC3.read_text(encoding="utf-8"), encoding="utf-8")
    r = env.run(folder, "--spec", str(outside))
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)
    r = env.run(folder, "--spec", "../外/指定.json")
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)
    r = env.run(folder, "--seido", str(zt.SEIDO))
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)
    # 中の場所が、外への別名
    os.symlink(outside, folder / "記録" / "別名の指定.json")
    r = env.run(folder, "--spec", "記録/別名の指定.json")
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)
    assert not (folder / zt.MODEL).exists()


def test_seido_folder_linked_outside_is_refused(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company(seido=False)
    outside = tmp_path / "外の制度データ"
    outside.mkdir()
    (outside / "省力化_第8回.json").write_text(zt.SEIDO.read_text(encoding="utf-8"), encoding="utf-8")
    os.symlink(outside, folder / "記録" / "制度データ")
    r = env.run(folder)
    assert r.returncode == 2 and "会社のフォルダの外" in zt.out(r)
    assert not (folder / zt.MODEL).exists()


@pytest.mark.parametrize("link", ["財務モデル.xlsx", ".hojokin/一時"])
def test_link_on_the_way_is_refused(tmp_path, link) -> None:
    """財務モデル.xlsx や作業の場所が別名なら、別名の先（外）を書き換えない。"""
    env = zt.Env(tmp_path)
    folder = env.company()
    outside = tmp_path / "外"
    outside.mkdir()
    if link == "財務モデル.xlsx":
        target = outside / "大事な.xlsx"
        target.write_bytes(b"keep")
        os.symlink(target, folder / zt.MODEL)
        r = env.run(folder, "--replace")
    else:
        os.symlink(outside, folder / ".hojokin" / "一時")
        r = env.run(folder)
    assert r.returncode == 2, zt.out(r)
    assert "別名（シンボリックリンク）" in zt.out(r)
    assert sorted(p.name for p in outside.iterdir()) == (["大事な.xlsx"] if link == "財務モデル.xlsx" else [])
    if link == "財務モデル.xlsx":
        assert (outside / "大事な.xlsx").read_bytes() == b"keep"


# ---------------------------------------------------------------- 計算し直し


def test_not_recalculated_is_a_mismatch_and_is_not_placed(tmp_path) -> None:
    """LibreOffice の代わりに、計算し直さずに写すだけのものを渡すと、値が空のままなので食い違いになり、置かない。"""
    env = zt.Env(tmp_path)
    folder = env.company()
    r = env.run(folder, soffice=fake_soffice(env, COPY_ONLY))
    assert r.returncode == 3, zt.out(r)
    text = zt.out(r)
    assert "食い違いました" in text and "作者に知らせてください" in text
    assert "財務モデル.xlsx は置いていません" in text
    assert not (folder / zt.MODEL).exists()
    assert not (folder / ".hojokin" / "一時" / "財務モデル").exists()


def test_libreoffice_failure_places_without_check(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    text = zt.ok(env.run(folder, soffice=fake_soffice(env, "echo 落ちた >&2; exit 1")))
    assert "LibreOffice で計算し直せませんでした" in text and "確かめはしていません" in text
    assert (folder / zt.MODEL).is_file()


# ---------------------------------------------------------------- 同梱の openpyxl と /usr/bin/python3


LOAD_CODE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from lib import zaimu_xlsx
import openpyxl, et_xmlfile
print(json.dumps({"openpyxl": openpyxl.__file__, "version": openpyxl.__version__, "et_xmlfile": et_xmlfile.__file__,
                  "lxml": "lxml" in sys.modules}))
"""


def test_bundled_openpyxl_loads_on_system_python(tmp_path) -> None:
    """lib/zaimu_xlsx.py は、利用者の site-packages を読まない /usr/bin/python3 でも、同梱の openpyxl で動く。"""
    plugin = zt.copy_plugin(tmp_path / "plugin")
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", LOAD_CODE, str(plugin)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    seen = json.loads(r.stdout.decode("utf-8"))
    vendor = plugin / "lib" / "vendor"
    assert seen["openpyxl"] == str(vendor / "openpyxl" / "__init__.py") and seen["version"] == "3.1.5"
    assert seen["et_xmlfile"] == str(vendor / "et_xmlfile" / "__init__.py")
    assert not list(plugin.rglob("__pycache__"))


def test_missing_bundle_stops_with_code_1(tmp_path) -> None:
    env = zt.Env(tmp_path)
    folder = env.company()
    shutil.rmtree(env.plugin / "lib" / "vendor" / "openpyxl")
    r = env.run(folder)
    assert r.returncode == 1 and "補助プログラム" in zt.out(r)
    assert not (folder / zt.MODEL).exists()
    assert not (folder / ".hojokin" / "一時" / "財務モデル").exists()
