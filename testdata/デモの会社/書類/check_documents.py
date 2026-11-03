# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4"]
# ///
"""デモの会社の書類（TASKS D2a）を、回答表と照らす。

make_documents.py の中の数字ではなく、できた PDF から取り出した文字を、回答表.md の文と照らす。
あわせて、決算書の足し算、期をまたぐつながり、書類どうしの食い違い、どのページにも
「架空のテスト用データ」があることを確かめる。合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社/書類/check_documents.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ANSWER_SHEET = HERE.parent / "回答表.md"
MARK = "架空のテスト用データ"

DOCUMENTS = [
    ("決算書_第17期.pdf", "決算書（第17期）"),
    ("決算書_第18期.pdf", "決算書（第18期）"),
    ("履歴事項全部証明書.pdf", "履歴事項全部証明書"),
    ("納税証明書_その2.pdf", "納税証明書（その2）"),
    ("法人事業概況説明書_第18期.pdf", "法人事業概況説明書（第18期）"),
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
        m = re.match(r"\|\s*([A-K]-\d{2})\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            answers[m[1]] = m[2]
    return answers


ANSWERS = load_answers()


def ans(answer_id: str, pattern: str) -> int:
    """回答表の行から、千円の数字を1つ取る。"""
    m = re.search(pattern, ANSWERS[answer_id])
    if not m:
        raise SystemExit(f"回答表の {answer_id} に「{pattern}」が見つかりません：{ANSWERS[answer_id]}")
    return int(m[1].replace(",", ""))


def ans_period(answer_id: str, period: int) -> int:
    return ans(answer_id, rf"第{period}期([\d,]+)千円")


def president_name() -> str:
    """A-08 の代表者の名前（空白を除く）。"""
    return re.search(r"代表取締役\s*(\S+\s?\S+)（", ANSWERS["A-08"])[1].replace(" ", "")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def read_pages(name: str) -> list[str]:
    reader = PdfReader(str(HERE / name))
    return [page.extract_text(extraction_mode="layout") for page in reader.pages]


def flat(text: str) -> str:
    """空白を除く（名前や住所が含まれるかを見るため）。"""
    return re.sub(r"[ 　\n]", "", text)


def find_page(pages: list[str], title: str) -> str:
    """見出しだけの行があるページを返す（表紙の目次は「1．」が付くので当たらない）。"""
    for text in pages:
        if re.search(rf"^\s*{re.escape(title)}\s*$", text, re.M):
            return text
    raise SystemExit(f"「{title}」のページが見つかりません")


def amounts(text: str, label: str) -> list[int]:
    """「科目の名前　金額　金額…」の行から金額を取る。行の頭の科目の名前で探す。"""
    m = re.search(rf"^\s*{re.escape(label)}((?:\s+[\d,]+)+)\s*$", text, re.M)
    if not m:
        raise SystemExit(f"「{label}」の行が見つかりません")
    return [int(v.replace(",", "")) for v in m[1].split()]


def amount(text: str, label: str) -> int:
    return amounts(text, label)[0]


def fmt(yen: int) -> str:
    return f"{yen:,}円"


def compare(answer_id: str, what: str, answer_thousand: int, pdf_yen: int) -> None:
    report(
        answer_thousand * 1000 == pdf_yen,
        f"{answer_id} {what}：回答表 {answer_thousand:,}千円 ／ PDF {fmt(pdf_yen)}",
    )


def sums_to(text: str, total_label: str, parts: list[str], where: str) -> None:
    got = amount(text, total_label)
    want = sum(amount(text, p) for p in parts)
    report(got == want, f"{where} {total_label} {fmt(got)} ＝ {'＋'.join(parts)}（{fmt(want)}）")


def equals(what: str, a: int, b: int) -> None:
    report(a == b, f"{what}：{fmt(a)} ／ {fmt(b)}")


# ---------------------------------------------------------------------------
# 和暦
# ---------------------------------------------------------------------------

ERA = {"令和": 2018, "平成": 1988}


def seireki(text: str) -> tuple[int, int, int]:
    m = re.search(r"(令和|平成)(\d+)年(\d+)月(\d+)日", text)
    if not m:
        raise SystemExit(f"日付が読めません：{text}")
    return ERA[m[1]] + int(m[2]), int(m[3]), int(m[4])


# ---------------------------------------------------------------------------
# 照らす
# ---------------------------------------------------------------------------

BS_SECTIONS = [
    ("流動資産合計", ["現金及び預金", "売掛金", "原材料", "その他流動資産"]),
    ("有形固定資産合計", ["機械及び装置", "車両運搬具", "工具、器具及び備品"]),
    ("無形固定資産合計", ["ソフトウエア"]),
    ("投資その他の資産合計", ["敷金及び保証金"]),
    ("固定資産合計", ["有形固定資産合計", "無形固定資産合計", "投資その他の資産合計"]),
    ("資産合計", ["流動資産合計", "固定資産合計"]),
    (
        "流動負債合計",
        ["買掛金", "1年内返済予定の長期借入金", "未払金及び未払費用", "未払法人税等", "その他流動負債"],
    ),
    ("固定負債合計", ["長期借入金"]),
    ("負債合計", ["流動負債合計", "固定負債合計"]),
    ("利益剰余金合計", ["繰越利益剰余金"]),
    ("株主資本合計", ["資本金", "利益剰余金合計"]),
    ("純資産合計", ["株主資本合計"]),
    ("負債及び純資産合計", ["負債合計", "純資産合計"]),
]
MFG_SECTIONS = [
    ("当期労務費", ["賃金給与", "法定福利費"]),
    ("当期製造経費", ["水道光熱費", "消耗品・包装材料費", "地代家賃", "減価償却費", "修繕費その他"]),
    ("当期総製造費用", ["当期材料費", "当期労務費", "当期製造経費"]),
]
SGA_ITEMS = ["役員報酬", "給料手当", "法定福利費", "福利厚生費", "荷造運賃", "車両費", "リース料", "減価償却費", "その他"]


def check_statements(period: int) -> dict[str, str]:
    name = f"決算書_第{period}期.pdf"
    pages = read_pages(name)
    bs = find_page(pages, "貸借対照表")
    pl = find_page(pages, "損益計算書")
    mfg = find_page(pages, "製造原価報告書")
    sga = find_page(pages, "販売費及び一般管理費内訳書")
    eq = find_page(pages, "株主資本等変動計算書")
    w = f"第{period}期"

    print(f"\n■ {name}：回答表と照らす")
    compare("F-01", f"{w} 売上高", ans_period("F-01", period), amount(pl, "売上高"))
    compare("F-02", f"{w} 売上総利益", ans_period("F-02", period), amount(pl, "売上総利益"))
    compare("F-03", f"{w} 営業利益", ans_period("F-03", period), amount(pl, "営業利益"))
    compare("F-04", f"{w} 経常利益", ans_period("F-04", period), amount(pl, "経常利益"))
    compare("F-05", f"{w} 当期純利益", ans_period("F-05", period), amount(pl, "当期純利益"))
    compare(
        "F-06",
        f"{w} 減価償却費（製造原価＋販管費）",
        ans_period("F-06", period),
        amount(mfg, "減価償却費") + amount(sga, "減価償却費"),
    )
    compare(
        "F-07",
        f"{w} 法定福利費（製造原価＋販管費）",
        ans_period("F-07", period),
        amount(mfg, "法定福利費") + amount(sga, "法定福利費"),
    )
    wages = amount(mfg, "賃金給与") + amount(sga, "給料手当")
    if period == 18:
        compare("D-03", f"{w} 従業員の給与（賃金給与＋給料手当）", ans("D-03", r"^([\d,]+)千円"), wages)
        compare("D-05", f"{w} 役員報酬", ans("D-05", r"第18期は([\d,]+)千円"), amount(sga, "役員報酬"))
    else:
        compare("D-04", f"{w} 従業員の給与（賃金給与＋給料手当）", ans("D-04", r"第17期は([\d,]+)千円"), wages)
        compare("D-05", f"{w} 役員報酬", ans("D-05", r"第17期も([\d,]+)千円"), amount(sga, "役員報酬"))
    compare("A-06", f"{w} 資本金", ans("A-06", r"^([\d,]+)千円"), amount(bs, "資本金"))

    if period == 18:
        for pattern, page, label in [
            (r"材料費([\d,]+)千円", mfg, "当期材料費"),
            (r"労務費([\d,]+)千円", mfg, "当期労務費"),
            (r"給与([\d,]+)千円", mfg, "賃金給与"),
            (r"法定福利費([\d,]+)千円", mfg, "法定福利費"),
            (r"製造経費([\d,]+)千円", mfg, "当期製造経費"),
            (r"水道光熱費([\d,]+)千円", mfg, "水道光熱費"),
            (r"消耗品・包材([\d,]+)千円", mfg, "消耗品・包装材料費"),
            (r"工場の家賃([\d,]+)千円", mfg, "地代家賃"),
            (r"減価償却費([\d,]+)千円", mfg, "減価償却費"),
            (r"修繕費など([\d,]+)千円", mfg, "修繕費その他"),
            (r"売上原価は合計([\d,]+)千円", pl, "売上原価"),
        ]:
            compare("F-09", f"{w} {label}", ans("F-09", pattern), amount(page, label))
        for label, pattern in [(x, rf"{x}([\d,]+)千円") for x in SGA_ITEMS] + [
            ("販売費及び一般管理費合計", r"合計([\d,]+)千円")
        ]:
            compare("F-10", f"{w} {label}", ans("F-10", pattern), amount(sga, label))
        compare("F-11", f"{w} 営業外収益合計", ans("F-11", r"営業外収益([\d,]+)千円"), amount(pl, "営業外収益合計"))
        compare("F-11", f"{w} 支払利息", ans("F-11", r"支払利息）([\d,]+)千円"), amount(pl, "支払利息"))
        compare("F-11", f"{w} 特別な損益はない（経常利益＝税引前当期純利益）", ans_period("F-04", 18), amount(pl, "税引前当期純利益"))
        compare("F-11", f"{w} 法人税等", ans("F-11", r"法人税等([\d,]+)千円"), amount(pl, "法人税、住民税及び事業税"))
        for pattern, label in [
            (r"現金・預金([\d,]+)千円", "現金及び預金"),
            (r"売掛金([\d,]+)千円", "売掛金"),
            (r"棚卸資産([\d,]+)千円", "原材料"),
            (r"その他の流動資産([\d,]+)千円", "その他流動資産"),
            (r"機械装置([\d,]+)千円", "機械及び装置"),
            (r"車両([\d,]+)千円", "車両運搬具"),
            (r"工具・器具([\d,]+)千円", "工具、器具及び備品"),
            (r"敷金・保証金([\d,]+)千円", "敷金及び保証金"),
            (r"ソフトウェア([\d,]+)千円", "ソフトウエア"),
            (r"合計([\d,]+)千円", "資産合計"),
        ]:
            compare("F-12", f"{w} {label}", ans("F-12", pattern), amount(bs, label))
        for pattern, label in [
            (r"買掛金([\d,]+)千円", "買掛金"),
            (r"未払金・未払費用([\d,]+)千円", "未払金及び未払費用"),
            (r"未払法人税等([\d,]+)千円", "未払法人税等"),
            (r"1年以内に返す借入金([\d,]+)千円", "1年内返済予定の長期借入金"),
            (r"その他の流動負債([\d,]+)千円", "その他流動負債"),
            (r"長期借入金([\d,]+)千円", "長期借入金"),
            (r"純資産は([\d,]+)千円", "純資産合計"),
            (r"資本金([\d,]+)千円", "資本金"),
            (r"利益剰余金([\d,]+)千円", "利益剰余金合計"),
            (r"合計([\d,]+)千円", "負債及び純資産合計"),
        ]:
            compare("F-13", f"{w} {label}", ans("F-13", pattern), amount(bs, label))
        compare(
            "F-14",
            f"{w} 借入金（1年内返済予定＋長期）",
            ans("F-14", r"([\d,]+)千円"),
            amount(bs, "1年内返済予定の長期借入金") + amount(bs, "長期借入金"),
        )

    print(f"\n■ {name}：足し算とつながり")
    for total_label, parts in BS_SECTIONS:
        sums_to(bs, total_label, parts, "貸借対照表")
    equals("貸借対照表 資産合計 ＝ 負債及び純資産合計", amount(bs, "資産合計"), amount(bs, "負債及び純資産合計"))
    equals(
        "製造原価報告書 当期材料費 ＝ 期首原材料＋仕入−期末原材料",
        amount(mfg, "当期材料費"),
        amount(mfg, "期首原材料棚卸高") + amount(mfg, "当期原材料仕入高") - amount(mfg, "期末原材料棚卸高"),
    )
    equals("期末原材料棚卸高 ＝ 貸借対照表の原材料", amount(mfg, "期末原材料棚卸高"), amount(bs, "原材料"))
    for total_label, parts in MFG_SECTIONS:
        sums_to(mfg, total_label, parts, "製造原価報告書")
    equals(
        "当期製品製造原価 ＝ 当期総製造費用＋期首仕掛品−期末仕掛品",
        amount(mfg, "当期製品製造原価"),
        amount(mfg, "当期総製造費用") + amount(mfg, "期首仕掛品棚卸高") - amount(mfg, "期末仕掛品棚卸高"),
    )
    sums_to(sga, "販売費及び一般管理費合計", SGA_ITEMS, "販管費内訳書")
    equals("損益計算書と製造原価報告書の当期製品製造原価", amount(pl, "当期製品製造原価"), amount(mfg, "当期製品製造原価"))
    equals(
        "売上原価 ＝ 期首製品＋当期製品製造原価−期末製品",
        amount(pl, "売上原価"),
        amount(pl, "期首製品棚卸高") + amount(pl, "当期製品製造原価") - amount(pl, "期末製品棚卸高"),
    )
    equals("売上総利益 ＝ 売上高−売上原価", amount(pl, "売上総利益"), amount(pl, "売上高") - amount(pl, "売上原価"))
    equals("損益計算書と販管費内訳書の販管費合計", amount(pl, "販売費及び一般管理費合計"), amount(sga, "販売費及び一般管理費合計"))
    equals(
        "営業利益 ＝ 売上総利益−販管費",
        amount(pl, "営業利益"),
        amount(pl, "売上総利益") - amount(pl, "販売費及び一般管理費合計"),
    )
    equals(
        "経常利益 ＝ 営業利益＋営業外収益−営業外費用",
        amount(pl, "経常利益"),
        amount(pl, "営業利益") + amount(pl, "営業外収益合計") - amount(pl, "営業外費用合計"),
    )
    equals(
        "当期純利益 ＝ 税引前当期純利益−法人税等",
        amount(pl, "当期純利益"),
        amount(pl, "税引前当期純利益") - amount(pl, "法人税、住民税及び事業税"),
    )
    opening, change, closing = amounts(eq, "繰越利益剰余金")
    equals("株主資本等変動計算書 当期純利益 ＝ 損益計算書", change, amount(pl, "当期純利益"))
    equals("繰越利益剰余金 当期末 ＝ 当期首＋当期純利益", closing, opening + change)
    equals("株主資本等変動計算書の当期末 ＝ 貸借対照表", closing, amount(bs, "繰越利益剰余金"))
    return {"bs": bs, "pl": pl, "mfg": mfg, "sga": sga, "eq": eq}


def check_across_periods(p17: dict[str, str], p18: dict[str, str]) -> None:
    print("\n■ 第17期と第18期のつながり")
    equals(
        "第18期の繰越利益剰余金の当期首 ＝ 第17期末",
        amounts(p18["eq"], "繰越利益剰余金")[0],
        amount(p17["bs"], "繰越利益剰余金"),
    )
    equals("第18期の期首原材料 ＝ 第17期末の原材料", amount(p18["mfg"], "期首原材料棚卸高"), amount(p17["bs"], "原材料"))


def check_registry() -> None:
    text = "\n".join(read_pages("履歴事項全部証明書.pdf"))
    f = flat(text)
    print("\n■ 履歴事項全部証明書：回答表と照らす")
    number = ANSWERS["A-03"]
    report(
        f"{number[1:5]}-{number[5:7]}-{number[7:]}" in f,
        f"A-03 会社法人等番号 ＝ 法人番号 {number} から先頭の検査用の数字を除いた12桁",
    )
    report(ANSWERS["A-01"] in f, f"A-01 商号：{ANSWERS['A-01']}")
    address = ANSWERS["B-01"].split("。")[0]
    report(f"本店{address}" in f, f"B-01 本店：{address}")
    y, m, d = map(int, re.search(r"(\d{4})年(\d+)月(\d+)日", ANSWERS["A-04"]).groups())
    founded = re.search(r"会社成立の年月日\s*((?:令和|平成)\d+年\d+月\d+日)", text)
    report(
        founded is not None and seireki(founded[1]) == (y, m, d),
        f"A-04 会社成立の年月日：回答表 {y}年{m}月{d}日 ／ PDF {founded[1] if founded else 'なし'}",
    )
    capital = re.search(r"資本金の額\s*金([\d,]+)万円", text)
    report(
        capital is not None and int(capital[1].replace(",", "")) * 10 == ans("A-06", r"^([\d,]+)千円"),
        f"A-06 資本金の額：回答表 {ans('A-06', r'^([\d,]+)千円'):,}千円 ／ PDF 金{capital[1] if capital else '?'}万円",
    )
    shares = re.search(r"発行済株式の総数\s*(\d+)株", text)
    report(
        shares is not None and int(shares[1]) == ans("A-07", r"発行した株は(\d+)株"),
        f"A-07 発行済株式の総数：回答表 {ans('A-07', r'発行した株は(\d+)株')}株 ／ PDF {shares[1] if shares else '?'}株",
    )
    president = president_name()
    director = re.search(r"、取締役の(\S+?)（", ANSWERS["A-09"])[1]
    report(f"代表取締役{president}" in f, f"A-08 代表取締役：{president}")
    report(f"取締役{president}" in f and f"取締役{director}" in f, f"A-09 取締役：{president}、{director}")
    report("監査役" not in f, "A-09 監査役はいない（PDF に監査役の記録がない）")
    issued = re.search(r"発行日\s*((?:令和)\d+年\d+月\d+日)", text)
    print(f"  （発行日：{issued[1]} ＝ {'%d-%02d-%02d' % seireki(issued[1])}）")


def check_tax_certificate() -> None:
    text = "\n".join(read_pages("納税証明書_その2.pdf"))
    f = flat(text)
    print("\n■ 納税証明書（その2）：回答表と照らす")
    report(ANSWERS["A-01"] in f, f"A-01 名称：{ANSWERS['A-01']}")
    report(ANSWERS["B-01"].split("。")[0] in f, "B-01 所在地")
    rows = re.findall(r"((?:令和)\d+年4月1日)〜((?:令和)\d+年3月31日)\s+([\d,]+)", text)
    periods = []
    for start, _end, income in rows:
        # 第1期は2008年4月1日に始まる（A-04）ので、第n期は (2007 + n) 年4月1日に始まる
        period = seireki(start)[0] - 2007
        periods.append(period)
        compare("F-08", f"第{period}期 所得金額", ans_period("F-08", period), int(income.replace(",", "")))
    report(periods == [16, 17, 18], f"直近3期分（第16期〜第18期）がある：{periods}")
    issued = re.search(r"発行日\s*((?:令和)\d+年\d+月\d+日)", text)
    print(f"  （発行日：{issued[1]} ＝ {'%d-%02d-%02d' % seireki(issued[1])}）")


def check_overview(p18: dict[str, str]) -> None:
    pages = read_pages("法人事業概況説明書_第18期.pdf")
    text = "\n".join(pages)
    f = flat(text)
    print("\n■ 法人事業概況説明書（第18期）：回答表と決算書と照らす")
    report(ANSWERS["A-01"] in f and ANSWERS["A-03"] in f, "A-01 法人名、A-03 法人番号")
    report(ANSWERS["B-01"].split("。")[0] in f, "B-01 納税地")
    employees = re.search(r"従業員\s+(\d+)人（正社員\s*(\d+)人、パート\s*(\d+)人）", text)
    c01 = re.search(r"^(\d+)人。正社員(\d+)人とパート(\d+)人", ANSWERS["C-01"]).groups()
    report(
        employees is not None and employees.groups() == c01,
        f"C-01 従業員：回答表 {c01[0]}人（正社員{c01[1]}人、パート{c01[2]}人） ／ PDF {employees.groups() if employees else 'なし'}",
    )
    officers = re.search(r"常勤役員\s+(\d+)人", text)
    a09 = re.search(r"の(\d+)人。", ANSWERS["A-09"])[1]
    report(officers is not None and officers[1] == a09, f"A-09 常勤役員：回答表 {a09}人 ／ PDF {officers[1] if officers else 'なし'}人")
    report(not re.search(r"(合計|計)\s+1[67]人", text), "役員と従業員を足した人数（17人など）を書いていない（C-01 の15人と紛れない）")

    def k(label: str) -> int:
        return amount(text, label) * 1000

    bs, pl, mfg, sga = p18["bs"], p18["pl"], p18["mfg"], p18["sga"]
    for label, from_statements in [
        ("売上高", amount(pl, "売上高")),
        ("売上原価", amount(pl, "売上原価")),
        ("うち原材料仕入高", amount(mfg, "当期原材料仕入高")),
        ("うち労務費", amount(mfg, "当期労務費")),
        ("売上総利益", amount(pl, "売上総利益")),
        ("役員報酬", amount(sga, "役員報酬")),
        ("地代家賃", amount(mfg, "地代家賃")),
        ("営業利益", amount(pl, "営業利益")),
        ("経常利益", amount(pl, "経常利益")),
        ("税引前当期純利益", amount(pl, "税引前当期純利益")),
        ("当期純利益", amount(pl, "当期純利益")),
        ("現金及び預金", amount(bs, "現金及び預金")),
        ("売掛金", amount(bs, "売掛金")),
        ("棚卸資産", amount(bs, "原材料")),
        ("買掛金", amount(bs, "買掛金")),
        ("借入金", amount(bs, "1年内返済予定の長期借入金") + amount(bs, "長期借入金")),
        ("純資産", amount(bs, "純資産合計")),
    ]:
        equals(f"主要科目 {label}（法人事業概況説明書 ／ 決算書）", k(label), from_statements)
    compare("D-03", "従業員給料", ans("D-03", r"^([\d,]+)千円"), k("従業員給料（製造原価の賃金給与を含む）"))
    compare("D-05", "代表者に対する報酬", ans("D-05", r"社長([\d,]+)千円"), k("うち代表者に対する報酬"))
    compare("F-06", "減価償却費", ans_period("F-06", 18), k("減価償却費"))
    compare("F-07", "法定福利費", ans_period("F-07", 18), k("法定福利費"))
    months = re.findall(r"^\s*((?:令和\d+年)?\d+月)\s+([\d,]+)\s*$", pages[-1], re.M)
    monthly = sum(int(v.replace(",", "")) for _, v in months) * 1000
    report(len(months) == 12, f"月別の売上高が12か月ある：{len(months)}か月")
    compare("F-01", "月別の売上高の12か月の合計", ans_period("F-01", 18), monthly)
    compare("F-01", "月別の売上高の「計」", ans_period("F-01", 18), k("計"))


def main() -> int:
    print("■ 書類の一覧（種類・形式・ページ数）と、どのページにも「架空のテスト用データ」があるか")
    for name, kind in DOCUMENTS:
        pages = read_pages(name)
        marked = [i for i, t in enumerate(pages, start=1) if MARK in flat(t)]
        report(
            len(marked) == len(pages),
            f"{kind}｜PDF｜{len(pages)}ページ｜{name}（印のあるページ {len(marked)}/{len(pages)}）",
        )

    p17 = check_statements(17)
    p18 = check_statements(18)
    check_across_periods(p17, p18)
    check_registry()
    check_tax_certificate()
    check_overview(p18)

    print("\n■ 書類どうしの社名・所在地・代表者")
    address = ANSWERS["B-01"].split("。")[0]
    president = president_name()
    for name, _kind in DOCUMENTS:
        f = flat("\n".join(read_pages(name)))
        has_president = president in f if not name.startswith("決算書") else True
        report(
            ANSWERS["A-01"] in f and address in f and has_president,
            f"{name}：社名・所在地{'・代表者' if not name.startswith('決算書') else ''}が回答表と同じ",
        )

    print()
    if failures:
        print(f"合わないもの {len(failures)}件")
        return 1
    print("すべて合いました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
