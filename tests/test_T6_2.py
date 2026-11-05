"""T6-2 画面と Excel（SPEC F6「今の状態」、DESIGN 4.6。TASKS B27）。

合格ライン：2つの案件の状態から HTML と Excel を作る → 両方に期待する値（書類ごとの原本か写しか、場所、提出版、
最後に変えた日、写しの元の原本、様式の項目ごとの申請書の進み具合、5年先までの期限を含む）が入り、一致する。
工程表に、両案件の段階・期限・今日の線が入る。期限ごとに、見込みか確定か、だれがするか、依頼の状態が入る。
書類を1つ足して作り直すと一覧に加わる。

材料は tests/status_tool.py（省力化 第9回は事業の完了の後、持続化 第20回は見積書等の提出の段階。今日 2028-02-10）。
計画書の Word は公式の様式から作るので、downloads/ がなければ飛ばす。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import status_tool as st
from lib import deadlines, status_book, status_view

PAGE = "今の状態.html"
BOOK = "今の状態.xlsx"


def make(tmp_path: Path) -> Path:
    folder = tmp_path / "やまぶき 惣菜"
    st.build(folder)
    assert status_view.refresh_page(folder) is None
    return folder


def page_and_book(folder: Path):
    tables = st.html_tables((folder / PAGE).read_text(encoding="utf-8"))
    return tables, st.xlsx_sheets(folder / BOOK)


def body(rows):
    """見出しの行を除いた行（空の行も除く）。"""
    return [tuple(r) for r in rows[1:] if any(r)]


@pytest.mark.slow
def test_page_and_book_have_the_same_values(tmp_path: Path) -> None:
    folder = make(tmp_path)
    tables, sheets = page_and_book(folder)
    assert set(sheets) == {"締切", "工程表", "作業", "書類", "不備", "申請書", "変更の履歴"}

    # ---- 書類：原本か写しか・場所・提出版・最後に変えた日・写しの元の原本（と、元の原本より新しい原本） ----
    page_docs = body(tables.tables["書類"])
    book_docs = body(sheets["書類"])
    assert page_docs == book_docs  # 一致する
    assert tuple(sheets["書類"][0]) == tuple(status_book.DOC_HEAD)
    by_place = {r[4]: r for r in book_docs}
    assert by_place[st.OLD_QUOTE][:2] == ("原本", "見積書") and by_place[st.OLD_QUOTE][6] == "2026-10-20"
    assert by_place[st.OLD_QUOTE][2] == "（案件をまたぐ）"
    copy = by_place[st.COPY]
    assert copy[:4] == ("写し", "見積書", st.CASE_A, "2_交付申請")
    assert copy[5] == "2_交付申請 1回目（2027-05-28）" and copy[6] == "2027-05-20"
    assert copy[7] == st.OLD_QUOTE and copy[8] == st.NEW_QUOTE  # 元の原本が新しくなっている
    word = by_place[st.WORD]
    assert word[:4] == ("申請書", "その1・2.docx", st.CASE_A, "1_申請")
    assert word[5] == "1_申請 1回目（2026-12-20）" and len(word[6]) == 10

    # ---- 申請書：様式の項目ごとの進み具合（まだ・下書き・仮の印あり）と文字数 ----
    page_forms = body(tables.tables["申請書（様式の項目ごとの進み具合）"])
    book_forms = [tuple(str(v) for v in r) for r in body(sheets["申請書"])]
    assert page_forms == book_forms
    items = st.pt.plan()["項目"]
    states = {(r[0], r[3]): r[4] for r in book_forms}
    assert states[(st.CASE_A, items[0]["名前"])] == "下書き"
    assert states[(st.CASE_A, items[st.PROVISIONAL_ITEM]["名前"])] == "仮の印あり"
    assert states[(st.CASE_A, items[-1]["名前"])] == "まだ"
    longest = max(st.plan_items(), key=lambda it: len(it["本文"]))
    written = next(r for r in book_forms if r[3] == longest["名前"])
    assert int(written[5]) > 100  # 文字数
    assert any(r[0] == st.CASE_B for r in book_forms)  # 2件目の様式の項目も並ぶ

    # ---- 5年先までの期限（年ごと） ----
    years = [r for r in body(sheets["締切"]) if r and r[2:3] and r[2].endswith("年目")]
    assert [r[2] for r in years] == [f"{n}年目" for n in range(1, 6)]
    for n, (r, year) in enumerate(zip(years, range(2029, 2034)), 1):
        assert r[0] == st.CASE_A and f"提出期間 {year}年4月1日" in r[3] and f"{year}年6月30日" in r[3], r
    page_years = body(tables.tables["長い期限（効果報告など、年ごと）"])
    assert page_years == [tuple(r) for r in years]

    # ---- 期限ごとの見込みか確定か・だれがするか・依頼の状態 ----
    tasks = body(sheets["締切"])
    request = next(r for r in tasks if r[4].startswith("見積書等（相見積を含む）を頼む"))
    assert request[3] == st.CASE_B and request[5] == "確定" and request[6] == "頼む：社長／書く：外部（業者）"
    assert request[7] == "依頼した"
    report = next(r for r in tasks if r[4] == "実績報告の期限")
    assert report[3] == st.CASE_A and report[5] == "確定" and "2028年3月1日" in report[1]
    estimate = next(r for r in tasks if r[4].startswith("事業場内最低賃金を確かめる"))
    assert estimate[5] == "見込み"
    page_rows = {tuple(r) for rows in tables.tables.values() for r in rows}
    for r in tasks:
        if r[0] in deadlines.GROUPS:  # 画面の表にも、同じ締切・案件・期限の名前・見込みか確定か・だれ・依頼の状態がある
            assert any(p[0] == r[1] and p[2:8] == (r[3], r[4], r[5], r[6], r[7], r[8]) for p in page_rows), r

    # ---- 工程表：両案件の段階・期限・今日の線 ----
    gantt = tables.tables["工程表"]
    head = gantt[0]
    today_col = head.index("2/2028") if "2/2028" in head else None
    classes = tables.classes["工程表"]
    marked = [i for i, c in enumerate(classes[0]) if "g-today" in c]
    assert len(marked) == 1  # 今日の線は1本（2028年2月の列）
    rows = gantt[1:]
    assert {r[0] for r in rows} == {st.CASE_A, st.CASE_B}
    labels_a = [r[1] for r in rows if r[0] == st.CASE_A]
    assert any(x.startswith("交付申請") for x in labels_a) and any(x.startswith("実績報告") for x in labels_a)
    assert [x for x in labels_a if "効果報告" in x][0].startswith("事業実施効果報告 1年目")
    labels_b = [r[1] for r in rows if r[0] == st.CASE_B]
    assert any(x.startswith("見積書等の提出") for x in labels_b) and any(x.startswith("実績報告") for x in labels_b)
    assert all("◆" in r for r in rows)  # どの帯にも期限の印
    assert all("g-today" in classes[i + 1][marked[0]] for i in range(len(rows)))  # 今日の線は全部の行を通る
    book_gantt = sheets["工程表"]
    assert book_gantt[1][book_gantt[0].index("2028年2月")] == "▼今日"
    assert [tuple(r[:3]) for r in book_gantt[2:]] == [tuple(r[:3]) for r in [(r[0], r[1].rsplit("（", 1)[0], r[2])
                                                                               for r in rows]]
    for page_row, book_row in zip(rows, book_gantt[2:]):  # 期限の印の月が同じ
        assert page_row[3:].index("◆") == book_row[4:].index("◆"), (page_row, book_row)
    assert today_col is None or today_col >= 0


@pytest.mark.slow
def test_adding_a_document_adds_a_row(tmp_path: Path) -> None:
    folder = make(tmp_path)
    ledger_path = folder / "記録" / "書類の台帳.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    place = "原本/決算・税/2027-06-07_納税証明書（その2）.pdf"
    ledger["原本"].append(st.original(4, place, "納税証明書（その2）", "2027-06-07"))
    st.write_json(ledger_path, ledger)
    assert status_view.refresh_page(folder) is None
    tables, sheets = page_and_book(folder)
    assert any(r[4] == place and r[0] == "原本" for r in body(sheets["書類"]))
    assert any(r[4] == place for r in body(tables.tables["書類"]))
    assert body(tables.tables["書類"]) == body(sheets["書類"])


@pytest.mark.slow
def test_same_content_is_not_rewritten(tmp_path: Path) -> None:
    """中身が同じなら、画面も Excel も書き直さない（同じバイト列）。"""
    folder = make(tmp_path)
    before = {name: (folder / name).read_bytes() for name in (PAGE, BOOK)}
    stamps = {name: (folder / name).stat().st_mtime_ns for name in (PAGE, BOOK)}
    assert status_view.refresh_page(folder) is None
    assert {name: (folder / name).read_bytes() for name in (PAGE, BOOK)} == before
    assert {name: (folder / name).stat().st_mtime_ns for name in (PAGE, BOOK)} == stamps
