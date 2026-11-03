# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pypdfium2==5.14.0", "pillow==13.0.0"]
# ///
"""スキャンの材料（TASKS D7）を作る。

T5-8（スキャンした書類の金額と明細を、正解と突き合わせる）と、T8-13（スキャンした見積書3通と経費のメモ1枚から
経費明細を作らせる）で使う材料と、その正解を作る。

作るもの：
- 材料/：テストで会社のフォルダに写すファイル。スキャンした PDF（文字のない、画像だけの PDF）と、スマホの写真（JPEG）。
  - D2b の見積書2通（つばさ台フードシステム・ほしみ機工）。testdata/デモの会社/書類/ のものを読むだけで、変えない。
  - つばさ台フードシステムの概算見積（現地を見る前のもの。2026年10月20日の見積に置き換わった）。FAX で届いた形。
  - 食材と包材の仕入れ先の納品書と請求書（今の事業の仕入れ。8% と 10% がまじる）。
  - 社長の経費のメモ（手書きの写真）。補助の対象にならない経費を1つ含む。
- 元の書類/：上の書類のうち、このスクリプトが描いた書類のきれいな PDF（読みにくくする前のもの）。テストでは使わない。
- 正解.json：書類ごとの読み取る項目（DESIGN 8.4）と、金額と明細の正解。読みにくい所と、隠れて読めない所。
- 経費明細の正解.json：T8-13 の経費明細の正解（1件目の省力化）。

数字と事実は testdata/デモの会社/回答表.md と D2b の見積書に合わせる。回答表にない数字と事実は、材料の一覧.md に挙げた。
どの書類と写真にも「架空のテスト用データ」を出す。

作者が手で書いて撮ったメモの写真に替えるときは、作者の写真/経費のメモ.jpg に置いてから、このスクリプトを流す
（あれば、描いたメモの代わりにそれを使う）。書く中身は 材料の一覧.md にある。そのまま写さず、向きを直して画素だけを
経費のメモ_作者の写真.jpg に保存し直し、それを 材料/ に写すので、EXIF・XMP（撮った位置・機種・日時）や色の情報は
入らない。作者の写真/ は Git の外（testdata/スキャン/.gitignore）で、元の写真はコミットされない。
経費のメモ_作者の写真.jpg はコミットし、元の写真がない機械でも、これから同じ 材料/ を作る。

同じ元のファイルと同じ版のライブラリからなら、何度作っても同じバイト列になる。PDF の日本語の字形は埋め込まれていないので、
PDFium が手元の字形で描く（Mac ならヒラギノ）。手書き風の字は Mac の Klee を使う。別の機械で作り直すと、画像のバイト列は変わることがある。

動かし方：uv run --script testdata/スキャン/make_scans.py
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import random
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent / "デモの会社" / "書類"
sys.path.insert(0, str(DOCS_DIR))

import pypdfium2 as pdfium  # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps  # noqa: E402
from reportlab.lib.colors import Color, black  # noqa: E402

import make_documents as d2a  # noqa: E402
import make_documents_part2 as d2b  # noqa: E402

GOTHIC = d2a.GOTHIC
MINCHO = d2a.MINCHO
LEFT = d2a.LEFT
RIGHT = d2a.RIGHT
PAGE_H = d2a.PAGE_H
COMPANY = d2a.COMPANY  # A-01
PRESIDENT = d2a.PRESIDENT  # A-08

MATERIAL_DIR = HERE / "材料"
ORIGINAL_DIR = HERE / "元の書類"
AUTHOR_PHOTO = HERE / "作者の写真" / "経費のメモ.jpg"  # 作者が置く元の写真。EXIF を持つので Git の外（.gitignore）
AUTHOR_MEMO = HERE / "経費のメモ_作者の写真.jpg"  # 上から EXIF などを落としたもの。コミットし、次からはこれから作る
ANSWER = HERE / "正解.json"
EXPENSE_ANSWER = HERE / "経費明細の正解.json"

DPI = 200
FIXED_TIME = dt.datetime(2026, 11, 4, 0, 0, 0)
MARK = "架空のテスト用データ"
IMAGE_BANNER = "架空のテスト用データ（hojokin-oss）　実在の会社・人物とは関係ありません"

BICUBIC = Image.Resampling.BICUBIC
BILINEAR = Image.Resampling.BILINEAR
LANCZOS = Image.Resampling.LANCZOS
NEAREST = Image.Resampling.NEAREST


def yen(v: int) -> str:
    return f"{v:,}"


def jdate(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


# ---------------------------------------------------------------------------
# 書類の中身（回答表にない数字と事実は、材料の一覧.md に挙げた）
# ---------------------------------------------------------------------------

def parse_jdate(text: str) -> dt.date:
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not m:
        raise ValueError(f"日付の形が違います：{text}")
    return dt.date(int(m[1]), int(m[2]), int(m[3]))


# D2b の見積書（読むだけ）。正解は make_documents_part2.py の明細と同じ
D2B_QUOTE_DATE = parse_jdate(d2b.QUOTE_DATE)  # H-04
D2B_QUOTE_VALID = parse_jdate(d2b.QUOTE_VALID_UNTIL)  # H-04

# つばさ台フードシステムの概算見積。現地を見る前に出したもので、2026年10月20日の見積に置き換わった。
# 議事録（D8、2026年9月10日）の「見積を10月中に2社に頼む」と合うよう、10月の日付にした
ROUGH_QUOTE = {
    "issuer": "株式会社つばさ台フードシステム",
    "number": "TFS-2610-0061",
    "date": dt.date(2026, 10, 6),
    "valid_until": dt.date(2026, 10, 31),
    "subject": d2b.SUBJECT,
    "items": [
        # (品名, 型番, 数量, 単位, 単価)。型番は D2b の見積と同じで、単価は少し高い
        ("盛り付けロボット", "TF-MR200", 2, "台", 4_000_000),
        ("自動計量機（組合せ計量 14ヘッド）", "TF-AW14", 1, "台", 3_300_000),
        ("トップシール包装機", "TF-TS60", 1, "台", 4_900_000),
        ("画像検査装置（盛り付け・ラベル、カメラ2台）", "TF-VI2", 1, "式", 3_700_000),
        ("重量チェッカー・ラベラー（一体型）", "TF-CL10", 1, "台", 1_900_000),
        ("搬送コンベヤ（ライン連結用）", "TF-CV8", 1, "式", 900_000),
        ("据付・試運転調整", "—", 1, "式", 600_000),
    ],
    "notes": [
        "この見積は、現地を見る前の概算です。据付の場所と電気の容量を現地で確かめたうえで、正式にお見積りします。",
        "金額は消費税抜きで表示しています。消費税（10%）は下に分けて記しました。",
        "納期：ご発注から約5か月の見込みです。",
        "受渡場所：御社 本社工場　　お支払い：ご相談のうえ決めます。",
    ],
    "fax_header": "2026/10/06 16:42　FROM：つばさ台フードシステム 営業部　　TO：やまぶき惣菜 様　　P.1/1",
}

# 食材と包材の仕入れ先（架空）。今の事業の仕入れで、補助の対象の経費ではない
SUPPLIER = "株式会社みつばね食品資材"
# 登録番号は T のあとに13桁。先頭の数字（法人番号の検査用の数字）は 1〜9 にしかならないので、0 にして実在の番号と重ならないようにした
SUPPLIER_REG_NO = "T0602418375196"
REDUCED = 8  # 軽減税率
STANDARD = 10

DELIVERY_NOTE = {
    "number": "N-261015-03",
    "date": dt.date(2026, 10, 15),
    "items": [
        # (品名, 数量, 単位, 単価, 税率)
        ("冷凍ほうれん草（カット）1kg", 30, "袋", 520, REDUCED),
        ("鶏もも肉（冷蔵）2kg", 12, "パック", 2_380, REDUCED),
        ("だし醤油 1.8L", 6, "本", 1_150, REDUCED),
        ("惣菜容器（中・黒）50枚入", 40, "袋", 640, STANDARD),
        ("トップシールフィルム 幅200mm×300m", 4, "巻", 7_800, STANDARD),
    ],
}
SECOND_DELIVERY = {
    "number": "N-261029-02",
    "date": dt.date(2026, 10, 29),
    "items": [
        ("冷凍かぼちゃ（ダイスカット）1kg", 20, "袋", 460, REDUCED),
        ("白だし 1.8L", 4, "本", 1_380, REDUCED),
        ("惣菜容器（小・黒）50枚入", 30, "袋", 520, STANDARD),
        ("配送料", 1, "回", 1_500, STANDARD),
    ],
}
INVOICE = {
    "number": "MT-2610-0418",
    "date": dt.date(2026, 10, 31),
    "period": (dt.date(2026, 10, 1), dt.date(2026, 10, 31)),
    "due": dt.date(2026, 11, 30),
    "deliveries": [DELIVERY_NOTE, SECOND_DELIVERY],
}
# 請求書の写真で、しみに隠れて読めない所（2回目の納品の「白だし」の単価）
HIDDEN_ITEM = ("白だし 1.8L", "単価")
ROUNDING = "税率ごとに、1円未満を切り捨て"

# 社長の経費のメモ（手書き）。1件目（省力化）のライン。見積書3通と一緒に使う（T8-13）
MEMO_DATE = dt.date(2026, 11, 2)
MEMO_LINES = [
    "11/2　盛り付け・包装のライン　かかるお金",
    "・機械一式 → つばさ台の 10/20 の見積でいく",
    "　　（2,250万・税抜）　ほしみは比べる用",
    "・ラベラーに、受注の表から品名と",
    "　アレルギーを送るソフト　30万くらい？",
    "　　→ つばさ台に見積をたのむ",
    "・試運転で使う惣菜の材料　10万くらい",
]
# メモから取る経費（品名, 書き方, 金額）
MEMO_EXPENSES = [
    ("ラベラーに受注の表から品名とアレルギーを送るソフト", "30万くらい？", 300_000),
    ("試運転で使う惣菜の材料", "10万くらい", 100_000),
]


def line_amount(qty: int, price: int) -> int:
    return qty * price


def tax_by_rate(lines: list[tuple[int, int]]) -> list[dict]:
    """(金額, 税率) の並びから、税率ごとの対象額と消費税（切り捨て）を出す。10% を先に並べる。"""
    out = []
    for rate in (STANDARD, REDUCED):
        base = sum(a for a, r in lines if r == rate)
        if base:
            out.append({"税率": rate, "対象額": base, "消費税": base * rate // 100})
    return out


# ---------------------------------------------------------------------------
# PDF を描く道具（D2a の Page と render を使う。頭の帯と足は D2a と同じ）
# ---------------------------------------------------------------------------


def draw_table(pg, header: list[str], rows: list[list[str]], widths: list[float], left_cols: set[int],
               fill: Color, size: float = 8.4) -> list[list[tuple[float, float, float, float]]]:
    """表を描き、セルの四隅（PDF の座標で x0, y0, x1, y1）を行ごとに返す。"""
    c = pg.c
    h = size + 9
    rects = []
    for r, cells in enumerate([header] + rows):
        xx = LEFT
        row_rects = []
        for i, (cell, w) in enumerate(zip(cells, widths)):
            if r == 0:
                c.setFillColor(fill)
                c.rect(xx, pg.y - 5, w, h, fill=1, stroke=1)
                c.setFillColor(black)
            else:
                c.rect(xx, pg.y - 5, w, h, fill=0, stroke=1)
            c.setFont(GOTHIC if r == 0 else MINCHO, size)
            if r == 0 or i in left_cols:
                c.drawString(xx + 4, pg.y, cell)
            else:
                c.drawRightString(xx + w - 4, pg.y, cell)
            row_rects.append((xx, pg.y - 5, xx + w, pg.y - 5 + h))
            xx += w
        rects.append(row_rects)
        pg.y -= h
    return rects


def draw_totals(pg, rows: list[tuple[str, int]], label_w: float, value_w: float, size: float = 8.4) -> None:
    """表の下の、合計の欄（ラベルと金額）。金額の欄は、表の金額の列の下に置く。"""
    c = pg.c
    h = size + 9
    for label, value in rows:
        c.rect(LEFT, pg.y - 5, label_w, h, fill=0, stroke=1)
        c.rect(LEFT + label_w, pg.y - 5, value_w, h, fill=0, stroke=1)
        c.setFont(GOTHIC, size)
        c.drawRightString(LEFT + label_w - 6, pg.y, label)
        c.drawRightString(LEFT + label_w + value_w - 4, pg.y, yen(value))
        pg.y -= h


def issuer_block(pg, name: str, reg_no: str | None, dept: str | None) -> None:
    c = pg.c
    x = LEFT + 300
    c.setFont(GOTHIC, 11)
    c.drawString(x, pg.y - 12, name)
    c.setFont(MINCHO, 9)
    c.drawString(x, pg.y - 27, "〒000-0000　架空の所在地（テスト用）")
    line = pg.y - 40
    if dept:
        c.drawString(x, line, dept)
        line -= 13
    if reg_no:
        c.drawString(x, line, f"登録番号　{reg_no}")


def rough_quote_pages() -> list:
    q = ROUGH_QUOTE
    subtotal = sum(line_amount(qty, price) for _, _, qty, _, price in q["items"])
    tax = subtotal * STANDARD // 100

    def page1(pg) -> None:
        c = pg.c
        # つばさ台の見積と同じ形（D2b）。題に「概算」を付ける
        pg.title("御見積書（概算）", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, f"見積番号　{q['number']}")
        c.drawRightString(RIGHT, pg.y + 5, f"発行日　{jdate(q['date'])}")
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{COMPANY}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        c.setFont(MINCHO, 10)
        c.drawString(LEFT, pg.y - 32, f"代表取締役　{PRESIDENT}　様")
        issuer_block(pg, q["issuer"], None, "営業部")
        pg.y -= 62
        pg.para("下記のとおり、概算のお見積りを申し上げます。", size=10)
        pg.kv("件名", q["subject"], key_width=110)
        pg.kv("見積金額（税込）", f"{yen(subtotal + tax)}円", key_width=110)
        pg.kv("有効期限", jdate(q["valid_until"]), key_width=110)
        pg.gap(4)
        widths = [24, 192, 58, 32, 26, 66, 77]
        rows = [
            [str(i), name, model, str(qty), unit, yen(price), yen(line_amount(qty, price))]
            for i, (name, model, qty, unit, price) in enumerate(q["items"], start=1)
        ]
        draw_table(pg, ["No.", "品名", "型番", "数量", "単位", "単価（税抜）", "金額（税抜）"], rows, widths,
                   {1, 2, 4}, Color(0.88, 0.92, 0.97))
        draw_totals(pg, [("小計（税抜）", subtotal), (f"消費税（{STANDARD}%）", tax), ("合計（税込）", subtotal + tax)],
                    sum(widths[:-1]), widths[-1])
        pg.gap(10)
        pg.heading("備考", 10)
        for note in q["notes"]:
            pg.para(f"・{note}", indent=1, size=9)

    return [page1]


def rate_label(rate: int) -> str:
    return f"{rate}%※" if rate == REDUCED else f"{rate}%"


def delivery_note_pages() -> list:
    n = DELIVERY_NOTE
    lines = [(line_amount(qty, price), rate) for _, qty, _, price, rate in n["items"]]
    by_rate = tax_by_rate(lines)
    subtotal = sum(a for a, _ in lines)
    tax = sum(t["消費税"] for t in by_rate)

    def page1(pg) -> None:
        c = pg.c
        pg.title("納　品　書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, f"納品書番号　{n['number']}")
        c.drawRightString(RIGHT, pg.y + 5, f"納品日　{jdate(n['date'])}")
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{COMPANY}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        issuer_block(pg, SUPPLIER, SUPPLIER_REG_NO, None)
        pg.y -= 62
        pg.para("下記のとおり納品いたしました。ご査収ください。", size=10)
        pg.kv("納品先", f"{COMPANY}　本社工場", key_width=110)
        pg.gap(4)
        widths = [24, 200, 36, 36, 60, 72, 47]
        rows = [
            [str(i), name, str(qty), unit, yen(price), yen(line_amount(qty, price)), rate_label(rate)]
            for i, (name, qty, unit, price, rate) in enumerate(n["items"], start=1)
        ]
        draw_table(pg, ["No.", "品名", "数量", "単位", "単価（税抜）", "金額（税抜）", "税率"], rows, widths,
                   {1, 3}, Color(0.9, 0.95, 0.88))
        totals = []
        for t in by_rate:
            totals.append((f"{t['税率']}%対象（税抜）", t["対象額"]))
            totals.append((f"消費税（{t['税率']}%）", t["消費税"]))
        totals += [("合計（税抜）", subtotal), ("消費税の合計", tax), ("合計（税込）", subtotal + tax)]
        draw_totals(pg, totals, sum(widths[:-2]), widths[-2])
        pg.gap(8)
        pg.para("・※は軽減税率（8%）の対象です。", indent=1, size=9)
        pg.para(f"・消費税の端数は、{ROUNDING}ています。", indent=1, size=9)
        pg.para("・代金は、月末締めの請求書でご請求します。", indent=1, size=9)
        pg.gap(10)
        c.rect(RIGHT - 90, pg.y - 50, 90, 60, fill=0, stroke=1)
        c.setFont(GOTHIC, 8)
        c.drawCentredString(RIGHT - 45, pg.y + 1, "受領印")

    return [page1]


# 請求書の、隠す所のセル（PDF の座標）。描いたときに入れる
HIDDEN_RECT: dict[str, tuple[float, float, float, float]] = {}


def invoice_pages() -> list:
    inv = INVOICE
    items = [(d, item) for d in inv["deliveries"] for item in d["items"]]
    lines = [(line_amount(qty, price), rate) for _, (_, qty, _, price, rate) in items]
    by_rate = tax_by_rate(lines)
    subtotal = sum(a for a, _ in lines)
    tax = sum(t["消費税"] for t in by_rate)

    def page1(pg) -> None:
        c = pg.c
        pg.title("請　求　書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, f"請求書番号　{inv['number']}")
        c.drawRightString(RIGHT, pg.y + 5, f"請求日　{jdate(inv['date'])}")
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{COMPANY}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        issuer_block(pg, SUPPLIER, SUPPLIER_REG_NO, None)
        pg.y -= 62
        pg.para("下記のとおりご請求申し上げます。", size=10)
        start, end = inv["period"]
        pg.kv("ご請求金額（税込）", f"{yen(subtotal + tax)}円", key_width=110)
        pg.kv("対象期間", f"{jdate(start)}〜{jdate(end)}（月末締め）", key_width=110)
        pg.kv("お支払期限", jdate(inv["due"]), key_width=110)
        pg.gap(4)
        widths = [44, 186, 32, 34, 56, 70, 53]
        rows = []
        for d, (name, qty, unit, price, rate) in items:
            rows.append([d["date"].strftime("%m/%d"), name, str(qty), unit, yen(price), yen(line_amount(qty, price)),
                         rate_label(rate)])
        rects = draw_table(pg, ["納品日", "品名", "数量", "単位", "単価（税抜）", "金額（税抜）", "税率"], rows, widths,
                           {0, 1, 3}, Color(0.9, 0.95, 0.88))
        for r, (_, (name, *_rest)) in enumerate(items, start=1):
            if name == HIDDEN_ITEM[0]:
                HIDDEN_RECT["請求書"] = rects[r][4]
        totals = []
        for t in by_rate:
            totals.append((f"{t['税率']}%対象（税抜）", t["対象額"]))
            totals.append((f"消費税（{t['税率']}%）", t["消費税"]))
        totals += [("合計（税抜）", subtotal), ("消費税の合計", tax), ("ご請求金額（税込）", subtotal + tax)]
        draw_totals(pg, totals, sum(widths[:-2]), widths[-2])
        pg.gap(8)
        pg.para("・※は軽減税率（8%）の対象です。", indent=1, size=9)
        pg.para(f"・消費税の端数は、{ROUNDING}ています。", indent=1, size=9)
        pg.para(f"・納品書：{DELIVERY_NOTE['number']}（10月15日）、{SECOND_DELIVERY['number']}（10月29日）", indent=1, size=9)
        pg.para("・お振込先は、別にお知らせしている口座です（架空のため書いていません）。", indent=1, size=9)

    return [page1]


# ---------------------------------------------------------------------------
# 画像にする道具（D5a の make_correct_set.py の写真とスキャンを、読みにくさの段階を変えられるようにした）
# ---------------------------------------------------------------------------


def render_page(pdf: Path, dpi: int = DPI) -> Image.Image:
    doc = pdfium.PdfDocument(str(pdf))
    try:
        if len(doc) != 1:
            raise SystemExit(f"{pdf.name} は1ページの書類ではありません（{len(doc)}ページ）")
        return doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def noise_layer(size: tuple[int, int], seed: int, cell: int) -> Image.Image:
    rng = random.Random(seed)
    w, h = max(1, size[0] // cell), max(1, size[1] // cell)
    small = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    return small.resize(size, BILINEAR)


def pdf_rect_to_px(rect: tuple[float, float, float, float], dpi: int = DPI) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    k = dpi / 72
    return int(x0 * k), int((PAGE_H - y1) * k), int(x1 * k), int((PAGE_H - y0) * k)


def add_stain(page: Image.Image, box: tuple[int, int, int, int], seed: int) -> Image.Image:
    """こげ茶のしみ。box（右寄せの数字が入ったセル）の数字だけを、まったく読めなくする。
    上と下の行の数字には、かからないようにする（隠れた所を1か所にとどめる）。"""
    rng = random.Random(seed)
    x0, y0, x1, y1 = box
    k = DPI / 72
    # 数字は右寄せ（右から4pt）。幅は約24pt。数字のまん中に芯を置く
    cx = int(x1 - (4 + 12) * k)
    cy = (y0 + y1) // 2 + 2
    rx, ry = int(17 * k), (y1 - y0) // 2 - 4
    mask = Image.new("L", page.size, 0)
    d = ImageDraw.Draw(mask)
    # 芯（数字を隠す。まったく透けない）
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    # 横へのにじみ（セルの高さの中にとどめる）
    for _ in range(8):
        ox = rng.randint(-rx - 10, rx + 10)
        r = rng.randint(ry // 2, ry - 2)
        oy = rng.randint(-(ry - r), ry - r)
        d.ellipse([cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r], fill=rng.randint(200, 255))
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    # 芯はぼかしたあとも透けないように、もう一度塗る
    ImageDraw.Draw(mask).ellipse([cx - rx + 6, cy - ry + 4, cx + rx - 6, cy + ry - 4], fill=255)
    # しみの色のむら
    base = Image.new("RGB", page.size, (108, 70, 40))
    blotch = noise_layer(page.size, seed=seed, cell=6).point(lambda v: 60 + v * 70 // 255)
    stain = Image.composite(Image.new("RGB", page.size, (86, 54, 30)), base, blotch)
    return Image.composite(stain, page, mask)


def save_image_pdf(img: Image.Image, dst: Path) -> None:
    img.save(
        dst,
        "PDF",
        resolution=DPI,
        title="スキャン",
        author="",
        creator="架空のスキャナ（テスト用）",
        producer="架空のスキャナ（テスト用）",
        creationDate=FIXED_TIME.timetuple(),
        modDate=FIXED_TIME.timetuple(),
    )


def make_scan(page: Image.Image, dst: Path, *, angle: float, seed: int, upside_down: bool = False) -> None:
    """スキャナで読んだ、画像だけの PDF。灰色で、わずかに傾き、地が真っ白でない。"""
    g = page.convert("L")
    g = g.rotate(angle, resample=BICUBIC, expand=False, fillcolor=255)
    if upside_down:
        # 紙を逆さに置いて読んだ
        g = g.rotate(180)
    g = g.point(lambda v: v * 92 // 100 + 14)
    g = Image.blend(g, noise_layer(g.size, seed=seed, cell=2), 0.04)
    save_image_pdf(g, dst)


def make_fax(page: Image.Image, dst: Path, header: str, *, seed: int) -> None:
    """FAX で届いた紙をスキャンした PDF。白黒の2値で、解像度が低く、字がかすれ、点のごみがある。"""
    g = page.convert("L")
    # FAX の頭の行（送った日時と相手）
    d = ImageDraw.Draw(g)
    d.text((70, 24), header, fill=0, font=printed_font(22))
    # 解像度を下げ（約100dpi）、ざらつきを足してから2値にする（細い線がかすれる）
    small = g.resize((g.width // 2, g.height // 2), LANCZOS)
    small = Image.blend(small, noise_layer(small.size, seed=seed, cell=1), 0.12)
    small = small.point(lambda v: 255 if v > 168 else 0)
    g = small.resize(page.size, NEAREST)
    g = g.rotate(-0.8, resample=NEAREST, expand=False, fillcolor=255)
    # 点のごみと、紙送りの縦の筋
    rng = random.Random(seed + 1)
    d = ImageDraw.Draw(g)
    for _ in range(1400):
        x, y, r = rng.randrange(g.width), rng.randrange(g.height), rng.choice((1, 1, 2, 2, 3))
        d.ellipse([x, y, x + r, y + r], fill=0)
    for x in (rng.randrange(200, g.width - 200) for _ in range(2)):
        d.line([(x, 0), (x, g.height)], fill=150, width=2)
    save_image_pdf(g, dst)


def perspective_coeffs(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """出力の4点 dst を、入力の4点 src に写す PERSPECTIVE の係数（8つ）。ガウスの消去法で解く。"""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    n = 8
    a = [row[:] + [b] for row, b in zip(rows, rhs)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                f = a[r][col] / a[col][col]
                for k in range(col, n + 1):
                    a[r][k] -= f * a[col][k]
    return [a[i][n] / a[i][i] for i in range(n)]


def make_photo(page: Image.Image, dst: Path, *, angle: float, keystone: float, blur: float, dim: int,
               quality: int, seed: int) -> None:
    """紙を机に置いて、スマホで撮った写真。傾き、手前が広く奥がせまい形（keystone）、影、明るさのむら、ぼけ。"""
    pw, ph = page.size
    size = (int(pw * 1.2), int(ph * 1.14))
    gradient = Image.linear_gradient("L").resize(size, BILINEAR)
    desk = ImageOps.colorize(gradient, black=(92, 76, 60), white=(136, 116, 94))
    paper = page.convert("RGBA").rotate(angle, resample=BICUBIC, expand=True)
    x = (size[0] - paper.size[0]) // 2
    y = (size[1] - paper.size[1]) // 2
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).rectangle([x + 18, y + 24, x + paper.size[0] + 18, y + paper.size[1] + 24], fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    desk = Image.composite(Image.new("RGB", size, (30, 24, 18)), desk, shadow)
    desk.paste(paper, (x, y), paper)
    # 斜めから撮った形（奥＝上がせまい）
    w, h = size
    d = keystone * w
    coeffs = perspective_coeffs([(-d, 0), (w + d, 0), (w, h), (0, h)], [(0, 0), (w, 0), (w, h), (0, h)])
    desk = desk.transform(size, Image.Transform.PERSPECTIVE, coeffs, BICUBIC, fillcolor=(92, 76, 60))
    # 明るさのむら（左上が明るく、右下が暗い）。dim が大きいほど暗い
    light = Image.radial_gradient("L").resize((size[0] * 2, size[1] * 2), BILINEAR)
    light = light.crop((size[0] // 2, size[1] // 2, size[0] // 2 + size[0], size[1] // 2 + size[1]))
    low = 205 - dim
    light = ImageOps.invert(light).point(lambda v: low + v * (255 - low) // 255)
    tint = Image.merge("RGB", (light, light.point(lambda v: v * 250 // 255), light.point(lambda v: v * 234 // 255)))
    photo = ImageChops.multiply(desk, tint)
    photo = photo.filter(ImageFilter.GaussianBlur(blur))
    grain = noise_layer(size, seed=seed, cell=2).convert("RGB")
    photo = Image.blend(photo, grain, 0.05)
    hh = min(size[1], size[0] * 4 // 3)
    ww = hh * 3 // 4
    left = (size[0] - ww) // 2
    top = (size[1] - hh) // 2
    photo = photo.crop((left, top, left + ww, top + hh)).resize((1536, 2048), LANCZOS)
    photo.save(dst, "JPEG", quality=quality)


PHOTO_LONG_SIDE = 2048  # 作者の写真を縮める長辺（描いた写真の 1536×2048 にそろえる）


def photo_leftovers(path: Path) -> list[str]:
    """JPEG に残った付けたし（EXIF・XMP・色の情報・コメントなど）を挙げる。なければ空。
    画像のデータ（SOS）の前にある APP1〜APP15 と COM の区切りも見る（Pillow が書くのは APP0 だけ）。"""
    found = []
    with Image.open(path) as img:
        if img.format != "JPEG":
            return [f"形式 {img.format}"]
        if img.getexif():
            found.append("EXIF")
        found += [k for k in ("exif", "xmp", "icc_profile", "photoshop", "comment") if k in img.info]
    data = path.read_bytes()
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:
            break
        if 0xE1 <= marker <= 0xEF or marker == 0xFE:
            found.append(f"区切り 0x{marker:02X}")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return found


def strip_author_photo(src: Path, dst: Path) -> None:
    """作者が撮った写真から、撮った位置・機種・日時などを落として dst に保存し直す。

    スマホの写真の EXIF には GPS の位置・機種・撮影日時が入る。XMP にも入ることがある。
    EXIF の向きの印で画素を回してから、画素だけを新しい画像に写して保存する（img.info の
    exif・xmp・icc_profile を引き継がない）。長辺を PHOTO_LONG_SIDE に縮める。"""
    try:
        with Image.open(src) as img:
            if img.format != "JPEG":
                raise SystemExit(f"{src.name} は JPEG ではありません（{img.format}）。JPEG で撮るか、JPEG に書き出してください")
            upright = ImageOps.exif_transpose(img).convert("RGB")
    except OSError as err:
        raise SystemExit(f"{src.name} を開けません（{err}）。JPEG で撮るか、JPEG に書き出してください") from err
    clean = Image.frombytes("RGB", upright.size, upright.tobytes())
    if max(clean.size) > PHOTO_LONG_SIDE:
        k = PHOTO_LONG_SIDE / max(clean.size)
        clean = clean.resize((round(clean.width * k), round(clean.height * k)), LANCZOS)
    clean.save(dst, "JPEG", quality=85)
    left = photo_leftovers(dst)
    if left:
        dst.unlink()
        raise SystemExit(f"{dst.name} に {left} が残りました。作るのを止めます")


# ---------------------------------------------------------------------------
# 手書きのメモ（手書き風の字で描く。作者が書いて撮った写真に替えられる）
# ---------------------------------------------------------------------------

HAND_FONT_GLOBS = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*.asset/AssetData/Klee.ttc",
    "/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/com_apple_MobileAsset_Font*/*.asset/AssetData/Klee.ttc",
    "/Library/Fonts/Klee*.ttc",
]
HAND_FONT_FALLBACK = [
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
PRINTED_FONT = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def printed_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in PRINTED_FONT:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit("日本語の書体が見つかりません。PRINTED_FONT に書体のファイルを足してください")


def hand_font_path() -> tuple[str, int]:
    for pattern in HAND_FONT_GLOBS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0], 0  # Klee Demibold（ボールペンに近い太さ）
    for candidate in HAND_FONT_FALLBACK:
        if Path(candidate).exists():
            print("手書き風の書体（Klee）が見つからないので、丸ゴシックで描きます", file=sys.stderr)
            return candidate, 0
    raise SystemExit("手書きのメモに使う書体が見つかりません。HAND_FONT_GLOBS に書体のファイルを足してください")


def draw_memo() -> Image.Image:
    """罫線のメモ用紙に、ボールペンで書いたような字。字ごとに大きさ・傾き・位置を少しずつずらす。"""
    w, h = 1240, 1680
    paper = Image.new("RGB", (w, h), (250, 248, 238))
    d = ImageDraw.Draw(paper)
    pitch, first = 92, 250
    for i in range(16):
        y = first + i * pitch
        if y < h - 40:
            d.line([(40, y), (w - 40, y)], fill=(168, 192, 222), width=2)
    d.line([(120, 150), (120, h - 30)], fill=(226, 150, 150), width=2)
    # 上の帯（印刷したシールを貼った形）
    d.rectangle([60, 40, w - 60, 104], fill=(255, 242, 190), outline=(214, 150, 0), width=2)
    d.text((w // 2, 72), IMAGE_BANNER, fill=(0, 0, 0), font=printed_font(26), anchor="mm")

    path, index = hand_font_path()
    rng = random.Random(1102)
    ink = (26, 34, 92)
    for row, text in enumerate(MEMO_LINES):
        x = 140.0 + rng.uniform(-4, 4)
        base = first + row * pitch - 8  # 罫線の少し上に書く
        size_row = 48 if row == 0 else 46
        for ch in text:
            if ch == "　":
                x += size_row * 0.9
                continue
            size = int(size_row * rng.uniform(0.93, 1.07))
            font = ImageFont.truetype(path, size, index=index)
            tile = Image.new("L", (size * 2, size * 2), 0)
            ImageDraw.Draw(tile).text((size // 2, size // 2), ch, fill=255, font=font)
            tile = tile.rotate(rng.uniform(-4, 4), resample=BICUBIC)
            jitter = rng.uniform(-3, 3) + (x - 140) * 0.006  # 右へいくほど少し下がる
            ink_img = Image.new("RGB", tile.size, ink)
            paper.paste(ink_img, (int(x - size // 2), int(base - size * 1.45 + jitter)), tile)
            x += font.getlength(ch) * rng.uniform(0.95, 1.03) + rng.uniform(-1, 2)
    return paper


# ---------------------------------------------------------------------------
# 正解
# ---------------------------------------------------------------------------


def quote_answer(file: str, source: str, form: str, difficulty: str, tests: list[str], kind: str, number: str,
                 date: dt.date, valid: dt.date, issuer: str, subject: str,
                 items: list[tuple[str, str, int, str, int]]) -> dict:
    detail = [
        {"品名": n, "型番": m, "数量": q, "単位": u, "単価": p, "金額": line_amount(q, p), "税率": STANDARD}
        for n, m, q, u, p in items
    ]
    by_rate = tax_by_rate([(x["金額"], STANDARD) for x in detail])
    subtotal = sum(x["金額"] for x in detail)
    tax = sum(t["消費税"] for t in by_rate)
    return {
        "ファイル": file,
        "形": form,
        "読みにくさ": difficulty,
        "元": source,
        "使うテスト": tests,
        "種類": kind,
        "番号": number,
        "発行日": date.isoformat(),
        "有効期限": valid.isoformat(),
        "宛名": COMPANY,
        "宛名の人": f"代表取締役 {PRESIDENT}",
        "発行者": issuer,
        "登録番号": None,
        "件名": subject,
        "税込か税抜か": "明細の単価・金額と小計は税抜。消費税を分けて書き、合計は税込",
        "明細": detail,
        "税率ごと": by_rate,
        "小計": subtotal,
        "消費税": tax,
        "合計": subtotal + tax,
        "端数の処理": None,
        "隠れた箇所": [],
    }


def trade_answer(file: str, form: str, difficulty: str, kind: str, number: str, date_key: str, date: dt.date,
                 deliveries: list[dict], extra: dict, hidden: list[dict]) -> dict:
    detail = []
    for dlv in deliveries:
        for name, qty, unit, price, rate in dlv["items"]:
            row = {"品名": name, "型番": None, "数量": qty, "単位": unit, "単価": price, "金額": line_amount(qty, price),
                   "税率": rate}
            if kind == "請求書":
                row = {"納品日": dlv["date"].isoformat(), "納品書番号": dlv["number"], **row}
            detail.append(row)
    by_rate = tax_by_rate([(x["金額"], x["税率"]) for x in detail])
    subtotal = sum(x["金額"] for x in detail)
    tax = sum(t["消費税"] for t in by_rate)
    answer = {
        "ファイル": file,
        "形": form,
        "読みにくさ": difficulty,
        "元": f"元の書類/{kind}_みつばね食品資材_{date.isoformat()}.pdf（このスクリプトが描いた）",
        "使うテスト": ["T5-8"],
        "種類": kind,
        "番号": number,
        date_key: date.isoformat(),
        **extra,
        "宛名": COMPANY,
        "宛名の人": None,
        "発行者": SUPPLIER,
        "登録番号": SUPPLIER_REG_NO,
        "件名": None,
        "税込か税抜か": "明細の単価・金額は税抜。税率ごとに対象額と消費税を書き、合計は税込",
        "明細": detail,
        "税率ごと": by_rate,
        "小計": subtotal,
        "消費税": tax,
        "合計": subtotal + tax,
        "端数の処理": ROUNDING,
        "隠れた箇所": hidden,
    }
    return answer


FILES = {
    "tsubasa": "scan_20261104_0001.pdf",
    "rough": "FAX_20261006_1642.pdf",
    "delivery": "scan_20261104_0003.pdf",
    "hoshimi": "IMG_2741.jpg",
    "invoice": "IMG_2742.jpg",
    "memo": "IMG_2745.jpg",
}


def answers() -> tuple[dict, dict]:
    t = d2b.QUOTES["つばさ台フードシステム"]
    h = d2b.QUOTES["ほしみ機工"]
    strip = lambda items: [(n, m, q, u, p) for n, m, q, u, p, _ in items]  # noqa: E731
    docs = [
        quote_answer(
            f"材料/{FILES['tsubasa']}", "testdata/デモの会社/書類/見積書_つばさ台フードシステム.pdf（D2b。読むだけ）",
            "スキャンした PDF（文字のない、画像だけの PDF）", "ふつう。灰色で、わずかに傾き、地がうすい灰色",
            ["T5-8", "T8-13"], "見積書", t["number"], D2B_QUOTE_DATE, D2B_QUOTE_VALID, t["issuer"], d2b.SUBJECT,
            strip(t["items"])),
        quote_answer(
            f"材料/{FILES['hoshimi']}", "testdata/デモの会社/書類/見積書_ほしみ機工.pdf（D2b。読むだけ）",
            "スマホの写真（JPEG）", "読みにくい。斜めから撮って奥がせまく、暗く、ぼけている。数字は拡大すれば読める",
            ["T5-8", "T8-13"], "見積書", h["number"], D2B_QUOTE_DATE, D2B_QUOTE_VALID, h["issuer"], d2b.SUBJECT,
            strip(h["items"])),
        quote_answer(
            f"材料/{FILES['rough']}", f"元の書類/見積書_つばさ台フードシステム_概算_{ROUGH_QUOTE['date'].isoformat()}.pdf（このスクリプトが描いた）",
            "FAX で届いた紙をスキャンした PDF（白黒の2値、文字のない画像だけの PDF）",
            "読みにくい。解像度が低く、細い線がかすれ、点のごみがある。数字は拡大すれば読める",
            ["T5-8", "T8-13"], "見積書", ROUGH_QUOTE["number"], ROUGH_QUOTE["date"], ROUGH_QUOTE["valid_until"],
            ROUGH_QUOTE["issuer"], ROUGH_QUOTE["subject"], ROUGH_QUOTE["items"]),
        trade_answer(
            f"材料/{FILES['delivery']}", "スキャンした PDF（文字のない、画像だけの PDF）",
            "ふつう。ただし紙を逆さに置いて読んだので、上下が逆になっている", "納品書", DELIVERY_NOTE["number"],
            "納品日", DELIVERY_NOTE["date"], [DELIVERY_NOTE], {"納品先": f"{COMPANY} 本社工場"}, []),
        trade_answer(
            f"材料/{FILES['invoice']}", "スマホの写真（JPEG）",
            "1か所読めない。2回目の納品の「白だし 1.8L」の単価に、こげ茶のしみがかかって数字が隠れている。ほかは読める",
            "請求書", INVOICE["number"], "請求日", INVOICE["date"], INVOICE["deliveries"],
            {"対象期間": [INVOICE["period"][0].isoformat(), INVOICE["period"][1].isoformat()],
             "支払期限": INVOICE["due"].isoformat()},
            [{
                "明細": HIDDEN_ITEM[0],
                "欄": HIDDEN_ITEM[1],
                "正しい値": next(p for n, _, _, p, _ in SECOND_DELIVERY["items"] if n == HIDDEN_ITEM[0]),
                "様子": "しみで数字が隠れていて、紙を見ないと読めない。数量（4）と金額（5,520）は読める",
                "望む振る舞い": "計算（5,520 ÷ 4）で埋めて済ませない。数量 × 単価 ＝ 金額を照合できないので「要確認」とし、"
                               "その部分の画像と読み取った数字を並べて社長に確かめる。計算で出る 1,380円を、確かめてもらう候補として示すのはよい（仮）",
            }]),
    ]
    answer = {
        "説明": "スキャンの材料（TASKS D7）の、書類ごとの読み取る項目（DESIGN 8.4）と、金額と明細の正解。T5-8 で、読み取った値と突き合わせる。"
                "金額は円。日付は YYYY-MM-DD。読みにくい所と隠れた所は、書類ごとの「読みにくさ」と「隠れた箇所」に書いた",
        "作ったタスク": "TASKS D7（2026-11-04）",
        "作るスクリプト": "testdata/スキャン/make_scans.py",
        "確かめるスクリプト": "testdata/スキャン/check_scans.py",
        "書類": docs,
    }

    # T8-13：1件目（省力化）の経費明細の正解
    rows = []
    for i, (name, model, qty, unit, price, group) in enumerate(t["items"], start=1):
        rows.append({
            "区分（参考）": "機械装置・システム構築費",
            "品名": name,
            "型番": model,
            "数量": qty,
            "単位": unit,
            "単価": price,
            "金額（税抜）": line_amount(qty, price),
            "根拠の種類": "見積書",
            "出典": f"材料/{FILES['tsubasa']}（{t['issuer']}、{t['number']}、2026年10月20日）の明細{i}",
            "回答表の区分（H-02）": group,
            "仮の印": False,
            "要確認": None,
        })
    software, trial = MEMO_EXPENSES
    rows.append({
        "区分（参考）": "機械装置・システム構築費（専用ソフトウェア）",
        "品名": software[0],
        "型番": None,
        "数量": 1,
        "単位": "式",
        "単価": software[2],
        "金額（税抜）": software[2],
        "根拠の種類": "メモ",
        "出典": f"材料/{FILES['memo']}（社長の経費のメモ、2026年11月2日）の「{software[1]}」",
        "回答表の区分（H-02）": None,
        "仮の印": True,
        "要確認": None,
        "注記": "見積がまだない（メモに「つばさ台に見積をたのむ」）。見積書がそろったら差し替える。税込か税抜かもメモからは分からない",
    })
    rows.append({
        "区分（参考）": None,
        "品名": trial[0],
        "型番": None,
        "数量": 1,
        "単位": "式",
        "単価": trial[2],
        "金額（税抜）": trial[2],
        "根拠の種類": "メモ",
        "出典": f"材料/{FILES['memo']}（社長の経費のメモ、2026年11月2日）の「{trial[1]}」",
        "回答表の区分（H-02）": None,
        "仮の印": True,
        "要確認": {
            "わけ": "導入する設備の試運転に伴う原材料費は、補助の対象にならない経費に挙がっている",
            "制度データの項目": "補助の対象にならない経費／試運転の原材料費・光熱費（testdata/正解/省力化_第8回.json）",
            "資料のページ": [{"資料": "要領8", "ページ": 23}, {"資料": "応募手引8", "ページ": 46}],
        },
    })
    quote_total = sum(r["金額（税抜）"] for r in rows if r["根拠の種類"] == "見積書")
    memo_total = sum(r["金額（税抜）"] for r in rows if r["根拠の種類"] == "メモ" and r["要確認"] is None)
    check_total = sum(r["金額（税抜）"] for r in rows if r["要確認"] is not None)
    expense = {
        "説明": "T8-13 の経費明細の正解。スキャンした見積書3通と経費のメモ1枚（手書きの写真）から作る、1件目（省力化）の経費明細。"
                "金額は円・税抜。区分は参考で、正しさは制度データ（補助の対象になる経費）に照らして判断する",
        "作ったタスク": "TASKS D7（2026-11-04）",
        "案件": "1件目：省力化（一般型）。盛り付け・計量・包装を画像検査つきでつなぐライン（回答表 H-01・H-02）",
        "制度データ": "testdata/正解/省力化_第8回.json",
        "材料": [f"材料/{FILES['tsubasa']}", f"材料/{FILES['hoshimi']}", f"材料/{FILES['rough']}", f"材料/{FILES['memo']}"],
        "経費のメモ": {
            "ファイル": f"材料/{FILES['memo']}",
            "形": (f"手書きのメモをスマホで撮った写真（JPEG）。作者が手で書いて撮ったもの（{AUTHOR_MEMO.name}。"
                  "EXIF などを落として保存し直した）"
                  if AUTHOR_MEMO.is_file() else
                  "手書きのメモをスマホで撮った写真（JPEG）。いまは手書き風の字で描いた仮のもの。作者が書いて撮った写真に替えてよい"),
            "書いた日": MEMO_DATE.isoformat(),
            "文面": MEMO_LINES,
            "経費": [{"品名": n, "書き方": w, "金額": a} for n, w, a in MEMO_EXPENSES],
        },
        "行": rows,
        "使わない見積": [
            {"ファイル": f"材料/{FILES['hoshimi']}", "見積": f"{h['issuer']}、{h['number']}、2026年10月20日",
             "わけ": "比べるための相見積。頼むのはつばさ台フードシステム（回答表 H-03・H-05、メモ「ほしみは比べる用」）"},
            {"ファイル": f"材料/{FILES['rough']}", "見積": f"{ROUGH_QUOTE['issuer']}、{ROUGH_QUOTE['number']}、2026年10月6日（概算）",
             "わけ": "現地を見る前の概算で、2026年10月20日の正式な見積に置き換わった。有効期限（2026年10月31日）も切れている。"
                     "メモに「つばさ台の 10/20 の見積でいく」"},
        ],
        "合計": {
            "見積書から（仮の印なし）": quote_total,
            "メモから（仮の印あり、要確認を除く）": memo_total,
            "要確認（対象にならない見込み）": check_total,
        },
        "合格の見方（案）": [
            "見積書から取った行の金額が、上の「行」の見積書の行と一致する。見積書の行は、明細の行ごとでも、回答表 H-02 の区分ごとにまとめてもよい。"
            "まとめたときは、元の明細の金額の和と一致すること。小計（税抜）22,500,000円に、消費税を入れていないこと",
            "ほしみ機工の相見積と、つばさ台の概算見積の金額が、経費明細に入っていない",
            "メモから取った金額（300,000円、100,000円）に仮の印がある",
            "試運転で使う惣菜の材料を「要確認」とし、資料のページ（要領8 の23ページ、応募手引8 の46ページ）か制度データの項目を示す",
        ],
    }
    return answer, expense


# ---------------------------------------------------------------------------


def build() -> None:
    sources = [DOCS_DIR / "見積書_つばさ台フードシステム.pdf", DOCS_DIR / "見積書_ほしみ機工.pdf"]
    missing = [p.name for p in sources if not p.is_file()]
    if missing:
        sys.exit(f"D2b の見積書がありません（D2b を先に作る）：{missing}")
    # D2b の見積が回答表と合うか（H-02・H-03。千円）
    for key, want in (("つばさ台フードシステム", 22_500), ("ほしみ機工", 24_100)):
        subtotal, _, _ = d2b.quote_totals(d2b.QUOTES[key]["items"])
        if subtotal != want * 1000:
            sys.exit(f"{key} の見積の小計 {subtotal:,}円が、回答表の {want:,}千円と合いません")

    for folder in (MATERIAL_DIR, ORIGINAL_DIR):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)

    # きれいな PDF を描く
    rough_pdf = ORIGINAL_DIR / f"見積書_つばさ台フードシステム_概算_{ROUGH_QUOTE['date'].isoformat()}.pdf"
    delivery_pdf = ORIGINAL_DIR / f"納品書_みつばね食品資材_{DELIVERY_NOTE['date'].isoformat()}.pdf"
    invoice_pdf = ORIGINAL_DIR / f"請求書_みつばね食品資材_{INVOICE['date'].isoformat()}.pdf"
    d2a.render(rough_pdf, "御見積書・概算（つばさ台フードシステム）", rough_quote_pages())
    d2a.render(delivery_pdf, "納品書（みつばね食品資材）", delivery_note_pages())
    d2a.render(invoice_pdf, "請求書（みつばね食品資材）", invoice_pages())

    # 読みにくくした材料を作る
    make_scan(render_page(sources[0]), MATERIAL_DIR / FILES["tsubasa"], angle=0.5, seed=7001)
    make_photo(render_page(sources[1]), MATERIAL_DIR / FILES["hoshimi"], angle=3.0, keystone=0.06, blur=1.4, dim=70,
               quality=70, seed=7002)
    make_fax(render_page(rough_pdf), MATERIAL_DIR / FILES["rough"], ROUGH_QUOTE["fax_header"], seed=7003)
    make_scan(render_page(delivery_pdf), MATERIAL_DIR / FILES["delivery"], angle=-0.6, seed=7004, upside_down=True)
    invoice = render_page(invoice_pdf)
    invoice = add_stain(invoice, pdf_rect_to_px(HIDDEN_RECT["請求書"]), seed=7005)
    make_photo(invoice, MATERIAL_DIR / FILES["invoice"], angle=-1.8, keystone=0.025, blur=0.8, dim=20, quality=84,
               seed=7006)
    memo_dst = MATERIAL_DIR / FILES["memo"]
    if AUTHOR_PHOTO.is_file():
        strip_author_photo(AUTHOR_PHOTO, AUTHOR_MEMO)
        print(f"作者の写真（{AUTHOR_PHOTO.relative_to(HERE)}）から EXIF などを落として、{AUTHOR_MEMO.name} に保存し直しました"
              "（元の写真は Git の外です）")
    if AUTHOR_MEMO.is_file():
        left = photo_leftovers(AUTHOR_MEMO)
        if left:
            sys.exit(f"{AUTHOR_MEMO.name} に {left} が残っています。元の写真を 作者の写真/経費のメモ.jpg に置いて流し直してください")
        shutil.copyfile(AUTHOR_MEMO, memo_dst)
        print(f"経費のメモは、作者が撮った写真（{AUTHOR_MEMO.name}）を使いました")
    else:
        make_photo(draw_memo(), memo_dst, angle=-2.4, keystone=0.03, blur=0.7, dim=25, quality=85, seed=7007)

    answer, expense = answers()
    for path, data in ((ANSWER, answer), (EXPENSE_ANSWER, expense)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    for path in sorted(ORIGINAL_DIR.iterdir()) + sorted(MATERIAL_DIR.iterdir()) + [ANSWER, EXPENSE_ANSWER]:
        print(f"{path.relative_to(HERE)}  {path.stat().st_size:,} バイト")


if __name__ == "__main__":
    build()
