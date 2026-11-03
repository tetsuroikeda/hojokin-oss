# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pypdfium2==5.14.0", "pillow==13.0.0"]
# ///
"""不備を仕込んだ書類セット（TASKS D5b）と、仕込んだ不備の一覧を作る。

T5-1（不備を仕込んだ書類セットを入れて、重大な不備の見逃しが0件か）で、会社のフォルダに入れる書類の一式。
D5a の正しい書類セット（正しいセット/）をもとに、書類を差し替える・抜く・足すで不備を仕込む。
不備の型は knowledge/不備の型.json（A1）の id と対にする。制度は省力化（一般型）第8回、段階は応募申請。

作り方：
- 不備を仕込む書類は、D2a・D2b の作り方の関数を、社名や日付などの値だけ差し替えて呼んで作る
  （make_documents.py・make_documents_part2.py は直さない。D6 と同じやり方）。
- 見積書は、D2b の quote() と同じ描き方で、印字する数字を1つずつ決められるようにした関数で描く
  （計算の合わない見積書を作るため）。正しい値を渡すと D2b の見積書と同じバイト列になることを、確かめのスクリプトで見る。
- 写真とスキャンは、不備を仕込んだ PDF を作ってから、D5a の make_photo・make_scan で写真とスキャンにする。
- 不備を仕込まない書類は、正しいセットのファイルをそのまま写す（同じバイト列）。

セットのフォルダ（不備を仕込んだセット/）には書類だけを置く。テストで会社のフォルダに写すのは、このフォルダの中だけ。
答え（仕込んだ不備の一覧）は、仕込んだ不備の一覧.json と セットの一覧.md に書く。
正しいセットと同じ会社のフォルダには入れない（同じ中身の書類が2つになり、T5-4 の「同じ中身」の知らせと紛れる）。

動かし方：uv run --script testdata/書類セット/make_defect_set.py
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCS = REPO / "testdata" / "デモの会社" / "書類"
CORRECT_DIR = HERE / "正しいセット"
SET_DIR = HERE / "不備を仕込んだセット"
LIST_FILE = HERE / "仕込んだ不備の一覧.json"

sys.path.insert(0, str(DOCS))
sys.path.insert(0, str(HERE))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Pt  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from reportlab.lib.colors import Color, black  # noqa: E402

import make_documents as d2a  # noqa: E402
import make_documents_part2 as d2b  # noqa: E402
from make_correct_set import make_photo, make_scan  # noqa: E402

# このセットで不備と言える申請の日の範囲（正しいセットと同じ。check_correct_set.py の APPLY_FROM・APPLY_UNTIL）
APPLY_FROM = "2026-11-01"
APPLY_UNTIL = "2027-01-21"

TSUBASA = "株式会社つばさ台フードシステム"  # 回答表 H-03
TSUBASA_KEY = "つばさ台フードシステム"
HOSHIMI_KEY = "ほしみ機工"

# ---------------------------------------------------------------------------
# 仕込む値（正しい値は D2a・D2b の値）
# ---------------------------------------------------------------------------

# 仕込み-01：履歴事項全部証明書の発行日を古くする（正しくは 令和8年10月22日）
OLD_REGISTRY_ISSUED = "令和8年6月15日"
# 仕込み-04：納税証明書（その2）を2期分だけにする（第16期を抜く）
TAX_PERIODS_KEPT = d2a.TAXABLE_INCOME[1:]
# 仕込み-05：役員名簿の社名を書き違える。「山吹惣菜」は D1 で法人番号公表サイトを調べ、0件だった名前（社名の確かめ.md）
WRONG_COMPANY = "株式会社山吹惣菜"
# 仕込み-06：決算書 第18期の本店の番地を違える（正しくは 八丁目12番5号。東糀谷は六丁目までなので、どちらも実在しない）
WRONG_ADDRESS = "東京都大田区東糀谷八丁目21番5号"
# 仕込み-07：法人事業概況説明書の代表者の字を違える（正しくは 沢村 宏之）
WRONG_PRESIDENT = "沢村 浩之"
# 仕込み-08：相見積の宛名で「株式会社」を後ろに付ける。「やまぶき惣菜」は D1 で0件だった名前
WRONG_ADDRESSEE = "やまぶき惣菜株式会社"
# 仕込み-17：労働者名簿から、いちばん新しく雇った人を落とす（15人 → 14人）
OMITTED_WORKER = "西村 春江"

# ---------------------------------------------------------------------------
# 見積書（D2b の quote() と同じ描き方で、印字する数字を決められるようにしたもの）
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class QuoteSpec:
    doc_name: str  # 頭と足に出す書類の名前
    tsubasa: bool  # つばさ台の書き方（表題「御見積書」、青い見出し）か、ほしみ機工の書き方か
    issuer: str
    number: str
    date: str
    valid_until: str
    subject: str
    rows: tuple  # (品名, 型番, 数量, 単位, 単価, 金額)。金額は印字する値（数量 × 単価と合わなくてもよい）
    subtotal: int
    tax: int
    total: int
    notes: tuple
    addressee: str = d2a.COMPANY
    president: str = d2a.PRESIDENT


def quote_from_d2b(key: str) -> QuoteSpec:
    """D2b の見積書と同じ中身の QuoteSpec（正しい値）。"""
    q = d2b.QUOTES[key]
    rows = tuple((name, model, qty, unit, price, qty * price) for name, model, qty, unit, price, _ in q["items"])
    subtotal, tax, total = d2b.quote_totals(q["items"])
    doc_name = next(doc for file, doc, _ in d2b.PDF_DOCUMENTS if file == q["file"])
    return QuoteSpec(
        doc_name=doc_name,
        tsubasa=key == TSUBASA_KEY,
        issuer=q["issuer"],
        number=q["number"],
        date=d2b.QUOTE_DATE,
        valid_until=d2b.QUOTE_VALID_UNTIL,
        subject=d2b.SUBJECT,
        rows=rows,
        subtotal=subtotal,
        tax=tax,
        total=total,
        notes=tuple(d2b.QUOTE_NOTES),
    )


def quote_pages(q: QuoteSpec) -> list:
    """見積書の1ページ。D2b の quote() と同じ配置で、数字は q に書いたとおりに印字する。"""
    yen = d2b.yen

    def page1(pg: d2a.Page) -> None:
        c = pg.c
        pg.title("御見積書" if q.tsubasa else "見　積　書", 18)
        c.setFont(d2a.MINCHO, 9.5)
        c.drawRightString(d2a.RIGHT, pg.y + 18, f"見積番号　{q.number}")
        c.drawRightString(d2a.RIGHT, pg.y + 5, f"発行日　{q.date}")
        c.setFont(d2a.GOTHIC, 13)
        c.drawString(d2a.LEFT, pg.y - 12, f"{q.addressee}　御中")
        c.line(d2a.LEFT, pg.y - 16, d2a.LEFT + 260, pg.y - 16)
        c.setFont(d2a.MINCHO, 10)
        c.drawString(d2a.LEFT, pg.y - 32, f"代表取締役　{q.president}　様")
        x = d2a.LEFT + 300
        c.setFont(d2a.GOTHIC, 11)
        c.drawString(x, pg.y - 12, q.issuer)
        c.setFont(d2a.MINCHO, 9)
        c.drawString(x, pg.y - 27, "〒000-0000　架空の所在地（テスト用）")
        c.drawString(x, pg.y - 40, "営業部")
        pg.y -= 62
        pg.para("下記のとおり、お見積り申し上げます。", size=10)
        pg.kv("件名", q.subject, key_width=110)
        pg.kv("見積金額（税込）", f"{yen(q.total)}円", key_width=110)
        pg.kv("有効期限", q.valid_until, key_width=110)
        pg.gap(4)
        widths = [24, 192, 58, 32, 26, 66, 77] if q.tsubasa else [24, 186, 64, 32, 26, 68, 75]
        header = ["No.", "品名", "型番", "数量", "単位", "単価（税抜）", "金額（税抜）"]
        rows = [header] + [
            [str(i), name, model, str(qty), unit, yen(price), yen(amount)]
            for i, (name, model, qty, unit, price, amount) in enumerate(q.rows, start=1)
        ]
        size = 8.4
        h = size + 9
        fill = Color(0.88, 0.92, 0.97) if q.tsubasa else Color(0.92, 0.92, 0.92)
        for r, cells in enumerate(rows):
            xx = d2a.LEFT
            for i, (cell, w) in enumerate(zip(cells, widths)):
                if r == 0:
                    c.setFillColor(fill)
                    c.rect(xx, pg.y - 5, w, h, fill=1, stroke=1)
                    c.setFillColor(black)
                else:
                    c.rect(xx, pg.y - 5, w, h, fill=0, stroke=1)
                c.setFont(d2a.GOTHIC if r == 0 else d2a.MINCHO, size)
                if r == 0 or i in (1, 2, 4):
                    c.drawString(xx + 4, pg.y, cell)
                else:
                    c.drawRightString(xx + w - 4, pg.y, cell)
                xx += w
            pg.y -= h
        label_w = sum(widths[:-1])
        for label, value in (("小計（税抜）", q.subtotal), (f"消費税（{d2b.TAX_RATE}%）", q.tax), ("合計（税込）", q.total)):
            c.rect(d2a.LEFT, pg.y - 5, label_w, h, fill=0, stroke=1)
            c.rect(d2a.LEFT + label_w, pg.y - 5, widths[-1], h, fill=0, stroke=1)
            c.setFont(d2a.GOTHIC, size)
            c.drawRightString(d2a.LEFT + label_w - 6, pg.y, label)
            c.drawRightString(d2a.LEFT + label_w + widths[-1] - 4, pg.y, yen(value))
            pg.y -= h
        pg.gap(10)
        pg.heading("備考", 10)
        for note in q.notes:
            pg.para(f"・{note}", indent=1, size=9)

    return [page1]


def render_quote(path: Path, q: QuoteSpec) -> None:
    d2a.render(path, q.doc_name, quote_pages(q))


# 仕込み-02・仕込み-09：頼むつもりの会社の見積書。有効期限が切れていて、3行目の単価が金額と合わない
MAIN_QUOTE_NUMBER = "TFS-2608-0097"
MAIN_QUOTE_DATE = "2026年8月3日"
MAIN_QUOTE_VALID_UNTIL = "2026年10月31日"
MISPRICED_ROW = 2  # 0から数えた行（3行目のトップシール包装機）
MISPRINTED_PRICE = 4_600_000  # 印字する単価（金額は 4,800,000 のまま）


def main_quote() -> QuoteSpec:
    q = quote_from_d2b(TSUBASA_KEY)
    rows = list(q.rows)
    name, model, qty, unit, _, amount = rows[MISPRICED_ROW]
    rows[MISPRICED_ROW] = (name, model, qty, unit, MISPRINTED_PRICE, amount)
    return dataclasses.replace(
        q, number=MAIN_QUOTE_NUMBER, date=MAIN_QUOTE_DATE, valid_until=MAIN_QUOTE_VALID_UNTIL, rows=tuple(rows)
    )


# 仕込み-08：相見積の宛名が違う
def hoshimi_quote() -> QuoteSpec:
    return dataclasses.replace(quote_from_d2b(HOSHIMI_KEY), addressee=WRONG_ADDRESSEE)


# 仕込み-10・仕込み-15：足した見積書。汎用のパソコンが入っていて、消費税の桁が違う
TERMINAL_ROWS = (
    ("ライン管理ソフト（実績の集計）", "—", 1, "本", 420_000, 420_000),
    ("ノートパソコン（市販品）", "—", 1, "台", 180_000, 180_000),
)
TERMINAL_SUBTOTAL = 600_000
TERMINAL_TAX = 6_000  # 正しくは 60,000
TERMINAL_TOTAL = TERMINAL_SUBTOTAL + TERMINAL_TAX


def terminal_quote() -> QuoteSpec:
    return QuoteSpec(
        doc_name="御見積書（つばさ台フードシステム・ライン管理端末）",
        tsubasa=True,
        issuer=TSUBASA,
        number="TFS-2610-0154",
        date="2026年10月20日",
        valid_until="2027年1月31日",
        subject="ライン管理ソフトと端末",
        rows=TERMINAL_ROWS,
        subtotal=TERMINAL_SUBTOTAL,
        tax=TERMINAL_TAX,
        total=TERMINAL_TOTAL,
        notes=(
            "金額は消費税抜きで表示しています。消費税（10%）は下に分けて記しました。",
            f"ライン管理ソフトは、盛り付け・包装ライン（見積番号 {MAIN_QUOTE_NUMBER}）の機械とつないで使います。",
            "ノートパソコンは市販品です。ライン管理ソフトのほか、事務の仕事にもお使いいただけます。",
            "納期：ご発注から約1か月。",
            "受渡場所：御社 本社工場　　お支払い：ご相談のうえ決めます。",
        ),
    )


# ---------------------------------------------------------------------------
# 仕込み-18：ラインの配置図（業者が作った図面）。盛り付けロボットが3台（見積書・カタログは2台）
# ---------------------------------------------------------------------------

LAYOUT_ROBOTS = 3
LAYOUT_FILE = "ライン配置図_つばさ台フードシステム.pdf"
LAYOUT_DOC_NAME = "ライン配置図（つばさ台フードシステム）"


def layout_pages() -> list:
    def page1(pg: d2a.Page) -> None:
        c = pg.c
        pg.title("ライン配置図（案）", 16)
        pg.center("惣菜の盛り付け・計量・包装・検査ライン", 11)
        pg.right("作成日　2026年10月20日")
        pg.right(f"{TSUBASA}　営業部")
        c.setFont(d2a.GOTHIC, 12)
        c.drawString(d2a.LEFT, pg.y, f"{d2a.COMPANY}　御中")
        pg.y -= 26
        pg.heading("配置（上から見た図。縮尺は目安）")
        # 置き場所の枠（幅2.5m×長さ12m）。本文の幅を12mにとる
        width = d2a.RIGHT - d2a.LEFT
        per_m = width / 12
        frame_h = 2.5 * per_m
        bottom = pg.y - frame_h
        c.setDash(4, 3)
        c.rect(d2a.LEFT, bottom, width, frame_h, fill=0, stroke=1)
        c.setDash()
        c.setFont(d2a.MINCHO, 7.5)
        c.drawRightString(d2a.RIGHT - 4, bottom + 5, "置き場所　幅2.5m×長さ12m")
        # 搬送コンベヤ（枠の下寄りを通し、機械はその上に並べる）
        conveyor_y = bottom + 26
        c.setFillColor(Color(0.85, 0.85, 0.85))
        c.rect(d2a.LEFT + 10, conveyor_y, width - 20, 10, fill=1, stroke=1)
        c.setFillColor(black)
        c.drawString(d2a.LEFT + 12, conveyor_y - 10, "搬送コンベヤ TF-CV8（合計約8m）　→ 流れる向き")
        # 機械の箱
        machines = [("自動計量機", "TF-AW14")]
        machines += [(f"盛り付けロボット（{i}）", "TF-MR200") for i in range(1, LAYOUT_ROBOTS + 1)]
        machines += [
            ("画像検査（盛り付け）", "TF-VI2"),
            ("トップシール包装機", "TF-TS60"),
            ("重量チェッカー・ラベラー", "TF-CL10"),
            ("画像検査（ラベル）", "TF-VI2"),
        ]
        box_w, box_h = 48, 40
        gap = (width - 20 - box_w * len(machines)) / (len(machines) - 1)
        x = d2a.LEFT + 10
        y = conveyor_y + 16
        for label, model in machines:
            c.setFillColor(Color(0.9, 0.95, 0.9))
            c.roundRect(x, y, box_w, box_h, 4, fill=1, stroke=1)
            c.setFillColor(black)
            c.setFont(d2a.GOTHIC, 6.8)
            for i, line in enumerate(d2a.wrap(label, d2a.GOTHIC, 6.8, box_w - 4)):
                c.drawCentredString(x + box_w / 2, y + box_h - 10 - i * 8, line)
            c.setFont(d2a.MINCHO, 6.2)
            c.drawCentredString(x + box_w / 2, y + 4, model)
            x += box_w + gap
        pg.y = bottom - 22
        pg.heading("機械の一覧")
        pg.table(
            [
                ["機械", "型番", "台数"],
                ["自動計量機（組合せ計量 14ヘッド）", "TF-AW14", "1台"],
                ["盛り付けロボット", "TF-MR200", f"{LAYOUT_ROBOTS}台"],
                ["画像検査装置（盛り付け・ラベル、カメラ2台）", "TF-VI2", "1式"],
                ["トップシール包装機", "TF-TS60", "1台"],
                ["重量チェッカー・ラベラー（一体型）", "TF-CL10", "1台"],
                ["搬送コンベヤ（ライン連結用。合計約8m）", "TF-CV8", "1式"],
            ],
            [305, 95, 75],
        )
        pg.heading("置き場所と据付")
        pg.kv("置き場所", "御社 本社工場の盛り付け室。幅2.5m×長さ12m", key_width=110)
        pg.kv("据付", "機械を置いて床に固定します。基礎工事は要りません", key_width=110)
        pg.kv("電源", "今の電気の容量で動かせます（現地で確かめました）", key_width=110)
        pg.gap(4)
        pg.para("この図は配置のイメージです。寸法は、据付の前に現地で測り直します。", size=9)

    return [page1]


# ---------------------------------------------------------------------------
# 仕込み-16：注文書（社長が Word で作って出した注文の控え）。交付決定の前に発注している
# ---------------------------------------------------------------------------

ORDER_FILE = "注文書_つばさ台フードシステム.docx"
ORDER_DATE = "2026年10月28日"
ORDER_NUMBER = "YS-2610-01"
ORDER_ITEM = ("盛り付けロボット", "TF-MR200", 2, 3_900_000)  # 見積書の1行目と同じ品名・型番・単価


def order_form(path: Path) -> None:
    doc = d2b.new_document("注文書")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("注文書")
    run.font.size = Pt(16)
    run.font.bold = True
    for text in (f"注文日　{ORDER_DATE}", f"注文番号　{ORDER_NUMBER}"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(text)
    p = doc.add_paragraph()
    run = p.add_run(f"{TSUBASA}　御中")
    run.font.size = Pt(12)
    run.font.bold = True
    doc.add_paragraph("営業部")
    for text in (d2a.COMPANY, f"〒144-0033　{d2a.ADDRESS}", f"代表取締役　{d2a.PRESIDENT}"):  # A-01、B-01、B-02、A-08
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(text)
    doc.add_paragraph(f"貴社の御見積書（見積番号 {MAIN_QUOTE_NUMBER}）にもとづき、下記のとおり注文いたします。")
    name, model, qty, price = ORDER_ITEM
    subtotal = qty * price
    tax = subtotal * d2b.TAX_RATE // 100
    yen = d2b.yen
    d2b.add_table(
        doc,
        [
            ["番号", "品名", "型番", "数量", "単価（税抜）", "金額（税抜）"],
            ["1", name, model, f"{qty}台", f"{yen(price)}円", f"{yen(subtotal)}円"],
            ["", "小計（税抜）", "", "", "", f"{yen(subtotal)}円"],
            ["", f"消費税（{d2b.TAX_RATE}%）", "", "", "", f"{yen(tax)}円"],
            ["", "合計（税込）", "", "", "", f"{yen(subtotal + tax)}円"],
        ],
        [10, 46, 24, 16, 36, 38],
    )
    doc.add_paragraph()
    for text in (
        "納期　2027年3月31日まで（据付と試運転調整を含む）",
        "受渡場所　当社 本社工場",
        "お支払い　据付と試運転調整が終わった月の翌月末に、銀行振込",
        "備考　盛り付けロボットは納期が長いので、先に注文します。ほかの機械は、補助金の結果が出てから注文します。",
        "上記のとおり注文いたします。注文請書をお送りください。",
    ):
        doc.add_paragraph(text)
    doc.save(path)
    d2b.normalize_office(path)


# ---------------------------------------------------------------------------
# 仕込み-11〜14：設備の費用の控え（社長が Excel で作ったメモ）
# ---------------------------------------------------------------------------

EXPENSE_FILE = "設備の費用の控え.xlsx"
EXPENSE_DATE = "2026年10月30日"
EXPENSE_HEADER = ["番号", "品名", "数量", "金額（税抜・円）", "見積", "メモ"]
EXPENSE_ROWS = [
    # (品名, 数量, 金額, 見積, メモ)。H-02 の区分の名前で書く
    ("盛り付けロボット", "2台", 7_800_000, "つばさ台の見積書", ""),
    ("自動計量機", "1台", 3_000_000, "つばさ台の見積書", ""),  # 仕込み-11（見積書は 3,200,000）
    ("トップシール包装機", "1台", 4_800_000, "つばさ台の見積書", ""),
    ("画像検査装置（盛り付けとラベル）", "1式", 3_960_000, "つばさ台の見積書", "税込"),  # 仕込み-12（税抜は 3,600,000）
    ("重量チェッカーとラベラー", "1台", 1_900_000, "つばさ台の見積書", ""),
    ("つなぐコンベヤと据え付け・調整", "1式", 1_200_000, "つばさ台の見積書", ""),
    ("金属検出機", "1台", 1_400_000, "まだ（業者に頼んでいない）", "ネットで見た値段"),  # 仕込み-13
    ("配送用の冷蔵車（軽）", "1台", 2_800_000, "ない（ディーラーに聞いた値段）", "惣菜の配送に使う"),  # 仕込み-14
]
EXPENSE_FIRST_ROW = 6  # 明細の最初の行（Excel の行番号）


def expense_memo(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "設備の費用"
    cols = len(EXPENSE_HEADER)
    thin = Side(style="thin", color="808080")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
    ws.cell(1, 1, d2a.BANNER).font = Font(name="游ゴシック", size=9, bold=True)
    ws.cell(1, 1).fill = PatternFill("solid", fgColor="FFF2BF")
    ws.cell(1, 1).alignment = Alignment(horizontal="center")
    ws.cell(2, 1, "設備の費用の控え").font = Font(name="游ゴシック", size=14, bold=True)
    ws.cell(3, 1, f"{d2a.COMPANY}　{EXPENSE_DATE}　社長のメモ（省力化の補助金の相談用）").font = Font(name="游ゴシック", size=10)
    for i, title in enumerate(EXPENSE_HEADER, start=1):
        cell = ws.cell(EXPENSE_FIRST_ROW - 1, i, title)
        cell.font = Font(name="游ゴシック", size=9, bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF6")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for r, (name, qty, amount, quote, memo) in enumerate(EXPENSE_ROWS, start=EXPENSE_FIRST_ROW):
        for i, value in enumerate([r - EXPENSE_FIRST_ROW + 1, name, qty, amount, quote, memo], start=1):
            cell = ws.cell(r, i, value if value != "" else None)
            cell.font = Font(name="游ゴシック", size=9)
            cell.border = border
            if i == 4:
                cell.number_format = "#,##0"
    total_row = EXPENSE_FIRST_ROW + len(EXPENSE_ROWS)
    ws.cell(total_row, 2, "合計").font = Font(name="游ゴシック", size=9, bold=True)
    ws.cell(total_row, 4, sum(a for _, _, a, _, _ in EXPENSE_ROWS)).font = Font(name="游ゴシック", size=9, bold=True)
    ws.cell(total_row, 4).number_format = "#,##0"
    for i in range(1, cols + 1):
        ws.cell(total_row, i).border = border
    for letter, width in zip("ABCDEF", [6, 30, 8, 16, 26, 20]):
        ws.column_dimensions[letter].width = width
    ws.oddHeader.center.text = "架空のテスト用データ（hojokin-oss）　実在の会社・人物とは関係ありません"
    ws.oddFooter.center.text = "架空のテスト用データ｜設備の費用の控え｜&P/&N"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    wb.properties.creator = "hojokin-oss のテスト用データ"
    wb.properties.lastModifiedBy = "hojokin-oss のテスト用データ"
    wb.properties.title = "設備の費用の控え（架空のテスト用データ）"
    wb.properties.created = wb.properties.modified = d2b.FIXED_TIME
    wb.save(path)
    d2b.normalize_office(path)


# ---------------------------------------------------------------------------
# 書類を作る
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def patched(module, **values):
    """モジュールの値を一時だけ差し替える（元の作り方の関数は、呼んだときにこの値を読む）。"""
    saved = {key: getattr(module, key) for key in values}
    for key, value in values.items():
        setattr(module, key, value)
    try:
        yield
    finally:
        for key, value in saved.items():
            setattr(module, key, value)


def render_d2a(path: Path, name: str) -> None:
    """D2a の書類を、D2a の main() と同じ名前で描く（そのときのモジュールの値で描く）。"""
    doc_name, build = next((doc, b) for file, doc, b in d2a.DOCUMENTS if file == name)
    d2a.render(path, doc_name, build())


# 写真とスキャンの元にする PDF の名前（セットでの名前 → 元の PDF の名前）
PHOTO_SOURCES = {"納税証明書_その2.jpg": "納税証明書_その2.pdf"}
SCAN_SOURCES = {"履歴事項全部証明書.pdf": "履歴事項全部証明書.pdf"}


def build_sources(src_dir: Path) -> None:
    """写真とスキャンの元にする、不備を仕込んだ PDF を作る。"""
    src_dir.mkdir(parents=True, exist_ok=True)
    with patched(d2a, TAXABLE_INCOME=TAX_PERIODS_KEPT):
        render_d2a(src_dir / "納税証明書_その2.pdf", "納税証明書_その2.pdf")
    with patched(d2a, REGISTRY_ISSUED=OLD_REGISTRY_ISSUED):
        render_d2a(src_dir / "履歴事項全部証明書.pdf", "履歴事項全部証明書.pdf")


def build(out_dir: Path, src_dir: Path | None = None) -> list[Path]:
    """out_dir に不備を仕込んだ書類セットを作る。中にあったものは消してから作る。
    src_dir を渡すと、写真とスキャンの元にした PDF をそこに残す（確かめのスクリプトが文字を読むため）。"""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    with contextlib.ExitStack() as stack:
        if src_dir is None:
            src_dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        build_sources(src_dir)
        for name, src in PHOTO_SOURCES.items():
            make_photo(src_dir / src, out_dir / name)  # 仕込み-04
        for name, src in SCAN_SOURCES.items():
            make_scan(src_dir / src, out_dir / name)  # 仕込み-01
    # 仕込み-03：決算書_第17期.pdf は入れない
    with patched(d2a, ADDRESS=WRONG_ADDRESS):  # 仕込み-06
        render_d2a(out_dir / "決算書_第18期.pdf", "決算書_第18期.pdf")
    with patched(d2a, PRESIDENT=WRONG_PRESIDENT):  # 仕込み-07
        render_d2a(out_dir / "法人事業概況説明書_第18期.pdf", "法人事業概況説明書_第18期.pdf")
    render_quote(out_dir / "見積書_つばさ台フードシステム.pdf", main_quote())  # 仕込み-02・09
    render_quote(out_dir / "見積書_ほしみ機工.pdf", hoshimi_quote())  # 仕込み-08
    render_quote(out_dir / "見積書_つばさ台フードシステム_ライン管理端末.pdf", terminal_quote())  # 仕込み-10・15
    d2a.render(out_dir / LAYOUT_FILE, LAYOUT_DOC_NAME, layout_pages())  # 仕込み-18
    with patched(d2b, COMPANY=WRONG_COMPANY):  # 仕込み-05
        d2b.officer_list(out_dir / "役員名簿.docx")
    order_form(out_dir / ORDER_FILE)  # 仕込み-16
    with patched(d2b, WORKERS=[w for w in d2b.WORKERS if w[0] != OMITTED_WORKER]):  # 仕込み-17
        d2b.worker_list(out_dir / "労働者名簿.xlsx")
    expense_memo(out_dir / EXPENSE_FILE)  # 仕込み-11〜14
    for name in UNCHANGED:
        shutil.copyfile(CORRECT_DIR / name, out_dir / name)
    return sorted(out_dir.iterdir())


def build_with_correct_values(out_dir: Path) -> dict[str, Path]:
    """不備を仕込むのと同じ道筋で、値を差し替えずに描く。D2a・D2b の元の書類と同じバイト列になれば、
    仕込んだ書類の違いは、差し替えた値だけだと言える（確かめのスクリプトが使う）。元の書類の名前 → 作ったファイル。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    made = {}
    for name in ("決算書_第18期.pdf", "法人事業概況説明書_第18期.pdf", "納税証明書_その2.pdf", "履歴事項全部証明書.pdf"):
        render_d2a(out_dir / name, name)
        made[name] = out_dir / name
    for key in (TSUBASA_KEY, HOSHIMI_KEY):
        name = d2b.QUOTES[key]["file"]
        render_quote(out_dir / name, quote_from_d2b(key))
        made[name] = out_dir / name
    d2b.officer_list(out_dir / "役員名簿.docx")
    made["役員名簿.docx"] = out_dir / "役員名簿.docx"
    d2b.worker_list(out_dir / "労働者名簿.xlsx")
    made["労働者名簿.xlsx"] = out_dir / "労働者名簿.xlsx"
    return made


# ---------------------------------------------------------------------------
# セットのファイルと、仕込んだ不備の一覧
# ---------------------------------------------------------------------------

SAME = "正しいセットと同じ（バイト列も同じ）"
CHANGED = "正しいセットの書類に、不備を仕込んで作り直した"
ADDED = "足した（正しいセットにない書類）"

# セットのファイル：(名前, 種類, 形式, 正しいセットとの関係)
FILES = [
    ("決算書_第18期.pdf", "決算書（第18期：2025年4月1日〜2026年3月31日）", "PDF", CHANGED),
    ("法人事業概況説明書_第18期.pdf", "法人事業概況説明書（第18期）", "PDF", CHANGED),
    ("納税証明書_その2.jpg", "納税証明書（その2）", "写真（JPEG）", CHANGED),
    ("履歴事項全部証明書.pdf", "履歴事項全部証明書", "スキャンした PDF（文字なし）", CHANGED),
    ("見積書_つばさ台フードシステム.pdf", "見積書（頼むつもりの会社。ラインの機械）", "PDF", CHANGED),
    ("見積書_ほしみ機工.pdf", "見積書（相見積）", "PDF", CHANGED),
    ("見積書_つばさ台フードシステム_ライン管理端末.pdf", "見積書（ライン管理ソフトと端末）", "PDF", ADDED),
    ("カタログ_つばさ台フードシステム.pdf", "機械のカタログ", "PDF", SAME),
    (LAYOUT_FILE, "ラインの配置図（業者が作った図面）", "PDF", ADDED),
    ("役員名簿.docx", "役員名簿（会社が持つ名簿）", "Word", CHANGED),
    ("株主名簿.docx", "株主名簿（会社が持つ名簿）", "Word", SAME),
    (ORDER_FILE, "注文書（社長が出した注文の控え）", "Word", ADDED),
    ("労働者名簿.xlsx", "労働者名簿", "Excel", CHANGED),
    (EXPENSE_FILE, "設備の費用の控え（社長のメモ）", "Excel", ADDED),
]
UNCHANGED = [name for name, _, _, how in FILES if how == SAME]
# 正しいセットにあって、このセットに入れない書類
REMOVED = [("決算書_第17期.pdf", "決算書（第17期：2024年4月1日〜2025年3月31日）")]

# 仕込んだ不備。型は knowledge/不備の型.json の id。「SPEC の重大」は SPEC F5（T5-1）が挙げる5つのどれか
# 「採点の手がかり（案）」は、最後の応答にどれも出てくれば、その不備を指摘したとみなす語（正規表現）。B12 で直してよい
DEFECTS = [
    {
        "id": "仕込み-01",
        "種類": "履歴事項全部証明書が、発行から3か月を超えている",
        "型": "不備-01",
        "SPEC の重大": "期限切れ",
        "重さ": "重大",
        "書類": ["履歴事項全部証明書.pdf"],
        "場所": "発行日",
        "仕込んだ値": f"{OLD_REGISTRY_ISSUED}（2026-06-15）",
        "正しい値": f"{d2a.REGISTRY_ISSUED}（2026-10-22）",
        "見つける手がかり": "公募要領 4-4 ② では、応募申請日に発行から3か月以内。2026-09-14 を過ぎると切れるので、申請の日の範囲のどの日でも切れている。スキャンなので、ページの画像を読んで発行日を取る",
        "直し方": "法務局で取り直す。申請の日に発行から3か月以内になるよう、締切に近い日に取る",
        "採点の手がかり（案）": ["履歴事項全部証明書", "3か月|３か月|期限|古い|取り直"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-02",
        "種類": "見積書の有効期限が切れている",
        "型": "不備-01",
        "SPEC の重大": "期限切れ",
        "重さ": "重大",
        "書類": ["見積書_つばさ台フードシステム.pdf"],
        "場所": "発行日と有効期限（見積番号も8月の番号にした）",
        "仕込んだ値": f"発行日 {MAIN_QUOTE_DATE}、有効期限 {MAIN_QUOTE_VALID_UNTIL}、見積番号 {MAIN_QUOTE_NUMBER}",
        "正しい値": f"発行日 {d2b.QUOTE_DATE}、有効期限 {d2b.QUOTE_VALID_UNTIL}、見積番号 {d2b.QUOTES[TSUBASA_KEY]['number']}",
        "見つける手がかり": "有効期限 2026-10-31 は、申請の日の範囲の始め（2026-11-01）より前。頼むつもりの会社の見積書で、50万円以上の機械の積算根拠（公募要領 4-4 ①）に使うもの",
        "直し方": "つばさ台フードシステムに、有効期限が申請の日より後の見積書を出し直してもらう",
        "採点の手がかり（案）": ["つばさ台", "有効期限|期限切れ|期限が切れ"],
        "関連して出てよい指摘": ["見積の日付が、会社の記録（回答表 H-04：2026年10月20日）と違う"],
    },
    {
        "id": "仕込み-03",
        "種類": "決算書が直近2期そろっていない（第17期がない）",
        "型": "不備-02",
        "SPEC の重大": "期数不足",
        "重さ": "重大",
        "書類": [],
        "抜いた書類": ["決算書_第17期.pdf"],
        "場所": "セット全体（決算書は第18期の1期だけ）",
        "仕込んだ値": "決算書は第18期（2025-04-01〜2026-03-31）の1期だけ",
        "正しい値": "第17期と第18期の2期",
        "見つける手がかり": "公募要領 4-4 ① では、損益計算書と貸借対照表は直近2期分。設立は2008年（回答表 A-04）で、2期の決算を迎えている",
        "直し方": "第17期（2024-04-01〜2025-03-31）の決算書を用意する（決算書は顧問の税理士が作っている）",
        "採点の手がかり（案）": ["決算書", "第17期|2期|２期|期数|足りな"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-04",
        "種類": "納税証明書（その2）が直近3期そろっていない（2期分だけ）",
        "型": "不備-02",
        "SPEC の重大": "期数不足",
        "重さ": "重大",
        "書類": ["納税証明書_その2.jpg"],
        "場所": "事業年度と所得金額の表",
        "仕込んだ値": "第17期・第18期の2期分（令和6年4月1日〜令和7年3月31日、令和7年4月1日〜令和8年3月31日）",
        "正しい値": "第16期〜第18期の3期分",
        "見つける手がかり": f"公募要領 4-4 ② では、納税証明書（その2）は直近3期分。発行日は {d2a.TAX_CERTIFICATE_ISSUED} のままで第18期は載っており、足りないのは第16期。写真なので、画像を読んで表を取る",
        "直し方": "税務署で、第16期〜第18期の3期分の納税証明書（その2）を取り直す",
        "採点の手がかり（案）": ["納税証明書", "3期|３期|期数|第16期|足りな"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-05",
        "種類": "社名の書き違い（役員名簿）",
        "型": "不備-03",
        "SPEC の重大": "名義の不一致",
        "重さ": "重大",
        "書類": ["役員名簿.docx"],
        "場所": "表題の下の社名",
        "仕込んだ値": WRONG_COMPANY,
        "正しい値": f"{d2a.COMPANY}（登記の商号）",
        "見つける手がかり": "履歴事項全部証明書の商号と違う（ひらがなを漢字で書いた）",
        "直し方": "登記の商号（株式会社やまぶき惣菜）に直す。指定様式の役員名簿は、登記のとおりの社名で作る",
        "採点の手がかり（案）": ["役員名簿", "山吹|社名|商号"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-06",
        "種類": "本店の所在地の番地が違う（決算書 第18期）",
        "型": "不備-03",
        "SPEC の重大": "名義の不一致",
        "重さ": "重大",
        "書類": ["決算書_第18期.pdf"],
        "場所": "表紙の所在地",
        "仕込んだ値": WRONG_ADDRESS,
        "正しい値": d2a.ADDRESS,
        "見つける手がかり": "履歴事項全部証明書・納税証明書・法人事業概況説明書・注文書の本店（八丁目12番5号）と違う",
        "直し方": "どちらが今の事実かを社長に確かめる。決算書の書き違いなら、顧問の税理士に直した決算書を出してもらう",
        "採点の手がかり（案）": ["決算書", "21番|所在地|住所|番地"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-07",
        "種類": "代表者の名前の字が違う（法人事業概況説明書）",
        "型": "不備-03",
        "SPEC の重大": "名義の不一致",
        "重さ": "重大",
        "書類": ["法人事業概況説明書_第18期.pdf"],
        "場所": "「1．法人の概要」の代表者",
        "仕込んだ値": WRONG_PRESIDENT,
        "正しい値": d2a.PRESIDENT,
        "見つける手がかり": "履歴事項全部証明書・納税証明書・役員名簿・株主名簿の代表者と字が違う",
        "直し方": "登記の名前（沢村 宏之）が正しいかを社長に確かめ、法人事業概況説明書を顧問の税理士に確かめてもらう",
        "採点の手がかり（案）": ["法人事業概況説明書|概況", "浩之|代表者"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-08",
        "種類": "見積書の宛名の社名が違う（「株式会社」の位置）",
        "型": "不備-03",
        "SPEC の重大": "名義の不一致",
        "重さ": "重大",
        "書類": ["見積書_ほしみ機工.pdf"],
        "場所": "宛名",
        "仕込んだ値": f"{WRONG_ADDRESSEE}　御中",
        "正しい値": f"{d2a.COMPANY}　御中",
        "見つける手がかり": "「株式会社」が後ろに付いていて、登記の商号と違う",
        "直し方": "ほしみ機工に、宛名を「株式会社やまぶき惣菜」に直した見積書を出し直してもらう",
        "採点の手がかり（案）": ["ほしみ", "宛名|やまぶき惣菜株式会社"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-09",
        "種類": "見積書の明細で「数量 × 単価 ＝ 金額」が合わない",
        "型": "不備-04",
        "SPEC の重大": "金額の不一致",
        "重さ": "重大",
        "書類": ["見積書_つばさ台フードシステム.pdf"],
        "場所": "明細の3行目（トップシール包装機 TF-TS60）",
        "仕込んだ値": "数量 1、単価 4,600,000、金額 4,800,000",
        "正しい値": "数量 1、単価 4,800,000、金額 4,800,000",
        "見つける手がかり": "1 × 4,600,000 ＝ 4,600,000 で、金額の 4,800,000 と合わない。明細の合計と小計（22,500,000）、消費税、合計は合う",
        "直し方": "読み直す。それでも合わなければ、その行の画像と読み取った数字を並べて社長に確かめ、つばさ台フードシステムに正しい見積書を出し直してもらう（SPEC F5）",
        "採点の手がかり（案）": ["トップシール|TF-TS60", "4,600,000|単価|合わな"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-10",
        "種類": "見積書の消費税が、小計の10%と合わない",
        "型": "不備-04",
        "SPEC の重大": "金額の不一致",
        "重さ": "重大",
        "書類": ["見積書_つばさ台フードシステム_ライン管理端末.pdf"],
        "場所": "消費税（10%）の欄と、合計・見積金額（税込）",
        "仕込んだ値": "小計 600,000、消費税 6,000、合計 606,000",
        "正しい値": "小計 600,000、消費税 60,000、合計 660,000",
        "見つける手がかり": "600,000 × 10% ＝ 60,000。小計 ＋ 消費税 ＝ 合計（606,000）は合うので、消費税の欄の桁の誤り",
        "直し方": "つばさ台フードシステムに、消費税と合計を直した見積書を出し直してもらう。補助の対象の金額は税抜の小計で数える",
        "採点の手がかり（案）": ["ライン管理|端末", "消費税|6,000|60,000"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-11",
        "種類": "経費の控えの金額が、見積書と合わない",
        "型": "不備-04",
        "SPEC の重大": "金額の不一致",
        "重さ": "重大",
        "書類": [EXPENSE_FILE, "見積書_つばさ台フードシステム.pdf"],
        "場所": "控えの2行目（自動計量機）",
        "仕込んだ値": "3,000,000円",
        "正しい値": "3,200,000円（つばさ台の見積書の自動計量機 TF-AW14）",
        "見つける手がかり": "控えの「見積」の欄は、つばさ台の見積書を指している。見積書の自動計量機は 3,200,000円",
        "直し方": "見積書の金額（3,200,000円）を正として、控えを直す",
        "採点の手がかり（案）": ["自動計量", "3,000,000|3,200,000|控え"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-12",
        "種類": "経費の控えに、税込の金額が混ざっている",
        "型": "不備-09",
        "SPEC の重大": None,
        "重さ": "要確認",
        "書類": [EXPENSE_FILE],
        "場所": "控えの4行目（画像検査装置）",
        "仕込んだ値": "3,960,000円（メモに「税込」。欄の見出しは「金額（税抜・円）」）",
        "正しい値": "3,600,000円（税抜）",
        "見つける手がかり": "3,960,000 ＝ 見積書の 3,600,000（税抜）× 1.1。ほかの行は税抜",
        "直し方": "制度データの決まり（補助の対象の金額は税抜）にそろえ、3,600,000円で数え直す",
        "採点の手がかり（案）": ["画像検査", "税込|税抜|3,960,000"],
        "関連して出てよい指摘": ["控えの金額が見積書（3,600,000円）と合わない、という金額の不一致の指摘"],
    },
    {
        "id": "仕込み-13",
        "種類": "50万円以上の設備に見積書がない",
        "型": "不備-08",
        "SPEC の重大": None,
        "重さ": "重大",
        "書類": [EXPENSE_FILE],
        "場所": "控えの7行目（金属検出機）",
        "仕込んだ値": "1,400,000円。見積の欄は「まだ（業者に頼んでいない）」",
        "正しい値": "（正しいセットの計画にない設備）",
        "見つける手がかり": "セットのどの見積書・カタログにも金属検出機がない。公募要領 4-4 ① では、50万円以上の機械装置に仕様・積算根拠が分かる書類（参考見積書など）が要る",
        "直し方": "業者に見積書を出してもらう。届くまでは、経費明細の金額に仮の印を付ける（SPEC F8）。計画に入れるかも社長に確かめる",
        "採点の手がかり（案）": ["金属検出", "見積"],
        "関連して出てよい指摘": ["控えの合計が、会社の記録の投資額（回答表 H-02：22,500千円）と違う"],
    },
    {
        "id": "仕込み-14",
        "種類": "補助の対象にならない経費がある（車両）",
        "型": "不備-10",
        "SPEC の重大": None,
        "重さ": "重大",
        "書類": [EXPENSE_FILE],
        "場所": "控えの8行目（配送用の冷蔵車）",
        "仕込んだ値": "配送用の冷蔵車（軽） 2,800,000円",
        "正しい値": "（正しいセットの計画にない経費）",
        "見つける手がかり": "制度データの補助の対象にならない経費「自動車などの車両・船舶・航空機」（要領8 p.20・p.23）に当たる。対象外と決まっているので重大",
        "直し方": "経費から外す。配送の車を補助金を使わずに買うかは、社長が決める",
        "採点の手がかり（案）": ["冷蔵車|車両", "対象外|対象にならない|対象になりません|補助の対象"],
        "関連して出てよい指摘": ["見積書がない、という指摘（対象外なので、見積書を取る前に外す）"],
    },
    {
        "id": "仕込み-15",
        "種類": "見積書の明細に、補助の対象にならない費目（汎用のパソコン）がある",
        "型": "不備-11",
        "SPEC の重大": None,
        "重さ": "重大",
        "書類": ["見積書_つばさ台フードシステム_ライン管理端末.pdf"],
        "場所": "明細の2行目（ノートパソコン（市販品））",
        "仕込んだ値": "ノートパソコン（市販品） 1台 180,000円。備考に「事務の仕事にもお使いいただけます」",
        "正しい値": "（正しいセットにない見積書）",
        "見つける手がかり": "制度データの「汎用性があり目的外に使えるもの（事務用のパソコンなど）」（要領8 p.23）に当たる。1行目のライン管理ソフトは、専用ソフトウェアとして対象になりうる",
        "直し方": "パソコンの行を除いて計上する。対象と対象外を分けた見積書を、業者に出し直してもらってもよい",
        "採点の手がかり（案）": ["パソコン", "対象外|対象にならない|対象になりません|汎用"],
        "関連して出てよい指摘": [],
    },
    {
        "id": "仕込み-16",
        "種類": "交付決定より前に発注している（事前着手）",
        "型": "不備-07",
        "SPEC の重大": "事前着手",
        "重さ": "重大",
        "書類": [ORDER_FILE],
        "場所": "注文日と注文した機械",
        "仕込んだ値": f"注文日 {ORDER_DATE}。盛り付けロボット TF-MR200 2台（7,800,000円、税抜）を、つばさ台フードシステムに注文",
        "正しい値": "（正しいセットには、発注・契約の書類がない。回答表 H-06：発注も契約もしていない）",
        "見つける手がかり": "申請の前で、交付決定はまだない。制度データの「交付決定前に発生した経費」（要領8 p.20 など。理由を問わず事前着手は認められない）",
        "直し方": "盛り付けロボットの経費を補助の対象にできるかを制度データで確かめて、社長に示す（交付決定前の発注は対象にならない）。ほかの機械は、交付決定の後に発注する",
        "採点の手がかり（案）": ["注文|発注", "事前着手|交付決定"],
        "関連して出てよい指摘": ["発注していない、という会社の記録（回答表 H-06）と違う"],
    },
    {
        "id": "仕込み-17",
        "種類": "従業員数が書類によって違う（労働者名簿 14人、法人事業概況説明書 15人）",
        "型": "不備-06",
        "SPEC の重大": None,
        "重さ": "重大",
        "書類": ["労働者名簿.xlsx", "法人事業概況説明書_第18期.pdf"],
        "場所": "労働者名簿の人の数",
        "仕込んだ値": f"14人（洗い場のパート {OMITTED_WORKER} が載っていない）",
        "正しい値": "15人（正社員7人、パート8人）",
        "見つける手がかり": "法人事業概況説明書（省力化では従業員数の確認書類。応募手引8 p.65）の従業員15人と合わない",
        "直し方": "制度データの定義（役員を含めない）で数え直し、どちらが正しいかを社長に確かめて、すべての書類をそろえる",
        "採点の手がかり（案）": ["従業員|労働者名簿", "14人|１４人|人数|食い違"],
        "関連して出てよい指摘": ["会社の記録（回答表 C-01：15人）と違う"],
    },
    {
        "id": "仕込み-18",
        "種類": "配置図と見積書で、機械の台数が違う",
        "型": "不備-14",
        "SPEC の重大": None,
        "重さ": "重大",
        "書類": [LAYOUT_FILE, "見積書_つばさ台フードシステム.pdf"],
        "場所": "配置図の図と「機械の一覧」（盛り付けロボット）",
        "仕込んだ値": f"盛り付けロボット {LAYOUT_ROBOTS}台",
        "正しい値": "2台（見積書・カタログ・回答表 H-02）",
        "見つける手がかり": "据付のある機械で、配置図（図面）と見積書の内容（台数）が違う",
        "直し方": "どちらが正しいかを社長に確かめ、つばさ台フードシステムに配置図か見積書を直してもらう",
        "採点の手がかり（案）": ["配置図", "3台|３台|台数"],
        "関連して出てよい指摘": [],
    },
]

# 形式の名前（ファイル → 一覧に書く形式）
FORMS = {name: form for name, _, form, _ in FILES}


def answers() -> dict:
    knowledge = json.loads((REPO / "knowledge" / "不備の型.json").read_text(encoding="utf-8"))
    type_names = {t["id"]: t["名前"] for t in knowledge["型"]}
    defects = []
    for d in DEFECTS:
        entry = dict(d)
        entry["型の名前"] = type_names[d["型"]]
        entry["形式"] = FORMS[d["書類"][0]] if d["書類"] else "（書類がない）"
        entry["見つけ方"] = next(t["見つけ方"] for t in knowledge["型"] if t["id"] == d["型"])
        defects.append(entry)
    by_file = {}
    for d in DEFECTS:
        for name in d["書類"] + d.get("抜いた書類", []):
            by_file.setdefault(name, []).append(d["id"])
    kinds = sorted({d["種類"] for d in DEFECTS})
    spec_critical = [d for d in DEFECTS if d["SPEC の重大"]]
    return {
        "説明": "TASKS D5b の答え。不備を仕込んだセット/ の書類に仕込んだ不備の一覧。会社のフォルダには写さない。"
        "T5-1 で、ツールの指摘と突き合わせる（DESIGN 11章）。型は knowledge/不備の型.json の id",
        "作ったスクリプト": "testdata/書類セット/make_defect_set.py",
        "セット": "不備を仕込んだセット",
        "元にしたセット": "正しいセット（TASKS D5a）",
        "制度": "省力化（一般型）第8回",
        "段階": "応募申請",
        "申請の日の範囲": {
            "始め": APPLY_FROM,
            "終わり": APPLY_UNTIL,
            "説明": "正しいセットと同じ範囲。この範囲のどの日に申請しても、下の不備はどれも不備で、ほかの日付は切れていない。T5-1 のケースで今日の日付を差し替えるときは、この範囲の日にする",
        },
        "数": {
            "不備": len(DEFECTS),
            "種類": len(kinds),
            "型": len({d["型"] for d in DEFECTS}),
            "SPEC の重大（期限切れ・期数不足・金額の不一致・名義の不一致・事前着手）": len(spec_critical),
            "そのほか": len(DEFECTS) - len(spec_critical),
            "重さ": {w: sum(1 for d in DEFECTS if d["重さ"] == w) for w in ("重大", "要確認", "助言")},
        },
        "種類の数え方": "SPEC F5 の不備チェックの例と同じ細かさで数える（社名・住所・代表者名、見積書の宛名・期限切れ、"
        "証明書の期限切れ、期数不足などを、それぞれ1種類とする）。1つの種類に1つの不備を仕込んだ。"
        "期数不足の2つ（決算書・納税証明書）を1種類とまとめても17種類",
        "ファイル": [
            {"ファイル": name, "種類": kind, "形式": form, "正しいセットとの関係": how, "不備": by_file.get(name, [])}
            for name, kind, form, how in FILES
        ],
        "抜いた書類": [{"ファイル": name, "種類": kind, "不備": by_file.get(name, [])} for name, kind in REMOVED],
        "不備": defects,
    }


def write_list(path: Path) -> None:
    path.write_text(json.dumps(answers(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    missing = [p for p in [CORRECT_DIR / n for n in UNCHANGED] if not p.is_file()]
    if missing or not DOCS.is_dir():
        sys.exit(f"元の書類がありません（D2a・D2b・D5a を先に作る）：{[str(p) for p in missing]}")
    for path in build(SET_DIR):
        print(f"{path.relative_to(HERE)}  {path.stat().st_size:,} バイト")
    write_list(LIST_FILE)
    print(LIST_FILE.relative_to(HERE))


if __name__ == "__main__":
    main()
