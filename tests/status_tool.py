"""2つの案件を進めた会社のフォルダを置くテストの部品（T6-2・T0-5。TASKS B27）。

- 1件目：省力化（一般型）第9回。申請と交付申請の提出版があり、事業の完了（2028-01-31）の後の実績報告の段階。
  計画書の Word（公式の様式に D9 の本文を書いたもの。tests/plan_tool.py と同じ書き方）は、項目の一部だけを書き、
  1つに仮の印を入れる。交付申請の見積書の写しは、古い原本から作ってあり、同じ相手先の新しい見積書の原本も台帳にある。
- 2件目：持続化（通常枠）第20回。申請の提出版があり、見積書等の提出の段階。見積書等を業者に頼んだ（依頼した）。
- 今日は 2028-02-10。決算は3月。制度データは testdata/正解/ の正解（省力化には tests/data/gimu/ の義務を足す）。
- 画面と Excel は、lib/status_view.py・lib/status_book.py の道具で作る。読むための小さな読み取り（表と、Excel のシート）も置く。
"""

from __future__ import annotations

import copy
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET

import hook_runner as hr
import plan_tool as pt

TODAY = "2028-02-10"
CASE_A = "2026_省力化（一般型）第9回"
CASE_B = "2026_持続化（通常枠）第20回"
JIZOKUKA = hr.REPO_ROOT / "testdata" / "正解" / "持続化_第20回.json"
DUTIES = hr.REPO_ROOT / "tests" / "data" / "gimu" / "省力化_第8回_義務.json"
WORD = f"案件/{CASE_A}/1_申請/申請書/その1・2.docx"
OLD_QUOTE = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"
NEW_QUOTE = "原本/見積・契約・請求/2027-06-07_見積書_つばさ台フードシステム.pdf"
REGISTRY = "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf"
COPY = f"案件/{CASE_A}/2_交付申請/添付する書類/見積書_つばさ台フードシステム.pdf"
VENDOR = "株式会社つばさ台フードシステム"
PROVISIONAL_ITEM = 1  # 本文.json の項目の番号（0から）。仮の印を入れる
UNWRITTEN = 2  # 後ろから数えて、書かない項目の数


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def original(n: int, place: str, kind: str, day: str, partner: str = "") -> dict:
    return {"id": f"原本-{n:04d}", "場所": place, "区分": place.split("/")[1], "種類": kind, "日付": day,
            "相手先": partner, "補足": "", "元の名前": Path(place).name, "元の場所": f"入れ口/{Path(place).name}",
            "ハッシュ": f"{n:064x}", "版の印": "0" * 40, "大きさ": 100, "整理した日時": f"{day}T10:00:00+09:00"}


def plan_items() -> List[dict]:
    items = copy.deepcopy(pt.plan()["項目"])
    items[PROVISIONAL_ITEM]["本文"] += "\n【仮：導入の時期は社長に確かめる】"
    return items[:-UNWRITTEN]


def build(folder: Path) -> None:
    """2つの案件を進めた会社のフォルダの中身を置く（目印の .hojokin/ は、呼ぶ側が用意する）。"""
    folder = Path(folder)
    (folder / ".hojokin").mkdir(parents=True, exist_ok=True)
    seido_a = pt.seido_with_positions()
    seido_a["義務"] = json.loads(DUTIES.read_text(encoding="utf-8"))["義務"]
    write_json(folder / "記録" / "制度データ" / "省力化_第8回.json", seido_a)
    write_json(folder / "記録" / "制度データ" / "持続化_第20回.json", json.loads(JIZOKUKA.read_text(encoding="utf-8")))
    write_json(folder / "記録" / "資料の本文" / CASE_A / "資料の一覧.json",
               {"案件": CASE_A, "制度": {"名前": "中小企業省力化投資補助金", "略称": "省力化", "公募回": "第8回"},
                "案件の回": "第9回", "資料": []})
    write_json(folder / "記録" / "資料の本文" / CASE_B / "資料の一覧.json",
               {"案件": CASE_B, "制度": {"名前": "小規模事業者持続化補助金", "略称": "持続化", "公募回": "第20回"},
                "案件の回": "第20回", "資料": []})
    for case, stages in ((CASE_A, ("1_申請", "2_交付申請", "3_実績報告")), (CASE_B, ("1_申請", "2_見積書等の提出"))):
        for stage in stages:
            for sub in ("申請書", "添付する書類"):
                (folder / "案件" / case / stage / sub).mkdir(parents=True, exist_ok=True)
    form = pt.form_or_skip()
    path = folder / WORD
    path.write_bytes(pt.word(form, plan_items()))
    copy_path = folder / COPY
    copy_path.write_bytes(b"%PDF-1.4 copy of the old quote")
    write_json(folder / "記録" / "期限の台帳.json", {
        "出来事": [
            {"案件": CASE_A, "名前": "採択発表", "日付": "2027-04-16", "状態": "確定", "出典": "社長の答え", "記録した日": "2027-04-20"},
            {"案件": CASE_A, "名前": "交付決定", "日付": "2027-06-25", "状態": "確定", "出典": "社長の答え", "記録した日": "2027-06-28"},
            {"案件": CASE_A, "名前": "補助事業の完了", "日付": "2028-01-31", "状態": "確定", "出典": "社長の答え", "記録した日": "2028-02-05"},
            {"案件": CASE_B, "名前": "採択発表", "日付": "2027-03-12", "状態": "確定", "出典": "社長の答え", "記録した日": "2027-03-15"},
        ],
        "作業": [
            {"種類": "依頼", "案件": CASE_B, "書類": "見積書等（相見積を含む）", "依頼先": "業者", "目安の日数": 7,
             "目安の出どころ": "会社の記録（前に社長に聞いた日数）", "状態": "依頼した", "頼む人": "社長",
             "依頼した日": "2028-02-05", "届いた日": "", "届いた書類": "", "記録した日": "2028-02-05"},
        ]})
    write_json(folder / "記録" / "書類の台帳.json", {"説明": "", "原本": [
        original(1, OLD_QUOTE, "見積書", "2026-10-20", VENDOR),
        original(2, REGISTRY, "履歴事項全部証明書", "2026-10-22"),
        original(3, NEW_QUOTE, "見積書", "2027-06-07", VENDOR),
    ], "写し": [
        {"id": "写し-0001", "場所": COPY, "案件": CASE_A, "段階": "2_交付申請", "書類": "見積書",
         "元の原本": [{"id": "原本-0001", "場所": OLD_QUOTE, "ハッシュ": f"{1:064x}", "日付": "2026-10-20"}],
         "ハッシュ": "f" * 64, "大きさ": 30, "整え方": [], "作った日時": "2027-05-20T09:00:00+09:00"},
    ], "確かめ済み": []})
    write_json(folder / "記録" / "提出版.json", {"提出版": [
        {"案件": CASE_A, "段階": "1_申請", "番号": 1, "日時": "2026-12-20T10:00:00+09:00", "版": "0" * 40,
         "ファイル": [{"書類": WORD, "大きさ": path.stat().st_size, "sha256": "0" * 64}]},
        {"案件": CASE_A, "段階": "2_交付申請", "番号": 1, "日時": "2027-05-28T10:00:00+09:00", "版": "0" * 40,
         "ファイル": [{"書類": COPY, "大きさ": copy_path.stat().st_size, "sha256": "0" * 64}]},
        {"案件": CASE_B, "段階": "1_申請", "番号": 1, "日時": "2026-12-10T10:00:00+09:00", "版": "0" * 40, "ファイル": []},
    ]})
    write_json(folder / "記録" / "会社の記録.json", {"項目": [
        {"id": "事実-0001", "種類": "事実", "名前": "決算月", "値": "3月"}]})
    settings = folder / ".hojokin" / "設定.json"
    value = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    value["今日の日付"] = TODAY
    write_json(settings, value)


# ---- 読み取り ----


class Tables(HTMLParser):
    """HTML の表を、直前の h2 の見出しごとに、行（セルの文字の並び）にして集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.head = ""
        self.in_h2 = False
        self.tables: Dict[str, List[List[str]]] = {}
        self.row: List[str] = []
        self.cell: List[str] = []
        self.in_cell = False
        self.classes: Dict[str, List[List[str]]] = {}
        self.row_classes: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.in_h2, self.head = True, ""
        elif tag == "tr":
            self.row, self.row_classes = [], []
        elif tag in ("td", "th"):
            self.in_cell, self.cell = True, []
            self.row_classes.append(dict(attrs).get("class") or "")
        elif tag == "br" and self.in_cell:
            self.cell.append("/")

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_h2 = False
        elif tag in ("td", "th"):
            self.in_cell = False
            self.row.append("".join(self.cell).strip())
        elif tag == "tr":
            self.tables.setdefault(self.head, []).append(self.row)
            self.classes.setdefault(self.head, []).append(self.row_classes)

    def handle_data(self, data):
        if self.in_h2:
            self.head += data
        elif self.in_cell:
            self.cell.append(data)


def html_tables(text: str) -> Tables:
    t = Tables()
    t.feed(text)
    return t


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def xlsx_sheets(path: Path) -> Dict[str, List[List[str]]]:
    """xlsx のシートごとの行（セルの文字。列の場所どおりに並べ、空のセルは ""）。"""
    out: Dict[str, List[List[str]]] = {}
    with zipfile.ZipFile(path) as z:
        book = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sheet in enumerate(book.find("m:sheets", NS), 1):
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            rows = []
            for row in root.find("m:sheetData", NS):
                values: Dict[int, str] = {}
                for c in row:
                    ref = c.get("r")
                    col = 0
                    for ch in ref:
                        if ch.isalpha():
                            col = col * 26 + (ord(ch) - 64)
                    text = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                    if not text:
                        v = c.find("m:v", NS)
                        text = v.text if v is not None else ""
                    values[col - 1] = text
                rows.append([values.get(j, "") for j in range(max(values) + 1)] if values else [])
            out[sheet.get("name")] = rows
    return out
