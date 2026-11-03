# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pillow>=10"]
# ///
"""デモの会社の、会社の資料と過去の書類（TASKS D8）を作る。

作るもの：
- 会社案内（PDF）、商品のご案内（PDF）、工場の会議の議事録（Word）、作業の写真4枚（JPEG。描いた絵）
- 既存事業の売上と経費の内訳（Excel。取引先の種類ごと・商品の種類ごと・月別・経費）
- 過去の申請1件：2025年のものづくり補助金（20次締切）の事業計画書の控え（Word）、
  採択結果の通知（不採択。PDF）、審査のコメント（PDF）。回答表 J-06 に合わせる

数字と事実は testdata/デモの会社/回答表.md と、D2a・D2b の書類に合わせる（行ごとに回答表の ID を添えた）。
ID のない事柄は回答表にないもので、資料の一覧.md の「回答表にない事柄」に挙げた。

どのページ・シート・写真にも「架空のテスト用データ」を出す。PDF・Word の描き方は D2a・D2b のものを使う。
通知と審査のコメントは、事務局の通知の見た目（ロゴ・公印・様式）を写さず、独自の配置にした。
写真は実在の工場が分からないよう、Pillow で描いた絵にした。人の顔は描かない。

動かし方：uv run --script testdata/会社の資料/make_materials.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# 材料は「材料/」にだけ置く。スクリプトと資料の一覧（答えや作る側の事情を書いたもの）を、
# テストで会社のフォルダに写す材料に混ぜないため
OUT_DIR = Path(__file__).resolve().parent / "材料"
DOCS_DIR = Path(__file__).resolve().parent.parent / "デモの会社" / "書類"
sys.path.insert(0, str(DOCS_DIR))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Pt  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from make_documents import ADDRESS, BANNER, COMPANY, GOTHIC, LEFT, PRESIDENT, Page, render  # noqa: E402
from make_documents_part2 import FIXED_TIME, add_table, new_document, normalize_office  # noqa: E402

# ---------------------------------------------------------------------------
# 会社案内（A-01、A-04〜A-06、A-08、A-12、A-13、B-01、C-01、E-01、E-03〜E-08、K-03）
# ---------------------------------------------------------------------------


def company_profile() -> list:
    def page1(pg: Page) -> None:
        pg.title(f"{COMPANY}　会社案内", 18)
        pg.center("病院・介護施設・スーパーの、毎日の食卓に", 11)
        pg.gap(8)
        pg.heading("ごあいさつ")
        pg.para(
            "1996年に先代が小さな惣菜店を始めてから、地域の食卓に惣菜を届けてきました。"  # A-05
            "いまは病院・介護施設・スーパーに、日替わりで約40品目の惣菜をお届けしています。"  # E-01、E-04
            "私たちが大切にしているのは、病院や介護施設の細かいご注文を断らないこと、"
            "そしてアレルギーの表示を間違えないことです。",  # K-03
            indent=1,
        )
        pg.right(f"代表取締役　{PRESIDENT}", 10)
        pg.gap(6)
        pg.heading("会社の概要")
        for key, value in (
            ("社名", COMPANY),  # A-01
            ("本店・工場", ADDRESS),  # B-01
            ("設立", "2008年4月1日"),  # A-04
            ("資本金", "1,000万円"),  # A-06
            ("代表者", f"代表取締役　{PRESIDENT}"),  # A-08
            ("従業員", "15名（正社員7名、パート8名）"),  # C-01
            ("事業の内容", "惣菜の製造と販売（煮物、焼き物、和え物、揚げ物など）"),  # A-11、A-12
            ("主なお取引先", "スーパー3社（14店舗）、病院2か所、介護施設11か所、仕出し・弁当店、飲食店"),  # E-01
            ("工場の稼働", "月曜から土曜、朝5時から15時"),  # E-07
            ("衛生の管理", "HACCP に沿った衛生管理"),  # E-08
            ("ホームページ", "https://www.example.com/"),  # A-13
            ("メール", "info@example.com"),  # A-13
        ):
            pg.kv(key, value, key_width=110)

    def page2(pg: Page) -> None:
        pg.heading("あゆみ")
        for key, value in (
            ("1996年", "先代が、個人で惣菜店を始める"),  # A-05
            ("2008年4月", f"{COMPANY}を設立する"),  # A-04
            ("2011年", "病院向けの惣菜の納入を始める"),
            ("2015年", f"{PRESIDENT}が代表取締役に就く"),  # A-05
            ("2016年", "介護施設向けに、やわらか食・きざみ食・ペースト食を始める"),
        ):
            pg.kv(key, value, key_width=110)
        pg.gap(8)
        pg.heading("私たちの強み")
        for text in (
            "病院や介護施設ごとの細かいご注文（やわらか食、きざみ食、ペースト食、減塩など）に応えます。",  # E-03
            "スーパーの日替わりのご注文に、いろいろな品を少しずつ、短い納期でお届けします。",  # E-03
            "アレルギーの表示は、事務の担当と工場長が二重に確かめています。",  # E-08
        ):
            pg.para(f"・{text}", indent=1)
        pg.gap(8)
        pg.heading("1日の流れ")
        for text in (
            "病院・介護施設：前日15時までのご注文を、翌朝お届けします。",  # E-05
            "スーパー：前日の夕方に数が決まり、朝6時と10時の2回お届けします。",  # E-05
            "1日に約3,500パック。日替わりで約40品目、月に約120品目をつくります。",  # E-04、E-06
        ):
            pg.para(f"・{text}", indent=1)

    return [page1, page2]


# ---------------------------------------------------------------------------
# 商品のご案内（A-12、E-03、E-05、E-08）
# ---------------------------------------------------------------------------

PRODUCT_KINDS = [
    ("煮物", "筑前煮、かぼちゃの煮物、ひじき煮、肉じゃが"),
    ("焼き物", "さばの塩焼き、鶏の照り焼き、だし巻き卵"),
    ("和え物", "ほうれん草の胡麻和え、白和え、ポテトサラダ"),
    ("揚げ物", "鶏の唐揚げ、コロッケ、白身魚のフライ"),
    ("ご飯もの・その他", "炊き込みご飯、季節の小鉢"),
]
FORMS = [
    ("普通食", "ふだんのかたさと大きさ"),
    ("やわらか食", "歯ぐきでつぶせるかたさに煮る"),
    ("きざみ食", "食べやすい大きさに細かく刻む"),
    ("ペースト食", "なめらかにして、まとまりをよくする"),
    ("減塩", "塩分を控えた味付け"),
]


def product_guide() -> list:
    def page1(pg: Page) -> None:
        pg.title("商品のご案内", 18)
        pg.center(COMPANY, 11)
        pg.gap(8)
        pg.heading("惣菜の種類（日替わりの例）")
        for key, value in PRODUCT_KINDS:
            pg.kv(key, value, key_width=130)
        pg.para("日替わりで1日に約40品目、月に約120品目をつくります。", indent=1, size=9.5)  # E-04
        pg.gap(8)
        pg.heading("病院・介護施設向けの形態")  # E-03
        for key, value in FORMS:
            pg.kv(key, value, key_width=130)
        pg.para("施設ごとに、形態・量・塩分のご指定に合わせます。", indent=1, size=9.5)

    def page2(pg: Page) -> None:
        pg.heading("包装と表示")
        for key, value in (
            ("容器", "1人前ずつのパック（スーパー向け・施設向け）"),
            ("ラベル", "品名、原材料、アレルギー、消費期限、重さ"),
            ("アレルギーの表示", "事務の担当と工場長が、二重に確かめます"),  # E-08
            ("保存", "10℃以下。消費期限は製造日を含めて2日"),
        ):
            pg.kv(key, value, key_width=130)
        pg.gap(8)
        pg.heading("ご注文とお届け")
        for key, value in (
            ("病院・介護施設", "前日15時までのご注文を、翌朝お届けします"),  # E-05
            ("スーパー", "前日の夕方に数を決めていただき、朝6時と10時の2回お届けします"),  # E-05
        ):
            pg.kv(key, value, key_width=130)
        pg.gap(8)
        pg.para("価格は、お取引の条件に合わせてご相談します。", size=9.5)

    return [page1, page2]


# ---------------------------------------------------------------------------
# 議事録（現場の困りごとの話し合い）。出る人の名前と仕事は、D2b の労働者名簿と同じ
# ---------------------------------------------------------------------------

MINUTES_FILE = "議事録_2026-09-10_工場の会議.docx"
MINUTES = {
    "title": "工場の会議　議事録",
    "meta": [
        ("日時", "2026年9月10日（木）15時30分〜16時30分"),
        ("場所", "本社工場　休憩室"),
        (
            "出た人",
            f"{PRESIDENT}（社長）、沢村 由美子（取締役）、大橋 健一（工場長）、中川 美穂（盛り付け・包装）、"
            "斉藤 照子（パート・盛り付け）、小西 沙織（事務・営業）",
        ),
        ("記録", "小西 沙織"),
    ],
    "items": [
        (
            "1．盛り付けから検品までの作業時間（工場長から）",
            [
                "8月17日から8月29日までの2週間（12日）、工程ごとに時間を測った。1日の延べ時間は、平均で約38時間だった。",  # G-03
                "内訳は、盛り付け約18時間、計量約7時間、包装（シール）約5時間、ラベル貼り約4時間、検品約4時間。",
                "きざみ食とペースト食の盛り付けは1食あたり約30秒かかり、普通食（約15秒）の約2倍だった。",
                "スーパーの6時便に間に合わせるため、5時から6時の1時間に盛り付けが集中している。",
            ],
        ),
        (
            "2．ミスとクレーム（小西さんから）",
            [
                "2025年度のクレーム7件の内訳は、計量のミス3件、ラベルのミス4件。ラベルの4件のうち1件が、アレルギーの表示の誤りだった。",  # G-04
                "7件のうち5件は、5時から6時の忙しい時間に作ったものだった。",
            ],
        ),
        (
            "3．包装の機械（中川さんから）",
            [
                "卓上のシール機2台のうち古いほうの1台が、この半年で4回止まった。止まるたびに、包装が約20分止まった。",  # G-02
            ],
        ),
        (
            "4．体の負担（斉藤さんから）",
            [
                "盛り付けを長く続けるので、手首や腰が痛いという人が3人いる。",
            ],
        ),
        (
            "5．人の募集（取締役から）",
            [
                "ハローワークでの募集は続けているが、朝5時から来られる人が見つからない。",  # C-13
            ],
        ),
        (
            "6．去年のものづくり補助金の振り返り（社長から）",
            [
                "去年は、機械の効果を業者の説明だけで書いた。審査のコメントでは、今の作業時間が示されていないこと、"
                "検品とラベルのミスへの対策がないこと、お金の用意の見込みが分からないことを指摘された。",  # J-06
                "今回は、自分たちで測った時間をもとに考える。盛り付けとラベルをカメラで確かめる機械も入れたい。",  # H-01
                "信用金庫には、10月に相談に行く。",  # H-12
            ],
        ),
        (
            "7．冷凍惣菜（小西さんから）",
            [
                "取引先の病院の管理栄養士から、「退院した人が家で食べられる、やわらか食や減塩のおかずがほしい」と言われている。",  # I-01
            ],
        ),
    ],
    "decisions": [
        "社長が、盛り付けと包装の機械を扱う業者2社に、10月中に見積を頼む。",  # H-03、H-04
        "工場長は、9月も作業時間を測り続ける。",
        "古いシール機は、修理の費用を中川さんが確かめる。",
        "冷凍惣菜の試作の相談は、次の会議で行う。",
    ],
    "next": "次の会議：2026年10月8日（木）15時30分から",
}


def minutes(path: Path) -> None:
    doc = new_document("工場の会議 議事録")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(MINUTES["title"])
    run.font.size = Pt(16)
    run.font.bold = True
    add_table(doc, [["項目", "内容"]] + [list(kv) for kv in MINUTES["meta"]], [25, 145])
    for heading, lines in MINUTES["items"]:
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(10)
        r = h.add_run(heading)
        r.font.bold = True
        for line in lines:
            doc.add_paragraph(f"・{line}")
    h = doc.add_paragraph()
    h.paragraph_format.space_before = Pt(10)
    h.add_run("決まったこと").font.bold = True
    for line in MINUTES["decisions"]:
        doc.add_paragraph(f"・{line}")
    doc.add_paragraph(MINUTES["next"])
    doc.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------
# 既存事業の売上と経費の内訳（Excel）。単位は千円。数式は使わず、値だけを入れる
# ---------------------------------------------------------------------------

DAYS_PER_YEAR = 300  # E-07（年に約300日）
# 取引先の種類ごと：(売上, 年間のパック数, 材料費)。第18期の売上は E-02、合計は F-01
BY_CUSTOMER = {
    17: [("スーパー", 101_500, 580_000, 41_100), ("病院・介護施設", 74_800, 340_000, 31_000), ("その他", 18_500, 100_000, 7_900)],
    18: [("スーパー", 105_000, 600_000, 42_500), ("病院・介護施設", 77_000, 350_000, 32_000), ("その他", 19_600, 100_000, 8_100)],
}
# 商品の種類ごと（第18期）：(売上, 年間のパック数)
BY_PRODUCT_18 = [
    ("煮物", 57_600, 300_000),
    ("焼き物", 46_200, 220_000),
    ("和え物", 36_800, 230_000),
    ("揚げ物", 42_000, 200_000),
    ("ご飯もの・その他", 19_000, 100_000),
]
# 第18期の月別の売上（病院・介護施設、その他）。スーパーは、月の売上（D2a の法人事業概況説明書）から2つを引いたもの
MONTHS_18 = ["2025年4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月", "2026年1月", "2月", "3月"]
MONTHLY_TOTAL_18 = [16_300, 16_600, 16_200, 16_800, 16_400, 16_500, 16_900, 17_000, 18_900, 16_200, 15_600, 18_200]
MONTHLY_CARE_18 = [6_300, 6_400, 6_400, 6_500, 6_400, 6_400, 6_500, 6_500, 6_600, 6_300, 6_100, 6_600]
MONTHLY_OTHER_18 = [1_500, 1_600, 1_400, 1_600, 1_500, 1_500, 1_600, 1_700, 2_600, 1_500, 1_300, 1_800]
# 経費（決算書の科目を、原材料費・人件費・減価償却費・その他の4つに分けた）。D2a の決算書と同じ数字
COSTS = {
    17: {
        "原材料費": [("材料費（製造原価）", 80_000)],
        "人件費": [
            ("賃金給与（製造原価）", 32_200),
            ("法定福利費（製造原価）", 4_800),
            ("役員報酬", 10_800),
            ("給料手当", 7_900),
            ("法定福利費（販管費）", 2_800),
            ("福利厚生費", 600),
        ],
        "減価償却費": [("減価償却費（製造原価）", 3_000), ("減価償却費（販管費）", 900)],
        "その他": [
            ("水道光熱費", 9_500),
            ("消耗品・包装材料費", 8_300),
            ("地代家賃", 4_800),
            ("修繕費その他", 900),
            ("荷造運賃", 7_200),
            ("車両費", 3_700),
            ("リース料", 2_600),
            ("その他（販管費）", 10_900),
        ],
    },
    18: {  # F-09、F-10
        "原材料費": [("材料費（製造原価）", 82_600)],
        "人件費": [
            ("賃金給与（製造原価）", 33_400),
            ("法定福利費（製造原価）", 5_000),
            ("役員報酬", 10_800),
            ("給料手当", 8_200),
            ("法定福利費（販管費）", 2_900),
            ("福利厚生費", 600),
        ],
        "減価償却費": [("減価償却費（製造原価）", 2_800), ("減価償却費（販管費）", 800)],
        "その他": [
            ("水道光熱費", 9_800),
            ("消耗品・包装材料費", 8_600),
            ("地代家賃", 4_800),
            ("修繕費その他", 1_200),
            ("荷造運賃", 7_400),
            ("車両費", 3_800),
            ("リース料", 2_600),
            ("その他（販管費）", 11_500),
        ],
    },
}
SALES = {17: 194_800, 18: 201_600}  # F-01


def business_breakdown(path: Path) -> None:
    thin = Side(style="thin", color="808080")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="E8EEF6")
    wb = Workbook()
    wb.remove(wb.active)

    def sheet(title: str, heading: str, header: list[str], rows: list[list], widths: list[int]) -> None:
        ws = wb.create_sheet(title)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(header), 6))
        ws.cell(1, 1, BANNER).font = Font(name="游ゴシック", size=9, bold=True)
        ws.cell(1, 1).fill = PatternFill("solid", fgColor="FFF2BF")
        ws.cell(2, 1, heading).font = Font(name="游ゴシック", size=13, bold=True)
        ws.cell(3, 1, f"{COMPANY}　単位：千円（パック数と単価を除く）。会計ソフトの集計から転記した").font = Font(
            name="游ゴシック", size=9
        )
        for i, title_ in enumerate(header, start=1):
            c = ws.cell(5, i, title_)
            c.font = Font(name="游ゴシック", size=9, bold=True)
            c.fill = head_fill
            c.border = border
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for r, values in enumerate(rows, start=6):
            for i, v in enumerate(values, start=1):
                c = ws.cell(r, i, v)
                c.font = Font(name="游ゴシック", size=9, bold=str(values[0]).startswith("合計"))
                c.border = border
                if isinstance(v, int):
                    c.number_format = "#,##0"
                elif isinstance(v, float):
                    c.number_format = "0.0%"
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[chr(64 + i)].width = w
        ws.oddHeader.center.text = "架空のテスト用データ（hojokin-oss）　実在の会社とは関係ありません"
        ws.oddFooter.center.text = f"架空のテスト用データ｜{title}｜&P/&N"
        ws.page_setup.orientation = "landscape"

    # 取引先の種類ごと
    rows = []
    for period in (17, 18):
        data = BY_CUSTOMER[period]
        for name, sales, packs, materials in data:
            rows.append([f"第{period}期", name, sales, packs, packs // DAYS_PER_YEAR, round(sales * 1000 / packs), materials, round(materials / sales, 3)])
        s = sum(d[1] for d in data)
        p = sum(d[2] for d in data)
        m = sum(d[3] for d in data)
        rows.append([f"合計（第{period}期）", "", s, p, p // DAYS_PER_YEAR, round(s * 1000 / p), m, round(m / s, 3)])
    sheet(
        "取引先の種類ごと",
        "取引先の種類ごとの売上と材料費（第17期・第18期）",
        ["期", "取引先の種類", "売上", "年間のパック数", "1日のパック数（年300日）", "平均単価（円）", "材料費", "材料費の割合"],
        rows,
        [16, 16, 12, 14, 14, 12, 12, 12],
    )
    # 商品の種類ごと
    rows = [[name, sales, packs, round(sales * 1000 / packs)] for name, sales, packs in BY_PRODUCT_18]
    s = sum(r[1] for r in BY_PRODUCT_18)
    p = sum(r[2] for r in BY_PRODUCT_18)
    rows.append(["合計", s, p, round(s * 1000 / p)])
    sheet("商品の種類ごと", "商品の種類ごとの売上（第18期）", ["商品の種類", "売上", "年間のパック数", "平均単価（円）"], rows, [18, 12, 14, 12])
    # 月別
    rows = []
    for month, total_, care, other in zip(MONTHS_18, MONTHLY_TOTAL_18, MONTHLY_CARE_18, MONTHLY_OTHER_18):
        rows.append([month, total_ - care - other, care, other, total_])
    rows.append(["合計", *[sum(r[i] for r in rows) for i in range(1, 5)]])
    sheet("月別の売上", "取引先の種類ごとの月別の売上（第18期）", ["月", "スーパー", "病院・介護施設", "その他", "計"], rows, [14, 12, 14, 12, 12])
    # 経費
    rows = []
    for group in ("原材料費", "人件費", "減価償却費", "その他"):
        items17 = dict(COSTS[17][group])
        for name, v18 in COSTS[18][group]:
            rows.append([group, name, items17[name], v18])
        rows.append([f"合計（{group}）", "", sum(items17.values()), sum(v for _, v in COSTS[18][group])])
    cost17 = sum(v for g in COSTS[17].values() for _, v in g)
    cost18 = sum(v for g in COSTS[18].values() for _, v in g)
    rows.append(["合計（経費）", "売上原価と販売費及び一般管理費の和", cost17, cost18])
    rows.append(["売上", "", SALES[17], SALES[18]])
    rows.append(["営業利益", "売上 − 経費", SALES[17] - cost17, SALES[18] - cost18])
    sheet("経費の内訳", "経費の内訳（決算書の科目を4つに分けた。第17期・第18期）", ["区分", "科目", "第17期", "第18期"], rows, [16, 34, 12, 12])

    wb.properties.creator = "hojokin-oss のテスト用データ"
    wb.properties.lastModifiedBy = "hojokin-oss のテスト用データ"
    wb.properties.title = "既存事業の売上と経費（架空のテスト用データ）"
    wb.properties.created = wb.properties.modified = FIXED_TIME
    wb.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------
# 作業の写真（描いた絵）。実在の工場が分からないもの。人の顔は描かない
# ---------------------------------------------------------------------------

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]
PHOTO_SIZE = (1280, 960)
PHOTO_MARK = "架空のテスト用データ（hojokin-oss）　描いたイメージで、実在の工場の写真ではありません"


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit("日本語の書体が見つかりません。FONT_CANDIDATES に書体のファイルを足してください")


def photo_base(caption: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", PHOTO_SIZE, (214, 218, 222))
    d = ImageDraw.Draw(img)
    # 壁の白いタイルと、ステンレスの作業台
    for x in range(0, PHOTO_SIZE[0], 80):
        d.line([(x, 60), (x, 300)], fill=(200, 204, 208), width=2)
    for y in range(60, 300, 80):
        d.line([(0, y), (PHOTO_SIZE[0], y)], fill=(200, 204, 208), width=2)
    for i in range(560):
        shade = 170 + int(40 * i / 560)
        d.line([(0, 300 + i), (PHOTO_SIZE[0], 300 + i)], fill=(shade, shade + 3, shade + 6))
    # 頭の帯と、足の説明
    d.rectangle([0, 0, PHOTO_SIZE[0], 56], fill=(255, 242, 191), outline=(217, 153, 0), width=3)
    d.text((PHOTO_SIZE[0] // 2, 28), PHOTO_MARK, fill=(0, 0, 0), font=font(24), anchor="mm")
    d.rectangle([0, PHOTO_SIZE[1] - 64, PHOTO_SIZE[0], PHOTO_SIZE[1]], fill=(40, 40, 40))
    d.text((24, PHOTO_SIZE[1] - 32), caption, fill=(255, 255, 255), font=font(28), anchor="lm")
    d.text((PHOTO_SIZE[0] - 24, PHOTO_SIZE[1] - 32), "架空のテスト用データ", fill=(255, 230, 150), font=font(22), anchor="rm")
    return img, d


def glove(d: ImageDraw.ImageDraw, x: int, y: int, angle_left: bool = True) -> None:
    """手袋をした手（上から見た形）。腕は画面の外から入る。"""
    blue = (120, 170, 220)
    edge = (80, 120, 170)
    arm_x = x - 160 if angle_left else x + 160
    d.polygon([(arm_x - 40, 900), (arm_x + 40, 900), (x + 30, y + 40), (x - 30, y + 40)], fill=(235, 235, 240), outline=(190, 190, 200))
    d.ellipse([x - 45, y - 40, x + 45, y + 60], fill=blue, outline=edge, width=3)
    for i, dx in enumerate((-36, -14, 8, 30)):
        d.rounded_rectangle([x + dx - 9, y - 90 + abs(i - 1.5) * 8, x + dx + 9, y - 20], radius=9, fill=blue, outline=edge, width=2)


def tray(d: ImageDraw.ImageDraw, x: int, y: int, foods: list[tuple[int, int, int]], filled: int) -> None:
    """仕切りのある容器。filled の数だけ仕切りに惣菜が入る。"""
    d.rounded_rectangle([x, y, x + 200, y + 140], radius=14, fill=(245, 245, 245), outline=(150, 150, 150), width=3)
    cells = [(x + 10, y + 10, x + 95, y + 130), (x + 105, y + 10, x + 190, y + 65), (x + 105, y + 75, x + 190, y + 130)]
    for i, (box, color) in enumerate(zip(cells, foods)):
        d.rectangle(box, outline=(190, 190, 190), width=2)
        if i < filled:
            bx0, by0, bx1, by1 = box
            d.ellipse([bx0 + 6, by0 + 6, bx1 - 6, by1 - 6], fill=color)
            for k in range(5):
                cx = bx0 + 14 + (k * 23) % max(bx1 - bx0 - 28, 1)
                cy = by0 + 14 + (k * 17) % max(by1 - by0 - 28, 1)
                d.ellipse([cx, cy, cx + 12, cy + 9], fill=tuple(max(c - 40, 0) for c in color))


NIMONO = (176, 120, 60)
AEMONO = (80, 140, 60)
AGEMONO = (200, 150, 70)
YAKIMONO = (150, 90, 50)


def photo_moritsuke() -> Image.Image:
    img, d = photo_base("作業の写真1　盛り付け（手で1つずつ容器に盛る）")
    for row in range(2):
        for col in range(5):
            filled = 3 if row == 1 else (col % 3) + 1
            tray(d, 70 + col * 230, 360 + row * 190, [NIMONO, AEMONO, AGEMONO], filled)
    d.ellipse([980, 330, 1230, 470], fill=(225, 225, 230), outline=(150, 150, 160), width=4)  # 惣菜を入れたボウル
    d.ellipse([1000, 345, 1210, 455], fill=NIMONO)
    glove(d, 560, 470)
    glove(d, 1080, 520, angle_left=False)
    return img


def photo_keiryo() -> Image.Image:
    img, d = photo_base("作業の写真2　計量（はかりで1つずつ量る）")
    d.rounded_rectangle([420, 420, 860, 760], radius=20, fill=(235, 235, 235), outline=(120, 120, 120), width=4)  # はかり
    d.rectangle([470, 650, 810, 730], fill=(30, 40, 30), outline=(90, 90, 90), width=3)
    d.text((640, 690), "152 g", fill=(120, 255, 140), font=font(56), anchor="mm")
    tray(d, 540, 460, [NIMONO, AEMONO, AGEMONO], 2)
    for col in range(3):
        tray(d, 80 + col * 0, 360 + col * 160, [YAKIMONO, AEMONO, NIMONO], 3)
    d.ellipse([950, 360, 1220, 520], fill=(225, 225, 230), outline=(150, 150, 160), width=4)
    d.ellipse([970, 375, 1200, 505], fill=AEMONO)
    glove(d, 780, 450, angle_left=False)
    return img


def photo_hoso() -> Image.Image:
    img, d = photo_base("作業の写真3　包装（卓上のシール機2台）")
    for x in (180, 720):
        d.rounded_rectangle([x, 380, x + 380, 720], radius=18, fill=(225, 228, 232), outline=(110, 110, 120), width=4)
        d.rectangle([x + 40, 420, x + 340, 520], fill=(90, 95, 100))  # 上のふた
        d.rectangle([x + 60, 540, x + 320, 690], fill=(250, 250, 250), outline=(160, 160, 160), width=3)  # 容器を置く台
        d.rounded_rectangle([x + 150, 360, x + 230, 395], radius=8, fill=(60, 60, 60))  # 取っ手
        d.ellipse([x + 330, 640, x + 360, 670], fill=(60, 180, 80))  # ランプ
    tray(d, 280, 550, [NIMONO, AEMONO, AGEMONO], 3)
    glove(d, 1000, 600, angle_left=False)
    return img


def photo_label() -> Image.Image:
    img, d = photo_base("作業の写真4　ラベル貼りと検品（目で見て確かめる）")
    d.rounded_rectangle([80, 360, 420, 600], radius=16, fill=(240, 240, 240), outline=(110, 110, 110), width=4)  # ラベルのプリンター
    d.rectangle([130, 560, 370, 640], fill=(255, 255, 255), outline=(170, 170, 170), width=2)
    for i in range(3):
        d.line([(145, 578 + i * 18), (355, 578 + i * 18)], fill=(120, 120, 120), width=3)
    for col in range(3):
        for row in range(2):
            x, y = 520 + col * 240, 360 + row * 200
            tray(d, x, y, [NIMONO, YAKIMONO, AEMONO], 3)
            if row == 0 or col < 2:
                d.rectangle([x + 40, y + 50, x + 160, y + 95], fill=(255, 255, 255), outline=(120, 120, 120), width=2)
                d.line([(x + 50, y + 65), (x + 150, y + 65)], fill=(90, 90, 90), width=3)
                d.line([(x + 50, y + 80), (x + 130, y + 80)], fill=(200, 60, 60), width=3)
    glove(d, 1120, 640, angle_left=False)
    return img


PHOTOS = [
    ("作業の写真_1_盛り付け.jpg", photo_moritsuke),
    ("作業の写真_2_計量.jpg", photo_keiryo),
    ("作業の写真_3_包装.jpg", photo_hoso),
    ("作業の写真_4_ラベル貼りと検品.jpg", photo_label),
]


# ---------------------------------------------------------------------------
# 過去の申請：2025年 ものづくり補助金（20次締切）。J-06。社長が自分で書いた（J-07：支援者はいない）
# ---------------------------------------------------------------------------

PAST_PLAN_FILE = "2025_ものづくり補助金_事業計画書の控え.docx"
PAST_NOTICE_FILE = "2025_ものづくり補助金_採択結果の通知.pdf"
PAST_REVIEW_FILE = "2025_ものづくり補助金_審査のコメント.pdf"
APPLICATION_NUMBER = "TEST-M20-0157"  # 架空。実際の申請番号の形は写していない
PLAN_TITLE = "盛り付けと包装の機械化で、病院・介護施設向けの形態別の惣菜を正確に届ける"
ROUND = "20次締切（2025年7月25日締切）"
NOTICE_DATE = "2025年10月28日"
PAST_MACHINES = [
    # (品名, 型番, 数量, 金額（円、税抜）)。株式会社つばさ台フードシステムの参考価格（H-02 の単価と同じ）
    ("盛り付けロボット", "TF-MR200", 2, 7_800_000),
    ("自動計量機", "TF-AW14", 1, 3_200_000),
    ("トップシール包装機", "TF-TS60", 1, 4_800_000),
]
SUBSIDY_RATE = (2, 3)  # 小規模企業者（製造業で従業員20人以下）
SUBSIDY_CAP = 10_000_000  # 従業員6〜20人
# 会社全体の数値目標（千円）。第17期は D2a の決算書の実績。人件費 ＝ 給与（従業員・役員）＋ 法定福利費 ＋ 福利厚生費
PLAN_COLUMNS = ["第17期（実績）", "基準年度 第18期（見込み）", "1年目 第19期", "2年目 第20期", "3年目 第21期"]
PLAN_ROWS = {
    "売上高": [194_800, 199_000, 206_000, 214_000, 222_000],
    "営業利益": [3_900, 4_200, 4_000, 5_000, 6_300],
    "人件費": [59_100, 60_300, 62_100, 63_900, 65_800],
    "減価償却費": [3_900, 3_600, 6_200, 5_500, 4_900],
    "給与支給総額（従業員）": [40_100, 41_000, 42_200, 43_500, 44_900],
    "給与支給総額（役員）": [10_800, 10_800, 11_100, 11_500, 11_900],
}
FTE = 12.3  # 従業員の人数（パートは正社員の時間に換算）：7 ＋（6人×30時間＋2人×16時間）÷ 40時間（C-04、C-05）


def plan_values() -> dict[str, list]:
    rows = dict(PLAN_ROWS)
    rows["付加価値額"] = [o + p + d for o, p, d in zip(rows["営業利益"], rows["人件費"], rows["減価償却費"])]
    rows["1人あたり給与支給総額（従業員）"] = [round(v / FTE) for v in rows["給与支給総額（従業員）"]]
    return rows


def cagr(values: list[float]) -> float:
    """基準年度（2列目）から3年目までの年平均の伸び率。"""
    return (values[4] / values[1]) ** (1 / 3) - 1


def past_plan(path: Path) -> None:
    doc = new_document("2025年 ものづくり補助金 事業計画書の控え")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("2025年　ものづくり補助金　事業計画書の控え")
    run.font.size = Pt(15)
    run.font.bold = True
    doc.add_paragraph("電子申請のシステムに入力した文を、社長が控えとして残したものです。")
    cost = sum(v for *_, v in PAST_MACHINES)
    subsidy = min(cost * SUBSIDY_RATE[0] // SUBSIDY_RATE[1], SUBSIDY_CAP)
    add_table(
        doc,
        [
            ["項目", "内容"],
            ["申請した補助金", f"ものづくり・商業・サービス生産性向上促進補助金　{ROUND}"],
            ["申請した枠", "製品・サービス高付加価値化枠"],
            ["申請番号", APPLICATION_NUMBER],
            ["申請者", f"{COMPANY}　代表取締役　{PRESIDENT}"],
            ["従業員の数", "15人（正社員7人、パート8人）"],  # C-01
            ["事業計画の名前", PLAN_TITLE],
            ["補助の対象にする経費", f"{cost:,}円（税抜）"],
            ["補助金の申請額", f"{subsidy:,}円"],
            ["作った人", f"代表取締役　{PRESIDENT}が自分で作った。作るのを手伝った人や専門家はいない"],  # J-06、J-07
            ["出した日", "2025年7月24日"],
        ],
        [40, 130],
    )

    def section(title: str, paragraphs: list[str]) -> None:
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(10)
        h.add_run(title).font.bold = True
        for text in paragraphs:
            doc.add_paragraph(text)

    section(
        "1．会社の概要",
        [
            "当社は、1996年に先代が始めた惣菜店をもとに、2008年に法人にした惣菜の製造会社です。"  # A-04、A-05
            "スーパー3社（14店舗）、病院2か所、介護施設11か所などに、日替わりで約40品目の惣菜をつくって届けています。"  # E-01、E-04
            "第17期（2025年3月期）の売上高は194,800千円です。",  # F-01
        ],
    )
    section(
        "2．今の状況と課題",
        [
            "盛り付け・計量・包装は手作業で、人が足りません。募集しても、朝の早い時間に来られる人が集まりません。"
            "注文が増えても、受けられない日があります。計量のばらつきやラベルの貼り間違いも、ときどき起きています。",  # G-02、G-05
        ],
    )
    section(
        "3．取り組む内容",
        [
            "盛り付けロボット2台、自動計量機、トップシール包装機を入れ、盛り付けから包装までを機械で行います。"
            "金額は、株式会社つばさ台フードシステムの参考価格です。",
        ],
    )
    add_table(
        doc,
        [["機械", "型番", "数量", "金額（税抜）"]]
        + [[name, model, str(qty), f"{v:,}円"] for name, model, qty, v in PAST_MACHINES]
        + [["合計", "", "", f"{cost:,}円"]],
        [60, 35, 20, 45],
    )
    section(
        "4．新しいサービス",
        [
            "機械で量をそろえて盛り付けることで、病院・介護施設ごとの形態（やわらか食、きざみ食、ペースト食）と量の指定に、"
            "いままでより正確に応えるサービスを始めます。",
        ],
    )
    section(
        "5．効果",
        [
            "業者の説明では、盛り付けから包装までの時間が約半分になります。浮いた人手で、注文の増加に応えます。"
            "1日の出荷を、約3,500パックから約4,200パックに増やせる見込みです。",
        ],
    )
    values = plan_values()
    section(
        "6．数値目標（単位：千円）",
        [
            f"付加価値額は年平均{cagr(values['付加価値額']):.1%}、給与支給総額は従業員・役員とも年平均3.0%以上ふやします。"
            "1人あたり給与支給総額（従業員）も、年平均3.0%以上ふやします。"
            "事業所内最低賃金は、毎年、東京都の最低賃金より30円以上高くします。",
        ],
    )
    order = ["売上高", "営業利益", "人件費", "減価償却費", "付加価値額", "給与支給総額（従業員）", "給与支給総額（役員）", "1人あたり給与支給総額（従業員）"]
    add_table(
        doc,
        [["項目"] + PLAN_COLUMNS] + [[name] + [f"{v:,}" for v in values[name]] for name in order],
        [44, 25, 27, 25, 25, 25],
    )
    doc.add_paragraph(
        "付加価値額は、営業利益・人件費・減価償却費の和です。1人あたり給与支給総額は、パートを正社員の時間に換算した12.3人で割りました。"
    )
    section(
        "7．実施の体制と日程",
        [
            "社長が責任者になり、工場長と盛り付け・包装の担当で機械を動かします。"
            "交付が決まったら発注し、約5か月で納入して据え付け、補助事業の期間の内に動かし始めます。",
        ],
    )
    section(
        "8．お金の用意",
        [
            "補助の対象にならない分と、補助金が入るまでの分は、自己資金と金融機関からの借入でまかないます。"
            "金融機関には、これから相談します。",
        ],
    )
    section("9．加点", ["加点の項目に当たる認定や宣言は、持っていません。"])  # J-04
    doc.save(path)
    normalize_office(path)


def past_notice() -> list:
    def page1(pg: Page) -> None:
        pg.right(NOTICE_DATE, 10)
        pg.gap(6)
        pg.c.setFont(GOTHIC, 12)
        pg.c.drawString(LEFT, pg.y, f"{COMPANY}")
        pg.y -= 18
        pg.c.drawString(LEFT, pg.y, f"代表取締役　{PRESIDENT}　様")
        pg.y -= 26
        pg.right("ものづくり補助金事務局（架空の表示。テスト用）", 10)
        pg.gap(14)
        pg.title("採択結果のお知らせ", 16)
        pg.para(
            f"{ROUND}にご申請いただいた事業計画について、審査の結果、補助金交付候補者として採択されなかったことをお知らせします。",
            size=10.5,
        )
        pg.gap(6)
        for key, value in (
            ("申請番号", APPLICATION_NUMBER),
            ("公募の回", ROUND),
            ("申請した枠", "製品・サービス高付加価値化枠"),
            ("事業計画の名前", PLAN_TITLE),
            ("結果", "不採択"),
        ):
            # 計画の名前が折り返さないよう、欄を広げて字を小さくする（読み取ったときに名前が切れないように）
            pg.kv(key, value, key_width=95, size=9.5)
        pg.gap(8)
        pg.para("審査で指摘された点は、別紙「審査のコメント」にまとめました。", size=10)
        pg.para("事業計画を見直して、次の公募で改めて申請することもできます。", size=10)

    return [page1]


REVIEW = [
    (
        "審査項目1　補助事業の適格性",
        [
            "盛り付け・計量・包装の工程を機械に置き換える内容が中心で、今の製品をつくる工程の改善にとどまっている。"
            "新しい製品・サービスの開発としての新しさが読み取れない。",
        ],
    ),
    (
        "審査項目2　経営力",
        [
            "取引先の種類ごとの売上や、市場・顧客の動きの分析が少ない。本事業が、会社の目標にどうつながるかが具体的でない。",
        ],
    ),
    (
        "審査項目3　事業性",
        [
            "付加価値額と給与支給総額の目標値について、算出の根拠が示されていない。",
            "効果（作業時間が約半分になる）の根拠が機械の業者の説明だけで、今の工程ごとの作業時間が示されていない。",
            "課題に挙げた計量やラベルの誤りについて、検品の方法など、解決の方法が示されていない。",
        ],
    ),
    (
        "審査項目4　実現可能性",
        [
            "機械を動かす人の体制や研修、導入の日程が具体的でない。",
            "自己資金と借入の内訳や、金融機関との相談の状況が示されておらず、資金調達の見込みが確かめられない。",
        ],
    ),
    ("審査項目5　政策面", ["特に指摘はない。"]),
]


def past_review() -> list:
    def page1(pg: Page) -> None:
        pg.title("審査のコメント", 16)
        pg.center("（別紙　採択結果のお知らせ）", 9.5)
        pg.gap(4)
        for key, value in (
            ("申請番号", APPLICATION_NUMBER),
            ("事業計画の名前", PLAN_TITLE),
            ("結果", "不採択"),
        ):
            pg.kv(key, value, key_width=95, size=9.5)
        pg.gap(6)
        pg.para("書面審査の項目ごとに、審査で指摘された点をまとめました。", size=10)
        for heading, comments in REVIEW:
            pg.gap(4)
            pg.heading(heading, 11)
            for text in comments:
                pg.para(f"・{text}", indent=1, size=10)

    return [page1]


# ---------------------------------------------------------------------------


def main() -> None:
    values = plan_values()
    if values["付加価値額"][0] != 3_900 + 59_100 + 3_900:
        raise ValueError("第17期の付加価値額が、決算書の数字と合いません")
    for period, data in BY_CUSTOMER.items():
        if sum(d[1] for d in data) != SALES[period]:
            raise ValueError(f"第{period}期の取引先の種類ごとの売上の和が、売上と合いません")
    OUT_DIR.mkdir(exist_ok=True)
    render(OUT_DIR / "会社案内.pdf", "会社案内", company_profile())
    render(OUT_DIR / "商品のご案内.pdf", "商品のご案内", product_guide())
    minutes(OUT_DIR / MINUTES_FILE)
    business_breakdown(OUT_DIR / "既存事業の売上と経費_第17期_第18期.xlsx")
    for name, draw in PHOTOS:
        draw().save(OUT_DIR / name, "JPEG", quality=85, comment=PHOTO_MARK.encode("utf-8"))
    past_plan(OUT_DIR / PAST_PLAN_FILE)
    render(OUT_DIR / PAST_NOTICE_FILE, "採択結果のお知らせ（2025年 ものづくり補助金）", past_notice())
    render(OUT_DIR / PAST_REVIEW_FILE, "審査のコメント（2025年 ものづくり補助金）", past_review())
    for path in sorted(OUT_DIR.iterdir()):
        if path.suffix in {".pdf", ".docx", ".xlsx", ".jpg"}:
            print(f"作った：{path.name}")


if __name__ == "__main__":
    main()
