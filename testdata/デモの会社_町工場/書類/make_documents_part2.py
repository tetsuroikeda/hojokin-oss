# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の書類の後半を PDF で作る。

作るもの：見積依頼書、要件の概要、見積書2通（かすみ野システム工房・しらうめソフト）と、
デモの不備/ の3通（期限切れの古い見積書、「一式」で宛名を誤った見積書、交付決定の前の注文書）。
数字と事実は testdata/デモの会社_町工場/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
ID のない数字は回答表にないもので、書類の一覧.md に挙げた。

PDF の描き方は make_documents.py のものを使う。どのページにも「架空のテスト用データ」の帯と足を付ける。
見積を出した会社の所在地は架空とし、電話番号とインボイスの登録番号は書かない。

動かし方：uv run --script testdata/デモの会社_町工場/書類/make_documents_part2.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.lib.colors import Color, black  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402

from make_documents import (  # noqa: E402
    ADDRESS,
    COMPANY,
    GOTHIC,
    LEFT,
    MINCHO,
    POSTAL_CODE,
    PRESIDENT,
    RIGHT,
    Page,
    render,
)

OUT_DIR = Path(__file__).resolve().parent
DEFECT_DIR = OUT_DIR / "デモの不備"

TAX_RATE = 10
KASUMINO = "株式会社かすみ野システム工房"  # H-03
SHIRAUME = "株式会社しらうめソフト"  # H-03
REQUEST_DATE = "2026年10月15日"  # L-19
QUOTE_DATE = "2026年10月26日"  # H-04
QUOTE_VALID_UNTIL = "2027年1月31日"  # H-04
SUBJECT = "見積と工程の仕組み（受注・見積・工程・進捗の管理と AI）の開発"
EMAIL = "info@example.com"  # A-13
PHONE = "03-0000-0000"  # A-15（架空の番号）

# ---------------------------------------------------------------------------
# 見積書の明細。(項目, 数量, 単位, 単価（円・税抜）)。数量は人月・台・か月
# ---------------------------------------------------------------------------

# かすみ野システム工房（H-02 の項目と金額のとおり）
KASUMINO_SYSTEM = [
    ("要件定義・業務の分析", "1.5", "人月", 1_200_000),
    ("設計", "2.5", "人月", 1_100_000),
    ("受注・見積の機能", "3.0", "人月", 1_000_000),
    ("工程・進捗の機能", "3.0", "人月", 1_000_000),
    ("見積の AI（図面の読み取り・似た部品の検索・見積の案）", "3.5", "人月", 1_100_000),
    ("工程と問い合わせの AI", "1.5", "人月", 1_100_000),
    ("会計ソフトと CAM との連携", "1.0", "人月", 1_000_000),
    ("試験", "0.9", "人月", 1_000_000),
    ("プロジェクトの管理", "1.25", "人月", 1_000_000),
    ("機械の稼働を取るセンサー", "10", "台", 120_000),
    ("工程の着手と完了を読む専用の読み取り端末", "4", "台", 150_000),
]
KASUMINO_CLOUD = [("クラウドの利用料（AI の利用料とサーバー）", "8", "か月", 150_000)]
KASUMINO_EXPLAIN = [
    "業務の流れ（引き合い・見積・受注・工程・加工・検査・出荷）の聞き取りと、要件の取りまとめ。",
    "画面・データ・AI の処理の流れ・クラウドの構成の設計。",
    "引き合いと見積の台帳、見積書の作成、受注の登録。過去の見積と図面を取り込む仕組みを含む（取り込む作業は御社）。",
    "工程表、作業指示、機械ごとの負荷の表示、進捗と実績の記録、注文ごとの原価の集計。",
    "図面（PDF）とメールを読み、形・寸法・精度・材料を拾い、過去の似た部品と機械の時間から、工程・時間・値段の案を作る。",
    "翌日の段取りの案と、納期の問い合わせへの返事の下書きを作る。",
    "会計ソフトへの売上・仕入のデータの受け渡しと、CAM のデータ（加工の時間）の取り込み。",
    "機能の試験、過去の図面を使った AI の精度の確かめ、納める前の弱いところの確かめ（脆弱性の確認）。",
    "日程と課題の管理、打ち合わせ、導入時の操作説明の準備。",
    "機械の稼働を取るセンサー。機械に取り付け、電気は機械から取る。",
    "工程の着手と完了を読み取る専用の端末。工場の中に置く。",
    "AI の利用料とサーバー。読ませたデータを学習に使わない契約の国内のクラウド。使い始めから8か月分。",
]

# しらうめソフト（回答表は合計 25,040千円だけ。人月と単価は決めた）
SHIRAUME_SYSTEM = [
    ("要件定義・業務分析", "1.6", "人月", 1_250_000),
    ("基本設計・詳細設計", "2.8", "人月", 1_150_000),
    ("受注・見積管理機能", "3.2", "人月", 1_050_000),
    ("工程・進捗管理機能", "3.2", "人月", 1_050_000),
    ("AI見積支援（図面読取・類似部品検索・見積案）", "3.8", "人月", 1_150_000),
    ("AI工程計画・問い合わせ回答支援", "1.6", "人月", 1_150_000),
    ("外部連携（会計ソフト・CAM）", "1.0", "人月", 1_050_000),
    ("総合試験（脆弱性診断を含む）", "1.0", "人月", 1_050_000),
    ("プロジェクト管理", "1.2", "人月", 1_050_000),
    ("稼働監視センサー", "10", "台", 145_000),
    ("工程実績読み取り端末", "4", "台", 160_000),
]
SHIRAUME_CLOUD = [("クラウド利用料（AI 利用料・サーバー）", "8", "か月", 180_000)]
SHIRAUME_EXPLAIN = [
    "現行業務の調査、要件定義書の作成。",
    "画面設計、データ設計、AI 処理の設計、クラウド構成の設計。",
    "引合・見積台帳、見積書発行、受注登録。過去の見積・図面データの取込機能を含む（取込作業は御社）。",
    "工程計画、作業指示、負荷表示、進捗・実績の記録、注文別原価の集計。",
    "図面・メールの読取、類似部品の検索、工程・加工時間・見積金額の案の作成。",
    "翌日の段取り案の作成、納期問い合わせへの回答文案の作成。",
    "会計ソフトとのデータ連携、CAM の加工時間データの取込。",
    "結合試験、総合試験、AI の精度確認、脆弱性診断。",
    "進捗・課題の管理、定例会、導入時の操作説明の準備。",
    "稼働監視センサー（機械に取付。電源は機械から取る）。",
    "工程の着手・完了を読み取る専用端末。",
    "AI 利用料とサーバー（入力データを学習に使わない国内のクラウド）。利用開始から8か月分。",
]

COMMON_NOTES = [
    "金額は消費税抜きで表示し、消費税（10%）は下に分けて記しました。",
    "開発の期間：ご発注から約8か月（要件定義と設計 約4か月、開発と試験 約3か月、試しの運用 約1か月）。",  # H-07
    "工事は要りません。センサーは機械に取り付け、電気は機械から取ります。社内のネットの線は今のものを使います。",  # H-08
    "研修：導入時の操作説明（社長・工場長・事務・営業の4人。費用は各機能の開発に含む）。",  # L-20
    "保守：別契約（本見積に含まない）。",  # L-11
    "過去の見積と図面を取り込む仕組みは、受注・見積の機能に含みます。取り込む作業は御社で行います。",  # L-12
    "図面のデータは、読ませたデータを学習に使わない契約の、国内のクラウドだけで扱います。",  # L-14
]

# ---------------------------------------------------------------------------
# デモの不備（回答表にない。書類の一覧.md の「デモの不備」に挙げた）
# ---------------------------------------------------------------------------

# かすみ野の前の版（2026年4月に社長が相談したときのもの）。AI と試験の人月、センサーの台数、クラウドの月数が違う
OLD_KASUMINO_SYSTEM = [
    ("要件定義・業務の分析", "1.5", "人月", 1_200_000),
    ("設計", "2.5", "人月", 1_100_000),
    ("受注・見積の機能", "3.0", "人月", 1_000_000),
    ("工程・進捗の機能", "3.0", "人月", 1_000_000),
    ("見積の AI（図面の読み取り・似た部品の検索・見積の案）", "3.0", "人月", 1_100_000),
    ("工程と問い合わせの AI", "1.0", "人月", 1_100_000),
    ("会計ソフトと CAM との連携", "1.0", "人月", 1_000_000),
    ("試験", "0.8", "人月", 1_000_000),
    ("プロジェクトの管理", "1.2", "人月", 1_000_000),
    ("機械の稼働を取るセンサー", "8", "台", 120_000),
    ("工程の着手と完了を読む専用の読み取り端末", "4", "台", 150_000),
]
OLD_KASUMINO_CLOUD = [("クラウドの利用料（AI の利用料とサーバー）", "6", "か月", 150_000)]

# しらうめの「一式」の見積（積算の根拠がない。宛名の社名が違う）
LUMP_SYSTEM = [("システム開発一式", "1", "式", 23_600_000)]
LUMP_CLOUD = [("クラウド利用料一式", "1", "式", 1_440_000)]
WRONG_ADDRESSEE = "株式会社みずなら精機"

# 交付決定の前の注文書
ORDER_DATE = "2026年11月2日"
ORDER_ITEM = ("見積の AI の試しの開発（図面の読み取りの部分）", "1", "式", 1_500_000)


def line_amount(qty: str, price: int) -> int:
    value = Decimal(qty) * price
    if value != value.to_integral_value():
        raise ValueError(f"数量 {qty} × 単価 {price} が円で割り切れません")
    return int(value)


def section_total(items: list[tuple]) -> int:
    return sum(line_amount(q, p) for _, q, _, p in items)


def yen(v: int) -> str:
    return f"{v:,}"


def fit(c, text: str, font: str, size: float, width: float) -> float:
    """幅に収まるまで文字を小さくする。"""
    while size > 6 and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 0.2
    return size


# ---------------------------------------------------------------------------
# 見積書
# ---------------------------------------------------------------------------


def quote(
    *,
    issuer: str,
    number: str,
    date: str,
    valid_until: str,
    addressee: str,
    system: list[tuple],
    cloud: list[tuple],
    explain: list[str] | None,
    notes: list[str],
    style: str,
    subject: str = SUBJECT,
    previous: bool = False,
) -> list:
    sub1 = section_total(system)
    sub2 = section_total(cloud)
    net = sub1 + sub2
    tax = net * TAX_RATE // 100
    grand = net + tax
    kasumino = style == "kasumino"
    fill = Color(0.86, 0.93, 0.88) if kasumino else Color(0.9, 0.9, 0.9)
    widths = [22, 214, 40, 32, 76, 91]

    def page1(pg: Page) -> None:
        c = pg.c
        pg.title("御見積書" if kasumino else "見　積　書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, f"見積番号　{number}")
        c.drawRightString(RIGHT, pg.y + 5, f"発行日　{date}")
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{addressee}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        c.setFont(MINCHO, 10)
        c.drawString(LEFT, pg.y - 32, f"代表取締役　{PRESIDENT}　様")
        x = LEFT + 300
        c.setFont(GOTHIC, 11)
        c.drawString(x, pg.y - 12, issuer)
        c.setFont(MINCHO, 9)
        c.drawString(x, pg.y - 27, "〒000-0000　架空の所在地（テスト用）")
        c.drawString(x, pg.y - 40, "システム開発部" if kasumino else "営業本部")
        pg.y -= 62
        pg.para("下記のとおり、お見積り申し上げます。", size=10)
        pg.kv("件名", subject, key_width=110)
        pg.kv("見積金額（税込）", f"{yen(grand)}円", key_width=110)
        pg.kv("有効期限", valid_until, key_width=110)
        if previous:
            pg.kv("版", "第1版（ご相談の時点の概算）", key_width=110)
        pg.gap(4)
        size = 8.4
        h = size + 9

        def cells(values: list[str], *, header: bool = False, bold: bool = False, shade: bool = False) -> None:
            xx = LEFT
            for i, (cell, w) in enumerate(zip(values, widths)):
                if header or shade:
                    c.setFillColor(fill)
                    c.rect(xx, pg.y - 5, w, h, fill=1, stroke=1)
                    c.setFillColor(black)
                else:
                    c.rect(xx, pg.y - 5, w, h, fill=0, stroke=1)
                font = GOTHIC if (header or bold) else MINCHO
                s = fit(c, cell, font, size, w - 8)
                c.setFont(font, s)
                if header or i in (1, 3):
                    c.drawString(xx + 4, pg.y, cell)
                else:
                    c.drawRightString(xx + w - 4, pg.y, cell)
                xx += w
            pg.y -= h

        def label_row(label: str, value: int) -> None:
            label_w = sum(widths[:-1])
            c.rect(LEFT, pg.y - 5, label_w, h, fill=0, stroke=1)
            c.rect(LEFT + label_w, pg.y - 5, widths[-1], h, fill=0, stroke=1)
            c.setFont(GOTHIC, size)
            c.drawRightString(LEFT + label_w - 6, pg.y, label)
            c.drawRightString(LEFT + label_w + widths[-1] - 4, pg.y, yen(value))
            pg.y -= h

        def section_row(label: str) -> None:
            c.setFillColor(Color(0.97, 0.97, 0.97))
            c.rect(LEFT, pg.y - 5, sum(widths), h, fill=1, stroke=1)
            c.setFillColor(black)
            c.setFont(GOTHIC, size)
            c.drawString(LEFT + 4, pg.y, label)
            pg.y -= h

        cells(["No.", "項目", "数量", "単位", "単価（税抜）", "金額（税抜）"], header=True)
        no = 1
        section_row("Ⅰ　機械装置・システム構築費")
        for name, qty, unit, price in system:
            cells([str(no), name, qty, unit, yen(price), yen(line_amount(qty, price))])
            no += 1
        label_row("小計（機械装置・システム構築費）", sub1)
        section_row("Ⅱ　クラウドの利用料")
        for name, qty, unit, price in cloud:
            cells([str(no), name, qty, unit, yen(price), yen(line_amount(qty, price))])
            no += 1
        label_row("小計（クラウドの利用料）", sub2)
        label_row("合計（税抜）", net)
        label_row(f"消費税（{TAX_RATE}%）", tax)
        label_row("合計（税込）", grand)
        pg.gap(6)
        c.setFont(MINCHO, 8.5)
        c.drawString(LEFT, pg.y, "人月：1人が1か月かけて行う作業の量。単価は1人月あたりの金額です。" if explain else "")
        pg.y -= 14

    def page2(pg: Page) -> None:
        pg.title("見積の内訳の説明と備考", 13)
        if explain:
            pg.heading("内訳の説明", 10.5)
            all_items = system + cloud
            for i, (item, text) in enumerate(zip(all_items, explain), start=1):
                pg.para(f"{i}．{item[0]}", indent=1, size=9, font=GOTHIC)
                pg.para(text, indent=2, size=9)
            pg.gap(6)
        pg.heading("備考", 10.5)
        for note in notes:
            pg.para(f"・{note}", indent=1, size=9)

    return [page1, page2]


def kasumino_quote() -> list:
    return quote(
        issuer=KASUMINO,
        number="KSK-2610-0087",
        date=QUOTE_DATE,
        valid_until=QUOTE_VALID_UNTIL,
        addressee=COMPANY,
        system=KASUMINO_SYSTEM,
        cloud=KASUMINO_CLOUD,
        explain=KASUMINO_EXPLAIN,
        notes=COMMON_NOTES + ["2026年10月15日付けの見積依頼書と要件の概要に基づいて積算しました。"],  # L-19
        style="kasumino",
    )


def shiraume_quote() -> list:
    return quote(
        issuer=SHIRAUME,
        number="SU-20261026-112",
        date=QUOTE_DATE,
        valid_until=QUOTE_VALID_UNTIL,
        addressee=COMPANY,
        system=SHIRAUME_SYSTEM,
        cloud=SHIRAUME_CLOUD,
        explain=SHIRAUME_EXPLAIN,
        notes=COMMON_NOTES + ["2026年10月15日付けの見積依頼書と要件の概要に基づいて積算しました。"],  # L-19
        style="shiraume",
    )


def old_kasumino_quote() -> list:
    return quote(
        issuer=KASUMINO,
        number="KSK-2604-0021",
        date="2026年4月10日",
        valid_until="2026年7月31日",
        addressee=COMPANY,
        system=OLD_KASUMINO_SYSTEM,
        cloud=OLD_KASUMINO_CLOUD,
        explain=KASUMINO_EXPLAIN[:11] + ["AI の利用料とサーバー。使い始めから6か月分。"],
        notes=[
            "金額は消費税抜きで表示し、消費税（10%）は下に分けて記しました。",
            "ご相談の時点の概算です。要件が決まりましたら、改めてお見積りします。",
            "保守：別契約（本見積に含まない）。",
        ],
        style="kasumino",
        previous=True,
    )


def lump_quote() -> list:
    return quote(
        issuer=SHIRAUME,
        number="SU-20261020-098",
        date="2026年10月20日",
        valid_until=QUOTE_VALID_UNTIL,
        addressee=WRONG_ADDRESSEE,
        system=LUMP_SYSTEM,
        cloud=LUMP_CLOUD,
        explain=None,
        notes=[
            "金額は消費税抜きで表示し、消費税（10%）は下に分けて記しました。",
            "詳細はご発注の後に打ち合わせのうえ決めます。",
        ],
        style="shiraume",
    )


# ---------------------------------------------------------------------------
# 注文書（交付決定の前の発注。デモの不備）
# ---------------------------------------------------------------------------


def order_form() -> list:
    name, qty, unit, price = ORDER_ITEM
    amount = line_amount(qty, price)
    tax = amount * TAX_RATE // 100

    def page1(pg: Page) -> None:
        c = pg.c
        pg.title("注　文　書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 18, "注文番号　MZ-2611-001")
        c.drawRightString(RIGHT, pg.y + 5, f"注文日　{ORDER_DATE}")
        c.setFont(GOTHIC, 13)
        c.drawString(LEFT, pg.y - 12, f"{KASUMINO}　御中")
        c.line(LEFT, pg.y - 16, LEFT + 260, pg.y - 16)
        x = LEFT + 270
        c.setFont(GOTHIC, 11)
        c.drawString(x, pg.y - 12, COMPANY)
        c.setFont(MINCHO, 9)
        c.drawString(x, pg.y - 27, f"〒{POSTAL_CODE}　{ADDRESS}")
        c.drawString(x, pg.y - 40, f"代表取締役　{PRESIDENT}")
        pg.y -= 62
        pg.para("下記のとおり注文します。", size=10)
        pg.gap(4)
        rows = [
            ["品名", "数量", "単価（税抜）", "金額（税抜）"],
            [name, f"{qty}{unit}", yen(price), yen(amount)],
            ["消費税（10%）", "", "", yen(tax)],
            ["合計（税込）", "", "", yen(amount + tax)],
        ]
        pg.table(rows, [255, 50, 80, 90], size=9)
        pg.kv("納期", "2026年12月25日", key_width=110)
        pg.kv("納める物", "図面（PDF）から形・寸法・材料を読み取る試しのプログラムと、その結果の報告", key_width=110)
        pg.kv("支払い", "納品の翌月末に振り込み", key_width=110)
        pg.kv("見積", "2026年10月26日付けの御見積書（KSK-2610-0087）とは別に、口頭で決めた金額", key_width=110)
        pg.gap(8)
        pg.para("（架空のテスト用データ。印はありません）", size=9)

    return [page1]


# ---------------------------------------------------------------------------
# 見積依頼書
# ---------------------------------------------------------------------------


def request_for_quote() -> list:
    def page1(pg: Page) -> None:
        c = pg.c
        pg.title("見積依頼書", 18)
        c.setFont(MINCHO, 9.5)
        c.drawRightString(RIGHT, pg.y + 5, f"{REQUEST_DATE}")
        pg.gap(4)
        c.setFont(GOTHIC, 11)
        c.drawString(LEFT, pg.y, f"{KASUMINO}　御中")
        c.drawString(LEFT, pg.y - 16, f"{SHIRAUME}　御中")
        x = LEFT + 270
        c.setFont(GOTHIC, 11)
        c.drawString(x, pg.y - 32, COMPANY)
        c.setFont(MINCHO, 9)
        c.drawString(x, pg.y - 46, f"〒{POSTAL_CODE}　{ADDRESS}")
        c.drawString(x, pg.y - 59, f"代表取締役　{PRESIDENT}")
        pg.y -= 84
        pg.para("下記の仕組みの開発について、お見積りをお願いします。同じ内容で2社にお願いしています。", size=10)  # L-19
        pg.gap(4)
        pg.kv("件名", SUBJECT, key_width=120)
        pg.kv("要件", f"別紙「要件の概要」（{REQUEST_DATE}）のとおり", key_width=120)
        pg.kv(
            "見積に入れるもの",
            "要件定義・業務の分析、設計、受注・見積の機能、工程・進捗の機能、見積の AI、工程と問い合わせの AI、"
            "会計ソフトと CAM との連携、試験、プロジェクトの管理、機械の稼働を取るセンサー（10台）、"
            "工程の着手と完了を読む専用の読み取り端末（4台）、クラウドの利用料（使い始めから8か月分）",
            key_width=120,
        )
        pg.kv("見積に入れないもの", "保守（別の契約で決めます）、社内のネットの工事（今のものを使います）", key_width=120)
        pg.kv(
            "見積の書き方",
            "項目ごとに「数量（人月・台・か月）× 単価 ＝ 金額」で積み上げてください。「一式」だけの書き方は避けてください。"
            "税抜の金額と消費税を分けて書いてください。研修（操作の説明）の費用の扱いも書いてください。",
            key_width=120,
        )
        pg.kv("宛名", f"{COMPANY}　代表取締役 {PRESIDENT}", key_width=120)
        pg.kv("提出の期限", "2026年10月30日", key_width=120)
        pg.kv("見積の有効期限", "2027年1月31日まで有効としてください", key_width=120)
        pg.kv("発注の予定", "2027年7月ごろ（補助金の交付決定を受けた後に、見積を取り直して発注する予定です）", key_width=120)  # L-10
        pg.kv("問い合わせ先", f"代表取締役 {PRESIDENT}　メール {EMAIL}　電話 {PHONE}（架空）", key_width=120)
        pg.gap(6)
        pg.para("・お預けする図面の例は、見積のためだけに使い、終わったら消してください。", size=9)  # K-05
        pg.para("・この依頼の内容を、ほかの目的に使わないでください。", size=9)

    return [page1]


# ---------------------------------------------------------------------------
# 要件の概要（仕様書の概要）
# ---------------------------------------------------------------------------

REQUIREMENTS = [
    (
        "1．目的",
        [
            "見積が社長と工場長の2人に集まり、返事に平均4日（営業日）かかって、他社に決まってしまう引き合いが月に約10件ある。"  # G-06
            "見積の下書きを AI に作らせ、返事を1日以内にする。",  # H-10
            "受注から工程・出荷までを1つの仕組みで見えるようにし、工程の組み直しと問い合わせの手間を減らす。",  # H-01
            "工場長が引退する前に、見積の考え方を会社のデータとして残す。",  # K-01
        ],
    ),
    (
        "2．今の業務と仕組み",
        [
            "客がメールで図面（PDF。一部は3次元のデータ）を送って見積を頼む → 見積を返す → 注文書が来る → 加工 → 検査 → 出荷。",  # E-05
            "見積は月に約120件、品番は月に約250（うち初めての図面が約70）。注文になるのは約3割。",  # E-06、E-04
            "見積は社長が作った Excel の表で計算している。受注と工程は Excel・ホワイトボード・紙の作業指示書。日報は紙。会計は市販の会計ソフト。",  # G-03
            "機械：マシニングセンタ5台（うち5軸が1台）、NC旋盤4台、複合加工機1台、三次元測定機1台。CAM のソフトが2本。",  # G-02
            "市販の生産管理のソフトを2つ試したが、機械ごとの時間の単価・段取りの時間・材料の取り方が合わなかった。",  # L-18
        ],
    ),
    (
        "3．作る機能",
        [
            "受注・見積の機能：引き合いと見積の台帳、見積書の作成と送る前の確かめ、受注の登録。過去の見積と図面を取り込む仕組みを含む。",
            "工程・進捗の機能：工程表、作業指示、機械ごとの負荷の表示、急ぎの割り込みのときの組み直し、進捗と実績の記録。",
            "原価の集計：注文ごとの材料・外注・機械の時間を集め、見積と実際を比べられるようにする。",  # L-05
            "どの機能も、社長・工場長・事務・営業の4人が、事務所と工場の端末から使う。",  # L-20
        ],
    ),
    (
        "4．AI の3つの役目",
        [
            "(1) 見積の案：図面とメールを読み、形・寸法・精度・材料を拾い、過去の似た部品と機械の時間から、工程・時間・値段の案を作る。",  # H-01
            "(2) 翌日の段取りの案：受注・進捗・機械の稼働から、翌日の段取りの案を作る。",
            "(3) 問い合わせの返事の下書き：納期の問い合わせ（1日に約12件）に、進捗から返事の下書きを作る。",  # L-02
        ],
    ),
    (
        "5．AI に任せないこと",
        [
            "値段を決めること、検査の合否、客へ送ること。AI の案は、社長か工場長が確かめてから使う。",  # L-04
            "AI の案と、実際に決めた値段の違いを残し、AI の見直しに使えるようにする。",  # L-04
        ],
    ),
    (
        "6．データの守り方",
        [
            "客の図面は秘密のもの。AI に読ませるのは、読ませたデータを AI の学習に使わない契約の、国内のクラウドだけにする。",  # L-14
            "使う人ごとにアカウントを分け、図面を見られる人を決められるようにする。",
            "納める前に、弱いところがないか（脆弱性）を確かめる。試験に含める。",  # L-14
        ],
    ),
    (
        "7．センサーと読み取り端末",
        [
            "機械の稼働を取るセンサー10台。機械に取り付け、電気は機械から取る。工事はしない。",  # H-02、H-08
            "工程の着手と完了を読む専用の読み取り端末4台。社内のネットの線は今のものを使う。",  # H-02、H-08
            "日報は端末とセンサーで集め、紙の日報をやめる。",  # L-03
        ],
    ),
    (
        "8．ほかの仕組みとの連携",
        [
            "会計ソフト：売上と仕入のデータを受け渡す。",
            "CAM：加工の時間のデータを取り込み、見積と工程に使う。",
        ],
    ),
    (
        "9．過去のデータの取り込み",
        [
            "過去8年の見積約9,000件とその図面を、AI が似た部品を探せる形で取り込む。",  # L-12
            "取り込む仕組みは開発に含める。取り込む作業は、当社の事務が2027年11月〜2028年1月に行う。",  # L-12
        ],
    ),
    (
        "10．試験と研修",
        [
            "機能の試験に加え、過去の図面を使って AI の案の精度を確かめる。",
            "本番の前に、社長・工場長・事務・営業の4人に使い方を教える（研修の費用は開発に含める）。",  # L-20
            "本番の前の1か月は、今のやり方と並べて試しに動かす。",  # L-10
        ],
    ),
    (
        "11．日程",
        [
            "発注は2027年7月ごろの予定（補助金の交付決定の後）。発注から約8か月で本番にする。",  # L-10、H-07
            "2027年7〜10月 要件定義と設計（約4か月）／11月〜2028年1月 作るのと試験（約3か月）／2月 試しの運用（約1か月）／3月 本番。",  # L-10、H-07
            "クラウドは2027年8月から使い始める（2028年3月まで8か月分を見積に入れる）。",  # L-10、H-02
        ],
    ),
    (
        "12．保守",
        [
            "本番の後の保守は、別に契約する（5年を考えている）。保守の費用は、この見積に入れない。",  # L-11
            "事業が終わった後の AI の利用料とサーバーは、当社が払う。",  # L-11
        ],
    ),
    (
        "13．見積の出し方",
        [
            "別紙の見積依頼書のとおり、項目ごとに「数量（人月・台・か月）× 単価」で積み上げる。",
        ],
    ),
]


def requirements_overview() -> list:
    # 節を、ページにほぼ等しく分ける（3ページ）
    groups = [REQUIREMENTS[0:4], REQUIREMENTS[4:9], REQUIREMENTS[9:]]

    def first(pg: Page) -> None:
        pg.title("要件の概要", 18)
        pg.center(f"件名：{SUBJECT}", 10)
        pg.right(f"{REQUEST_DATE}　{COMPANY}")
        pg.gap(4)
        body(pg, groups[0])

    def body(pg: Page, sections: list) -> None:
        for heading, items in sections:
            pg.heading(heading, 11)
            for item in items:
                pg.para(f"・{item}", indent=1, size=9.5)
            pg.gap(6)

    def make(i: int):
        def draw(pg: Page) -> None:
            pg.title(f"要件の概要（{i + 1}）", 12)
            body(pg, groups[i])

        return draw

    return [first, make(1), make(2)]


# ---------------------------------------------------------------------------

PDF_DOCUMENTS = [
    (OUT_DIR / "見積依頼書.pdf", "見積依頼書", request_for_quote),
    (OUT_DIR / "要件の概要.pdf", "要件の概要", requirements_overview),
    (OUT_DIR / "見積書_かすみ野システム工房.pdf", "御見積書（かすみ野システム工房）", kasumino_quote),
    (OUT_DIR / "見積書_しらうめソフト.pdf", "見積書（しらうめソフト）", shiraume_quote),
    (DEFECT_DIR / "見積書_かすみ野システム工房_旧.pdf", "御見積書（かすみ野システム工房・旧）", old_kasumino_quote),
    (DEFECT_DIR / "見積書_しらうめソフト_一式.pdf", "見積書（しらうめソフト・一式）", lump_quote),
    (DEFECT_DIR / "注文書_試しの開発.pdf", "注文書（試しの開発）", order_form),
]


def main() -> None:
    # 見積の小計と合計が、回答表（H-02・H-03）と合うか（円）
    for system, cloud, sub1, net in (
        (KASUMINO_SYSTEM, KASUMINO_CLOUD, 21_000_000, 22_200_000),
        (SHIRAUME_SYSTEM, SHIRAUME_CLOUD, 23_600_000, 25_040_000),
        (LUMP_SYSTEM, LUMP_CLOUD, 23_600_000, 25_040_000),
    ):
        if section_total(system) != sub1 or section_total(system) + section_total(cloud) != net:
            raise ValueError(f"見積の小計 {section_total(system):,}円・合計が、回答表と合いません")
    if len(KASUMINO_EXPLAIN) != len(KASUMINO_SYSTEM) + len(KASUMINO_CLOUD):
        raise ValueError("かすみ野の内訳の説明の数が、明細の行の数と合いません")
    if len(SHIRAUME_EXPLAIN) != len(SHIRAUME_SYSTEM) + len(SHIRAUME_CLOUD):
        raise ValueError("しらうめの内訳の説明の数が、明細の行の数と合いません")
    DEFECT_DIR.mkdir(exist_ok=True)
    for path, doc_name, build in PDF_DOCUMENTS:
        render(path, doc_name, build())
        print(f"作った：{path.relative_to(OUT_DIR)}")


if __name__ == "__main__":
    main()
