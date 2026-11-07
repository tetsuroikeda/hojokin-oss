# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の書類の前半を作る。

作るもの：決算書（第34期・第35期・第36期）、履歴事項全部証明書、納税証明書（その2）、法人事業概況説明書（第36期）
（ここまで PDF）と、役員名簿・株主名簿（Word）、労働者名簿（Excel）。
数字と事実は testdata/デモの会社_町工場/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
ID のない数字は回答表にないもので、書類の一覧.md の「回答表にない数字と事実」に挙げた。

作り方は testdata/デモの会社/書類/make_documents.py（やまぶき惣菜）に合わせた。
どのページ・どのシートにも「架空のテスト用データ」を出す。公印・透かし・役所の様式の配置は写さない。
同じ中身なら同じバイト列になるよう、PDF は invariant で、Word と Excel は zip の時刻と作成日時をそろえて作る。

動かし方：uv run --script testdata/デモの会社_町工場/書類/make_documents.py
"""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT_DIR = Path(__file__).resolve().parent

GOTHIC = "HeiseiKakuGo-W5"
MINCHO = "HeiseiMin-W3"
pdfmetrics.registerFont(UnicodeCIDFont(GOTHIC))
pdfmetrics.registerFont(UnicodeCIDFont(MINCHO))

PAGE_W, PAGE_H = A4
LEFT = 60
RIGHT = PAGE_W - 60
TOP = PAGE_H - 92
BANNER = "架空のテスト用データ（hojokin-oss）　実在の会社・人物・役所とは関係ありません。本物の書類ではありません。"
BANNER_FILL = Color(1.0, 0.95, 0.75)
BANNER_LINE = Color(0.85, 0.6, 0.0)
FIXED_TIME = dt.datetime(2026, 11, 7, 0, 0, 0)

# ---------------------------------------------------------------------------
# 会社の事実（回答表の ID）
# ---------------------------------------------------------------------------

COMPANY = "株式会社みずなら精工"  # A-01
COMPANY_KANA = "ミズナラセイコウ"  # A-02
CORPORATE_NUMBER = "2011801088452"  # A-03
# 会社法人等番号は、法人番号から先頭の検査用の数字を除いた12桁
REGISTRY_NUMBER = f"{CORPORATE_NUMBER[1:5]}-{CORPORATE_NUMBER[5:7]}-{CORPORATE_NUMBER[7:]}"
POSTAL_CODE = "124-0025"  # B-02
ADDRESS = "東京都葛飾区西新小岩九丁目7番3号"  # B-01
PRESIDENT = "真柴 浩一"  # A-08
PRESIDENT_KANA = "ましば こういち"  # A-08
DIRECTOR = "真柴 典子"  # A-09
DIRECTOR_KANA = "ましば のりこ"
# 役員の住所（回答表にない）。西新小岩は五丁目までとみて、ない丁目にした（確かめていない。書類の一覧.md）。
# 取締役は社長の母で、別に住んでいる（A-09）
PRESIDENT_ADDRESS = "東京都葛飾区西新小岩八丁目2番15号"
DIRECTOR_ADDRESS = "東京都葛飾区西新小岩六丁目11番4号"
SHARES_ISSUED = 400  # A-07
SHAREHOLDERS = [(PRESIDENT, 280), (DIRECTOR, 120)]  # A-07

# 役員の就任と重任（回答表にない）。代表の交代は2016年（A-05）。任期10年として2026年6月に重任
REAPPOINTED = "令和8年6月26日"
REAPPOINTED_REGISTERED = "令和8年7月3日"

# ---------------------------------------------------------------------------
# 決算の数字（千円）。書類には円で出す
# ---------------------------------------------------------------------------

PERIODS = {
    34: {
        "start": "令和5年4月1日",
        "end": "令和6年3月31日",
        # 損益：F-01〜F-05（第34期）に合うよう、内訳は回答表にない数字で組んだ
        # （給与の合計 D-04、役員報酬 D-05、減価償却費 F-06、法定福利費 F-07 には合わせた）
        "sales": 290_000,  # F-01
        # 材料費 63,000 ＝ 期首の原材料 3,900 ＋ 仕入 63,200 − 期末の原材料 4,100（第35期の期首）
        "materials_opening": 3_900,
        "materials_purchased": 63_200,
        # 仕掛品は期首 6,800、期末 7,200（第35期の期首）
        "wip_opening": 6_800,
        "labor": [("賃金給与", 60_900), ("法定福利費", 9_100)],
        "outsourcing": [("外注加工費", 45_500)],
        "overhead": [
            ("電力費", 10_300),
            ("工具・消耗品費", 13_900),
            ("地代家賃", 9_600),
            ("減価償却費", 16_600),
            ("修繕費", 2_900),
            ("その他製造経費", 1_500),
        ],
        "sga": [
            ("役員報酬", 13_800),  # D-05
            ("給料手当", 10_200),
            ("法定福利費", 3_400),
            ("福利厚生費", 1_100),
            ("荷造運賃", 3_200),
            ("旅費交通費", 1_400),
            ("通信費", 900),
            ("広告宣伝費", 400),
            ("支払手数料", 1_900),
            ("租税公課", 1_600),
            ("保険料", 1_400),
            ("減価償却費", 1_500),
            ("リース料", 2_200),
            ("消耗品費", 1_400),
            ("交際費", 700),
            ("その他", 3_100),
        ],
        "non_operating_income": [("雑収入", 300)],
        "non_operating_expenses": [("支払利息", 1_500)],
        "income_taxes": 2_500,
        # 貸借：回答表にない数字。第35期に減価償却 16,800、設備の取得 5,000（CAPEX_35）、借入金の返済 14,400 で
        # 第35期末になり、第35期の現金の増減とも合うようにした（現金は、ほかの科目を決めてから逆算した）
        "current_assets": [
            ("現金及び預金", 42_400),
            ("受取手形", 5_800),
            ("売掛金", 49_200),
            ("原材料", 4_100),
            ("仕掛品", 7_200),
            ("その他流動資産", 1_800),
        ],
        "tangible_assets": [
            ("建物附属設備", 4_600),
            ("機械及び装置", 75_900),
            ("車両運搬具", 2_800),
            ("工具、器具及び備品", 6_100),
        ],
        "intangible_assets": [("ソフトウエア", 1_900)],
        "investments": [("敷金及び保証金", 4_800), ("その他の投資", 1_200)],
        "current_liabilities": [
            ("買掛金", 26_500),
            ("1年内返済予定の長期借入金", 14_400),
            ("未払金及び未払費用", 9_200),
            ("未払法人税等", 1_600),
            ("その他流動負債", 3_400),
        ],
        "fixed_liabilities": [("長期借入金", 90_800)],
        "capital": 20_000,  # A-06
        "retained_opening": 36_700,  # 第34期末 41,900 − 当期純利益 5,200
    },
    35: {
        "start": "令和6年4月1日",
        "end": "令和7年3月31日",
        # 損益：F-01〜F-05（第35期）に合うよう、内訳は回答表にない数字で組んだ
        # （給与の合計 D-04、役員報酬 D-05、減価償却費 F-06、法定福利費 F-07 には合わせた）
        "sales": 302_000,  # F-01
        "materials_opening": 4_100,
        "materials_purchased": 68_200,
        "wip_opening": 7_200,
        "labor": [("賃金給与", 62_900), ("法定福利費", 9_400)],
        "outsourcing": [("外注加工費", 47_500)],
        "overhead": [
            ("電力費", 10_100),
            ("工具・消耗品費", 14_400),
            ("地代家賃", 9_600),
            ("減価償却費", 15_400),
            ("修繕費", 3_200),
            ("その他製造経費", 1_600),
        ],
        "sga": [
            ("役員報酬", 14_400),  # D-05
            ("給料手当", 10_500),
            ("法定福利費", 3_500),
            ("福利厚生費", 1_100),
            ("荷造運賃", 3_300),
            ("旅費交通費", 1_500),
            ("通信費", 900),
            ("広告宣伝費", 400),
            ("支払手数料", 1_900),
            ("租税公課", 1_700),
            ("保険料", 1_400),
            ("減価償却費", 1_400),
            ("リース料", 2_200),
            ("消耗品費", 1_400),
            ("交際費", 700),
            ("その他", 3_000),
        ],
        "non_operating_income": [("雑収入", 300)],
        "non_operating_expenses": [("支払利息", 1_400)],
        "income_taxes": 3_000,
        # 貸借：回答表にない数字。第36期に減価償却 15,500、設備の取得 6,000、借入金の返済 14,400 で
        # 第36期末（F-12・F-13）になり、第36期の現金の増減とも合うようにした
        "current_assets": [
            ("現金及び預金", 46_300),
            ("受取手形", 6_000),
            ("売掛金", 51_000),
            ("原材料", 4_300),
            ("仕掛品", 7_200),
            ("その他流動資産", 1_900),
        ],
        "tangible_assets": [
            ("建物附属設備", 4_200),
            ("機械及び装置", 66_200),
            ("車両運搬具", 2_300),
            ("工具、器具及び備品", 5_200),
        ],
        "intangible_assets": [("ソフトウエア", 1_600)],
        "investments": [("敷金及び保証金", 4_800), ("その他の投資", 1_200)],
        "current_liabilities": [
            ("買掛金", 27_900),
            ("1年内返済予定の長期借入金", 14_400),
            ("未払金及び未払費用", 9_500),
            ("未払法人税等", 2_000),
            ("その他流動負債", 3_600),
        ],
        "fixed_liabilities": [("長期借入金", 76_400)],
        "capital": 20_000,  # A-06
        "retained_opening": 41_900,  # 第35期末 48,400 − 当期純利益 6,500
    },
    36: {
        "start": "令和7年4月1日",
        "end": "令和8年3月31日",
        "sales": 311_000,  # F-01
        # 材料費 70,000（F-09）＝ 期首の原材料 4,300（第35期末）＋ 仕入 70,300 − 期末の原材料 4,600
        "materials_opening": 4_300,
        "materials_purchased": 70_300,
        # 仕掛品は期首・期末とも 7,200。当期総製造費用 ＝ 売上原価 248,600（F-09）
        "wip_opening": 7_200,
        "labor": [("賃金給与", 64_900), ("法定福利費", 9_700)],  # F-09
        "outsourcing": [("外注加工費", 49_000)],  # F-09
        "overhead": [  # F-09
            ("電力費", 10_200),
            ("工具・消耗品費", 14_800),
            ("地代家賃", 9_600),
            ("減価償却費", 14_200),
            ("修繕費", 3_600),
            ("その他製造経費", 2_600),
        ],
        "sga": [  # F-10
            ("役員報酬", 14_400),
            ("給料手当", 10_900),
            ("法定福利費", 3_600),
            ("福利厚生費", 1_200),
            ("荷造運賃", 3_400),
            ("旅費交通費", 1_600),
            ("通信費", 900),
            ("広告宣伝費", 500),
            ("支払手数料", 2_000),
            ("租税公課", 1_800),
            ("保険料", 1_400),
            ("減価償却費", 1_300),
            ("リース料", 2_200),
            ("消耗品費", 1_500),
            ("交際費", 700),
            ("その他", 3_000),
        ],
        "non_operating_income": [("雑収入", 400)],  # F-11（科目の名前は回答表にない）
        "non_operating_expenses": [("支払利息", 1_400)],  # F-11
        "income_taxes": 3_400,  # F-11
        "current_assets": [  # F-12（棚卸資産 11,800 を原材料 4,600 と仕掛品 7,200 に分けた）
            ("現金及び預金", 48_600),
            ("受取手形", 6_200),
            ("売掛金", 52_400),
            ("原材料", 4_600),
            ("仕掛品", 7_200),
            ("その他流動資産", 2_000),
        ],
        "tangible_assets": [  # F-12
            ("建物附属設備", 3_800),
            ("機械及び装置", 58_600),
            ("車両運搬具", 1_900),
            ("工具、器具及び備品", 4_400),
        ],
        "intangible_assets": [("ソフトウエア", 1_300)],  # F-12
        "investments": [("敷金及び保証金", 4_800), ("その他の投資", 1_200)],  # F-12
        "current_liabilities": [  # F-13
            ("買掛金", 28_600),
            ("1年内返済予定の長期借入金", 14_400),
            ("未払金及び未払費用", 9_800),
            ("未払法人税等", 2_400),
            ("その他流動負債", 3_800),
        ],
        "fixed_liabilities": [("長期借入金", 62_000)],  # F-13
        "capital": 20_000,  # A-06
        "retained_opening": 48_400,  # 第35期末の繰越利益剰余金（配当はしていない）
    },
}

# 期の中で取得した設備（千円。回答表にない）。前の期末の貸借を逆算するのに使う
CAPEX_35 = {"機械及び装置": 4_000, "工具、器具及び備品": 1_000}
CAPEX_36 = {"機械及び装置": 5_000, "工具、器具及び備品": 1_000}
CAPEX = {35: CAPEX_35, 36: CAPEX_36}

# 課税所得（F-08）。納税証明書（その2）の所得金額
TAXABLE_INCOME = [
    ("令和5年4月1日", "令和6年3月31日", 7_900),
    ("令和6年4月1日", "令和7年3月31日", 9_600),
    ("令和7年4月1日", "令和8年3月31日", 11_200),
]

# 第36期の月別の売上高（千円）。回答表にない数字。12か月の合計が F-01 の 311,000 になる
MONTHLY_SALES_36 = [
    ("令和7年4月", 25_100),
    ("5月", 24_300),
    ("6月", 26_000),
    ("7月", 25_800),
    ("8月", 22_900),
    ("9月", 26_400),
    ("10月", 26_700),
    ("11月", 26_200),
    ("12月", 27_100),
    ("令和8年1月", 24_000),
    ("2月", 26_500),
    ("3月", 30_000),
]

REGISTRY_ISSUED = "令和8年10月22日"
TAX_CERTIFICATE_ISSUED = "令和8年10月23日"


def total(rows: list[tuple[str, int]]) -> int:
    return sum(v for _, v in rows)


def figures(p: dict) -> dict:
    """期の数字から、合計と利益を計算する（千円）。"""
    f = {}
    assets = dict(p["current_assets"])
    f["materials_closing"] = assets["原材料"]
    f["wip_closing"] = assets["仕掛品"]
    f["materials"] = p["materials_opening"] + p["materials_purchased"] - f["materials_closing"]
    f["labor"] = total(p["labor"])
    f["outsourcing"] = total(p["outsourcing"])
    f["overhead"] = total(p["overhead"])
    f["manufacturing_total"] = f["materials"] + f["labor"] + f["outsourcing"] + f["overhead"]
    f["manufacturing"] = f["manufacturing_total"] + p["wip_opening"] - f["wip_closing"]
    f["cost_of_sales"] = f["manufacturing"]  # 製品の棚卸は期首・期末とも0
    f["gross_profit"] = p["sales"] - f["cost_of_sales"]
    f["sga"] = total(p["sga"])
    f["operating_income"] = f["gross_profit"] - f["sga"]
    f["ordinary_income"] = (
        f["operating_income"] + total(p["non_operating_income"]) - total(p["non_operating_expenses"])
    )
    f["pretax_income"] = f["ordinary_income"]  # 特別な損益はない（F-11）
    f["net_income"] = f["pretax_income"] - p["income_taxes"]
    f["retained_closing"] = p["retained_opening"] + f["net_income"]
    f["current_assets"] = total(p["current_assets"])
    f["tangible_assets"] = total(p["tangible_assets"])
    f["intangible_assets"] = total(p["intangible_assets"])
    f["investments"] = total(p["investments"])
    f["fixed_assets"] = f["tangible_assets"] + f["intangible_assets"] + f["investments"]
    f["assets"] = f["current_assets"] + f["fixed_assets"]
    f["current_liabilities"] = total(p["current_liabilities"])
    f["fixed_liabilities"] = total(p["fixed_liabilities"])
    f["liabilities"] = f["current_liabilities"] + f["fixed_liabilities"]
    f["equity"] = p["capital"] + f["retained_closing"]
    if f["assets"] != f["liabilities"] + f["equity"]:
        raise ValueError(f"貸借が合いません：資産 {f['assets']}、負債と純資産 {f['liabilities'] + f['equity']}")
    return f


def check_cash_flow(no: int) -> None:
    """第no期の現金の増減を間接法で出し、前の期末と第no期末の現金の差と合うかを確かめる。"""
    prev, cur = PERIODS[no - 1], PERIODS[no]
    capex = sum(CAPEX[no].values())
    f = figures(cur)
    a_prev, a_cur = dict(prev["current_assets"]), dict(cur["current_assets"])
    l_prev, l_cur = dict(prev["current_liabilities"]), dict(cur["current_liabilities"])
    depreciation = dict(cur["overhead"])["減価償却費"] + dict(cur["sga"])["減価償却費"]
    working = sum(a_prev[k] - a_cur[k] for k in a_prev if k != "現金及び預金")
    working += sum(l_cur[k] - l_prev[k] for k in l_prev if k != "1年内返済予定の長期借入金")
    operating = f["net_income"] + depreciation + working
    investing = -capex - (total(cur["investments"]) - total(prev["investments"]))
    loans_prev = l_prev["1年内返済予定の長期借入金"] + total(prev["fixed_liabilities"])
    loans_cur = l_cur["1年内返済予定の長期借入金"] + total(cur["fixed_liabilities"])
    financing = loans_cur - loans_prev
    change = a_cur["現金及び預金"] - a_prev["現金及び預金"]
    if operating + investing + financing != change:
        raise ValueError(f"第{no}期の現金の増減が合いません：{operating + investing + financing} ／ {change}")
    fixed_prev = total(prev["tangible_assets"]) + total(prev["intangible_assets"])
    fixed_cur = total(cur["tangible_assets"]) + total(cur["intangible_assets"])
    if fixed_prev + capex - depreciation != fixed_cur:
        raise ValueError(f"第{no - 1}期末の固定資産 ＋ 取得 − 減価償却費 が、第{no}期末と合いません")


def yen(thousand: int) -> str:
    return f"{thousand * 1000:,}"


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """文字の幅で折り返す（日本語は1文字ずつ切ってよい）。改行の文字でも行を分ける。"""
    lines = []
    for part in text.split("\n"):
        line = ""
        for ch in part:
            if pdfmetrics.stringWidth(line + ch, font, size) > width:
                lines.append(line)
                line = ch
            else:
                line += ch
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# ページを描く道具
# ---------------------------------------------------------------------------


class Page:
    def __init__(self, c: canvas.Canvas, doc_name: str, index: int, count: int):
        self.c = c
        self.y = TOP
        self.step = 15  # 科目の行の高さ
        # 頭の帯
        c.setFillColor(BANNER_FILL)
        c.setStrokeColor(BANNER_LINE)
        c.setLineWidth(1)
        c.rect(LEFT - 20, PAGE_H - 52, RIGHT - LEFT + 40, 26, fill=1, stroke=1)
        c.setFillColor(black)
        c.setFont(GOTHIC, 8.6)
        c.drawCentredString(PAGE_W / 2, PAGE_H - 42.5, BANNER)
        # 足
        c.setFont(GOTHIC, 8)
        c.drawCentredString(PAGE_W / 2, 30, f"架空のテスト用データ｜{doc_name}｜{index}/{count}ページ")
        c.setStrokeColor(black)
        c.setLineWidth(0.6)

    def title(self, text: str, size: float = 16) -> None:
        self.c.setFont(GOTHIC, size)
        self.c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= size + 10

    def center(self, text: str, size: float = 10.5) -> None:
        self.c.setFont(MINCHO, size)
        self.c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= size + 6

    def right(self, text: str, size: float = 9.5) -> None:
        self.c.setFont(MINCHO, size)
        self.c.drawRightString(RIGHT, self.y, text)
        self.y -= size + 6

    def gap(self, h: float = 8) -> None:
        self.y -= h

    def heading(self, text: str, size: float = 11) -> None:
        self.c.setFont(GOTHIC, size)
        self.c.drawString(LEFT, self.y, text)
        self.y -= size + 7

    def row(self, label: str, amount: str | None = None, indent: int = 0, bold: bool = False) -> None:
        """科目の名前と金額の1行。合計の行（bold）は上に線を引く。"""
        font = GOTHIC if bold else MINCHO
        if bold and amount is not None:
            self.c.line(RIGHT - 120, self.y + 11, RIGHT, self.y + 11)
        self.c.setFont(font, 10)
        self.c.drawString(LEFT + 16 * indent, self.y, label)
        if amount is not None:
            self.c.drawRightString(RIGHT, self.y, amount)
        self.y -= self.step

    def kv(self, key: str, value: str, key_width: float = 130, size: float = 10) -> None:
        """項目と中身の1組。中身は折り返す。"""
        lines = wrap(value, MINCHO, size, RIGHT - LEFT - key_width - 8)
        top = self.y + size + 3
        self.c.setFont(GOTHIC, size)
        self.c.drawString(LEFT + 4, self.y, key)
        self.c.setFont(MINCHO, size)
        for line in lines:
            self.c.drawString(LEFT + key_width, self.y, line)
            self.y -= size + 5
        bottom = self.y + size - 1
        self.c.rect(LEFT, bottom, RIGHT - LEFT, top - bottom, fill=0, stroke=1)
        self.c.line(LEFT + key_width - 6, bottom, LEFT + key_width - 6, top)
        self.y -= 4

    def para(self, text: str, indent: int = 0, size: float = 10, font: str = MINCHO) -> None:
        x = LEFT + 16 * indent
        for line in wrap(text, font, size, RIGHT - x):
            self.c.setFont(font, size)
            self.c.drawString(x, self.y, line)
            self.y -= size + 5

    def table(self, rows: list[list[str]], widths: list[float], header: bool = True, size: float = 9.5) -> None:
        """罫線のある表。1列目は左寄せ、ほかは右寄せ。"""
        h = size + 8
        x0 = LEFT
        for r, cells in enumerate(rows):
            self.c.setFont(GOTHIC if (header and r == 0) else MINCHO, size)
            x = x0
            for i, (cell, w) in enumerate(zip(cells, widths)):
                self.c.rect(x, self.y - 5, w, h, fill=0, stroke=1)
                if i == 0 or (header and r == 0):
                    self.c.drawString(x + 5, self.y, cell)
                else:
                    self.c.drawRightString(x + w - 5, self.y, cell)
                x += w
            self.y -= h
        self.y -= 6


def render(path: Path, doc_name: str, pages: list) -> None:
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"{doc_name}（架空のテスト用データ）")
    c.setAuthor("hojokin-oss のテスト用データ")
    for i, draw in enumerate(pages, start=1):
        draw(Page(c, doc_name, i, len(pages)))
        c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# 決算書
# ---------------------------------------------------------------------------


def financial_statements(no: int) -> list:
    p = PERIODS[no]
    f = figures(p)
    term = f"自 {p['start']}　至 {p['end']}"
    contents = [
        "貸借対照表",
        "損益計算書",
        "製造原価報告書",
        "販売費及び一般管理費内訳書",
        "株主資本等変動計算書",
        "個別注記表",
    ]

    def head(pg: Page, name: str, when: str) -> None:
        pg.title(name)
        pg.center(when)
        pg.center(COMPANY)
        pg.right("（単位：円）")
        pg.gap(2)

    def cover(pg: Page) -> None:
        pg.gap(120)
        pg.title(f"第{no}期　決算報告書", 24)
        pg.gap(10)
        pg.center(term, 12)
        pg.gap(120)
        pg.center(COMPANY, 16)
        pg.center(ADDRESS, 11)
        pg.gap(60)
        pg.heading("目次")
        for i, name in enumerate(contents, start=1):
            pg.para(f"{i}．{name}", indent=1)

    def bs(pg: Page) -> None:
        head(pg, "貸借対照表", f"{p['end']}現在")
        pg.step = 12.4  # 1ページに収める
        pg.row("資産の部", bold=True)
        pg.row("Ⅰ 流動資産", indent=1)
        for k, v in p["current_assets"]:
            pg.row(k, yen(v), indent=2)
        pg.row("流動資産合計", yen(f["current_assets"]), indent=1, bold=True)
        pg.row("Ⅱ 固定資産", indent=1)
        pg.row("1 有形固定資産", indent=2)
        for k, v in p["tangible_assets"]:
            pg.row(k, yen(v), indent=3)
        pg.row("有形固定資産合計", yen(f["tangible_assets"]), indent=2, bold=True)
        pg.row("2 無形固定資産", indent=2)
        for k, v in p["intangible_assets"]:
            pg.row(k, yen(v), indent=3)
        pg.row("無形固定資産合計", yen(f["intangible_assets"]), indent=2, bold=True)
        pg.row("3 投資その他の資産", indent=2)
        for k, v in p["investments"]:
            pg.row(k, yen(v), indent=3)
        pg.row("投資その他の資産合計", yen(f["investments"]), indent=2, bold=True)
        pg.row("固定資産合計", yen(f["fixed_assets"]), indent=1, bold=True)
        pg.row("資産合計", yen(f["assets"]), bold=True)
        pg.gap(4)
        pg.row("負債の部", bold=True)
        pg.row("Ⅰ 流動負債", indent=1)
        for k, v in p["current_liabilities"]:
            pg.row(k, yen(v), indent=2)
        pg.row("流動負債合計", yen(f["current_liabilities"]), indent=1, bold=True)
        pg.row("Ⅱ 固定負債", indent=1)
        for k, v in p["fixed_liabilities"]:
            pg.row(k, yen(v), indent=2)
        pg.row("固定負債合計", yen(f["fixed_liabilities"]), indent=1, bold=True)
        pg.row("負債合計", yen(f["liabilities"]), bold=True)
        pg.gap(4)
        pg.row("純資産の部", bold=True)
        pg.row("Ⅰ 株主資本", indent=1)
        pg.row("資本金", yen(p["capital"]), indent=2)
        pg.row("利益剰余金", indent=2)
        pg.row("その他利益剰余金", indent=3)
        pg.row("繰越利益剰余金", yen(f["retained_closing"]), indent=4)
        pg.row("利益剰余金合計", yen(f["retained_closing"]), indent=2, bold=True)
        pg.row("株主資本合計", yen(f["equity"]), indent=1, bold=True)
        pg.row("純資産合計", yen(f["equity"]), bold=True)
        pg.row("負債及び純資産合計", yen(f["liabilities"] + f["equity"]), bold=True)

    def pl(pg: Page) -> None:
        head(pg, "損益計算書", term)
        pg.row("Ⅰ 売上高", indent=0)
        pg.row("売上高", yen(p["sales"]), indent=1)
        pg.row("Ⅱ 売上原価", indent=0)
        pg.row("期首製品棚卸高", "0", indent=1)
        pg.row("当期製品製造原価", yen(f["manufacturing"]), indent=1)
        pg.row("期末製品棚卸高", "0", indent=1)
        pg.row("売上原価", yen(f["cost_of_sales"]), indent=1, bold=True)
        pg.row("売上総利益", yen(f["gross_profit"]), bold=True)
        pg.row("Ⅲ 販売費及び一般管理費", indent=0)
        pg.row("販売費及び一般管理費合計", yen(f["sga"]), indent=1)
        pg.row("営業利益", yen(f["operating_income"]), bold=True)
        pg.row("Ⅳ 営業外収益", indent=0)
        for k, v in p["non_operating_income"]:
            pg.row(k, yen(v), indent=1)
        pg.row("営業外収益合計", yen(total(p["non_operating_income"])), indent=1, bold=True)
        pg.row("Ⅴ 営業外費用", indent=0)
        for k, v in p["non_operating_expenses"]:
            pg.row(k, yen(v), indent=1)
        pg.row("営業外費用合計", yen(total(p["non_operating_expenses"])), indent=1, bold=True)
        pg.row("経常利益", yen(f["ordinary_income"]), bold=True)
        pg.row("税引前当期純利益", yen(f["pretax_income"]), bold=True)
        pg.row("法人税、住民税及び事業税", yen(p["income_taxes"]), indent=1)
        pg.row("当期純利益", yen(f["net_income"]), bold=True)

    def manufacturing(pg: Page) -> None:
        head(pg, "製造原価報告書", term)
        pg.step = 14
        pg.row("Ⅰ 材料費", indent=0)
        pg.row("期首原材料棚卸高", yen(p["materials_opening"]), indent=1)
        pg.row("当期原材料仕入高", yen(p["materials_purchased"]), indent=1)
        pg.row("期末原材料棚卸高", yen(f["materials_closing"]), indent=1)
        pg.row("当期材料費", yen(f["materials"]), indent=1, bold=True)
        pg.row("Ⅱ 労務費", indent=0)
        for k, v in p["labor"]:
            pg.row(k, yen(v), indent=1)
        pg.row("当期労務費", yen(f["labor"]), indent=1, bold=True)
        pg.row("Ⅲ 外注費", indent=0)
        for k, v in p["outsourcing"]:
            pg.row(k, yen(v), indent=1)
        pg.row("当期外注費", yen(f["outsourcing"]), indent=1, bold=True)
        pg.row("Ⅳ 製造経費", indent=0)
        for k, v in p["overhead"]:
            pg.row(k, yen(v), indent=1)
        pg.row("当期製造経費", yen(f["overhead"]), indent=1, bold=True)
        pg.row("当期総製造費用", yen(f["manufacturing_total"]), bold=True)
        pg.row("期首仕掛品棚卸高", yen(p["wip_opening"]), indent=1)
        pg.row("期末仕掛品棚卸高", yen(f["wip_closing"]), indent=1)
        pg.row("当期製品製造原価", yen(f["manufacturing"]), bold=True)

    def sga(pg: Page) -> None:
        head(pg, "販売費及び一般管理費内訳書", term)
        for k, v in p["sga"]:
            pg.row(k, yen(v), indent=1)
        pg.row("販売費及び一般管理費合計", yen(f["sga"]), bold=True)

    def equity(pg: Page) -> None:
        head(pg, "株主資本等変動計算書", term)
        cap = yen(p["capital"])
        opening = yen(p["capital"] + p["retained_opening"])
        rows = [
            ["区分", "当期首残高", "当期純利益", "当期末残高"],
            ["資本金", cap, "0", cap],
            ["繰越利益剰余金", yen(p["retained_opening"]), yen(f["net_income"]), yen(f["retained_closing"])],
            ["株主資本合計", opening, yen(f["net_income"]), yen(f["equity"])],
            ["純資産合計", opening, yen(f["net_income"]), yen(f["equity"])],
        ]
        pg.table(rows, [130, 115, 115, 115])
        pg.para("当期中に剰余金の配当は行っていない。")

    def notes(pg: Page) -> None:
        pg.title("個別注記表")
        pg.center(term)
        pg.center(COMPANY)
        pg.gap(6)
        pg.heading("1．重要な会計方針に係る事項に関する注記")
        pg.para(
            "(1) 棚卸資産の評価基準及び評価方法　原材料は最終仕入原価法、仕掛品は個別法による原価法によっている。",
            indent=1,
        )
        pg.para(
            "(2) 固定資産の減価償却の方法　有形固定資産は定率法（建物附属設備は定額法）によっている。"
            "無形固定資産（自社利用のソフトウエア）は、社内における利用可能期間（5年）に基づく定額法によっている。",
            indent=1,
        )
        pg.para("(3) 消費税等の会計処理　税抜方式によっている。", indent=1)
        pg.gap(6)
        pg.heading("2．株主資本等変動計算書に関する注記")
        pg.para(f"(1) 当事業年度の末日における発行済株式の数　普通株式 {SHARES_ISSUED}株", indent=1)  # A-07
        pg.para("(2) 当事業年度中に行った剰余金の配当　該当なし", indent=1)
        pg.gap(6)
        pg.heading("3．重要な後発事象に関する注記")
        pg.para("該当事項はない。", indent=1)

    return [cover, bs, pl, manufacturing, sga, equity, notes]


# ---------------------------------------------------------------------------
# 履歴事項全部証明書
# ---------------------------------------------------------------------------


def registry_certificate() -> list:
    def page1(pg: Page) -> None:
        def kv(key: str, value: str) -> None:
            pg.kv(key, value, key_width=190)

        pg.title("履歴事項全部証明書")
        pg.center("（架空のテスト用データ。登記所の証明文・登記官の名前・印はありません）", 9)
        pg.gap(6)
        kv("会社法人等番号", REGISTRY_NUMBER)
        kv("商号", COMPANY)
        kv("本店", ADDRESS)
        kv("公告をする方法", "官報に掲載してする")
        kv("会社成立の年月日", "平成2年4月2日")  # A-04
        kv(
            "目的",
            "1．金属製品及び機械部品の切削加工\n"
            "2．精密機械部品の製造及び販売\n"
            "3．試作品の設計及び製作の受託\n"
            "4．前各号に附帯又は関連する一切の事業",
        )
        kv("発行可能株式総数", "1600株")
        kv("発行済株式の総数並びに種類及び数", f"発行済株式の総数　{SHARES_ISSUED}株")  # A-07
        kv("資本金の額", "金2,000万円")  # A-06
        kv(
            "株式の譲渡制限に関する規定",
            "当会社の株式を譲渡により取得するには、株主総会の承認を受けなければならない。",
        )
        # 役員（A-08、A-09）。監査役はいない
        kv(
            "役員に関する事項",
            f"取締役　{PRESIDENT}\n{REAPPOINTED}重任　{REAPPOINTED_REGISTERED}登記\n"
            f"取締役　{DIRECTOR}\n{REAPPOINTED}重任　{REAPPOINTED_REGISTERED}登記\n"
            f"{PRESIDENT_ADDRESS}\n代表取締役　{PRESIDENT}\n{REAPPOINTED}重任　{REAPPOINTED_REGISTERED}登記",
        )
        kv("登記記録に関する事項", "設立　平成2年4月2日登記")
        pg.gap(10)
        pg.para(f"発行日　{REGISTRY_ISSUED}")
        pg.para("発行した所　架空の登記所（テスト用）")

    return [page1]


# ---------------------------------------------------------------------------
# 納税証明書（その2）
# ---------------------------------------------------------------------------


def tax_certificate() -> list:
    def page1(pg: Page) -> None:
        pg.title("納税証明書（その2　所得金額用）")
        pg.center("（架空のテスト用データ。税務署長の証明・印はありません）", 9)
        pg.gap(6)
        pg.kv("住所（所在地）", ADDRESS)
        pg.kv("氏名（名称）", COMPANY)
        pg.kv("代表者の氏名", PRESIDENT)
        pg.kv("証明を受ける事項", "所得金額（法人税）")
        pg.kv("使用目的", "補助金の申請")
        pg.gap(8)
        rows = [["事業年度", "所得金額（円）"]]
        for start, end, income in TAXABLE_INCOME:  # F-08
            rows.append([f"{start}〜{end}", yen(income)])
        pg.table(rows, [300, 175])
        pg.gap(10)
        pg.para(f"発行日　{TAX_CERTIFICATE_ISSUED}")
        pg.para("発行した所　架空の税務署（テスト用）")

    return [page1]


# ---------------------------------------------------------------------------
# 法人事業概況説明書（第36期）
# ---------------------------------------------------------------------------


def business_overview() -> list:
    p = PERIODS[36]
    f = figures(p)
    sga = dict(p["sga"])
    labor = dict(p["labor"])
    overhead = dict(p["overhead"])
    assets = dict(p["current_assets"])
    liabilities = dict(p["current_liabilities"])
    term = f"自 {p['start']}　至 {p['end']}"

    def k(v: int) -> str:
        return f"{v:,}"

    def page1(pg: Page) -> None:
        pg.title("法人事業概況説明書")
        pg.center(term)
        pg.center("（架空のテスト用データ。国税庁の書式の配置とは別に組んだもの）", 9)
        pg.gap(4)
        pg.heading("1．法人の概要")
        pg.kv("法人名", COMPANY)
        pg.kv("法人番号", CORPORATE_NUMBER)
        pg.kv("納税地", ADDRESS)
        pg.kv("代表者", PRESIDENT)
        pg.kv("事業の内容", "金属部品の切削加工（半導体の製造装置、産業用ロボット・工作機械、医療機器の部品。試作と小ロット）")  # A-11、A-12
        pg.kv("事業所", "本店と工場が同じ所に1か所。ほかに支店・営業所はない")  # B-01
        pg.kv("資本金", "20,000,000円")  # A-06
        pg.kv("決算期", "3月")  # A-10
        pg.gap(4)
        pg.heading("2．期末の従業員等の状況")
        pg.kv("役員", "2人（代表取締役、取締役）")  # A-09
        pg.kv("従業員", "18人（正社員 16人、パート 2人）")  # C-01
        pg.kv("うち代表者の家族", "0人")  # C-08
        pg.gap(4)
        pg.heading("3．主な取引先の種類")
        pg.para(
            "1年に取引のある会社は約60社。主な取引先は、半導体の製造装置のメーカー3社、"
            "産業用ロボットや工作機械のメーカー3社、医療機器のメーカー2社。",
            indent=1,
        )  # E-01
        pg.gap(4)
        pg.heading("4．経理の状況")
        pg.para("帳簿は市販の会計ソフトでつけている。決算と申告は顧問の税理士に頼んでいる。青色申告。", indent=1)  # G-03、F-18
        pg.para("消費税は税抜経理。インボイスの登録は令和5年10月1日。", indent=1)  # F-16

    def page2(pg: Page) -> None:
        pg.title("法人事業概況説明書（つづき）", 12)
        pg.heading("5．主要科目（単位：千円）")
        rows = [
            ["科目", "金額"],
            ["売上高", k(p["sales"])],
            ["売上原価", k(f["cost_of_sales"])],
            ["うち原材料仕入高", k(p["materials_purchased"])],
            ["うち労務費", k(f["labor"])],
            ["うち外注加工費", k(f["outsourcing"])],
            ["売上総利益", k(f["gross_profit"])],
            ["役員報酬", k(sga["役員報酬"])],
            ["うち代表者に対する報酬", "10,800"],  # D-05
            ["従業員給料（製造原価の賃金給与を含む）", k(labor["賃金給与"] + sga["給料手当"])],  # D-03
            ["法定福利費", k(labor["法定福利費"] + sga["法定福利費"])],  # F-07
            ["減価償却費", k(overhead["減価償却費"] + sga["減価償却費"])],  # F-06
            ["地代家賃", k(overhead["地代家賃"])],
            ["営業利益", k(f["operating_income"])],
            ["経常利益", k(f["ordinary_income"])],
            ["税引前当期純利益", k(f["pretax_income"])],
            ["当期純利益", k(f["net_income"])],
            ["現金及び預金", k(assets["現金及び預金"])],
            ["受取手形・売掛金", k(assets["受取手形"] + assets["売掛金"])],
            ["棚卸資産", k(assets["原材料"] + assets["仕掛品"])],
            ["買掛金", k(liabilities["買掛金"])],
            ["借入金", k(liabilities["1年内返済予定の長期借入金"] + total(p["fixed_liabilities"]))],  # F-14
            ["純資産", k(f["equity"])],
        ]
        pg.table(rows, [300, 175], size=8.6)
        pg.heading("6．月別の売上高（単位：千円）")
        rows = [["月", "売上高"]] + [[m, k(v)] for m, v in MONTHLY_SALES_36]
        rows.append(["計", k(total(MONTHLY_SALES_36))])
        pg.table(rows, [300, 175], size=8.6)

    if total(MONTHLY_SALES_36) != p["sales"]:
        raise ValueError("月別の売上高の合計が、年の売上高と合いません")
    return [page1, page2]


# ---------------------------------------------------------------------------
# Word と Excel を同じバイト列にする
# ---------------------------------------------------------------------------


def normalize_office(path: Path) -> None:
    """zip の中の時刻と、docProps/core.xml の作成・更新の日時をそろえる。"""
    with zipfile.ZipFile(path) as zin:
        items = [(info.filename, zin.read(info.filename)) for info in zin.infolist()]
    stamp = FIXED_TIME.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in items:
            if name == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>" + stamp, data)
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME.timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zout.writestr(info, data)


# ---------------------------------------------------------------------------
# Word の名簿（役員名簿・株主名簿）。会社が自分で持つ名簿として作る
# ---------------------------------------------------------------------------

AS_OF = "2026年11月1日現在"


def set_cell_shading(cell, color: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    props.append(shd)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(text)
    run._r.append(end)


def new_document(doc_name: str) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "游明朝"
    style.font.size = Pt(10.5)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "游明朝")
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(20)
    section.top_margin = section.bottom_margin = Mm(22)
    head = section.header.paragraphs[0]
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = head.add_run(BANNER)
    run.font.size = Pt(8)
    run.font.bold = True
    run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = foot.add_run(f"架空のテスト用データ｜{doc_name}｜")
    run.font.size = Pt(8)
    add_page_field(foot)
    foot.add_run("ページ").font.size = Pt(8)
    props = doc.core_properties
    props.title = f"{doc_name}（架空のテスト用データ）"
    props.author = "hojokin-oss のテスト用データ"
    props.last_modified_by = "hojokin-oss のテスト用データ"
    props.created = props.modified = FIXED_TIME
    props.revision = 1
    props.comments = ""
    props.keywords = ""
    props.subject = ""
    props.category = ""
    return doc


def add_title(doc, title: str, as_of: str = AS_OF) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.font.size = Pt(16)
    run.font.bold = True
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run(f"{COMPANY}　{as_of}")


def add_table(doc, rows: list[list[str]], widths_mm: list[float], size: float = 9) -> None:
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.autofit = False
    for i, column in enumerate(table.columns):
        column.width = Mm(widths_mm[i])
    for r, cells in enumerate(rows):
        for i, text in enumerate(cells):
            cell = table.cell(r, i)
            cell.width = Mm(widths_mm[i])
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.font.size = Pt(size)
            if r == 0:
                run.font.bold = True
                set_cell_shading(cell, "E8EEF6")


def officer_list(path: Path) -> None:
    doc = new_document("役員名簿")
    add_title(doc, "役員名簿")
    rows = [
        ["役職", "氏名（ふりがな）", "生年月日", "性別", "住所", "就任年月日", "常勤・担当"],
        # A-08。生年月日の月日は回答表にない（回答表は1977年生まれだけ）。代表は2016年に継いだ（A-05）
        [
            "代表取締役",
            f"{PRESIDENT}（{PRESIDENT_KANA}）",
            "1977年8月19日",
            "男",
            PRESIDENT_ADDRESS,
            "2016年6月28日（2026年6月26日重任）",
            "常勤。経営全般と見積",
        ],
        # A-09。生年月日・ふりがな・就任の日は回答表にない
        [
            "取締役",
            f"{DIRECTOR}（{DIRECTOR_KANA}）",
            "1950年2月11日",
            "女",
            DIRECTOR_ADDRESS,
            "1990年4月2日（2026年6月26日重任）",
            "経理",
        ],
    ]
    add_table(doc, rows, [20, 34, 24, 10, 36, 30, 22])
    doc.add_paragraph()
    for text in (
        "役員は上の2人です。監査役は置いていません。",  # A-09
        f"取締役の{DIRECTOR}は代表取締役の母で、別に住んでいます。経理を担当しています。",  # A-09
        "取締役の任期は10年です。2026年6月26日の定時株主総会で、2人とも重任しました。",
    ):
        doc.add_paragraph(text)
    doc.save(path)
    normalize_office(path)


def shareholder_list(path: Path) -> None:
    doc = new_document("株主名簿")
    add_title(doc, "株主名簿")
    doc.add_paragraph(f"発行済株式の総数　{SHARES_ISSUED}株（普通株式）。株券は発行していません。")
    acquired = {
        PRESIDENT: ("2016年6月28日", "譲渡による取得（同日の株主総会で承認）"),
        DIRECTOR: ("1990年4月2日", "設立の時に引き受けた"),
    }
    addresses = {PRESIDENT: PRESIDENT_ADDRESS, DIRECTOR: DIRECTOR_ADDRESS}
    rows = [["番号", "株主の氏名", "住所", "株式の種類と数", "持株の割合", "取得の年月日", "取得の事由"]]
    for i, (name, shares) in enumerate(SHAREHOLDERS, start=1):
        rows.append(
            [
                str(i),
                name,
                addresses[name],
                f"普通株式 {shares}株",
                f"{shares / SHARES_ISSUED:.1%}",
                acquired[name][0],
                acquired[name][1],
            ]
        )
    rows.append(["", "合計", "", f"{sum(s for _, s in SHAREHOLDERS)}株", "100.0%", "", ""])
    add_table(doc, rows, [10, 26, 38, 26, 18, 26, 32])
    doc.add_paragraph()
    doc.add_paragraph("ほかの会社は、当社の株を持っていません。")  # A-07
    doc.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------
# 労働者名簿（Excel）。C-01〜C-07、C-13、L-16 に合わせる
# ---------------------------------------------------------------------------

# 名前・生年月日・住所・雇入れの日・履歴は回答表にない（架空）。住所は、西新小岩のない丁目（六〜十丁目）にした
WORKERS = [
    # 正社員16人（C-02）。1日8時間・週5日（C-04）。平均46歳、工場長61歳（C-13。2026年11月1日の年齢）
    ("坂本 茂", "さかもと しげる", "男", dt.date(1965, 6, 12), "東京都葛飾区西新小岩七丁目4番9号",
     dt.date(1990, 4, 2), "正社員", "期間の定めなし", "工場長", 8, 5, "先代の個人事業で旋盤の加工"),
    ("小林 誠司", "こばやし せいじ", "男", dt.date(1970, 3, 25), "東京都葛飾区西新小岩六丁目8番1号",
     dt.date(1993, 4, 1), "正社員", "期間の定めなし", "加工（NC旋盤）", 8, 5, "工業高校を卒業"),
    ("高橋 浩二", "たかはし こうじ", "男", dt.date(1972, 10, 8), "東京都葛飾区西新小岩十丁目3番12号",
     dt.date(1996, 5, 7), "正社員", "期間の定めなし", "加工（マシニングセンタ）", 8, 5, "金型の工場で加工"),
    ("渡辺 剛", "わたなべ つよし", "男", dt.date(1975, 1, 30), "東京都葛飾区西新小岩八丁目9番6号",
     dt.date(2001, 4, 1), "正社員", "期間の定めなし", "加工（5軸マシニングセンタ）", 8, 5, "精密部品の工場で加工"),
    ("伊藤 隆之", "いとう たかゆき", "男", dt.date(1978, 7, 14), "東京都葛飾区西新小岩六丁目15番3号",
     dt.date(2004, 4, 1), "正社員", "期間の定めなし", "加工（複合加工機）", 8, 5, "機械の部品の工場で旋盤"),
    ("山本 達也", "やまもと たつや", "男", dt.date(1979, 5, 22), "東京都葛飾区西新小岩七丁目12番8号",
     dt.date(2008, 10, 1), "正社員", "期間の定めなし", "加工（NC旋盤）", 8, 5, "自動車部品の工場で加工"),
    ("中村 健太", "なかむら けんた", "男", dt.date(1983, 4, 3), "東京都葛飾区西新小岩十丁目6番2号",
     dt.date(2010, 4, 1), "正社員", "期間の定めなし", "加工（マシニングセンタ）", 8, 5, "工作機械の販売店で整備"),
    ("加藤 翔", "かとう しょう", "男", dt.date(1987, 9, 17), "東京都葛飾区西新小岩八丁目1番14号",
     dt.date(2013, 4, 1), "正社員", "期間の定めなし", "加工（マシニングセンタ）", 8, 5, "専門学校（機械科）を卒業"),
    ("吉田 亮", "よしだ りょう", "男", dt.date(1991, 6, 1), "東京都葛飾区西新小岩六丁目2番7号",
     dt.date(2017, 4, 1), "正社員", "期間の定めなし", "加工（NC旋盤）", 8, 5, "板金の工場"),
    ("佐々木 拓海", "ささき たくみ", "男", dt.date(1997, 5, 19), "東京都葛飾区西新小岩七丁目10番5号",
     dt.date(2021, 4, 1), "正社員", "期間の定めなし", "加工（マシニングセンタ）", 8, 5, "工業高校を卒業"),
    ("松田 優斗", "まつだ ゆうと", "男", dt.date(2002, 8, 8), "東京都葛飾区西新小岩十丁目13番1号",
     dt.date(2024, 10, 1), "正社員", "期間の定めなし", "加工（NC旋盤）", 8, 5, "物流の倉庫での作業"),
    ("井上 和也", "いのうえ かずや", "男", dt.date(1981, 2, 27), "東京都葛飾区西新小岩八丁目6番11号",
     dt.date(2006, 4, 1), "正社員", "期間の定めなし", "CAM のプログラム", 8, 5, "設計事務所で機械の図面"),
    ("木村 直樹", "きむら なおき", "男", dt.date(1968, 12, 10), "東京都葛飾区西新小岩六丁目12番4号",
     dt.date(1995, 4, 1), "正社員", "期間の定めなし", "品質・検査", 8, 5, "計測機器の会社で校正"),
    ("林 裕子", "はやし ゆうこ", "女", dt.date(1977, 6, 5), "東京都葛飾区西新小岩十丁目9番10号",
     dt.date(2011, 6, 1), "正社員", "期間の定めなし", "品質・検査", 8, 5, "電子部品の工場で検査"),
    ("清水 恵美", "しみず えみ", "女", dt.date(1973, 3, 15), "東京都葛飾区西新小岩七丁目1番3号",
     dt.date(2003, 4, 1), "正社員", "期間の定めなし", "事務", 8, 5, "建材の商社で経理事務"),
    ("山田 大輔", "やまだ だいすけ", "男", dt.date(1981, 9, 29), "東京都葛飾区西新小岩八丁目11番2号",
     dt.date(2012, 4, 1), "正社員", "期間の定めなし", "営業", 8, 5, "工具の商社で営業"),
    # パート2人（C-03）。2人とも1日6時間・週5日（C-05）、期間の定めなし、雇ってから3年以上（C-06）
    ("藤田 幸子", "ふじた さちこ", "女", dt.date(1968, 2, 20), "東京都葛飾区西新小岩六丁目5番13号",
     dt.date(2019, 4, 1), "パート", "期間の定めなし", "検査の補助", 6, 5, "電子部品の工場で組立"),
    ("岡本 真理", "おかもと まり", "女", dt.date(1975, 7, 7), "東京都葛飾区西新小岩十丁目2番8号",
     dt.date(2021, 9, 1), "パート", "期間の定めなし", "事務の補助", 6, 5, "保険の代理店で事務"),
]
WORKER_HEADER = [
    "番号",
    "氏名",
    "ふりがな",
    "性別",
    "生年月日",
    "住所",
    "雇入れの年月日",
    "雇用の形態",
    "契約の期間",
    "従事する業務の種類",
    "1日の所定労働時間",
    "週の所定労働日数",
    "週の所定労働時間",
    "履歴（前の仕事）",
    "退職・死亡の年月日と事由",
]


def worker_list(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "労働者名簿"
    cols = len(WORKER_HEADER)
    thin = Side(style="thin", color="808080")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
    ws.cell(1, 1, BANNER).font = Font(name="游ゴシック", size=9, bold=True)
    ws.cell(1, 1).fill = PatternFill("solid", fgColor="FFF2BF")
    ws.cell(1, 1).alignment = Alignment(horizontal="center")
    ws.cell(2, 1, "労働者名簿").font = Font(name="游ゴシック", size=14, bold=True)
    ws.cell(3, 1, f"{COMPANY}　{AS_OF}（在籍している人。役員は入れていない）").font = Font(name="游ゴシック", size=10)
    for i, title in enumerate(WORKER_HEADER, start=1):
        cell = ws.cell(5, i, title)
        cell.font = Font(name="游ゴシック", size=9, bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF6")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for r, w in enumerate(WORKERS, start=6):
        name, kana, sex, born, address, hired, kind, term, job, hours, days, history = w
        values = [r - 5, name, kana, sex, born, address, hired, kind, term, job, hours, days, hours * days, history, ""]
        for i, value in enumerate(values, start=1):
            cell = ws.cell(r, i, value)
            cell.font = Font(name="游ゴシック", size=9)
            cell.border = border
            if isinstance(value, dt.date):
                cell.number_format = 'yyyy"年"m"月"d"日"'
    for letter, width in zip("ABCDEFGHIJKLMNO", [5, 12, 16, 5, 16, 32, 16, 9, 16, 26, 9, 9, 9, 26, 16]):
        ws.column_dimensions[letter].width = width
    ws.row_dimensions[5].height = 30
    ws.freeze_panes = "C6"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.oddHeader.center.text = "架空のテスト用データ（hojokin-oss）　実在の会社・人物とは関係ありません"
    ws.oddFooter.center.text = "架空のテスト用データ｜労働者名簿｜&P/&N"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    wb.properties.creator = "hojokin-oss のテスト用データ"
    wb.properties.lastModifiedBy = "hojokin-oss のテスト用データ"
    wb.properties.title = "労働者名簿（架空のテスト用データ）"
    wb.properties.created = wb.properties.modified = FIXED_TIME
    wb.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------

DOCUMENTS = [
    ("決算書_第34期.pdf", "第34期 決算報告書", lambda: financial_statements(34)),
    ("決算書_第35期.pdf", "第35期 決算報告書", lambda: financial_statements(35)),
    ("決算書_第36期.pdf", "第36期 決算報告書", lambda: financial_statements(36)),
    ("履歴事項全部証明書.pdf", "履歴事項全部証明書", registry_certificate),
    ("納税証明書_その2.pdf", "納税証明書（その2）", tax_certificate),
    ("法人事業概況説明書_第36期.pdf", "法人事業概況説明書（第36期）", business_overview),
]


def main() -> None:
    # 期をまたぐつながり：第35期・第36期の期首は、前の期末と同じ
    for no in (35, 36):
        before = figures(PERIODS[no - 1])
        if PERIODS[no]["retained_opening"] != before["retained_closing"]:
            raise ValueError(f"第{no}期の期首の繰越利益剰余金が、第{no - 1}期末と合いません")
        if PERIODS[no]["materials_opening"] != before["materials_closing"]:
            raise ValueError(f"第{no}期の期首の原材料が、第{no - 1}期末と合いません")
        if PERIODS[no]["wip_opening"] != before["wip_closing"]:
            raise ValueError(f"第{no}期の期首の仕掛品が、第{no - 1}期末と合いません")
        check_cash_flow(no)
    for name, doc_name, build in DOCUMENTS:
        render(OUT_DIR / name, doc_name, build())
        print(f"作った：{name}")
    officer_list(OUT_DIR / "役員名簿.docx")
    print("作った：役員名簿.docx")
    shareholder_list(OUT_DIR / "株主名簿.docx")
    print("作った：株主名簿.docx")
    worker_list(OUT_DIR / "労働者名簿.xlsx")
    print("作った：労働者名簿.xlsx")


if __name__ == "__main__":
    main()
