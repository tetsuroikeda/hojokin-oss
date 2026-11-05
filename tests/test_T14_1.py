"""T14-1 データのそろい（SPEC F14、TASKS D12）。

合格ライン：デモの会社の書類と表の材料がすべてそろい、不備を仕込んだセットに不備の一覧が付く。

- SPEC F14 の材料の表を1行ずつ読み、行ごとに、材料のファイルがあることを確かめる（表の行が増えたり変わったりしたら、
  この対応表 MATERIALS も直すまで落ちる）。
- 公式の様式や公募要領から作る材料（手で直した計画書の Word、公募要領の新旧2版、混ぜた制度データ、引用つきの答え）は、
  リポに入れず、テストのときに downloads/ からスクリプトで作る（DESIGN 11章）。ここでは作るスクリプトがあることを確かめ、
  downloads/ があれば一時の場所に作ってみる（なければ飛ばす。時間がかかるので slow）。
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Dict, List

import pytest

from conftest import REPO_ROOT

SPEC = REPO_ROOT / "SPEC.md"
TD = REPO_ROOT / "testdata"
MARK = "架空のテスト用データ"

# SPEC F14 の材料の表の「材料」の文 → 材料のファイル（リポの根からの場所。* はいくつかのファイル）
MATERIALS: Dict[str, List[str]] = {
    "デモの会社の回答表": ["testdata/デモの会社/回答表.md"],
    "所在地だけを変えた回答表3つ（大都市＝デモの所在地、地方の県庁所在地、町村）": [
        "testdata/回答表/所在地_大都市.md", "testdata/回答表/所在地_県庁所在地.md", "testdata/回答表/所在地_町村.md"],
    "従業員25人の回答表、賃上げの計画が立たない回答表、情報を一部抜いた回答表": [
        "testdata/回答表/従業員25人.md", "testdata/回答表/賃上げの計画が立たない.md", "testdata/回答表/情報を一部抜いた.md"],
    "回答表にも記録にもない事柄と、公募要領にない事柄を含む設定": ["testdata/回答表/T0-10_設定.json"],
    "台本（前の版を見る・戻す、食い違う答え、交付決定前の発注の相談、4種類の指摘、「今回だけ」の指示とどちらとも取れる指示、記録の手直し）": [
        "testdata/台本/台本.json", "testdata/台本/確かめること.json"],
    "正しい書類セットと、不備を仕込んだ書類セット（不備の種類15以上。PDF、写真、Word、Excel を含み、仕込んだ不備の一覧つき）": [
        "testdata/書類セット/正しいセット/*", "testdata/書類セット/不備を仕込んだセット/*", "testdata/書類セット/仕込んだ不備の一覧.json"],
    "1つ足し、1つ書き換え、1つ動かし、1つ名前を変えた書類セット": [
        "testdata/書類の変化/開いたときの確認/前/**/*", "testdata/書類の変化/開いたときの確認/後/**/*", "testdata/書類の変化/正解.json"],
    "散らばった書類11件（名前がばらばら。種類が分かるもの8件、分からないもの2件、同じ中身のもの1件）": [
        "testdata/書類の変化/散らばった書類/**/*"],
    "取り直した納税証明書、記録と違う従業員数の書類": [
        "testdata/書類の変化/取り直した納税証明書/*", "testdata/書類の変化/従業員数の食い違い/*"],
    "過去の申請書1件と、その採否の通知・受けた指摘のメモ": [
        "testdata/会社の資料/材料/2025_ものづくり補助金_事業計画書の控え.docx",
        "testdata/会社の資料/材料/2025_ものづくり補助金_採択結果の通知.pdf",
        "testdata/会社の資料/材料/2025_ものづくり補助金_不採択の後の相談のメモ.docx"],
    "不採択の通知と、不採択の後の相談で受けた指摘のメモ": [
        "testdata/会社の資料/材料/2025_ものづくり補助金_採択結果の通知.pdf",
        "testdata/会社の資料/材料/2025_ものづくり補助金_不採択の後の相談のメモ.docx"],
    "会社の資料（会社案内、議事録〈現場の困りごとの話し合い〉、商品の資料、作業の写真）": [
        "testdata/会社の資料/材料/会社案内.pdf", "testdata/会社の資料/材料/議事録_*.docx",
        "testdata/会社の資料/材料/商品のご案内.pdf", "testdata/会社の資料/材料/作業の写真_*.jpg"],
    "既存事業の売上と経費の内訳（商品・取引先の種類ごと）": ["testdata/会社の資料/材料/既存事業の売上と経費_*.xlsx"],
    "スキャンした PDF と写真の見積書・請求書・納品書（読みにくいものを含む）と、金額と明細の正解": [
        "testdata/スキャン/材料/*.pdf", "testdata/スキャン/材料/*.jpg", "testdata/スキャン/正解.json"],
    "経費のメモ（手書きの写真を含む。補助の対象にならない経費を1つ含む）と、経費明細の正解": [
        "testdata/スキャン/材料/IMG_2745.jpg", "testdata/スキャン/経費明細の正解.json"],
    "架空の差し戻し文5件": ["testdata/計画書/材料/5_差し戻し/差し戻し_*"],
    "聞き取りの内容と違う記述を混ぜた計画書": ["testdata/計画書/材料/2_食い違いを混ぜた計画書/本文.json"],
    "質問20問とその正解（省力化と持続化）": ["testdata/質問/質問.json", "testdata/質問/正解.json"],
    "公募要領の新旧2版（実際の改訂版や前の回と新しい回、または一部を書き換えた版）": [
        "testdata/制度データ/新旧2版の正解.json", "testdata/制度データ/make_materials.py"],
    "制度データの正解（省力化と持続化。義務・返還条件を含む）": [
        "testdata/正解/省力化_第8回.json", "testdata/正解/省力化_第8回_義務と返還条件.json",
        "testdata/正解/持続化_第20回.json", "testdata/正解/持続化_第20回_義務と返還条件.json"],
    "模擬の申請画面": ["mock/screen.py", "mock/server.py", "mock/screen_jizokuka.py", "mock/server_jizokuka.py"],
    "社長の答えがないと直せない指摘を含む計画書": ["testdata/計画書/材料/3_社長の答えが要る計画書/本文.json"],
    "社長が言い回しを手で直した計画書の Word": ["testdata/計画書/make_plans.py", "testdata/計画書/正解.json"],
    "出典のページと違う値、そのページにない根拠の文、2回の読み取りで食い違う重要な項目を混ぜた制度データ": [
        "testdata/制度データ/混ぜたものの一覧.json", "testdata/制度データ/make_materials.py"],
    "そのページにない引用を付けた答え": ["testdata/制度データ/混ぜたものの一覧.json", "testdata/制度データ/make_materials.py"],
    "計画を下回る実績（採択後の年度分）": [
        "testdata/計画書/材料/6_計画を下回る実績/実績_1年目.json", "testdata/計画書/材料/6_計画を下回る実績/財務モデルの指定.json"],
    "架空の採択の通知と交付決定の通知（日付入り）、決算日をまたぐ納税証明書": [
        "testdata/期限/材料/通知/*採択*.pdf", "testdata/期限/材料/通知/*交付決定*.pdf", "testdata/期限/材料/納税証明書/*.pdf",
        "testdata/期限/正解.json"],
    "台本（外部への依頼で「依頼した」と伝える、目安の日数を聞かれたときの答え、届いた書類を入れる）": [
        "testdata/期限/台本_外部への依頼.md"],
}

# SPEC F14 のデモの会社の書類（「など」の前に挙がった9種類）→ testdata/デモの会社/書類/ のファイルの名前の頭
DEMO_DOCUMENTS = {
    "決算書": "決算書_", "履歴事項全部証明書": "履歴事項全部証明書", "納税証明書": "納税証明書", "見積書": "見積書_",
    "カタログ": "カタログ_", "法人事業概況説明書": "法人事業概況説明書", "役員名簿": "役員名簿", "株主名簿": "株主名簿",
    "労働者名簿": "労働者名簿",
}


def spec_rows() -> Dict[str, List[str]]:
    """SPEC F14 の材料の表（材料 → 使うテスト）。"""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("| 材料 | 使うテスト |")
    rows: Dict[str, List[str]] = {}
    for line in text[start:].splitlines()[2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows[cells[0]] = re.findall(r"T\d+-\d+b?", cells[1])
    return rows


def files_of(pattern: str) -> List[Path]:
    if any(c in pattern for c in "*?["):
        return sorted(p for p in REPO_ROOT.glob(pattern) if p.is_file() and p.name != ".DS_Store")
    p = REPO_ROOT / pattern
    return [p] if p.is_file() else []


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_spec_rows_match_materials() -> None:
    """SPEC F14 の材料の表の行と、この対応表の行が同じ（表が変わったら、対応表を直す）。"""
    rows = spec_rows()
    assert len(rows) >= 28
    assert sorted(rows) == sorted(MATERIALS)
    # デモの会社の回答表だけは「振る舞いテスト全般」で、テスト番号を挙げていない
    assert [k for k, tests in rows.items() if not tests] == ["デモの会社の回答表"]


@pytest.mark.parametrize("material", sorted(MATERIALS))
def test_material_files_exist(material: str) -> None:
    """表の行ごとに、材料のファイルがすべてある（空でない）。"""
    for pattern in MATERIALS[material]:
        found = files_of(pattern)
        assert found, f"{material}：{pattern} がない"
        for p in found:
            assert p.stat().st_size > 0, p


def test_demo_documents() -> None:
    """デモの会社の書類が、SPEC F14 に挙がった9種類そろう。"""
    names = [p.name for p in (TD / "デモの会社" / "書類").iterdir() if p.is_file()]
    for kind, head in DEMO_DOCUMENTS.items():
        assert any(n.startswith(head) for n in names), kind


def test_answer_tables() -> None:
    """回答表の変種は、デモの会社の回答表と同じ ID の行を持ち、架空の印がある。"""
    row = re.compile(r"^\| ([A-K]-\d{2}) \|", re.M)
    demo = row.findall((TD / "デモの会社" / "回答表.md").read_text(encoding="utf-8"))
    assert len(demo) >= 100
    for name in ("所在地_大都市", "所在地_県庁所在地", "所在地_町村", "従業員25人", "賃上げの計画が立たない", "情報を一部抜いた"):
        text = (TD / "回答表" / f"{name}.md").read_text(encoding="utf-8")
        assert row.findall(text) == demo, name
        assert MARK in text, name
    t0_10 = json.loads((TD / "回答表" / "T0-10_設定.json").read_text(encoding="utf-8"))
    assert t0_10["テスト"] == "T0-10" and t0_10["会社のこと"]["見る語"] and t0_10["制度のこと"]["見る語"]


def test_defect_set_has_list() -> None:
    """不備を仕込んだセットに、不備の一覧が付く（種類15以上。一覧の書類がセットにある）。2つのセットに PDF・写真・Word・Excel がある。"""
    listed = json.loads((TD / "書類セット" / "仕込んだ不備の一覧.json").read_text(encoding="utf-8"))
    defects = listed["不備"]
    assert len({d["種類"] for d in defects}) >= 15
    assert all(d.get("重さ") and d.get("直し方") for d in defects)
    defect_dir = TD / "書類セット" / "不備を仕込んだセット"
    in_set = {p.name for p in defect_dir.iterdir() if p.is_file()}
    for d in defects:
        for doc in d["書類"]:
            assert doc in in_set, (d["id"], doc)
    for f in listed["ファイル"]:
        assert f["ファイル"] in in_set
    for folder in ("正しいセット", "不備を仕込んだセット"):
        suffixes = {p.suffix.lower() for p in (TD / "書類セット" / folder).iterdir() if p.is_file()}
        assert {".pdf", ".jpg", ".docx", ".xlsx"} <= suffixes, folder


def test_scattered_documents_count() -> None:
    """散らばった書類は11件。"""
    files = files_of("testdata/書類の変化/散らばった書類/**/*")
    assert len(files) == 11


def test_sendbacks_and_questions() -> None:
    """差し戻し文は5件。質問は20問（答えが資料にある15問、ない5問）で、省力化と持続化の両方。"""
    assert len(files_of("testdata/計画書/材料/5_差し戻し/差し戻し_*")) == 5
    answers = json.loads((TD / "質問" / "正解.json").read_text(encoding="utf-8"))["正解"]
    kinds = [a["区分"] for a in answers]
    assert len(answers) == 20 and kinds.count("資料にある") == 15 and kinds.count("資料にない") == 5
    assert len({a["案件"] for a in answers}) == 2


def test_scripts_cover_tests() -> None:
    """台本が SPEC の台本の行のテストを、期限の台本が T6-6 をまかなう。"""
    scripts = json.loads((TD / "台本" / "台本.json").read_text(encoding="utf-8"))
    used = {t for s in (scripts["台本"] if isinstance(scripts, dict) else scripts) for t in s["使うテスト"]}
    row = next(k for k in MATERIALS if k.startswith("台本（前の版"))
    assert set(spec_rows()[row]) <= used
    assert "T6-6" in (TD / "期限" / "台本_外部への依頼.md").read_text(encoding="utf-8")


@pytest.mark.slow
def test_from_downloads_seido_materials(tmp_path: Path) -> None:
    """downloads/ から、公募要領の新旧2版・混ぜた制度データ・引用つきの答えを作れる（D10）。"""
    mm = load("seido_make_materials", TD / "制度データ" / "make_materials.py")
    if not mm.have_downloads():
        pytest.skip("downloads/ に省力化 第8回の資料がない")
    built = mm.build(tmp_path.resolve())
    assert set(built["読み取り"]) == {1, 2}
    assert len(built["T4-2"]) == len(mm.ANSWERS)
    assert set(built["T7-1"]) == {"変更あり", "変更なし"}
    for kind, company in built["T7-1"].items():
        root = mm._text_root(company)
        assert (root / "要領8").is_dir() and (root / mm.NEW_ID).is_dir(), kind


@pytest.mark.slow
def test_from_downloads_hand_edited_word(tmp_path: Path) -> None:
    """downloads/ の公式の様式から、社長が言い回しを手で直した計画書の Word を作れる（D9）。"""
    mp = load("keikakusho_make_plans", TD / "計画書" / "make_plans.py")
    if not mp.FORM.exists():
        pytest.skip("downloads/ に省力化の事業計画書（その1・2）の様式がない")
    made = mp.build_words(tmp_path)
    edited = f"{mp.PLAN_EDITED}/その1・2_社長が直した版.docx"
    assert edited in made
    assert (tmp_path / edited).stat().st_size > 0
    assert (tmp_path / edited).read_bytes() != (tmp_path / f"{mp.PLAN_EDITED}/その1・2_ツールが書いた版.docx").read_bytes()
