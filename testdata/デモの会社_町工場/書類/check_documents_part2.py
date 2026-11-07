# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4"]
# ///
"""デモの会社（2社目・町工場）の書類の後半を、回答表と照らす。

make_documents_part2.py の中の数字ではなく、できた PDF から取り出した文字を、回答表.md の文と照らす。
見積書は「数量 × 単価 ＝ 金額」、明細の和 ＝ 小計、小計の和 ＝ 合計（税抜）、その10% ＝ 消費税、
合計（税抜）＋ 消費税 ＝ 合計（税込）を確かめ、かすみ野システム工房の明細を H-02 の項目ごとに照らす。
デモの不備/ の3通は、仕込んだ不備がそのとおり入っているかを確かめる（正しい書類セットとは照らさない）。
どのページにも「架空のテスト用データ」が頭と足にあることも確かめる。合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社_町工場/書類/check_documents_part2.py
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ANSWER_SHEET = HERE.parent / "回答表.md"
MARK = "架空のテスト用データ"
TODAY = dt.date(2026, 11, 7)  # デモの日の目安（有効期限切れを見る）

KASUMINO = ("見積書_かすみ野システム工房.pdf", "株式会社かすみ野システム工房")
SHIRAUME = ("見積書_しらうめソフト.pdf", "株式会社しらうめソフト")
REQUEST = "見積依頼書.pdf"
REQUIREMENTS = "要件の概要.pdf"
OLD = "デモの不備/見積書_かすみ野システム工房_旧.pdf"
LUMP = "デモの不備/見積書_しらうめソフト_一式.pdf"
ORDER = "デモの不備/注文書_試しの開発.pdf"

# 見積の行を H-02 の項目に当てる言葉と、H-02 からその項目の金額（千円）を取る書き方
# （台数・月数のある項目は、数も取る）
ITEMS = [
    ("要件定義", r"要件定義", r"要件定義・業務の分析([\d,]+)千円"),
    ("設計", r"設計", r"、設計([\d,]+)千円"),
    ("受注・見積の機能", r"受注", r"受注・見積の機能([\d,]+)千円"),
    ("工程・進捗の機能", r"工程・進捗", r"工程・進捗の機能([\d,]+)千円"),
    ("見積の AI", r"見積の AI|AI見積", r"見積の AI（[^）]*）([\d,]+)千円"),
    ("工程と問い合わせの AI", r"問い合わせ", r"工程と問い合わせの AI ([\d,]+)千円"),
    ("会計ソフトと CAM との連携", r"連携", r"連携([\d,]+)千円"),
    ("試験", r"試験", r"、試験([\d,]+)千円"),
    ("プロジェクトの管理", r"プロジェクト", r"プロジェクトの管理([\d,]+)千円"),
    ("センサー", r"センサー", r"センサー(\d+)台分([\d,]+)千円"),
    ("読み取り端末", r"端末", r"読み取り端末(\d+)台([\d,]+)千円"),
    ("クラウドの利用料", r"クラウド", r"月[\d,]+千円の(\d+)か月分）([\d,]+)千円"),
]

failures: list[str] = []


def report(ok: bool, text: str) -> None:
    print(f"  {'○' if ok else '×'} {text}")
    if not ok:
        failures.append(text)


# ---------------------------------------------------------------------------
# 回答表
# ---------------------------------------------------------------------------


def load_answers() -> dict[str, str]:
    answers = {}
    for line in ANSWER_SHEET.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-L]-\d{2})\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            answers[m[1]] = m[2]
    return answers


ANSWERS = load_answers()


def find(answer_id: str, pattern: str) -> re.Match:
    m = re.search(pattern, ANSWERS[answer_id])
    if not m:
        raise SystemExit(f"回答表の {answer_id} に「{pattern}」が見つかりません：{ANSWERS[answer_id]}")
    return m


def num(text: str) -> int:
    return int(text.replace(",", ""))


def flat(text: str) -> str:
    return re.sub(r"[ 　\n]", "", text)


def date_of(text: str) -> dt.date:
    y, m, d = (int(v) for v in re.search(r"(\d{4})年(\d+)月(\d+)日", text).groups())
    return dt.date(y, m, d)


def pdf_pages(name: str) -> list[str]:
    return [p.extract_text(extraction_mode="layout") for p in PdfReader(str(HERE / name)).pages]


def check_marks(name: str, pages: list[str]) -> None:
    missing = [i for i, text in enumerate(pages, start=1) if flat(text).count(MARK) < 2]
    report(not missing, f"{name}：PDF {len(pages)}ページ。すべての頭と足に「{MARK}」（足りないページ：{missing or 'なし'}）")


# ---------------------------------------------------------------------------
# 見積書の明細と計算
# ---------------------------------------------------------------------------

ROW = re.compile(
    r"^\s*(\d+)\s*(\D.*?)\s+([\d.]+)\s*(人月|台|か月|式)\s+([\d,]+)\s+([\d,]+)\s*$", re.M
)


def money(text: str, label: str) -> int:
    m = re.search(rf"{re.escape(label)}\s+([\d,]+)", text)
    if not m:
        raise SystemExit(f"「{label}」の金額が見つかりません")
    return num(m[1])


def read_quote(name: str) -> dict:
    """見積書を読み、計算を確かめて、明細と合計を返す。"""
    pages = pdf_pages(name)
    check_marks(name, pages)
    text = "\n".join(pages)
    first = pages[0]
    rows = [
        {
            "no": int(m[1]), "item": m[2].strip(), "qty": m[3], "unit": m[4],
            "price": num(m[5]), "amount": num(m[6]), "pos": m.start(),
        }
        for m in ROW.finditer(first)
    ]
    report(len(rows) >= 2, f"明細の行を {len(rows)} 行読めた")
    for r in rows:
        want = Decimal(r["qty"]) * r["price"]
        report(
            want == r["amount"],
            f"{r['no']}. {r['item']}：{r['qty']}{r['unit']} × {r['price']:,}円 ＝ {int(want):,}円 ／ 書いてある金額 {r['amount']:,}円",
        )
    sub1 = money(first, "小計（機械装置・システム構築費）")
    sub2 = money(first, "小計（クラウドの利用料）")
    net = money(first, "合計（税抜）")
    tax = money(first, "消費税（10%）")
    grand = money(first, "合計（税込）")
    shown = num(re.search(r"見積金額（税込）\s+([\d,]+)円", first)[1])
    # 明細の行は、小計（機械装置・システム構築費）の行より上がⅠ、下がⅡ
    cut = first.index("小計（機械装置・システム構築費）")
    in_system = [r for r in rows if r["pos"] < cut]
    in_cloud = [r for r in rows if r not in in_system]
    report(sum(r["amount"] for r in in_system) == sub1, f"Ⅰの明細の和 {sum(r['amount'] for r in in_system):,}円 ＝ 小計 {sub1:,}円")
    report(sum(r["amount"] for r in in_cloud) == sub2, f"Ⅱの明細の和 {sum(r['amount'] for r in in_cloud):,}円 ＝ 小計 {sub2:,}円")
    report(sub1 + sub2 == net, f"小計の和 {sub1 + sub2:,}円 ＝ 合計（税抜） {net:,}円")
    report(net * 10 // 100 == tax, f"合計（税抜）の10% {net * 10 // 100:,}円 ＝ 消費税 {tax:,}円")
    report(net + tax == grand, f"合計（税抜）＋ 消費税 {net + tax:,}円 ＝ 合計（税込） {grand:,}円")
    report(shown == grand, f"上の見積金額（税込） {shown:,}円 ＝ 合計（税込） {grand:,}円")
    issued = date_of(re.search(r"発行日\s+(\d{4}年\d+月\d+日)", first)[1])
    valid = date_of(re.search(r"有効期限\s+(\d{4}年\d+月\d+日)", first)[1])
    addressee = re.search(r"^\s*(\S+)\s*御中", first, re.M)[1]
    return {
        "text": text, "flat": flat(text), "rows": rows, "system": in_system, "cloud": in_cloud,
        "sub1": sub1, "sub2": sub2, "net": net, "issued": issued, "valid": valid, "addressee": addressee,
    }


def item_of(item: str) -> str:
    for key, pattern, _ in ITEMS:
        if re.search(pattern, item):
            return key
    raise SystemExit(f"見積の行「{item}」が、H-02 のどの項目にも当たりません")


def check_quote_common(q: dict, name: str, issuer: str) -> None:
    company = ANSWERS["A-01"]
    president = find("A-08", r"代表取締役\s*(\S+\s?\S+)（")[1].replace(" ", "")
    m = find("H-04", r"(\d{4})年(\d+)月(\d+)日付け。有効期限は(\d{4})年(\d+)月(\d+)日")
    issued = dt.date(int(m[1]), int(m[2]), int(m[3]))
    valid = dt.date(int(m[4]), int(m[5]), int(m[6]))
    report(q["issued"] == issued, f"H-04 発行日 {issued} ／ 見積書 {q['issued']}")
    report(q["valid"] == valid, f"H-04 有効期限 {valid} ／ 見積書 {q['valid']}")
    report(q["addressee"] == company, f"A-01 宛名「{company} 御中」 ／ 見積書「{q['addressee']}」")
    report(president in q["flat"], f"A-08 宛名の代表者「{president}」")
    report(issuer in q["flat"] and issuer.replace("株式会社", "") in ANSWERS["H-03"], f"H-03 発行者「{issuer}」")
    report(not any("一式" in r["item"] or r["unit"] == "式" for r in q["rows"]), "「一式」の行がない（項目ごとに積み上げている）")
    report(all(r["unit"] in ("人月", "台", "か月") for r in q["rows"]), "数量の単位は人月・台・か月")
    report("税抜" in q["text"] and "税込" in q["text"], "税抜と税込の別が書いてある")
    for want, what in [
        ("研修：導入時の操作説明", "L-20 研修は導入時の操作説明"),
        ("費用は各機能の開発に含む", "L-20 研修の費用は各機能の開発に含む"),
        ("保守：別契約（本見積に含まない）", "L-11 保守は別契約で、見積に含まない"),
        ("工事は要りません", "H-08 工事は要らない"),
        ("電気は機械から取ります", "H-08 センサーの電気は機械から取る"),
        ("ご発注から約8か月", "H-07 期間は約8か月"),
        ("取り込む仕組みは、受注・見積の機能に含みます", "L-12 過去のデータを取り込む仕組みは見積に入っている"),
        ("取り込む作業は御社で行います", "L-12 取り込む作業は自社"),
        ("学習に使わない契約の、国内のクラウド", "L-14 学習に使わない国内のクラウド"),
        ("2026年10月15日付けの見積依頼書", "L-19 10月15日の見積依頼書に基づく"),
    ]:
        report(want in q["flat"].replace(" ", ""), what)
    h07 = find("H-07", r"約(\d+)か月（要件定義と設計で約(\d+)か月、作るのと試験で約(\d+)か月、試しに動かすのに約(\d+)か月）").groups()
    report(
        f"約{h07[0]}か月（要件定義と設計約{h07[1]}か月、開発と試験約{h07[2]}か月、試しの運用約{h07[3]}か月）" in q["flat"],
        f"H-07 期間の内訳 {h07[1]}＋{h07[2]}＋{h07[3]}か月",
    )


def check_quotes() -> None:
    print(f"\n■ {KASUMINO[0]}")
    k = read_quote(KASUMINO[0])
    check_quote_common(k, *KASUMINO)
    print("  （H-02 の項目と照らす）")
    want_sub1 = num(find("H-02", r"機械装置・システム構築費が([\d,]+)千円")[1])
    want_net = num(find("H-02", r"合計([\d,]+)千円（税抜）")[1])
    report(k["sub1"] == want_sub1 * 1000, f"H-02 機械装置・システム構築費：回答表 {want_sub1:,}千円 ／ 見積書 {k['sub1']:,}円")
    report(k["net"] == want_net * 1000, f"H-02 合計（税抜）：回答表 {want_net:,}千円 ／ 見積書 {k['net']:,}円")
    want_h03 = num(find("H-03", r"かすみ野システム工房（([\d,]+)千円")[1])
    report(k["net"] == want_h03 * 1000, f"H-03 かすみ野の見積（税抜）：回答表 {want_h03:,}千円 ／ 見積書 {k['net']:,}円")
    by_item = {item_of(r["item"]): r for r in k["rows"]}
    report(len(by_item) == len(ITEMS) == len(k["rows"]), f"H-02 の{len(ITEMS)}項目が1行ずつある（明細 {len(k['rows'])}行）")
    for key, _, pattern in ITEMS:
        r = by_item.get(key)
        m = find("H-02", pattern)
        thousand = num(m[m.lastindex])
        ok = r is not None and r["amount"] == thousand * 1000
        detail = f"回答表 {thousand:,}千円 ／ 見積書 {r['amount']:,}円" if r else "見積書にない"
        if m.lastindex == 2 and r is not None:
            ok = ok and Decimal(r["qty"]) == int(m[1])
            detail += f"（数 回答表 {m[1]} ／ 見積書 {r['qty']}{r['unit']}）"
        report(ok, f"H-02 {key}：{detail}")
    cloud_month = num(find("H-02", r"月([\d,]+)千円の\d+か月分")[1])
    report(
        by_item["クラウドの利用料"]["price"] == cloud_month * 1000 and by_item["クラウドの利用料"] in k["cloud"],
        f"H-02 クラウドは月{cloud_month:,}千円で、機械装置・システム構築費とは別の区分",
    )

    print(f"\n■ {SHIRAUME[0]}")
    s = read_quote(SHIRAUME[0])
    check_quote_common(s, *SHIRAUME)
    want = num(find("H-03", r"しらうめソフト（([\d,]+)千円")[1])
    report(s["net"] == want * 1000, f"H-03 しらうめの見積（税抜）：回答表 {want:,}千円 ／ 見積書 {s['net']:,}円")
    report(s["sub1"] == 23_600_000, f"機械装置・システム構築費の小計 23,600,000円 ／ 見積書 {s['sub1']:,}円")
    s_items = {item_of(r["item"]): r for r in s["rows"]}
    report(set(s_items) == set(by_item) and len(s["rows"]) == len(k["rows"]), "H-03 同じ要件：項目の組み立てがかすみ野と同じ")
    for key in ("センサー", "読み取り端末", "クラウドの利用料"):
        a, b = by_item[key], s_items.get(key, {"qty": "?", "unit": ""})
        report(a["qty"] == b["qty"] and a["unit"] == b["unit"], f"H-03 同じ要件：{key} かすみ野 {a['qty']}{a['unit']} ／ しらうめ {b['qty']}{b['unit']}")
    report(k["net"] < s["net"], f"H-05 かすみ野のほうが安い（{k['net']:,}円 ＜ {s['net']:,}円）")


# ---------------------------------------------------------------------------
# 見積依頼書と要件の概要
# ---------------------------------------------------------------------------


def check_request() -> None:
    print(f"\n■ {REQUEST}")
    pages = pdf_pages(REQUEST)
    check_marks(REQUEST, pages)
    f = flat("\n".join(pages))
    d = find("L-19", r"(\d{4})年(\d+)月(\d+)日に、同じ要件の資料（見積依頼書）を(\d)社")
    report(f"{d[1]}年{d[2]}月{d[3]}日" in f, f"L-19 日付 {d[1]}年{d[2]}月{d[3]}日")
    report("株式会社かすみ野システム工房御中" in f and "株式会社しらうめソフト御中" in f, f"L-19・H-03 {d[4]}社に同じ内容で依頼")
    report(ANSWERS["A-01"] in f and ANSWERS["B-01"].split("。")[0] in f, "A-01・B-01 依頼した会社と所在地")
    report("「一式」だけの書き方は避けて" in f, "「一式」を避け、数量×単価で積み上げるよう頼んでいる")
    report("保守" in f and "見積に入れないもの" in f, "L-11 保守は見積に入れない")


def check_requirements() -> None:
    print(f"\n■ {REQUIREMENTS}")
    pages = pdf_pages(REQUIREMENTS)
    check_marks(REQUIREMENTS, pages)
    report(3 <= len(pages) <= 4, f"3〜4ページ：{len(pages)}ページ")
    f = flat("\n".join(pages))
    report("2026年10月15日" in f and ANSWERS["A-01"] in f, "発行はみずなら精工、2026年10月15日")
    for want, what in [
        ("受注・見積の機能", "受注・見積の機能"),
        ("工程・進捗の機能", "工程・進捗の機能"),
        ("(1)見積の案", "AI の役目1：図面とメールから見積の案"),
        ("(2)翌日の段取りの案", "AI の役目2：翌日の段取りの案"),
        ("(3)問い合わせの返事の下書き", "AI の役目3：問い合わせの返事の下書き"),
        ("値段を決めること、検査の合否、客へ送ること", "L-04 AI に任せないこと"),
        ("学習に使わない契約の、国内のクラウドだけ", "L-14 データの守り方"),
        ("脆弱性", "L-14 納める前に弱いところを確かめる"),
        ("センサー10台", "H-02 センサー10台"),
        ("読み取り端末4台", "H-02 読み取り端末4台"),
        ("電気は機械から取る", "H-08 電気は機械から取る"),
        ("会計ソフト", "会計ソフトとの連携"),
        ("CAM", "CAM との連携"),
        ("過去8年の見積約9,000件", "L-12 過去のデータ"),
        ("取り込む作業は、当社の事務が2027年11月〜2028年1月に行う", "L-12 取り込む作業は自社"),
        ("社長・工場長・事務・営業の4人に使い方を教える", "L-20 研修"),
        ("2027年7〜10月要件定義と設計", "L-10 7〜10月に要件定義と設計"),
        ("11月〜2028年1月作るのと試験", "L-10 11月〜1月に作るのと試験"),
        ("2月試しの運用", "L-10 2月に試しに動かす"),
        ("3月本番", "L-10 3月から本番"),
        ("2027年8月から使い始める", "L-10 クラウドは2027年8月から"),
        ("保守の費用は、この見積に入れない", "L-11 保守の費用は見積に入れない"),
    ]:
        report(want in f, what)


# ---------------------------------------------------------------------------
# デモの不備（仕込んだ不備が入っているか）
# ---------------------------------------------------------------------------


def check_defects() -> None:
    print(f"\n■ {OLD}（不備：有効期限切れの古い見積書）")
    o = read_quote(OLD)
    report(o["issued"] == dt.date(2026, 4, 10), f"発行日 2026-04-10 ／ {o['issued']}")
    report(o["valid"] == dt.date(2026, 7, 31) and o["valid"] < TODAY, f"有効期限 {o['valid']} は {TODAY} より前（期限切れ）")
    report(o["net"] * 1 != num(find("H-02", r"合計([\d,]+)千円（税抜）")[1]) * 1000, f"金額は今の見積と違う（{o['net']:,}円）")
    report(o["addressee"] == ANSWERS["A-01"], "宛名は正しい（期限切れだけを不備にする）")

    print(f"\n■ {LUMP}（不備：積算の根拠のない「一式」と、宛名の名義の違い）")
    q = read_quote(LUMP)
    report(any("一式" in r["item"] for r in q["system"]), "機械装置・システム構築費が「一式」1行だけ")
    report(len(q["system"]) == 1 and q["system"][0]["unit"] == "式", "数量×単価の積み上げがない（1式）")
    report(any("一式" in r["item"] for r in q["cloud"]), "クラウドの利用料も「一式」")
    report(q["sub1"] == 23_600_000 and q["net"] == num(find("H-03", r"しらうめソフト（([\d,]+)千円")[1]) * 1000, "金額は正しい見積と同じ（不備は書き方と宛名）")
    report("精機" in q["addressee"] and q["addressee"] != ANSWERS["A-01"], f"宛名「{q['addressee']}」は A-01「{ANSWERS['A-01']}」と違う")
    report(q["issued"] == dt.date(2026, 10, 20), f"発行日 2026-10-20 ／ {q['issued']}")

    print(f"\n■ {ORDER}（不備：交付決定の前の発注）")
    pages = pdf_pages(ORDER)
    check_marks(ORDER, pages)
    text = "\n".join(pages)
    f = flat(text)
    ordered = date_of(re.search(r"注文日\s+(\d{4}年\d+月\d+日)", text)[1])
    grant = find("L-10", r"交付決定は(\d{4})年(\d+)月ごろ")
    grant_month = dt.date(int(grant[1]), int(grant[2]), 1)
    report(ordered == dt.date(2026, 11, 2), f"注文日 2026-11-02 ／ {ordered}")
    report(ordered < grant_month, f"注文日 {ordered} は交付決定（{grant[1]}年{grant[2]}月ごろ。L-10）より前")
    report("株式会社かすみ野システム工房御中" in f and ANSWERS["A-01"] in f, "みずなら精工からかすみ野システム工房への注文")
    report("見積のAIの試しの開発（図面の読み取りの部分）" in f, "品名：見積の AI の試しの開発（図面の読み取りの部分）")
    m = re.search(r"1式\s+([\d,]+)\s+([\d,]+)", text)
    report(m is not None and num(m[2]) == 1_500_000, "金額 1,500,000円（税抜）")
    report(money(text, "消費税（10%）") == 150_000 and money(text, "合計（税込）") == 1_650_000, "消費税 150,000円、合計 1,650,000円")
    report("まだしていない" in ANSWERS["H-06"], "H-06（発注はまだ）と食い違う書類として仕込んだ")


def main() -> None:
    check_quotes()
    check_request()
    check_requirements()
    check_defects()
    print()
    if failures:
        print(f"合わないもの：{len(failures)}件")
        for f in failures:
            print(f"  × {f}")
        sys.exit(1)
    print("すべて合いました。")


if __name__ == "__main__":
    main()
