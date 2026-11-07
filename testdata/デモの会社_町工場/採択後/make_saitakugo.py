# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の採択後の材料を作る（DESIGN 3章 2:35–2:50 の場面）。

作るもの（このフォルダの中）：
- 省力化（一般型）第9回の採択の通知と交付決定通知書（PDF）
- 持続化（通常枠）第20回の採択通知書と交付決定通知書（PDF）
- 省力化の交付申請への差し戻しの文（テキスト。システム構築費の明細）

日付は1社目（testdata/期限/正解.json）と同じ日にそろえた。会社の事実は ../回答表.md に合わせる（行ごとに回答表の ID を添えた）。
補助事業完了期限日は、省力化 第9回の公募要領（downloads/shoryokuka_ippan/application_guidelines_ippan_09.pdf）の
p.8・p.25「交付決定日から14か月以内（採択発表日から16か月後の日まで）」で計算する（早いほう）。

PDF の描き方は ../書類/make_documents.py のもの（帯・足・invariant）を使う。そのスクリプトは直さない。
どのページにも「架空のテスト用データ」の帯を付ける。公印・役所の人の名前・本物の様式の配置は入れない。
事務局は固有の名前を出さず、「（架空）」を付けた表示にする。同じ中身なら同じバイト列になる。

動かし方：uv run --script testdata/デモの会社_町工場/採択後/make_saitakugo.py
"""

from __future__ import annotations

import calendar
import datetime as dt
import sys
from pathlib import Path
from typing import List

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent / "書類"
sys.path.insert(0, str(DOCS_DIR))

import make_documents as base  # noqa: E402
from make_documents import COMPANY, CORPORATE_NUMBER, GOTHIC, LEFT, PRESIDENT, Page, render  # noqa: E402

WEEKDAYS = "月火水木金土日"
D = dt.date

# ---------------------------------------------------------------------------
# ファイルの名前
# ---------------------------------------------------------------------------

SHORYOKU_ADOPTION_FILE = "省力化_第9回_採択の通知.pdf"
SHORYOKU_GRANT_FILE = "省力化_第9回_交付決定通知書.pdf"
JIZOKU_ADOPTION_FILE = "持続化_第20回_採択通知書.pdf"
JIZOKU_GRANT_FILE = "持続化_第20回_交付決定通知書.pdf"
REMAND_FILE = "差し戻し_システム構築費の明細.txt"

# ---------------------------------------------------------------------------
# 日付と金額（日付はどれも1社目の testdata/期限/正解.json と同じ。回答表にない）
# ---------------------------------------------------------------------------

SHORYOKU = {
    "制度": "中小企業省力化投資補助金（一般型）",
    "公募回": "第9回",
    "申請番号": "TEST-S09-0563",  # 架空。1社目（TEST-S09-0421）と別にした
    "事業計画名": "AI による図面の見積と工程管理の仕組みの導入",  # H-01 の要約
    "採択発表日": D(2027, 4, 16),
    "交付申請日": D(2027, 5, 28),
    "交付決定日": D(2027, 6, 25),
    # デモの計画書の補助申請金額（13,600,000円）に合わせる（作者の指示）。H-02 の機械装置・システム構築費 21,000千円から、
    # 読み取り端末（600千円）を除いた 20,400千円。クラウドの利用料（1,200千円）も除く。どちらも業者に中身を確かめ中として計画書で除いた
    "経費の区分": "機械装置・システム構築費",
    "補助対象経費": 20_400_000,
    "補助率": (2, 3),  # 小規模企業者（設定.md の参考の結論）
    # 事業実施期間（公募要領 第9回 p.8・p.25）
    "実施の月数_交付決定から": 14,
    "実施の月数_採択発表から": 16,
    # 交付申請の期限（公募要領 第9回 p.25：原則、採択発表日から2か月後の日）
    "交付申請の月数": 2,
}

JIZOKU = {
    "制度": "小規模事業者持続化補助金（一般型 通常枠）",
    "公募回": "第20回",
    "申請番号": "TEST-J20-0419",  # 架空。1社目（TEST-J20-0388）と別にした
    "枠": "通常枠（賃金引上げ特例）",  # 設定.md
    "事業計画名": "医療機器・計測機器の業界に向けた加工技術の発信と試作の販路開拓",  # I-01、I-02 の要約
    "採択発表日": D(2027, 3, 12),
    "交付決定日": D(2027, 4, 23),
    "補助対象経費": 3_000_000,  # I-03（税抜）
    "補助率": (2, 3),  # 黒字なので2/3（設定.md の参考の結論）
    # 持続化 第20回 公募要領（要領20）の決まった日付。1社目と同じ
    "補助事業実施期限": D(2028, 3, 31),
    "実績報告書の提出期限": D(2028, 4, 10),
}

# 差し戻し（省力化の交付申請へ）。1社目の差し戻し（6月2日に送り、6月11日まで）と同じ日にした
REMAND_SENT = D(2027, 6, 2)
REMAND_DUE = D(2027, 6, 11)
PM_ITEM = "プロジェクトの管理"  # H-02、見積書の明細
PM_MONTHS = "1.25"  # 見積書の明細の人月（../書類/make_documents_part2.py の KASUMINO の明細）
VENDOR = "株式会社かすみ野システム工房"  # H-03、H-05

SHORYOKU_SENDER = "（架空）中小企業省力化投資補助金 一般型 事務局（テスト用）"
JIZOKU_SENDER = "（架空）小規模事業者持続化補助金 事務局（テスト用）"
REMAND_SENDER = "（架空）一般型 事務局（テスト用）"

# ---------------------------------------------------------------------------
# 計算
# ---------------------------------------------------------------------------


def add_months(d: dt.date, months: int) -> dt.date:
    """応当日。応当日がない月は、その月の末日。この材料の日付は、どれも応当日がある（1社目と同じ数え方）。"""
    index = d.month - 1 + months
    year = d.year + index // 12
    month = index % 12 + 1
    return D(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def grant_amount(cost: int, rate: tuple) -> int:
    """補助対象経費 × 補助率。1円未満は切り捨て。"""
    return cost * rate[0] // rate[1]


def shoryoku_grant_amount() -> int:
    return grant_amount(SHORYOKU["補助対象経費"], SHORYOKU["補助率"])


def jizoku_grant_amount() -> int:
    return grant_amount(JIZOKU["補助対象経費"], JIZOKU["補助率"])


def shoryoku_completion_candidates() -> dict:
    s = SHORYOKU
    return {
        "交付決定日から14か月": add_months(s["交付決定日"], s["実施の月数_交付決定から"]),
        "採択発表日から16か月": add_months(s["採択発表日"], s["実施の月数_採択発表から"]),
    }


def shoryoku_completion() -> dt.date:
    """補助事業完了期限日：2つの候補の早いほう（公募要領 第9回 p.8・p.25）。"""
    return min(shoryoku_completion_candidates().values())


def shoryoku_application_deadline() -> dt.date:
    return add_months(SHORYOKU["採択発表日"], SHORYOKU["交付申請の月数"])


def jp(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def rate_text(rate: tuple) -> str:
    return f"{rate[0]}/{rate[1]}"


def check_story() -> None:
    """日付と金額のつじつま。合わなければ作らない。"""
    s, j = SHORYOKU, JIZOKU
    if not (s["採択発表日"] < s["交付申請日"] < REMAND_SENT < REMAND_DUE <= shoryoku_application_deadline() < s["交付決定日"]):
        raise ValueError("省力化の日付の順番が合いません（採択→交付申請→差し戻し→出し直し→交付申請の期限→交付決定）")
    if not (s["交付決定日"] < shoryoku_completion()):
        raise ValueError("補助事業完了期限日が交付決定日より前です")
    if shoryoku_grant_amount() > 15_000_000:
        raise ValueError("省力化の交付決定額が、従業員6〜20人の補助上限（1,500万円）を超えています")
    if not (j["採択発表日"] < j["交付決定日"] < j["補助事業実施期限"] < j["実績報告書の提出期限"]):
        raise ValueError("持続化の日付の順番が合いません")
    if jizoku_grant_amount() > 2_000_000:
        raise ValueError("持続化の交付決定額が、通常枠（賃金引上げ特例）の補助上限（200万円）を超えています")


# ---------------------------------------------------------------------------
# 書類を描く
# ---------------------------------------------------------------------------

# 行の頭に来てはいけない文字（句読点と閉じかっこ）。前の行の終わりに付ける
LINE_HEAD_NG = "、。，．）」』】"


def para(pg: Page, text: str, size: float = 10) -> None:
    """折り返して書く。句読点を行の頭に出さない。段落のあとに小さな空きを入れる。"""
    lines: List[str] = []
    for line in base.wrap(text, base.MINCHO, size, base.RIGHT - LEFT):
        while lines and line and line[0] in LINE_HEAD_NG:
            lines[-1] += line[0]
            line = line[1:]
        if line:
            lines.append(line)
    pg.c.setFont(base.MINCHO, size)
    for line in lines:
        pg.c.drawString(LEFT, pg.y, line)
        pg.y -= size + 5
    pg.gap(4)


def letter_head(pg: Page, issued: dt.date, sender: str) -> None:
    pg.right(jp(issued), 10)
    pg.gap(6)
    pg.c.setFont(GOTHIC, 12)
    pg.c.drawString(LEFT, pg.y, COMPANY)  # A-01
    pg.y -= 18
    pg.c.drawString(LEFT, pg.y, f"代表取締役　{PRESIDENT}　様")  # A-08
    pg.y -= 26
    pg.right(sender, 10)
    pg.gap(14)


def shoryoku_adoption() -> list:
    s = SHORYOKU

    def page1(pg: Page) -> None:
        letter_head(pg, s["採択発表日"], SHORYOKU_SENDER)
        pg.title("採択のお知らせ", 16)
        para(pg,
             f"{s['制度']} {s['公募回']}公募にご申請いただいた事業計画について、審査の結果、"
             "補助金交付候補者として採択されましたので、お知らせします。",
             size=10.5)
        pg.gap(6)
        for key, value in (
            ("申請番号", s["申請番号"]),
            ("公募の回", f"{s['公募回']}公募"),
            ("事業者名", COMPANY),  # A-01
            ("法人番号", CORPORATE_NUMBER),  # A-03
            ("事業計画名", s["事業計画名"]),  # H-01
            ("採択発表日", jp(s["採択発表日"])),
            ("結果", "採択（補助金交付候補者）"),
        ):
            pg.kv(key, value, key_width=95, size=10)
        pg.gap(8)
        # 交付申請の期限は、1社目と同じく日付を書かない（通知の日付から計算し直す場面のため）
        para(pg, "採択の後は、研修動画の視聴（確認テストを含む）と交付申請を行ってください。交付申請の期限と手続きは、公募要領と事務局の案内のとおりです。", size=10)
        para(pg, "システム構築費を計上している事業者は、交付申請のときに、システム構築費の明細もあわせて出してください。", size=10)
        para(pg, "交付決定の前に、発注・契約・支払いをしないでください。交付決定の前の経費は、補助の対象になりません。", size=10)

    return [page1]


def shoryoku_grant() -> list:
    s = SHORYOKU
    completion = shoryoku_completion()
    amount = shoryoku_grant_amount()

    def page1(pg: Page) -> None:
        letter_head(pg, s["交付決定日"], SHORYOKU_SENDER)
        pg.title("交付決定通知書", 16)
        para(pg,
             f"{jp(s['交付申請日'])}付けで申請のあった補助金の交付について、次のとおり交付することを決定しましたので、通知します。",
             size=10.5)
        pg.gap(6)
        for key, value in (
            ("申請番号", s["申請番号"]),
            ("公募の回", f"{s['制度']} {s['公募回']}公募"),
            ("事業者名", COMPANY),  # A-01
            ("交付決定日", jp(s["交付決定日"])),
            ("事業計画名", s["事業計画名"]),  # H-01
            ("経費の区分", f"{s['経費の区分']}　{s['補助対象経費']:,}円（税抜）"),  # H-02
            ("補助対象経費", f"{s['補助対象経費']:,}円（税抜）"),
            ("補助率", rate_text(s["補助率"])),
            ("交付決定額", f"{amount:,}円"),
            ("補助事業の実施期間", f"{jp(s['交付決定日'])}から{jp(completion)}まで"),
            ("補助事業完了期限日", jp(completion)),
        ):
            pg.kv(key, value, key_width=110, size=10)
        pg.gap(8)
        para(pg, "補助事業は、交付決定日から始められます。交付決定日より前に発注・契約したものは、補助の対象になりません。", size=10)
        para(pg, "発注・納品・検収・支払いは、補助事業完了期限日までに済ませてください。", size=10)
        para(pg, "補助事業を完了したら、完了した日から起算して30日を経過した日と、補助事業完了期限日の、いずれか早い日までに実績報告を行ってください。", size=10)
        para(pg, "交付決定額は補助金の上限の額です。補助金の額は、実績報告を確かめた後に確定します。経費の配分や内容を変えるときは、前もって承認を受けてください。", size=10)

    return [page1]


def jizoku_adoption() -> list:
    j = JIZOKU

    def page1(pg: Page) -> None:
        letter_head(pg, j["採択発表日"], JIZOKU_SENDER)
        pg.title("採択通知書", 16)
        para(pg,
             f"{j['制度']} {j['公募回']}公募にご申請いただいた補助事業計画について、審査の結果、採択されましたので、お知らせします。",
             size=10.5)
        pg.gap(6)
        for key, value in (
            ("申請番号", j["申請番号"]),
            ("公募の回", f"{j['公募回']}公募"),
            ("申請した枠", j["枠"]),
            ("事業者名", COMPANY),  # A-01
            ("事業計画名", j["事業計画名"]),  # I-01、I-02
            ("採択発表日", jp(j["採択発表日"])),
            ("結果", "採択"),
        ):
            pg.kv(key, value, key_width=95, size=10)
        pg.gap(8)
        para(pg, "採択の後、経費の価格が妥当であることを示す見積書等（相見積もりを含む）を出してください。見積書等の提出期限は、公募要領のとおりです。見積書等を確かめた後に、交付決定を通知します。", size=10)
        para(pg, "交付決定の前に、発注・契約・支払いをしないでください。", size=10)

    return [page1]


def jizoku_grant() -> list:
    j = JIZOKU
    amount = jizoku_grant_amount()

    def page1(pg: Page) -> None:
        letter_head(pg, j["交付決定日"], JIZOKU_SENDER)
        pg.title("交付決定通知書", 16)
        para(pg, "ご提出いただいた見積書等を確かめ、補助金の交付を次のとおり決定しましたので、通知します。", size=10.5)
        pg.gap(6)
        for key, value in (
            ("申請番号", j["申請番号"]),
            ("公募の回", f"{j['制度']} {j['公募回']}公募"),
            ("事業者名", COMPANY),  # A-01
            ("交付決定日", jp(j["交付決定日"])),
            ("事業計画名", j["事業計画名"]),  # I-01、I-02
            ("補助対象経費", f"{j['補助対象経費']:,}円（税抜）"),  # I-03
            ("補助率", rate_text(j["補助率"])),
            ("交付決定額", f"{amount:,}円"),
            ("補助事業の実施期間", f"{jp(j['交付決定日'])}から{jp(j['補助事業実施期限'])}まで"),
            ("実績報告書の提出期限", jp(j["実績報告書の提出期限"])),
        ):
            pg.kv(key, value, key_width=120, size=10)
        pg.gap(8)
        para(pg, "補助事業が実施期間の途中で終わったとき（支払いまで済んだとき）は、その日から起算して30日を経過した日と、実績報告書の提出期限の、いずれか早い日までに実績報告書を出してください。", size=10)
        para(pg, "補助事業の終了から1年後の状況について、事業効果等状況報告を出してください。期限は事務局からお知らせします。", size=10)

    return [page1]


def remand_text() -> str:
    s = SHORYOKU
    lines = [
        "（架空のテスト用データ。事務局からの連絡を、社長がそのまま貼り付けたもの）",
        "",
        f"件名：交付申請の修正のお願い（申請番号 {s['申請番号']}）",
        f"送った日：{jp(REMAND_SENT)}",
        "",
        f"{COMPANY}　ご担当者様",
        "",
        f"{s['交付申請日'].year}年{s['交付申請日'].month}月{s['交付申請日'].day}日に出していただいた交付申請を確かめたところ、次の点を直していただく必要があります。",
        f"直した上で、{jp(REMAND_DUE)}までに、もう一度出してください。",
        "",
        "【修正1】システム構築費の明細",
        f"添付の見積書（{VENDOR}）にある「{PM_ITEM}」{PM_MONTHS}人月が、システム構築費の明細に書かれた作業の工程のどれに当たるのかが分からず、積算の根拠を確かめられません。",
        f"「{PM_ITEM}」で行う作業の内容と、作業ごとの工数（人月）の内訳を示した明細に直して、出し直してください。",
        "明細の工数と単価から出した金額の合計が、見積書の金額と合うようにしてください。",
        "",
        "ご不明な点は、申請番号を添えてお問い合わせください。",
        REMAND_SENDER,
    ]
    return "\n".join(lines) + "\n"


def build(out: Path) -> List[Path]:
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for name, doc_name, pages in (
        (SHORYOKU_ADOPTION_FILE, "採択のお知らせ（省力化 第9回）", shoryoku_adoption()),
        (SHORYOKU_GRANT_FILE, "交付決定通知書（省力化 第9回）", shoryoku_grant()),
        (JIZOKU_ADOPTION_FILE, "採択通知書（持続化 第20回）", jizoku_adoption()),
        (JIZOKU_GRANT_FILE, "交付決定通知書（持続化 第20回）", jizoku_grant()),
    ):
        render(out / name, doc_name, pages)
        made.append(out / name)
    (out / REMAND_FILE).write_bytes(remand_text().encode("utf-8"))
    made.append(out / REMAND_FILE)
    return made


def main() -> None:
    check_story()
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE
    for path in build(out):
        print(f"作った：{path.name}")
    print(f"補助事業完了期限日：{jp(shoryoku_completion())}（候補："
          + "、".join(f"{k} {jp(v)}" for k, v in shoryoku_completion_candidates().items()) + "）")


if __name__ == "__main__":
    main()
