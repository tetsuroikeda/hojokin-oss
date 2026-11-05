"""T5-1 不備の検出（SPEC F5「不備チェック」、TASKS B12）。T5-2（誤った指摘）の道具の部分もここで見る。

合格ライン（T5-1）：不備を仕込んだ書類セット（F14）を入れる。重大な不備（期限切れ、期数不足、金額の不一致、名義の不一致、
事前着手）の見逃し0件。ほかは90%以上（仮）を検出。すべての指摘に重さと直し方。
合格ライン（T5-2）：不備のない書類セットを入れる。「重大」の誤指摘0件。

このファイルは2つを見る。
1. 不備チェックの道具（skills/shorui/scripts/fubi.py）：書類から読み取った項目（このテストが、仕込んだ不備の一覧
   testdata/書類セット/仕込んだ不備の一覧.json の値で作る）をコードで照らすと、コードで見つける型（期限切れ・期数不足・
   名義の不一致・宛名・従業員数・事前着手）の仕込みがすべて候補に出ること。正しいセットの値では、重大の候補が0件。
   重さか直し方のない指摘は残さないこと。残した不備の数が、今の状態の画面に出ること。
2. 振る舞い（eval の T5-1）で残した出力の突き合わせ：環境変数 HOJOKIN_T5_1_KEPT に、eval が残した会社のフォルダを渡すと、
   `記録/不備の一覧.json` を仕込んだ不備の一覧と突き合わせる（仕込みごとの「採点の手がかり（案）」が、1つの指摘の中に
   そろって出るか）。渡さなければ飛ばす。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt

FUBI = Path("skills") / "shorui" / "scripts" / "fubi.py"
SEEDED = json.loads((hr.REPO_ROOT / "testdata" / "書類セット" / "仕込んだ不備の一覧.json").read_text(encoding="utf-8"))
SEIDO = json.loads((hr.REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))
CASE = "2026_省力化（一般型）第9回"
TODAY = "2026-11-05"
NAME = "株式会社やまぶき惣菜"
ADDRESS = "東京都大田区東糀谷八丁目12番5号"
BOSS = "代表取締役 沢村 宏之"


def correct_readings() -> list:
    """正しいセットの書類から読み取ったことにする項目（testdata/書類セット/セットの一覧.md の値）。"""
    base = {"社名": NAME, "所在地": ADDRESS, "代表者": BOSS}
    return [
        dict(base, 原本="原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf", 種類="履歴事項全部証明書",
             制度データの書類="履歴事項全部証明書", 発行日="2026-10-22"),
        dict(base, 原本="原本/決算・税/2024-04-01_決算書.pdf", 種類="決算書", 制度データの書類="損益計算書（直近2期分）",
             期=["第17期"]),
        dict(base, 原本="原本/決算・税/2025-04-01_決算書.pdf", 種類="決算書", 制度データの書類="損益計算書（直近2期分）",
             期=["第18期"]),
        {"原本": "原本/決算・税/2026-10-23_納税証明書（その2）.jpg", "種類": "納税証明書（その2）",
         "制度データの書類": "納税証明書（その2）", "発行日": "2026-10-23", "期": ["第16期", "第17期", "第18期"], "社名": NAME,
         "所在地": ADDRESS},
        dict(base, 原本="原本/決算・税/2025-04-01_法人事業概況説明書.pdf", 種類="法人事業概況説明書", 従業員数=15),
        {"原本": "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf", "種類": "見積書",
         "発行日": "2026-10-20", "有効期限": "2027-01-31", "宛名": f"{NAME} 御中"},
        {"原本": "原本/見積・契約・請求/2026-10-20_見積書_ほしみ機工.pdf", "種類": "見積書", "発行日": "2026-10-20",
         "有効期限": "2027-01-31", "宛名": f"{NAME}　御中"},
        dict(base, 原本="原本/登記・名簿/2026-11-01_役員名簿.docx", 種類="役員名簿"),
        {"原本": "原本/登記・名簿/2026-11-01_労働者名簿.xlsx", "種類": "労働者名簿", "社名": NAME, "従業員数": 15},
    ]


def defect_readings() -> list:
    """不備を仕込んだセットの書類から読み取ったことにする項目（仕込んだ不備の一覧の「仕込んだ値」）。"""
    docs = {d["種類"] + d["原本"]: d for d in correct_readings()}
    out = []
    for d in correct_readings():
        d = dict(d)
        if d["種類"] == "履歴事項全部証明書":
            d.update(発行日="2026-06-15", 原本="原本/登記・名簿/2026-06-15_履歴事項全部証明書.pdf")  # 仕込み-01
        if d["原本"].endswith("見積書_つばさ台フードシステム.pdf"):
            d.update(発行日="2026-08-03", 有効期限="2026-10-31")  # 仕込み-02
        if d["原本"] == "原本/決算・税/2024-04-01_決算書.pdf":
            continue  # 仕込み-03（第17期を抜いた）
        if d["種類"] == "納税証明書（その2）":
            d["期"] = ["第17期", "第18期"]  # 仕込み-04
        if d["種類"] == "役員名簿":
            d["社名"] = "株式会社山吹惣菜"  # 仕込み-05
        if d["原本"] == "原本/決算・税/2025-04-01_決算書.pdf":
            d["所在地"] = "東京都大田区東糀谷八丁目21番5号"  # 仕込み-06
        if d["種類"] == "法人事業概況説明書":
            d["代表者"] = "代表取締役 沢村 浩之"  # 仕込み-07
        if d["原本"].endswith("見積書_ほしみ機工.pdf"):
            d["宛名"] = "やまぶき惣菜株式会社　御中"  # 仕込み-08
        if d["種類"] == "労働者名簿":
            d["従業員数"] = 14  # 仕込み-17
        out.append(d)
    out.append({"原本": "原本/見積・契約・請求/2026-10-28_注文書_つばさ台フードシステム.docx", "種類": "注文書",
                "発注日": "2026-10-28", "補助事業の経費": True, "社名": NAME})  # 仕込み-16
    assert docs  # 正しいセットの読み取りをもとにした
    return out


def run(company: vt.Company, command: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": company.env.path, "HOME": str(company.env.home), "TMPDIR": str(company.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(company.env.plugin / FUBI), command, "--folder", str(company.folder), *args],
        env=env, cwd=company.env.cwd, capture_output=True, timeout=120,
    )


def ok_json(r: subprocess.CompletedProcess):
    return json.loads(ct.ok(r))


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき惣菜")
    # 道具は同梱の知見（knowledge/不備の型.json）を読む（tests/company_tool.py の写しは lib と skills だけ）
    shutil.copytree(hr.REPO_ROOT / "knowledge", c.env.plugin / "knowledge")
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = TODAY
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (c.folder / "案件" / CASE / "1_申請" / "添付する書類").mkdir(parents=True)
    listed = {"制度": dict(SEIDO["制度"], 略称="省力化"), "資料": []}
    c.write(f"記録/資料の本文/{CASE}/資料の一覧.json", json.dumps(listed, ensure_ascii=False))
    c.write("記録/制度データ/省力化_第8回.json", json.dumps(SEIDO, ensure_ascii=False))
    return c


def candidates(company: vt.Company, readings: list) -> list:
    company.write("記録/一時/書類の読み取り.json", json.dumps({"書類": readings}, ensure_ascii=False))
    return ok_json(run(company, "check", "--case", CASE, "--input", "記録/一時/書類の読み取り.json"))["コードで見つけた不備の候補"]


def test_rules_show_the_measures(company) -> None:
    out = ok_json(run(company, "rules", "--case", CASE))
    assert out["今日"] == TODAY and out["交付決定の日"].startswith("まだ")
    names = {r["名前"]: r for r in out["この段階で集める書類の決まり"]}
    assert names["履歴事項全部証明書"]["有効期限"] == "応募申請日に発行から3か月以内"
    assert names["納税証明書（その2）"]["期数"] == 3
    assert "見積書" not in names  # 交付申請の書類は、応募申請の段階では出さない
    assert any(x["名前"] == "自動車などの車両・船舶・航空機" for x in out["補助の対象にならない経費"])
    assert {t["id"] for t in out["不備の型"]} >= {"不備-01", "不備-02", "不備-03", "不備-04", "不備-07"}


CODE_FOUND = {"仕込み-01": "不備-01", "仕込み-02": "不備-01", "仕込み-03": "不備-02", "仕込み-04": "不備-02",
              "仕込み-05": "不備-03", "仕込み-06": "不備-03", "仕込み-07": "不備-03", "仕込み-08": "不備-03",
              "仕込み-16": "不備-07", "仕込み-17": "不備-06"}


def hint_matches(seeded: dict, text: str) -> bool:
    return all(re.search(h, text) for h in seeded["採点の手がかり（案）"])


def test_code_finds_the_seeded_defects_it_can(company) -> None:
    found = candidates(company, defect_readings())
    texts = [f"{f['種類']} {f['書類']} {f['内容']}" for f in found]
    for seeded in SEEDED["不備"]:
        if seeded["id"] not in CODE_FOUND:
            continue
        hit = [f for f, t in zip(found, texts) if f["型"] == CODE_FOUND[seeded["id"]] and hint_matches(seeded, t)]
        assert hit, (seeded["id"], seeded["採点の手がかり（案）"], texts)
        assert all(f["重さ"] == seeded["重さ"] and f["直し方"] for f in hit), hit


def test_correct_set_gives_no_serious_candidate(company) -> None:
    assert [f for f in candidates(company, correct_readings()) if f["重さ"] == "重大"] == []


def test_record_needs_weight_and_fix_and_updates_the_page(company) -> None:
    bad = {"不備": [{"重さ": "大事", "種類": "期限切れ", "書類": "履歴事項全部証明書", "直し方": "取り直す"},
                   {"重さ": "重大", "種類": "期数不足", "書類": "決算書", "直し方": ""}]}
    company.write("記録/一時/不備.json", json.dumps(bad, ensure_ascii=False))
    r = run(company, "record", "--case", CASE, "--input", "記録/一時/不備.json")
    assert r.returncode == 2 and "重さ" in r.stdout.decode("utf-8") and "直し方" in r.stdout.decode("utf-8")
    assert not (company.folder / "記録" / "不備の一覧.json").exists()

    found = candidates(company, defect_readings())
    company.write("記録/一時/不備.json", json.dumps({"確かめた書類": [], "不備": found}, ensure_ascii=False))
    out = ok_json(run(company, "record", "--case", CASE, "--input", "記録/一時/不備.json"))
    assert out["数"]["重大"] == len(found)
    page = (company.folder / "今の状態.html").read_text(encoding="utf-8")
    assert f"重大 {len(found)}件" in page and "<h2>不備</h2>" in page


# ---- 2. eval で残した出力の突き合わせ ----


def kept_matches(kept: Path) -> dict:
    data = json.loads((kept / "記録" / "不備の一覧.json").read_text(encoding="utf-8"))
    items = data["不備"]
    texts = [" ".join(str(v) for v in item.values()) for item in items]
    result = {"見つけた": [], "見逃した": [], "指摘": items}
    for seeded in SEEDED["不備"]:
        (result["見つけた"] if any(hint_matches(seeded, t) for t in texts) else result["見逃した"]).append(seeded)
    return result


KEPT = os.environ.get("HOJOKIN_T5_1_KEPT")


@pytest.mark.skipif(not KEPT, reason="eval の T5-1 で残した会社のフォルダを HOJOKIN_T5_1_KEPT に渡すと流れる")
def test_kept_defects_match_the_seeded_list() -> None:
    result = kept_matches(Path(KEPT))
    serious = [s for s in SEEDED["不備"] if s.get("SPEC の重大")]
    missed_serious = [s["id"] for s in result["見逃した"] if s in serious]
    others = [s for s in SEEDED["不備"] if s not in serious]
    found_others = [s for s in result["見つけた"] if s in others]
    print(f"見つけた {len(result['見つけた'])}/{len(SEEDED['不備'])}。SPEC の重大 {len(serious) - len(missed_serious)}/{len(serious)}、"
          f"ほか {len(found_others)}/{len(others)}。見逃し：{[s['id'] for s in result['見逃した']]}")
    assert missed_serious == []
    assert len(found_others) / len(others) >= 0.9
    assert all(i.get("重さ") in ("重大", "要確認", "助言") and str(i.get("直し方") or "").strip() for i in result["指摘"])
