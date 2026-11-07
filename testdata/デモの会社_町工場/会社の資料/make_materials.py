# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の会社の資料を作る。

作るもの：会社案内（PDF・2ページ）、話し合いの議事録（Word）、客の図面の例（PDF・1ページ）。
数字と事実は testdata/デモの会社_町工場/回答表.md に合わせる（行ごとに回答表の ID を添えた）。
回答表にない事実は、資料の一覧.md に挙げた。議事録には、議事録にしか出てこない事実を1つ入れた。

PDF・Word の描き方は ../書類/make_documents.py のものを使う。どのページにも「架空のテスト用データ」を出す。

動かし方：uv run --script testdata/デモの会社_町工場/会社の資料/make_materials.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "書類"))

from docx.shared import Pt  # noqa: E402
from reportlab.lib.colors import Color, black  # noqa: E402

from make_documents import (  # noqa: E402
    ADDRESS,
    COMPANY,
    COMPANY_KANA,
    GOTHIC,
    LEFT,
    MINCHO,
    PAGE_W,
    POSTAL_CODE,
    PRESIDENT,
    RIGHT,
    WORKERS,
    Page,
    add_table,
    new_document,
    normalize_office,
    render,
)

# 議事録に出る人（労働者名簿の人と同じ名前）
CHIEF = next(w[0] for w in WORKERS if w[8] == "工場長")
CLERK = next(w[0] for w in WORKERS if w[8] == "事務")
SALES = next(w[0] for w in WORKERS if w[8] == "営業")

# ---------------------------------------------------------------------------
# 会社案内（2ページ）
# ---------------------------------------------------------------------------


def company_profile() -> list:
    def page1(pg: Page) -> None:
        c = pg.c
        c.setFillColor(Color(0.16, 0.3, 0.45))
        c.rect(LEFT - 20, pg.y - 46, RIGHT - LEFT + 40, 66, fill=1, stroke=0)
        c.setFillColor(Color(1, 1, 1))
        c.setFont(GOTHIC, 22)
        c.drawCentredString(PAGE_W / 2, pg.y - 8, COMPANY)
        c.setFont(GOTHIC, 10.5)
        c.drawCentredString(PAGE_W / 2, pg.y - 30, "1個から、精度と納期を守る切削加工")  # K-03、E-03
        c.setFillColor(black)
        pg.y -= 72
        pg.center("会社案内", 12)
        pg.gap(6)
        pg.heading("ごあいさつ")
        pg.para(
            "当社は、金属の部品を削って作る町工場です。半導体の製造装置、産業用ロボット・工作機械、"
            "医療機器の部品を、試作と小ロット（1個から50個くらい）を中心に作っています。"  # A-11、A-12
            "1個からでも断らないこと、精度と納期を守ることを大事にしています。",  # K-03
            indent=1,
        )
        pg.para(f"代表取締役　{PRESIDENT}", indent=1, font=GOTHIC)
        pg.gap(6)
        pg.heading("会社の概要")
        for key, value in (
            ("社名", f"{COMPANY}（{COMPANY_KANA}）"),  # A-01、A-02
            ("代表者", f"代表取締役　{PRESIDENT}"),  # A-08
            ("創業", "1974年（個人で旋盤の加工を始める）"),  # A-05
            ("設立", "1990年4月2日"),  # A-04
            ("資本金", "2,000万円"),  # A-06
            ("従業員", "18人（正社員16人、パート2人）"),  # C-01
            ("所在地", f"〒{POSTAL_CODE}　{ADDRESS}（本店・工場）"),  # B-01、B-02
            ("工場", "延べ床面積 約620㎡。事務所は工場の2階"),  # G-01
            ("電話", "03-0000-0000（架空の番号）"),  # A-15
            ("サイト・メール", "https://www.example.com/　info@example.com"),  # A-13
            ("事業の内容", "金属部品の切削加工（アルミ・ステンレス・チタン）。試作と小ロット"),  # A-11、E-03
        ):
            pg.kv(key, value, key_width=110, size=9.5)
        pg.gap(6)
        pg.heading("沿革")
        for year, text in (
            ("1974年", "先代（今の社長の父）が、個人で旋盤の加工を始める"),  # A-05
            ("1990年", "株式会社として設立する（4月2日）"),  # A-04、A-05
            ("2016年", f"{PRESIDENT}が代表取締役を継ぐ"),  # A-05
        ):
            pg.kv(year, text, key_width=110, size=9.5)

    def page2(pg: Page) -> None:
        pg.title("製品と技術", 14)
        pg.heading("主な製品")
        for text in (
            "半導体の製造装置の部品",
            "産業用ロボット・工作機械の部品",
            "医療機器の部品",
        ):  # A-12
            pg.para(f"・{text}", indent=1)
        pg.para("試作と小ロット（1個から50個くらい）が中心です。", indent=1)  # A-12
        pg.gap(6)
        pg.heading("当社の強み")
        for text in (
            "アルミ・ステンレス・チタンの難しい形の部品を、1個から短い納期で作れます。",  # E-03
            "1000分の1ミリ単位の精度に応えます。",  # E-03
            "三次元測定機で測った検査の成績書を、出荷する部品に付けます。",  # E-03、E-08
        ):
            pg.para(f"・{text}", indent=1)
        pg.gap(6)
        pg.heading("主な設備")
        pg.table(
            [
                ["設備", "台数"],
                ["マシニングセンタ（うち5軸 1台）", "5台"],  # G-02
                ["NC旋盤", "4台"],
                ["複合加工機", "1台"],
                ["三次元測定機", "1台"],
                ["CAM のソフト", "2本"],
            ],
            [330, 145],
        )
        pg.heading("お取引先の業界")
        pg.para(
            "半導体の製造装置のメーカー、産業用ロボットや工作機械のメーカー、医療機器のメーカーなど、"
            "1年に約60社とお取引があります。",  # E-01
            indent=1,
        )
        pg.gap(6)
        pg.heading("ご注文の流れ")
        pg.para(
            "図面（PDF。3次元のデータも可）をメールでお送りください → お見積り → ご注文 → 加工 → 検査 → 出荷。"
            "納期は平均で2〜3週間です。",  # E-05
            indent=1,
        )

    return [page1, page2]


# ---------------------------------------------------------------------------
# 議事録（Word）
# ---------------------------------------------------------------------------

# 議事録にしか出てこない事実：工場長が、見積で迷ったときの決まりを手帳に書きためていること（約200項目）
MINUTES_ONLY_FACT = (
    f"{CHIEF}工場長は、見積で迷ったときの自分の決まり（材料の取り方、段取りの時間の目安、"
    "外注に出すかどうかの線など）を、20年ほど前から手帳に書きためている。いまは約200項目ある。"
)


def minutes(path: Path) -> None:
    doc = new_document("議事録（2026年9月30日）")
    p = doc.add_paragraph()
    run = p.add_run("議事録　見積の困りごとについての話し合い")
    run.font.size = Pt(15)
    run.font.bold = True
    add_table(
        doc,
        [
            ["項目", "内容"],
            ["日時", "2026年9月30日（水）17時〜18時"],
            ["場所", "本社2階の事務所"],
            [
                "出た人",
                f"社長（{PRESIDENT}）、工場長（{CHIEF}）、事務（{CLERK}）、営業（{SALES}）",
            ],
            ["記録", f"{CLERK}"],
        ],
        [30, 140],
        size=9.5,
    )

    def section(title: str, lines: list[str]) -> None:
        h = doc.add_paragraph()
        r = h.add_run(title)
        r.font.bold = True
        r.font.size = Pt(11)
        for line in lines:
            doc.add_paragraph(line, style="List Bullet")

    section(
        "1．見積にかかっている時間（記録の結果）",
        [
            f"{CLERK}さんが、9月に2週間、見積1件ごとの時間を記録した。1件で平均約75分。",  # L-01
            "内訳は、図面を読んで形・寸法・精度・材料を拾うのに約20分、工程と段取りを考えるのに約20分、"
            "材料と外注（めっき・熱処理）の値段を調べるのに約15分、加工の時間を見積もるのに約10分、"
            "見積書を作って送るのに約10分。",  # L-01
            "見積は月に約120件（社長が約70件、工場長が約50件）。月に約150時間かかっている。",  # G-04、L-01
            "見積のほかに、1日あたり、工程の組み直し（急ぎの割り込みのたびに）を工場長が約1.5時間、"
            "納期の問い合わせ（1日に約12件）への返事を社長と事務で約1.5時間、"
            "紙の日報と原価の集計を事務が約1時間かけている。",  # L-02
        ],
    )
    section(
        "2．見積の遅れと、逃している仕事",
        [
            f"{SALES}さんから：見積の返事に、平均で4日（営業日）かかっている。客は2日以内を望んでいる。",  # G-06
            "2025年度は、返事が遅れて他社に決まった引き合いが、月に約10件あった。急ぎの見積は、月に5件ほど断った。",  # L-06
            "見積ができるのが社長と工場長の2人だけなので、人を増やしても回らない。",  # G-06
        ],
    )
    section(
        "3．市販のソフトを試した結果",
        [
            "市販の生産管理のソフトを2つ試したが、うちの見積の出し方（機械ごとの時間の単価、段取りの時間、"
            "材料の取り方）と合わず、Excel に戻った。",  # L-18
            "AI の部分も、うちの過去の見積と機械に合わせないと使えない、という意見でまとまった。",  # L-18
        ],
    )
    section(
        "4．工場長の見積の考え方",
        [
            MINUTES_ONLY_FACT,
            "新しい仕組みを作るときに、業者に見せて、AI が見積の案を作るときの手がかりにできないかを相談する。",
            "工場長が引退する前に、見積の考え方を会社に残したい（社長）。",  # K-01
        ],
    )
    section(
        "5．AI に任せないことと、客の図面の守り方",
        [
            "AI に任せきりにはしない。値段を決めること、検査の合否、客へ送ることは人がする。"  # K-05、L-04
            "AI の案は、社長か工場長が確かめてから使う。",  # L-04
            "案と実際に決めた値段の違いは残して、AI の見直しに使う。",  # L-04
            "客の図面は外に出してはいけないもの。AI に読ませるなら、読ませたデータを学習に使わない契約の、"
            "国内のクラウドだけにする。主な取引先には、説明して了承をもらう。",  # K-05、L-14
        ],
    )
    section(
        "6．次にすること",
        [
            "社長が、見積依頼書と要件の概要を作り、10月15日に2社に渡して、同じ要件で見積を頼む。",  # L-19
        ],
    )
    doc.save(path)
    normalize_office(path)


# ---------------------------------------------------------------------------
# 図面の例（ブラケット）
# ---------------------------------------------------------------------------

S = 2.0  # 1mm を何ポイントで描くか（尺度は実寸ではない）

DRAWING = {
    "number": "BR-2609-014",
    "name": "ブラケット",
    "material": "A5052",
    "finish": "白アルマイト処理（膜厚 5〜10μm）",
    "quantity": "20個",
    "general_tolerance": "JIS B 0405 中級（m）",
    "client": "架空の客先（テスト用）",
}


def drawing() -> list:
    def arrow(c, x: float, y: float, dx: float, dy: float) -> None:
        """(x, y) を先にした矢印の頭。(dx, dy) は矢の向き（単位ベクトル）。"""
        size = 4
        px, py = -dy, dx
        c.line(x, y, x - dx * size + px * 1.6, y - dy * size + py * 1.6)
        c.line(x, y, x - dx * size - px * 1.6, y - dy * size - py * 1.6)

    def hdim(c, x1: float, x2: float, y: float, base: float, text: str) -> None:
        """横の寸法。base は図の線の高さ、y は寸法線の高さ。"""
        c.setLineWidth(0.3)
        c.line(x1, base, x1, y + (3 if y > base else -3))
        c.line(x2, base, x2, y + (3 if y > base else -3))
        c.line(x1, y, x2, y)
        arrow(c, x1, y, -1, 0)
        arrow(c, x2, y, 1, 0)
        c.setFont(MINCHO, 8)
        c.drawCentredString((x1 + x2) / 2, y + 2.5, text)
        c.setLineWidth(0.9)

    def vdim(c, y1: float, y2: float, x: float, base: float, text: str) -> None:
        c.setLineWidth(0.3)
        c.line(base, y1, x + (3 if x > base else -3), y1)
        c.line(base, y2, x + (3 if x > base else -3), y2)
        c.line(x, y1, x, y2)
        arrow(c, x, y1, 0, -1)
        arrow(c, x, y2, 0, 1)
        c.saveState()
        c.translate(x - 2.5, (y1 + y2) / 2)
        c.rotate(90)
        c.setFont(MINCHO, 8)
        c.drawCentredString(0, 0, text)
        c.restoreState()
        c.setLineWidth(0.9)

    def center_lines(c, x: float, y: float, r: float) -> None:
        c.setLineWidth(0.25)
        c.setDash(6, 2)
        c.line(x - r - 6, y, x + r + 6, y)
        c.line(x, y - r - 6, x, y + r + 6)
        c.setDash()
        c.setLineWidth(0.9)

    def page1(pg: Page) -> None:
        c = pg.c
        pg.title("図面の例（客から届いた図面のつもりで描いた架空のもの）", 11)
        c.setLineWidth(0.9)
        # 外枠
        c.rect(LEFT - 10, 60, RIGHT - LEFT + 20, pg.y - 60, fill=0, stroke=1)
        # 正面図：幅 80、高さ 58（下の 8 は底板の前の面）
        fx, fy = LEFT + 60, 560
        w, h = 80 * S, 58 * S
        c.setFont(GOTHIC, 9)
        c.drawString(fx, fy + h + 34, "正面図")
        c.rect(fx, fy, w, h, fill=0, stroke=1)
        c.line(fx, fy + 8 * S, fx + w, fy + 8 * S)
        hx, hy = fx + 40 * S, fy + 38 * S
        c.circle(hx, hy, 5 * S, fill=0, stroke=1)
        center_lines(c, hx, hy, 5 * S)
        hdim(c, fx, fx + w, fy + h + 16, fy + h, "80±0.05")
        vdim(c, fy, fy + h, fx - 18, fx, "58±0.1")
        vdim(c, fy, hy, fx + w + 18, fx + w, "38±0.02")
        c.setLineWidth(0.3)
        c.line(hx + 4 * S, hy + 4 * S, hx + 30 * S, hy + 12 * S)
        c.setLineWidth(0.9)
        c.setFont(MINCHO, 8)
        c.drawString(hx + 30 * S + 2, hy + 12 * S, "φ10H7（+0.015/0）　Ra1.6")
        # 側面図（右から見る）：奥行き 40、高さ 58、板の厚さ 8
        sx, sy = fx + w + 90, fy
        c.setFont(GOTHIC, 9)
        c.drawString(sx, sy + h + 34, "右側面図")
        path = c.beginPath()
        path.moveTo(sx, sy)
        for px, py in ((40, 0), (40, 8), (8, 8), (8, 58), (0, 58)):
            path.lineTo(sx + px * S, sy + py * S)
        path.close()
        c.drawPath(path, fill=0, stroke=1)
        c.setDash(3, 2)
        c.setLineWidth(0.5)
        c.line(sx, sy + 33 * S, sx + 8 * S, sy + 33 * S)
        c.line(sx, sy + 43 * S, sx + 8 * S, sy + 43 * S)
        c.setDash()
        c.setLineWidth(0.9)
        hdim(c, sx, sx + 40 * S, sy - 18, sy, "40±0.1")
        hdim(c, sx, sx + 8 * S, sy + h + 14, sy + h, "8")
        vdim(c, sy, sy + 8 * S, sx + 40 * S + 16, sx + 40 * S, "8")
        c.setFont(MINCHO, 8)
        c.drawString(sx + 12 * S, sy + 40 * S, "直角度 0.02")
        # 平面図（上から見る）：幅 80、奥行き 40。φ6.6 の穴が2つ（ピッチ 50）
        tx, ty = fx, fy - 40 * S - 50
        c.setFont(GOTHIC, 9)
        c.drawString(tx, ty - 34, "平面図")
        c.rect(tx, ty, w, 40 * S, fill=0, stroke=1)
        c.line(tx, ty + 32 * S, tx + w, ty + 32 * S)
        for px in (15, 65):
            cx, cy = tx + px * S, ty + 16 * S
            c.circle(cx, cy, 3.3 * S, fill=0, stroke=1)
            center_lines(c, cx, cy, 3.3 * S)
        hdim(c, tx, tx + 15 * S, ty - 16, ty, "15")
        hdim(c, tx + 15 * S, tx + 65 * S, ty - 16, ty, "50±0.02")
        c.setFont(MINCHO, 8)
        c.drawString(tx + w + 10, ty + 16 * S, "2-φ6.6 キリ")
        # 注記
        nx, ny = LEFT + 10, 300
        c.setFont(GOTHIC, 9)
        c.drawString(nx, ny, "注記")
        c.setFont(MINCHO, 8.5)
        for i, text in enumerate(
            (
                "1．指示のない角は C0.5",
                "2．バリ・カエリのないこと",
                f"3．表面処理：{DRAWING['finish']}",
                "4．φ10H7 の穴は、表面処理の後に寸法を満たすこと",
                "5．検査の成績書を付けること（三次元測定機で測る寸法：80、38、50、φ10H7）",
            ),
            start=1,
        ):
            c.drawString(nx, ny - 14 * i, text)
        # 表題欄
        bx, by, bw = LEFT + 175, 75, RIGHT - LEFT - 175
        rows = [
            ("図番", DRAWING["number"]),
            ("品名", DRAWING["name"]),
            ("材料", DRAWING["material"]),
            ("表面処理", DRAWING["finish"]),
            ("数量", DRAWING["quantity"]),
            ("普通公差", DRAWING["general_tolerance"]),
            ("尺度", "NTS（実寸ではない）"),
            ("作成", f"{DRAWING['client']}　2026年9月"),
        ]
        rh = 15
        for i, (key, value) in enumerate(reversed(rows)):
            y = by + i * rh
            c.setLineWidth(0.6)
            c.rect(bx, y, 70, rh, fill=0, stroke=1)
            c.rect(bx + 70, y, bw - 70, rh, fill=0, stroke=1)
            c.setFont(GOTHIC, 8)
            c.drawString(bx + 4, y + 4.5, key)
            c.setFont(MINCHO, 8.5)
            c.drawString(bx + 74, y + 4.5, value)
        c.setFont(MINCHO, 7.5)
        c.drawString(LEFT, 66, "単位：mm。AI が図面を読む例として見せるための架空の図面です。")

    return [page1]


# ---------------------------------------------------------------------------


def main() -> None:
    render(HERE / "会社案内.pdf", "会社案内", company_profile())
    print("作った：会社案内.pdf")
    minutes(HERE / "議事録_2026-09-30_見積の困りごと.docx")
    print("作った：議事録_2026-09-30_見積の困りごと.docx")
    render(HERE / "図面の例_ブラケット.pdf", "図面の例（ブラケット）", drawing())
    print("作った：図面の例_ブラケット.pdf")


if __name__ == "__main__":
    main()
