# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4"]
# ///
"""デモの会社の書類の前半（TASKS D2a）を PDF で作る。

作るもの：決算書（第17期・第18期）、履歴事項全部証明書、納税証明書（その2）、法人事業概況説明書（第18期）。
数字と事実は testdata/デモの会社/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
ID のない数字は回答表にないもので、書類の一覧.md の「回答表にない数字と事実」に挙げた。

どのページにも「架空のテスト用データ」の帯を付ける。公印・透かし・役所の様式の配置は写さない。
同じ中身なら同じバイト列になるよう、invariant で作る。

動かし方：uv run --script testdata/デモの会社/書類/make_documents.py
"""

from __future__ import annotations

from pathlib import Path

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

# ---------------------------------------------------------------------------
# 会社の事実（回答表の ID）
# ---------------------------------------------------------------------------

COMPANY = "株式会社やまぶき惣菜"  # A-01
CORPORATE_NUMBER = "3010801099731"  # A-03
# 会社法人等番号は、法人番号から先頭の検査用の数字を除いた12桁
REGISTRY_NUMBER = f"{CORPORATE_NUMBER[1:5]}-{CORPORATE_NUMBER[5:7]}-{CORPORATE_NUMBER[7:]}"
ADDRESS = "東京都大田区東糀谷八丁目12番5号"  # B-01
PRESIDENT = "沢村 宏之"  # A-08
DIRECTOR = "沢村 由美子"  # A-09

# ---------------------------------------------------------------------------
# 決算の数字（千円）。書類には円で出す
# ---------------------------------------------------------------------------

PERIODS = {
    17: {
        "start": "令和6年4月1日",
        "end": "令和7年3月31日",
        # 損益：売上高 F-01、売上総利益 F-02、営業利益 F-03、経常利益 F-04、当期純利益 F-05 に合うよう、
        # 内訳は回答表にない数字で組んだ（給与の合計 D-04、役員報酬 D-05、減価償却費 F-06、法定福利費 F-07 には合わせた）
        "sales": 194_800,  # F-01
        "materials_opening": 3_200,
        "materials_purchased": 80_100,
        "labor": [("賃金給与", 32_200), ("法定福利費", 4_800)],
        "overhead": [
            ("水道光熱費", 9_500),
            ("消耗品・包装材料費", 8_300),
            ("地代家賃", 4_800),
            ("減価償却費", 3_000),
            ("修繕費その他", 900),
        ],
        "sga": [
            ("役員報酬", 10_800),  # D-05
            ("給料手当", 7_900),
            ("法定福利費", 2_800),
            ("福利厚生費", 600),
            ("荷造運賃", 7_200),
            ("車両費", 3_700),
            ("リース料", 2_600),
            ("減価償却費", 900),
            ("その他", 10_900),
        ],
        "non_operating_income": [("雑収入", 400)],
        "non_operating_expenses": [("支払利息", 900)],
        "income_taxes": 1_100,
        # 貸借：回答表にない数字。第18期の期首と、借入金の返済（年7,200）でつながるようにした
        "current_assets": [
            ("現金及び預金", 22_300),
            ("売掛金", 23_800),
            ("原材料", 3_300),
            ("その他流動資産", 1_100),
        ],
        "tangible_assets": [
            ("機械及び装置", 16_600),
            ("車両運搬具", 3_900),
            ("工具、器具及び備品", 2_000),
        ],
        "intangible_assets": [("ソフトウエア", 500)],
        "investments": [("敷金及び保証金", 6_000)],
        "current_liabilities": [
            ("買掛金", 11_100),
            ("1年内返済予定の長期借入金", 7_200),
            ("未払金及び未払費用", 6_500),
            ("未払法人税等", 700),
            ("その他流動負債", 2_300),
        ],
        "fixed_liabilities": [("長期借入金", 27_000)],
        "capital": 10_000,  # A-06
        "retained_opening": 12_400,
    },
    18: {
        "start": "令和7年4月1日",
        "end": "令和8年3月31日",
        "sales": 201_600,  # F-01
        # 材料費 82,600（F-09）＝ 期首の原材料 3,300（第17期末）＋ 仕入 82,900 − 期末の原材料 3,600（F-12）
        "materials_opening": 3_300,
        "materials_purchased": 82_900,
        "labor": [("賃金給与", 33_400), ("法定福利費", 5_000)],  # F-09
        "overhead": [  # F-09
            ("水道光熱費", 9_800),
            ("消耗品・包装材料費", 8_600),
            ("地代家賃", 4_800),
            ("減価償却費", 2_800),
            ("修繕費その他", 1_200),
        ],
        "sga": [  # F-10
            ("役員報酬", 10_800),
            ("給料手当", 8_200),
            ("法定福利費", 2_900),
            ("福利厚生費", 600),
            ("荷造運賃", 7_400),
            ("車両費", 3_800),
            ("リース料", 2_600),
            ("減価償却費", 800),
            ("その他", 11_500),
        ],
        "non_operating_income": [("雑収入", 300)],  # F-11（科目の名前は回答表にない）
        "non_operating_expenses": [("支払利息", 900)],  # F-11
        "income_taxes": 1_300,  # F-11
        "current_assets": [  # F-12
            ("現金及び預金", 21_400),
            ("売掛金", 24_800),
            ("原材料", 3_600),
            ("その他流動資産", 1_200),
        ],
        "tangible_assets": [  # F-12
            ("機械及び装置", 14_200),
            ("車両運搬具", 3_100),
            ("工具、器具及び備品", 1_700),
        ],
        "intangible_assets": [("ソフトウエア", 400)],  # F-12
        "investments": [("敷金及び保証金", 6_000)],  # F-12
        "current_liabilities": [  # F-13
            ("買掛金", 11_600),
            ("1年内返済予定の長期借入金", 7_200),
            ("未払金及び未払費用", 6_900),
            ("未払法人税等", 900),
            ("その他流動負債", 2_400),
        ],
        "fixed_liabilities": [("長期借入金", 19_800)],  # F-13
        "capital": 10_000,  # A-06
        "retained_opening": 14_700,  # 第17期末の繰越利益剰余金（配当はしていない）
    },
}

# 課税所得（F-08）。納税証明書（その2）の所得金額
TAXABLE_INCOME = [
    ("令和5年4月1日", "令和6年3月31日", 2_500),
    ("令和6年4月1日", "令和7年3月31日", 3_300),
    ("令和7年4月1日", "令和8年3月31日", 4_300),
]

# 第18期の月別の売上高（千円）。回答表にない数字。12か月の合計が F-01 の 201,600 になる
MONTHLY_SALES_18 = [
    ("令和7年4月", 16_300),
    ("5月", 16_600),
    ("6月", 16_200),
    ("7月", 16_800),
    ("8月", 16_400),
    ("9月", 16_500),
    ("10月", 16_900),
    ("11月", 17_000),
    ("12月", 18_900),
    ("令和8年1月", 16_200),
    ("2月", 15_600),
    ("3月", 18_200),
]

# 発行日（回答表にない）。どちらも申請の締切（2026年12月）の3か月より内
REGISTRY_ISSUED = "令和8年10月22日"
TAX_CERTIFICATE_ISSUED = "令和8年10月23日"


def total(rows: list[tuple[str, int]]) -> int:
    return sum(v for _, v in rows)


def figures(p: dict) -> dict:
    """期の数字から、合計と利益を計算する（千円）。"""
    f = {}
    f["materials_closing"] = dict(p["current_assets"])["原材料"]
    f["materials"] = p["materials_opening"] + p["materials_purchased"] - f["materials_closing"]
    f["labor"] = total(p["labor"])
    f["overhead"] = total(p["overhead"])
    f["manufacturing"] = f["materials"] + f["labor"] + f["overhead"]
    f["cost_of_sales"] = f["manufacturing"]  # 製品と仕掛品の棚卸は期首・期末とも0
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

    def para(self, text: str, indent: int = 0, size: float = 10) -> None:
        x = LEFT + 16 * indent
        for line in wrap(text, MINCHO, size, RIGHT - x):
            self.c.setFont(MINCHO, size)
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
        pg.step = 13.5  # 1ページに収める
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
        pg.gap(6)
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
        pg.gap(6)
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
        pg.row("Ⅰ 材料費", indent=0)
        pg.row("期首原材料棚卸高", yen(p["materials_opening"]), indent=1)
        pg.row("当期原材料仕入高", yen(p["materials_purchased"]), indent=1)
        pg.row("期末原材料棚卸高", yen(f["materials_closing"]), indent=1)
        pg.row("当期材料費", yen(f["materials"]), indent=1, bold=True)
        pg.row("Ⅱ 労務費", indent=0)
        for k, v in p["labor"]:
            pg.row(k, yen(v), indent=1)
        pg.row("当期労務費", yen(f["labor"]), indent=1, bold=True)
        pg.row("Ⅲ 製造経費", indent=0)
        for k, v in p["overhead"]:
            pg.row(k, yen(v), indent=1)
        pg.row("当期製造経費", yen(f["overhead"]), indent=1, bold=True)
        pg.row("当期総製造費用", yen(f["manufacturing"]), bold=True)
        pg.row("期首仕掛品棚卸高", "0", indent=1)
        pg.row("期末仕掛品棚卸高", "0", indent=1)
        pg.row("当期製品製造原価", yen(f["manufacturing"]), bold=True)

    def sga(pg: Page) -> None:
        head(pg, "販売費及び一般管理費内訳書", term)
        for k, v in p["sga"]:
            pg.row(k, yen(v), indent=1)
        pg.row("販売費及び一般管理費合計", yen(f["sga"]), bold=True)

    def equity(pg: Page) -> None:
        head(pg, "株主資本等変動計算書", term)
        cap = yen(p["capital"])
        rows = [
            ["区分", "当期首残高", "当期純利益", "当期末残高"],
            ["資本金", cap, "0", cap],
            ["繰越利益剰余金", yen(p["retained_opening"]), yen(f["net_income"]), yen(f["retained_closing"])],
            [
                "株主資本合計",
                yen(p["capital"] + p["retained_opening"]),
                yen(f["net_income"]),
                yen(f["equity"]),
            ],
            [
                "純資産合計",
                yen(p["capital"] + p["retained_opening"]),
                yen(f["net_income"]),
                yen(f["equity"]),
            ],
        ]
        pg.table(rows, [130, 115, 115, 115])
        pg.para("当期中に剰余金の配当は行っていない。")

    def notes(pg: Page) -> None:
        pg.title("個別注記表")
        pg.center(term)
        pg.center(COMPANY)
        pg.gap(6)
        pg.heading("1．重要な会計方針に係る事項に関する注記")
        pg.para("(1) 棚卸資産の評価基準及び評価方法　原材料は、最終仕入原価法による原価法によっている。", indent=1)
        pg.para(
            "(2) 固定資産の減価償却の方法　有形固定資産は定率法によっている。"
            "無形固定資産（自社利用のソフトウエア）は、社内における利用可能期間（5年）に基づく定額法によっている。",
            indent=1,
        )
        pg.para("(3) 消費税等の会計処理　税抜方式によっている。", indent=1)
        pg.gap(6)
        pg.heading("2．株主資本等変動計算書に関する注記")
        pg.para("(1) 当事業年度の末日における発行済株式の数　普通株式 200株", indent=1)  # A-07
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
        kv("会社成立の年月日", "平成20年4月1日")  # A-04
        kv(
            "目的",
            "1．惣菜、弁当その他の調理食品の製造及び販売\n"
            "2．病院、介護施設等に対する食事用食品の製造及び販売\n"
            "3．食料品の通信販売\n"
            "4．前各号に附帯又は関連する一切の事業",
        )
        kv("発行可能株式総数", "800株")
        kv("発行済株式の総数並びに種類及び数", "発行済株式の総数　200株")  # A-07
        kv("資本金の額", "金1,000万円")  # A-06
        kv(
            "株式の譲渡制限に関する規定",
            "当会社の株式を譲渡により取得するには、株主総会の承認を受けなければならない。",
        )
        # 役員（A-08、A-09）。代表取締役の住所は、実在しない丁目にした
        kv(
            "役員に関する事項",
            f"取締役　{PRESIDENT}\n令和7年6月26日重任　令和7年7月3日登記\n"
            f"取締役　{DIRECTOR}\n令和7年6月26日重任　令和7年7月3日登記\n"
            f"東京都大田区東糀谷七丁目3番8号\n代表取締役　{PRESIDENT}\n令和7年6月26日重任　令和7年7月3日登記",
        )
        kv("登記記録に関する事項", "設立　平成20年4月1日登記")
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
# 法人事業概況説明書（第18期）
# ---------------------------------------------------------------------------


def business_overview() -> list:
    p = PERIODS[18]
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
        pg.kv("事業の内容", "惣菜の製造と販売（スーパー、病院、介護施設向け）")  # A-11、A-12
        pg.kv("事業所", "本店と工場が同じ所に1か所。ほかに支店・営業所はない")  # B-01
        pg.kv("資本金", "10,000,000円")  # A-06
        pg.kv("決算期", "3月")  # A-10
        pg.gap(4)
        pg.heading("2．期末の従業員等の状況")
        pg.kv("常勤役員", "2人")  # A-09
        pg.kv("従業員", "15人（正社員 7人、パート 8人）")  # C-01
        pg.kv("うち代表者の家族", "0人")  # C-08
        pg.gap(4)
        pg.heading("3．主な取引先の種類")
        pg.para("スーパー3社（14店舗）、病院2か所、介護施設11か所。ほかに仕出し・弁当の店と飲食店。", indent=1)  # E-01
        pg.gap(4)
        pg.heading("4．経理の状況")
        pg.para("帳簿は会計ソフトでつけている。決算と申告は顧問の税理士に頼んでいる。青色申告。", indent=1)  # F-18
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
            ["売上総利益", k(f["gross_profit"])],
            ["役員報酬", k(sga["役員報酬"])],
            ["うち代表者に対する報酬", "7,200"],  # D-05
            ["従業員給料（製造原価の賃金給与を含む）", k(labor["賃金給与"] + sga["給料手当"])],  # D-03
            ["法定福利費", k(labor["法定福利費"] + sga["法定福利費"])],  # F-07
            ["減価償却費", k(overhead["減価償却費"] + sga["減価償却費"])],  # F-06
            ["地代家賃", k(overhead["地代家賃"])],
            ["営業利益", k(f["operating_income"])],
            ["経常利益", k(f["ordinary_income"])],
            ["税引前当期純利益", k(f["pretax_income"])],
            ["当期純利益", k(f["net_income"])],
            ["現金及び預金", k(assets["現金及び預金"])],
            ["売掛金", k(assets["売掛金"])],
            ["棚卸資産", k(assets["原材料"])],
            ["買掛金", k(liabilities["買掛金"])],
            ["借入金", k(liabilities["1年内返済予定の長期借入金"] + dict(p["fixed_liabilities"])["長期借入金"])],  # F-14
            ["純資産", k(f["equity"])],
        ]
        pg.table(rows, [300, 175], size=9)
        pg.heading("6．月別の売上高（単位：千円）")
        rows = [["月", "売上高"]] + [[m, k(v)] for m, v in MONTHLY_SALES_18]
        rows.append(["計", k(total(MONTHLY_SALES_18))])
        pg.table(rows, [300, 175], size=9)

    if total(MONTHLY_SALES_18) != p["sales"]:
        raise ValueError("月別の売上高の合計が、年の売上高と合いません")
    return [page1, page2]


# ---------------------------------------------------------------------------

DOCUMENTS = [
    ("決算書_第17期.pdf", "第17期 決算報告書", lambda: financial_statements(17)),
    ("決算書_第18期.pdf", "第18期 決算報告書", lambda: financial_statements(18)),
    ("履歴事項全部証明書.pdf", "履歴事項全部証明書", registry_certificate),
    ("納税証明書_その2.pdf", "納税証明書（その2）", tax_certificate),
    ("法人事業概況説明書_第18期.pdf", "法人事業概況説明書（第18期）", business_overview),
]


def main() -> None:
    # 期をまたぐつながり：第18期の期首は第17期末と同じ
    f17 = figures(PERIODS[17])
    if PERIODS[18]["retained_opening"] != f17["retained_closing"]:
        raise ValueError("第18期の期首の繰越利益剰余金が、第17期末と合いません")
    if PERIODS[18]["materials_opening"] != f17["materials_closing"]:
        raise ValueError("第18期の期首の原材料が、第17期末と合いません")
    for name, doc_name, build in DOCUMENTS:
        render(OUT_DIR / name, doc_name, build())
        print(f"作った：{name}")


if __name__ == "__main__":
    main()
