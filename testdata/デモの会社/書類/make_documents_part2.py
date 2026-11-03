# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社の書類の後半（TASKS D2b）を作る。

作るもの：見積書2通とカタログ（PDF）、役員名簿と株主名簿（Word）、労働者名簿（Excel）。
数字と事実は testdata/デモの会社/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
ID のない数字は回答表にないもので、書類の一覧.md の「回答表にない数字と事実（D2b）」に挙げた。

どのページ・どのシートにも「架空のテスト用データ」を出す。PDF の描き方は make_documents.py（D2a）のものを使う。
名簿は会社が自分で持つ名簿として作り、省力化の【指定様式】の役員名簿・株主・出資者名簿は写さない。
Word と Excel も、同じ中身なら同じバイト列になるよう、zip の時刻と作成日時をそろえる。

動かし方：uv run --script testdata/デモの会社/書類/make_documents_part2.py
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Mm, Pt  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from reportlab.lib.colors import Color, black, white  # noqa: E402

from make_documents import (  # noqa: E402
    BANNER,
    COMPANY,
    DIRECTOR,
    GOTHIC,
    LEFT,
    MINCHO,
    PAGE_W,
    PRESIDENT,
    RIGHT,
    Page,
    render,
    wrap,
)

OUT_DIR = Path(__file__).resolve().parent

# 名簿の住所。代表取締役の住所は履歴事項全部証明書（D2a）と同じ。取締役は同居（A-09）
OFFICER_ADDRESS = "東京都大田区東糀谷七丁目3番8号"
AS_OF = "2026年11月1日現在"
FIXED_TIME = dt.datetime(2026, 11, 3, 0, 0, 0)

# ---------------------------------------------------------------------------
# 見積書（H-02〜H-04、H-07、H-08）
# ---------------------------------------------------------------------------

# 明細（円、税抜）。H-02 の6つの区分ごとに、どの行が当たるかを group に書く
QUOTES = {
    "つばさ台フードシステム": {
        "file": "見積書_つばさ台フードシステム.pdf",
        "issuer": "株式会社つばさ台フードシステム",  # H-03
        "number": "TFS-2610-0153",
        "items": [
            # (品名, 型番, 数量, 単位, 単価, H-02 の区分)
            ("盛り付けロボット", "TF-MR200", 2, "台", 3_900_000, "盛り付けロボット"),
            ("自動計量機（組合せ計量 14ヘッド）", "TF-AW14", 1, "台", 3_200_000, "自動計量機"),
            ("トップシール包装機", "TF-TS60", 1, "台", 4_800_000, "トップシール包装機"),
            ("画像検査装置（盛り付け・ラベル、カメラ2台）", "TF-VI2", 1, "式", 3_600_000, "画像検査装置"),
            ("重量チェッカー・ラベラー（一体型）", "TF-CL10", 1, "台", 1_900_000, "重量チェッカーとラベラー"),
            ("搬送コンベヤ（ライン連結用）", "TF-CV8", 1, "式", 700_000, "コンベヤと据え付け・調整"),
            ("据付・試運転調整", "—", 1, "式", 500_000, "コンベヤと据え付け・調整"),
        ],
    },
    "ほしみ機工": {
        "file": "見積書_ほしみ機工.pdf",
        "issuer": "株式会社ほしみ機工",  # H-03
        "number": "HK-20261020-07",
        "items": [
            ("惣菜盛付ロボット", "HMR-5", 2, "台", 4_150_000, "盛り付けロボット"),
            ("組合せ計量機（14ヘッド）", "HCW-14", 1, "台", 3_400_000, "自動計量機"),
            ("トップシール機", "HTS-12", 1, "台", 5_100_000, "トップシール包装機"),
            ("画像検査システム（盛付・ラベル）", "HVS-2", 1, "式", 3_900_000, "画像検査装置"),
            ("ウェイトチェッカー付きラベラー", "HWL-30", 1, "台", 2_000_000, "重量チェッカーとラベラー"),
            ("連結コンベヤ", "HCV-8", 1, "式", 800_000, "コンベヤと据え付け・調整"),
            ("据付・調整作業", "—", 1, "式", 600_000, "コンベヤと据え付け・調整"),
        ],
    },
}
QUOTE_DATE = "2026年10月20日"  # H-04
QUOTE_VALID_UNTIL = "2027年1月31日"  # H-04
TAX_RATE = 10
SUBJECT = "惣菜の盛り付け・計量・包装・検査ライン"
QUOTE_NOTES = [
    "金額は消費税抜きで表示しています。消費税（10%）は下に分けて記しました。",
    "納期：ご発注から約5か月。据付と試運転調整に、さらに約1か月かかります。",  # H-07
    "電気工事は含みません。御社の今の電気の容量で動かせることを、現地で確かめました。",  # H-08
    "据付は、機械を置いて床に固定する作業です。基礎工事は含みません。",  # H-08
    "受渡場所：御社 本社工場　　お支払い：ご相談のうえ決めます。",
]


def quote_totals(items: list[tuple]) -> tuple[int, int, int]:
    subtotal = sum(qty * price for _, _, qty, _, price, _ in items)
    tax = subtotal * TAX_RATE // 100
    return subtotal, tax, subtotal + tax


def yen(v: int) -> str:
    return f"{v:,}"


def quote(key: str) -> list:
    q = QUOTES[key]
    items = q["items"]
    subtotal, tax, grand = quote_totals(items)
    tsubasa = key == "つばさ台フードシステム"

    def page1(pg: Page) -> None:
        c = pg.c
        pg.title("御見積書" if tsubasa else "見　積　書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, f"見積番号　{q['number']}")
        c.drawRightString(RIGHT, pg.y + 5, f"発行日　{QUOTE_DATE}")
        # 宛名（A-01、A-08）
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{COMPANY}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        c.setFont(MINCHO, 10)
        c.drawString(LEFT, pg.y - 32, f"代表取締役　{PRESIDENT}　様")
        # 発行者（架空。実在しない郵便番号と所在地にし、電話番号と登録番号は書かない）
        x = LEFT + 300
        c.setFont(GOTHIC, 11)
        c.drawString(x, pg.y - 12, q["issuer"])
        c.setFont(MINCHO, 9)
        c.drawString(x, pg.y - 27, "〒000-0000　架空の所在地（テスト用）")
        c.drawString(x, pg.y - 40, "営業部")
        pg.y -= 62
        pg.para("下記のとおり、お見積り申し上げます。", size=10)
        pg.kv("件名", SUBJECT, key_width=110)
        pg.kv("見積金額（税込）", f"{yen(grand)}円", key_width=110)
        pg.kv("有効期限", QUOTE_VALID_UNTIL, key_width=110)
        pg.gap(4)
        # 明細の表
        # 列の幅の和は、本文の幅（RIGHT − LEFT）に合わせる
        widths = [24, 192, 58, 32, 26, 66, 77] if tsubasa else [24, 186, 64, 32, 26, 68, 75]
        header = ["No.", "品名", "型番", "数量", "単位", "単価（税抜）", "金額（税抜）"]
        rows = [header] + [
            [str(i), name, model, str(qty), unit, yen(price), yen(qty * price)]
            for i, (name, model, qty, unit, price, _) in enumerate(items, start=1)
        ]
        size = 8.4
        h = size + 9
        fill = Color(0.88, 0.92, 0.97) if tsubasa else Color(0.92, 0.92, 0.92)
        for r, cells in enumerate(rows):
            xx = LEFT
            for i, (cell, w) in enumerate(zip(cells, widths)):
                if r == 0:
                    c.setFillColor(fill)
                    c.rect(xx, pg.y - 5, w, h, fill=1, stroke=1)
                    c.setFillColor(black)
                else:
                    c.rect(xx, pg.y - 5, w, h, fill=0, stroke=1)
                c.setFont(GOTHIC if r == 0 else MINCHO, size)
                if r == 0 or i in (1, 2, 4):
                    c.drawString(xx + 4, pg.y, cell)
                else:
                    c.drawRightString(xx + w - 4, pg.y, cell)
                xx += w
            pg.y -= h
        # 小計・消費税・合計
        label_w = sum(widths[:-1])
        for label, value in (("小計（税抜）", subtotal), (f"消費税（{TAX_RATE}%）", tax), ("合計（税込）", grand)):
            c.rect(LEFT, pg.y - 5, label_w, h, fill=0, stroke=1)
            c.rect(LEFT + label_w, pg.y - 5, widths[-1], h, fill=0, stroke=1)
            c.setFont(GOTHIC, size)
            c.drawRightString(LEFT + label_w - 6, pg.y, label)
            c.drawRightString(LEFT + label_w + widths[-1] - 4, pg.y, yen(value))
            pg.y -= h
        pg.gap(10)
        pg.heading("備考", 10)
        for note in QUOTE_NOTES:
            pg.para(f"・{note}", indent=1, size=9)

    return [page1]


# ---------------------------------------------------------------------------
# カタログ（つばさ台フードシステム）。機械は写真ではなく図で描く
# ---------------------------------------------------------------------------

# ラインの能力（回答表にない数字。H-09・H-10・E-07 と合うように決めた）
LINE_PACKS_PER_MINUTE = 12  # いちばん遅いトップシール包装機に合わせる
PACKS_PER_DAY = 4_500  # H-10
LINE_STAFF = 2  # H-09
FACTORY_HOURS = 10  # E-07（朝5時から15時）

MACHINES = [
    {
        "name": "盛り付けロボット",
        "model": "TF-MR200",
        "text": "つかむ手と吸い付ける手を付け替えて、煮物・焼き物・揚げ物・和え物を容器の決まった位置に盛り付けます。"
        "品目ごとの盛り付けの形を登録しておき、画面で呼び出して切り替えます。",
        "spec": [
            ("能力", "1台あたり毎分最大8食"),
            ("盛り付け位置のずれ", "±5mm 以内"),
            ("使える容器", "幅100〜250mm"),
            ("電源", "三相200V　2.0kW"),
            ("大きさ・重さ", "幅900×奥行800×高さ1,600mm　約280kg"),
            ("洗浄", "食品に触れる部品は外して水洗いできます"),
        ],
    },
    {
        "name": "自動計量機（組合せ計量）",
        "model": "TF-AW14",
        "text": "14個の計量の器から、決めた重さに近い組合せを選んで落とします。和え物や煮物の1食分の量をそろえます。",
        "spec": [
            ("能力", "毎分最大40回"),
            ("計量の範囲", "20〜500g"),
            ("ばらつきの目安", "±1.5g"),
            ("電源", "単相200V　1.2kW"),
        ],
    },
    {
        "name": "トップシール包装機",
        "model": "TF-TS60",
        "text": "容器の上面にフィルムを熱でシールします。容器に合わせた金型は、約10分で交換できます。",
        "spec": [
            ("能力", "毎分最大12パック"),
            ("使える容器", "最大で幅230×奥行180mm"),
            ("電源", "三相200V　4.5kW"),
        ],
    },
    {
        "name": "画像検査装置（盛り付け・ラベル）",
        "model": "TF-VI2",
        "text": "カメラ2台で、盛り付けの欠けやはみ出しと、ラベルの品名・アレルギー表示・日付を確かめます。"
        "ラベルの文字は注文のデータと照らし、合わないパックはラインの外に出します。",
        "spec": [
            ("能力", "毎分最大30パック"),
            ("カメラ", "2台（盛り付け用・ラベル用）"),
            ("電源", "単相100V　0.5kW"),
        ],
    },
    {
        "name": "重量チェッカー・ラベラー（一体型）",
        "model": "TF-CL10",
        "text": "1パックずつ重さを量り、決めた範囲から外れたものを外します。品名・原材料・アレルギー・消費期限・重さを印字して貼ります。",
        "spec": [
            ("能力", "毎分最大30パック"),
            ("量れる重さ", "20〜1,500g"),
            ("電源", "単相100V　0.8kW"),
        ],
    },
    {
        "name": "搬送コンベヤ（ライン連結用）",
        "model": "TF-CV8",
        "text": "上の機械をつなぎ、容器を次の機械へ送ります。ステンレス製で、水洗いできます。",
        "spec": [
            ("長さ", "合計約8m"),
            ("電源", "単相100V　0.2kW"),
        ],
    },
]
LINE_POWER_KW = 2 * 2.0 + 1.2 + 4.5 + 0.5 + 0.8 + 0.2


def catalog() -> list:
    def box(c, x: float, y: float, w: float, h: float, label: str, sub: str) -> None:
        c.setFillColor(Color(0.9, 0.95, 0.9))
        c.roundRect(x, y, w, h, 6, fill=1, stroke=1)
        c.setFillColor(black)
        c.setFont(GOTHIC, 8.5)
        for i, line in enumerate(wrap(label, GOTHIC, 8.5, w - 8)):
            c.drawCentredString(x + w / 2, y + h - 14 - i * 11, line)
        c.setFont(MINCHO, 7.5)
        c.drawCentredString(x + w / 2, y + 6, sub)

    def cover(pg: Page) -> None:
        c = pg.c
        pg.title("惣菜の盛り付け・包装ライン", 20)
        pg.center("製品のご案内　2026年版", 12)
        pg.center("株式会社つばさ台フードシステム", 11)
        pg.gap(14)
        pg.heading("ラインの構成")
        # 構成図：左から右へ流れる。盛り付けロボットは2台
        names = [
            ("自動計量機", "TF-AW14"),
            ("盛り付けロボット（2台）", "TF-MR200"),
            ("画像検査（盛り付け）", "TF-VI2"),
            ("トップシール包装機", "TF-TS60"),
            ("重量チェッカー・ラベラー", "TF-CL10"),
            ("画像検査（ラベル）", "TF-VI2"),
        ]
        w, h, gap = 66, 56, 12
        y = pg.y - h
        x = LEFT
        for i, (label, sub) in enumerate(names):
            box(c, x, y, w, h, label, sub)
            if i < len(names) - 1:
                c.line(x + w, y + h / 2, x + w + gap, y + h / 2)
                c.line(x + w + gap - 4, y + h / 2 + 3, x + w + gap, y + h / 2)
                c.line(x + w + gap - 4, y + h / 2 - 3, x + w + gap, y + h / 2)
            x += w + gap
        c.setFont(MINCHO, 8)
        c.drawString(LEFT, y - 14, "機械どうしは搬送コンベヤ（TF-CV8）でつなぎます。図は配置のイメージです（写真ではありません）。")
        pg.y = y - 40
        pg.heading("ラインの特長")
        for text in (
            "品目ごとの盛り付けの形・重さ・ラベルを登録し、画面で呼び出して切り替えます。多品種・小ロットの日替わりに向きます。",
            "盛り付けとラベルをカメラで確かめ、合わないパックはラインの外に出します。",
            "パックごとの重さと検査の結果を記録に残します。",
        ):
            pg.para(f"・{text}", indent=1)

    def machine_page(start: int, end: int, heading: str):
        def draw(pg: Page) -> None:
            pg.title(heading, 14)
            for m in MACHINES[start:end]:
                pg.heading(f"{m['name']}　{m['model']}")
                pg.para(m["text"], indent=1, size=9.5)
                pg.gap(2)
                for key, value in m["spec"]:
                    pg.kv(key, value, key_width=130, size=9)
                pg.gap(8)

        return draw

    def capacity(pg: Page) -> None:
        pg.title("ラインの能力と導入の目安", 14)
        per_hour = LINE_PACKS_PER_MINUTE * 60
        minutes = PACKS_PER_DAY * 60 // per_hour
        for key, value in (
            ("ライン全体の能力", f"毎分最大{LINE_PACKS_PER_MINUTE}パック（1時間に最大{per_hour:,}パック）"),
            (
                "1日{:,}パックのとき".format(PACKS_PER_DAY),
                f"ラインの稼働は約{minutes // 60}時間{minutes % 60}分（段取り替えの時間を除く）",
            ),
            ("段取り替え", "品目の切り替えは、登録した設定を呼び出して1回約1分。容器が変わり金型を替えるときは約10分"),
            ("ラインに付く人の目安", f"{LINE_STAFF}人（材料の投入、監視と段取り替え）"),
            ("電源", f"三相200V・単相100V／200V。消費電力の合計 約{LINE_POWER_KW:.1f}kW"),
            ("置き場所の目安", "幅2.5m×長さ12m"),
            ("据付", "機械を置いて床に固定します。基礎工事は要りません"),
            ("納期", "ご発注から約5か月。据付と試運転調整に約1か月"),
            ("操作の説明", "据付の後、操作と日々の点検の説明を行います"),
        ):
            pg.kv(key, value, key_width=150, size=9.5)
        pg.gap(10)
        pg.para("数字は目安です。品目・容器・盛り付けの形によって変わります。", size=9)
        pg.para("価格は別にお見積りします。", size=9)

    return [
        cover,
        machine_page(0, 2, "盛り付けと計量"),
        machine_page(2, 6, "包装・検査・ラベルと、つなぐ機械"),
        capacity,
    ]


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
# Word の名簿（役員名簿・株主名簿）
# ---------------------------------------------------------------------------


def set_cell_shading(cell, color: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    props.append(shd)


def add_page_field(paragraph) -> None:
    """足にページ番号を入れる。"""
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
    # 頭の帯と足は、どのページにも出る
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


def add_title(doc, title: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.font.size = Pt(16)
    run.font.bold = True
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.add_run(f"{COMPANY}　{AS_OF}")


def add_table(doc, rows: list[list[str]], widths_mm: list[float]) -> None:
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
            run.font.size = Pt(9)
            if r == 0:
                run.font.bold = True
                set_cell_shading(cell, "E8EEF6")


def officer_list(path: Path) -> None:
    doc = new_document("役員名簿")
    add_title(doc, "役員名簿")
    rows = [
        ["役職", "氏名（ふりがな）", "生年月日", "性別", "住所", "就任年月日", "常勤・担当"],
        # A-08。生年月日の月日は回答表にない（回答表は1974年生まれだけ）
        [
            "代表取締役",
            f"{PRESIDENT}（さわむら ひろゆき）",
            "1974年6月14日",
            "男",
            OFFICER_ADDRESS,
            "2015年6月26日（2025年6月26日重任）",
            "常勤。経営全般",
        ],
        # A-09。生年月日とふりがなは回答表にない
        [
            "取締役",
            f"{DIRECTOR}（さわむら ゆみこ）",
            "1976年9月3日",
            "女",
            OFFICER_ADDRESS,
            "2015年6月26日（2025年6月26日重任）",
            "常勤。経理と総務",
        ],
    ]
    add_table(doc, rows, [20, 34, 24, 10, 36, 30, 22])
    doc.add_paragraph()
    for text in (
        "役員は上の2人です。監査役は置いていません。",  # A-09
        f"取締役の{DIRECTOR}は代表取締役の妻で、同居しています。",  # A-09
        "取締役の任期は10年です。2025年6月26日の定時株主総会で、2人とも重任しました。",  # D2a の履歴事項全部証明書
    ):
        doc.add_paragraph(text)
    doc.save(path)
    normalize_office(path)


SHAREHOLDERS = [
    # (氏名, 株の数) A-07。取得の日と事由は回答表にない
    (PRESIDENT, 150),
    (DIRECTOR, 50),
]
SHARES_ISSUED = 200  # A-07


def shareholder_list(path: Path) -> None:
    doc = new_document("株主名簿")
    add_title(doc, "株主名簿")
    doc.add_paragraph(f"発行済株式の総数　{SHARES_ISSUED}株（普通株式）。株券は発行していません。")
    rows = [["番号", "株主の氏名", "住所", "株式の種類と数", "持株の割合", "取得の年月日", "取得の事由"]]
    for i, (name, shares) in enumerate(SHAREHOLDERS, start=1):
        rows.append(
            [
                str(i),
                name,
                OFFICER_ADDRESS,
                f"普通株式 {shares}株",
                f"{shares / SHARES_ISSUED:.1%}",
                "2015年6月26日",
                "譲渡による取得（同日の株主総会で承認）",
            ]
        )
    rows.append(["", "合計", "", f"{sum(s for _, s in SHAREHOLDERS)}株", "100.0%", "", ""])
    add_table(doc, rows, [10, 26, 38, 26, 18, 26, 32])
    doc.add_paragraph()
    doc.add_paragraph("ほかの会社は、当社の株を持っていません。")  # A-07
    doc.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------
# 労働者名簿（Excel）。C-01〜C-06、C-15 に合わせる
# ---------------------------------------------------------------------------

# 名前・生年月日・雇入れの日・住所・履歴は回答表にない（架空）。住所は、東糀谷に実在しない丁目（七〜十丁目）にした
WORKERS = [
    # 正社員7人（C-02）。1日8時間・週5日（C-04）
    ("大橋 健一", "おおはし けんいち", "男", dt.date(1971, 3, 8), "東京都大田区東糀谷九丁目4番11号",
     dt.date(2008, 4, 1), "正社員", "期間の定めなし", "工場長（製造の管理）", 8, 5, "惣菜店（先代の個人事業）の調理"),
    ("森田 正樹", "もりた まさき", "男", dt.date(1980, 7, 21), "東京都大田区東糀谷十丁目2番6号",
     dt.date(2010, 5, 10), "正社員", "期間の定めなし", "調理", 8, 5, "飲食店の調理"),
    ("吉岡 恵", "よしおか めぐみ", "女", dt.date(1985, 11, 2), "東京都大田区東糀谷九丁目15番3号",
     dt.date(2014, 4, 1), "正社員", "期間の定めなし", "調理", 8, 5, "給食会社の調理"),
    ("石井 大輔", "いしい だいすけ", "男", dt.date(1992, 2, 14), "東京都大田区東糀谷七丁目9番20号",
     dt.date(2017, 4, 1), "正社員", "期間の定めなし", "調理", 8, 5, "調理の専門学校を卒業"),
    ("中川 美穂", "なかがわ みほ", "女", dt.date(1988, 5, 30), "東京都大田区東糀谷十丁目7番1号",
     dt.date(2016, 9, 1), "正社員", "期間の定めなし", "盛り付け・包装", 8, 5, "食品工場の包装"),
    ("平田 誠", "ひらた まこと", "男", dt.date(1979, 9, 17), "東京都大田区東糀谷九丁目1番18号",
     dt.date(2012, 6, 1), "正社員", "期間の定めなし", "配送", 8, 5, "運送会社の配送"),
    ("小西 沙織", "こにし さおり", "女", dt.date(1990, 12, 5), "東京都大田区東糀谷七丁目12番4号",
     dt.date(2019, 4, 1), "正社員", "期間の定めなし", "事務・営業", 8, 5, "食品卸の営業事務"),
    # パート8人（C-03）。6人は1日6時間・週5日、2人は1日4時間・週4日（C-05）。
    # 期間の定めなし5人、1年ごとの契約3人（C-06）。60歳以上は4人（C-15。2026年11月1日の年齢）。
    # 盛り付けから検品までのパート5人は、どれも1日6時間（G-03：正社員1人8時間＋パート5人×6時間＝延べ38時間）。
    # 1日4時間の2人は、調理の補助と洗い場にした
    ("山口 久美子", "やまぐち くみこ", "女", dt.date(1962, 4, 11), "東京都大田区東糀谷十丁目11番9号",
     dt.date(2013, 10, 1), "パート", "期間の定めなし", "調理の補助", 6, 5, "スーパーの惣菜売場"),
    ("岡田 由紀", "おかだ ゆき", "女", dt.date(1964, 6, 3), "東京都大田区東糀谷十丁目3番17号",
     dt.date(2015, 3, 1), "パート", "期間の定めなし", "調理の補助", 4, 4, "事務"),
    ("斉藤 照子", "さいとう てるこ", "女", dt.date(1959, 1, 19), "東京都大田区東糀谷七丁目5番14号",
     dt.date(2011, 7, 1), "パート", "期間の定めなし", "盛り付け・計量・包装・検品", 6, 5, "弁当店の盛り付け"),
    ("松本 和子", "まつもと かずこ", "女", dt.date(1968, 8, 25), "東京都大田区東糀谷九丁目8番2号",
     dt.date(2018, 4, 1), "パート", "期間の定めなし", "盛り付け・計量・包装・検品", 6, 5, "飲食店の接客"),
    ("野村 さゆり", "のむら さゆり", "女", dt.date(1983, 10, 28), "東京都大田区東糀谷九丁目10番5号",
     dt.date(2021, 4, 1), "パート", "1年ごとの契約（更新）", "盛り付け・計量・包装・検品", 6, 5, "食品工場の検品"),
    ("上田 真由美", "うえだ まゆみ", "女", dt.date(1987, 2, 9), "東京都大田区東糀谷七丁目14番8号",
     dt.date(2022, 5, 9), "パート", "1年ごとの契約（更新）", "盛り付け・計量・包装・検品", 6, 5, "飲食店の調理補助"),
    ("原 秀夫", "はら ひでお", "男", dt.date(1970, 5, 7), "東京都大田区東糀谷九丁目13番1号",
     dt.date(2016, 11, 1), "パート", "期間の定めなし", "盛り付け・計量・包装・検品", 6, 5, "製造業の工場勤務"),
    ("西村 春江", "にしむら はるえ", "女", dt.date(1961, 12, 15), "東京都大田区東糀谷十丁目6番12号",
     dt.date(2023, 6, 1), "パート", "1年ごとの契約（更新）", "洗い場", 4, 4, "給食センターの洗浄"),
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
    # 頭の帯（シートの1行目）。印刷したときも、頭と足に出す
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
    for letter, width in zip(
        "ABCDEFGHIJKLMNO", [5, 12, 16, 5, 16, 30, 16, 9, 18, 24, 9, 9, 9, 20, 16]
    ):
        ws.column_dimensions[letter].width = width
    ws.row_dimensions[5].height = 30
    ws.freeze_panes = "C6"
    # 印刷は横1ページに収める
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

PDF_DOCUMENTS = [
    (QUOTES["つばさ台フードシステム"]["file"], "御見積書（つばさ台フードシステム）", lambda: quote("つばさ台フードシステム")),
    (QUOTES["ほしみ機工"]["file"], "見積書（ほしみ機工）", lambda: quote("ほしみ機工")),
    ("カタログ_つばさ台フードシステム.pdf", "製品のご案内（つばさ台フードシステム）", catalog),
]


def main() -> None:
    # 見積の小計が H-02・H-03 と合うか（千円）
    for key, want in (("つばさ台フードシステム", 22_500), ("ほしみ機工", 24_100)):
        subtotal, _, _ = quote_totals(QUOTES[key]["items"])
        if subtotal != want * 1000:
            raise ValueError(f"{key} の見積の小計 {subtotal:,}円が、回答表の {want:,}千円と合いません")
    for name, doc_name, build in PDF_DOCUMENTS:
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
