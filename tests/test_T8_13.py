"""T8-13 経費明細（SPEC F8「経費明細」、DESIGN 8.4。TASKS B20）。

合格ライン：スキャンした見積書3通と経費のメモ1枚（F14）から経費明細を作らせる。見積書から取った金額が正解と一致する。
メモから取った金額に仮の印がある。補助の対象にならない経費を「要確認」として示す。

このファイルは2つを見る。
1. 経費明細の道具（lib/keihi.py・skills/kaku/scripts/keihi.py）：正解（testdata/スキャン/経費明細の正解.json）の行を渡すと
   残り、見積書の行は照合済みの見積書の明細と一致し、メモの行は「仮」、試運転の材料は要確認と資料のページを持つ。
   照合していない見積書・金額の食い違い・期限切れの見積書（つばさ台の概算）・資料のページのない要確認は、何も書かずに断る。
2. 振る舞い（eval の T8-13）で残した出力の突き合わせ：環境変数 HOJOKIN_T8_13_KEPT に、eval が残した会社のフォルダを渡すと、
   `記録/経費明細.json` を正解と突き合わせる（正解の「合格の見方（案）」）。渡さなければ飛ばす。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

SEIRI = Path("skills") / "shorui" / "scripts" / "seiri.py"
KINGAKU = Path("skills") / "shorui" / "scripts" / "kingaku.py"
KEIHI = Path("skills") / "kaku" / "scripts" / "keihi.py"
SCAN = hr.REPO_ROOT / "testdata" / "スキャン"
READINGS = {d["番号"]: d for d in json.loads((SCAN / "正解.json").read_text(encoding="utf-8"))["書類"]}
ANSWER = json.loads((SCAN / "経費明細の正解.json").read_text(encoding="utf-8"))
CASE = "2026_省力化（一般型）第9回"
TODAY = "2026-11-05"
QUOTES = {  # 材料 → (日付, 相手先, 補足, 見積番号)
    "scan_20261104_0001.pdf": ("2026-10-20", "つばさ台フードシステム", "", "TFS-2610-0153"),
    "IMG_2741.jpg": ("2026-10-20", "ほしみ機工", "", "HK-20261020-07"),
    "FAX_20261006_1642.pdf": ("2026-10-06", "つばさ台フードシステム", "概算", "TFS-2610-0061"),
}
MAIN = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"
ESTIMATE = "原本/見積・契約・請求/2026-10-06_見積書_つばさ台フードシステム_概算.pdf"
MEMO = "原本/会社の資料/2026-11-02_経費のメモ.jpg"


def run(company: vt.Company, script: Path, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / script), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


def reading_of(doc: dict) -> dict:
    keys = ("種類", "番号", "発行日", "有効期限", "宛名", "発行者", "税込か税抜か", "明細", "税率ごと", "小計", "消費税", "合計",
            "端数の処理")
    return {k: copy.deepcopy(doc.get(k)) for k in keys}


@pytest.fixture
def company(tmp_path) -> vt.Company:
    """見積書3通とメモを原本にし、見積書3通の読み取りを照合済みにした会社のフォルダ。"""
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for name, (day, partner, note, number) in QUOTES.items():
        c.write(f"入れ口/{name}", (SCAN / "材料" / name).read_bytes())
        args = ["--path", f"入れ口/{name}", "--category", "見積・契約・請求", "--kind", "見積書", "--date", day,
                "--partner", partner]
        place = ok_json(run(c, SEIRI, "organize", *(args + (["--note", note] if note else []))))["新しい場所"]
        c.write("記録/一時/読み取り.json", json.dumps(reading_of(READINGS[number]), ensure_ascii=False))
        assert ok_json(run(c, KINGAKU, "check", "--path", place, "--input", "記録/一時/読み取り.json", "--model",
                           "sonnet"))["状態"] == "照合済み"
    c.write("入れ口/IMG_2745.jpg", (SCAN / "材料" / "IMG_2745.jpg").read_bytes())
    ok_json(run(c, SEIRI, "organize", "--path", "入れ口/IMG_2745.jpg", "--category", "会社の資料", "--kind", "経費のメモ",
                "--date", "2026-11-02"))
    return c


def answer_rows() -> list:
    """正解の行を、道具に渡す形にする。"""
    rows = []
    for i, row in enumerate(ANSWER["行"], 1):
        out = {"経費の区分": row["区分（参考）"] or "", "品名": row["品名"], "型番": row["型番"], "数量": row["数量"],
               "単位": row["単位"], "単価": row["単価"], "金額": row["金額（税抜）"], "根拠": row["根拠の種類"],
               "出典": row["出典"]}
        if row["根拠の種類"] == "見積書":
            out.update(原本=MAIN, 明細の番号=i)
        else:
            out["原本"] = MEMO
        if row["要確認"]:
            pages = "、".join(f"{p['資料']} p.{p['ページ']}" for p in row["要確認"]["資料のページ"])
            out["要確認"] = {"わけ": row["要確認"]["わけ"], "資料のページ": pages}
        rows.append(out)
    return rows


def save(company: vt.Company, rows: list) -> subprocess.CompletedProcess:
    company.write("記録/一時/経費明細.json", json.dumps({"行": rows}, ensure_ascii=False))
    return run(company, KEIHI, "save", "--case", CASE, "--input", "記録/一時/経費明細.json")


def record(company_folder: Path) -> dict:
    data = json.loads((company_folder / "記録" / "経費明細.json").read_text(encoding="utf-8"))
    return data["案件"][-1]


def check_against_answer(entry: dict) -> None:
    """正解の「合格の見方（案）」で照らす。"""
    quote_rows = [r for r in entry["行"] if r["根拠"] == "見積書"]
    want = [r for r in ANSWER["行"] if r["根拠の種類"] == "見積書"]
    # 見積書の行：明細ごとでも、まとめてもよい。金額の和は 22,500,000（税抜。消費税を入れない）
    assert sum(r["金額"] for r in quote_rows) == ANSWER["合計"]["見積書から（仮の印なし）"] == 22500000
    if len(quote_rows) == len(want):
        assert sorted(r["金額"] for r in quote_rows) == sorted(r["金額（税抜）"] for r in want)
    assert all(r["状態"] == "確定" for r in quote_rows)
    # 相見積と概算の金額が入っていない（使った見積書は、つばさ台の 10/20 だけ）
    assert {r["原本"] for r in quote_rows} == {entry["使った見積書"][0]} and len(entry["使った見積書"]) == 1
    assert "ほしみ" not in entry["使った見積書"][0] and "概算" not in entry["使った見積書"][0]
    amounts = {r["金額"] for r in entry["行"]}
    for number in ("HK-20261020-07", "TFS-2610-0061"):
        assert READINGS[number]["小計"] not in amounts
    # メモから取った金額（300,000円、100,000円）に仮の印
    memo = {r["金額"]: r for r in entry["行"] if r["根拠"] in ("メモ", "聞き取り")}
    assert set(memo) >= {300000, 100000}
    assert all(r["状態"] == "仮" for r in memo.values())
    # 試運転で使う惣菜の材料を要確認にし、資料のページを示す（ほかの行も、迷うものを要確認にするのはよい。SPEC F8）
    trial = memo[100000]
    assert "要確認" in trial and ("23" in trial["要確認"]["資料のページ"] or "46" in trial["要確認"]["資料のページ"])
    assert all("要確認" not in r for r in quote_rows)  # 見積書の機械の行は対象の経費


def test_answer_rows_are_saved(company) -> None:
    out = ok_json(save(company, answer_rows()))
    assert out["合計"] == {"見積書から": 22500000, "仮（メモ・聞き取りから）": 300000, "要確認": 100000,
                         "全体（要確認を除く）": 22800000}
    check_against_answer(record(company.folder))


def test_grouped_quote_rows_are_allowed(company) -> None:
    """見積書の行は、まとめてもよい（明細の番号の一覧。金額はその和）。"""
    rows = answer_rows()
    grouped = [dict(rows[5], 品名="コンベヤと据え付け・調整", 金額=1200000, 明細の番号=[6, 7], 数量=1, 単価=1200000)]
    ok_json(save(company, rows[:5] + grouped + rows[7:]))
    check_against_answer(record(company.folder))


@pytest.mark.parametrize("change, words", [
    (lambda rows: rows[0].update(金額=7_800_001), "合いません"),
    (lambda rows: rows[0].update(金額=8_580_000), "合いません"),  # 消費税を入れた金額
    (lambda rows: rows[0].update(原本=ESTIMATE), "有効期限"),
    (lambda rows: rows[8]["要確認"].update(資料のページ=""), "資料のページ"),
    (lambda rows: rows[1].update(金額="320万"), "整数"),
    (lambda rows: rows[2].update(明細の番号=None), "明細の番号"),
])
def test_refuses_without_writing(company, change, words) -> None:
    rows = answer_rows()
    change(rows)
    r = save(company, rows)
    assert r.returncode == 2 and words in r.stdout.decode("utf-8"), r.stdout.decode("utf-8")
    assert not (company.folder / "記録" / "経費明細.json").exists()


def test_unverified_quote_is_refused(company) -> None:
    data = json.loads((company.folder / "記録" / "金額の読み取り.json").read_text(encoding="utf-8"))
    for d in data["書類"]:
        if d["原本"] == MAIN:
            d["状態"] = "要確認"
    company.write("記録/金額の読み取り.json", json.dumps(data, ensure_ascii=False))
    r = save(company, answer_rows())
    assert r.returncode == 2 and "照合を通っていません" in r.stdout.decode("utf-8")


KEPT = os.environ.get("HOJOKIN_T8_13_KEPT")


@pytest.mark.skipif(not KEPT, reason="eval の T8-13 で残した会社のフォルダを HOJOKIN_T8_13_KEPT に渡すと流れる")
def test_kept_expense_list_matches_the_answer() -> None:
    check_against_answer(record(Path(KEPT)))
