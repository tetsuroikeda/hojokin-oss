# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の書類の前半を、回答表と照らす。

make_documents.py の中の数字ではなく、できたファイル（PDF・Word・Excel）から取り出した文字を、
回答表.md の文と照らす。あわせて、決算書の足し算、第34期・第35期・第36期のつながり、書類どうしの食い違い、
名簿と履歴事項全部証明書の一致、どのページ・シートにも「架空のテスト用データ」があることを確かめる。
合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社_町工場/書類/check_documents.py
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ANSWER_SHEET = HERE.parent / "回答表.md"
MARK = "架空のテスト用データ"
AS_OF = dt.date(2026, 11, 1)  # 名簿の日付

DOCUMENTS = [
    ("決算書_第34期.pdf", "決算書（第34期）"),
    ("決算書_第35期.pdf", "決算書（第35期）"),
    ("決算書_第36期.pdf", "決算書（第36期）"),
    ("履歴事項全部証明書.pdf", "履歴事項全部証明書"),
    ("納税証明書_その2.pdf", "納税証明書（その2）"),
    ("法人事業概況説明書_第36期.pdf", "法人事業概況説明書（第36期）"),
]
OFFICERS = "役員名簿.docx"
SHAREHOLDERS = "株主名簿.docx"
WORKERS = "労働者名簿.xlsx"

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


def ans(answer_id: str, pattern: str) -> int:
    """回答表の行から、千円の数字を1つ取る。"""
    return int(find(answer_id, pattern)[1].replace(",", ""))


def ans_period(answer_id: str, period: int) -> int:
    return ans(answer_id, rf"第{period}期([\d,]+)千円")


def president_name() -> str:
    """A-08 の代表者の名前（空白を除く）。"""
    return find("A-08", r"代表取締役\s*(\S+\s?\S+)（")[1].replace(" ", "")


def director_name() -> str:
    return find("A-09", r"と、取締役の(\S+?)（")[1]


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
        f"{answer_id} {what}：回答表 {answer_thousand:,}千円 ／ 書類 {fmt(pdf_yen)}",
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


def founded_year() -> int:
    return int(find("A-04", r"(\d{4})年")[1])


def period_of(start: str) -> int:
    """事業年度の始まりの日（4月1日）から、第何期かを出す。第1期は設立の年（A-04）に始まる。"""
    return seireki(start)[0] - founded_year() + 1


# ---------------------------------------------------------------------------
# 決算書
# ---------------------------------------------------------------------------

BS_SECTIONS = [
    ("流動資産合計", ["現金及び預金", "受取手形", "売掛金", "原材料", "仕掛品", "その他流動資産"]),
    ("有形固定資産合計", ["建物附属設備", "機械及び装置", "車両運搬具", "工具、器具及び備品"]),
    ("無形固定資産合計", ["ソフトウエア"]),
    ("投資その他の資産合計", ["敷金及び保証金", "その他の投資"]),
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
    ("当期外注費", ["外注加工費"]),
    ("当期製造経費", ["電力費", "工具・消耗品費", "地代家賃", "減価償却費", "修繕費", "その他製造経費"]),
    ("当期総製造費用", ["当期材料費", "当期労務費", "当期外注費", "当期製造経費"]),
]
SGA_ITEMS = [
    "役員報酬", "給料手当", "法定福利費", "福利厚生費", "荷造運賃", "旅費交通費", "通信費", "広告宣伝費",
    "支払手数料", "租税公課", "保険料", "減価償却費", "リース料", "消耗品費", "交際費", "その他",
]


def check_statements(period: int) -> dict[str, str]:
    name = f"決算書_第{period}期.pdf"
    pages = read_pages(name)
    bs = find_page(pages, "貸借対照表")
    pl = find_page(pages, "損益計算書")
    mfg = find_page(pages, "製造原価報告書")
    sga = find_page(pages, "販売費及び一般管理費内訳書")
    eq = find_page(pages, "株主資本等変動計算書")
    notes = find_page(pages, "個別注記表")
    w = f"第{period}期"

    print(f"\n■ {name}：回答表と照らす")
    report(len(pages) == 7, f"{w} 表紙と6つの表で7ページ：{len(pages)}ページ")
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
    if period == 36:
        compare("D-03", f"{w} 従業員の給与（賃金給与＋給料手当）", ans("D-03", r"^([\d,]+)千円"), wages)
        compare("D-05", f"{w} 役員報酬", ans("D-05", r"第36期は([\d,]+)千円"), amount(sga, "役員報酬"))
    else:
        # D-04 は「第35期は…、第34期は…」、D-05 は「第35期も…、第34期は…」
        compare("D-04", f"{w} 従業員の給与（賃金給与＋給料手当）", ans("D-04", rf"第{period}期は([\d,]+)千円"), wages)
        compare("D-05", f"{w} 役員報酬", ans("D-05", rf"第{period}期[もは]([\d,]+)千円"), amount(sga, "役員報酬"))
    compare("A-06", f"{w} 資本金", ans("A-06", r"^([\d,]+)千円"), amount(bs, "資本金"))
    shares = ans("A-07", r"発行した株は(\d+)株")
    report(f"普通株式{shares}株" in flat(notes), f"A-07 {w} 個別注記表の発行済株式 {shares}株")

    if period == 36:
        for pattern, page, label in [
            (r"材料費([\d,]+)千円", mfg, "当期材料費"),
            (r"外注加工費（[^）]*）([\d,]+)千円", mfg, "外注加工費"),
            (r"労務費([\d,]+)千円", mfg, "当期労務費"),
            (r"給与([\d,]+)千円", mfg, "賃金給与"),
            (r"法定福利費([\d,]+)千円", mfg, "法定福利費"),
            (r"製造経費([\d,]+)千円", mfg, "当期製造経費"),
            (r"電力費([\d,]+)千円", mfg, "電力費"),
            (r"工具・消耗品費([\d,]+)千円", mfg, "工具・消耗品費"),
            (r"工場の家賃([\d,]+)千円", mfg, "地代家賃"),
            (r"減価償却費([\d,]+)千円", mfg, "減価償却費"),
            (r"修繕費([\d,]+)千円", mfg, "修繕費"),
            (r"その他([\d,]+)千円", mfg, "その他製造経費"),
            (r"売上原価は合計([\d,]+)千円", mfg, "当期総製造費用"),
            (r"売上原価は合計([\d,]+)千円", pl, "売上原価"),
        ]:
            compare("F-09", f"{w} {label}", ans("F-09", pattern), amount(page, label))
        for label, pattern in [(x, rf"{x}([\d,]+)千円") for x in SGA_ITEMS] + [
            ("販売費及び一般管理費合計", r"合計([\d,]+)千円")
        ]:
            compare("F-10", f"{w} {label}", ans("F-10", pattern), amount(sga, label))
        compare("F-11", f"{w} 営業外収益合計", ans("F-11", r"営業外収益([\d,]+)千円"), amount(pl, "営業外収益合計"))
        compare("F-11", f"{w} 支払利息", ans("F-11", r"支払利息）([\d,]+)千円"), amount(pl, "支払利息"))
        compare("F-11", f"{w} 特別な損益はない（経常利益＝税引前当期純利益）", ans_period("F-04", 36), amount(pl, "税引前当期純利益"))
        compare("F-11", f"{w} 法人税等", ans("F-11", r"法人税等([\d,]+)千円"), amount(pl, "法人税、住民税及び事業税"))
        for pattern, value, label in [
            (r"現金・預金([\d,]+)千円", amount(bs, "現金及び預金"), "現金及び預金"),
            (r"受取手形([\d,]+)千円", amount(bs, "受取手形"), "受取手形"),
            (r"売掛金([\d,]+)千円", amount(bs, "売掛金"), "売掛金"),
            (r"棚卸資産（材料と仕掛品）([\d,]+)千円", amount(bs, "原材料") + amount(bs, "仕掛品"), "原材料＋仕掛品"),
            (r"その他の流動資産([\d,]+)千円", amount(bs, "その他流動資産"), "その他流動資産"),
            (r"建物附属設備([\d,]+)千円", amount(bs, "建物附属設備"), "建物附属設備"),
            (r"機械装置([\d,]+)千円", amount(bs, "機械及び装置"), "機械及び装置"),
            (r"工具・器具・備品([\d,]+)千円", amount(bs, "工具、器具及び備品"), "工具、器具及び備品"),
            (r"車両([\d,]+)千円", amount(bs, "車両運搬具"), "車両運搬具"),
            (r"ソフトウェア([\d,]+)千円", amount(bs, "ソフトウエア"), "ソフトウエア"),
            (r"敷金・保証金([\d,]+)千円", amount(bs, "敷金及び保証金"), "敷金及び保証金"),
            (r"その他の投資([\d,]+)千円", amount(bs, "その他の投資"), "その他の投資"),
            (r"合計([\d,]+)千円", amount(bs, "資産合計"), "資産合計"),
        ]:
            compare("F-12", f"{w} {label}", ans("F-12", pattern), value)
        for pattern, label in [
            (r"買掛金([\d,]+)千円", "買掛金"),
            (r"未払金・未払費用([\d,]+)千円", "未払金及び未払費用"),
            (r"未払法人税等([\d,]+)千円", "未払法人税等"),
            (r"1年以内に返す長期借入金([\d,]+)千円", "1年内返済予定の長期借入金"),
            (r"その他の流動負債([\d,]+)千円", "その他流動負債"),
            (r"、長期借入金([\d,]+)千円", "長期借入金"),
            (r"純資産は([\d,]+)千円", "純資産合計"),
            (r"資本金([\d,]+)千円", "資本金"),
            (r"利益剰余金([\d,]+)千円", "利益剰余金合計"),
            (r"）。合計([\d,]+)千円", "負債及び純資産合計"),
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
    equals("期末仕掛品棚卸高 ＝ 貸借対照表の仕掛品", amount(mfg, "期末仕掛品棚卸高"), amount(bs, "仕掛品"))
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
    report("配当は行っていない" in flat(eq), "剰余金の配当はしていない")
    return {"bs": bs, "pl": pl, "mfg": mfg, "sga": sga, "eq": eq}


def check_across_periods(before: dict[str, str], after: dict[str, str], period: int) -> None:
    """第(period−1)期末と第period期の期首のつながりを確かめる。"""
    a, b = f"第{period - 1}期", f"第{period}期"
    print(f"\n■ {a}と{b}のつながり")
    equals(
        f"{b}の繰越利益剰余金の当期首 ＝ {a}末",
        amounts(after["eq"], "繰越利益剰余金")[0],
        amount(before["bs"], "繰越利益剰余金"),
    )
    # 第36期末の利益剰余金（F-13）から、第period期〜第36期の当期純利益（F-05）を引くと、第(period−1)期末になる（配当なし）
    later = range(period, 37)
    retained36 = ans("F-13", r"利益剰余金([\d,]+)千円")
    want = (retained36 - sum(ans_period("F-05", n) for n in later)) * 1000
    minus = "".join(f" − F-05 の第{n}期 {ans_period('F-05', n):,}千円" for n in later)
    equals(f"{a}末の利益剰余金 ＝ F-13 の {retained36:,}千円{minus}（配当なし）", amount(before["bs"], "利益剰余金合計"), want)
    equals(f"{b}の期首原材料 ＝ {a}末の原材料", amount(after["mfg"], "期首原材料棚卸高"), amount(before["bs"], "原材料"))
    equals(f"{b}の期首仕掛品 ＝ {a}末の仕掛品", amount(after["mfg"], "期首仕掛品棚卸高"), amount(before["bs"], "仕掛品"))
    equals("資本金は変わらない", amount(after["bs"], "資本金"), amount(before["bs"], "資本金"))
    loans_before = amount(before["bs"], "1年内返済予定の長期借入金") + amount(before["bs"], "長期借入金")
    loans_after = amount(after["bs"], "1年内返済予定の長期借入金") + amount(after["bs"], "長期借入金")
    equals(
        f"借入金の減り ＝ {a}末の1年内返済予定（{b}に新しい借入なし）",
        loans_before - loans_after,
        amount(before["bs"], "1年内返済予定の長期借入金"),
    )


# ---------------------------------------------------------------------------
# 登記・納税・概況説明書
# ---------------------------------------------------------------------------


def registry_facts() -> dict:
    text = "\n".join(read_pages("履歴事項全部証明書.pdf"))
    f = flat(text)
    address = re.search(r"(東京都葛飾区[^号]+?号)代表取締役", f)[1]
    reappointed = seireki(re.search(r"((?:令和)\d+年\d+月\d+日)重任", f)[1])
    shares = int(re.search(r"発行済株式の総数(\d+)株", f)[1])
    return {"text": text, "flat": f, "address": address, "reappointed": reappointed, "shares": shares}


def check_registry() -> None:
    reg = registry_facts()
    text, f = reg["text"], reg["flat"]
    print("\n■ 履歴事項全部証明書：回答表と照らす")
    number = ANSWERS["A-03"]
    report(
        f"{number[1:5]}-{number[5:7]}-{number[7:]}" in f,
        f"A-03 会社法人等番号 ＝ 法人番号 {number} から先頭の検査用の数字を除いた12桁",
    )
    report(ANSWERS["A-01"] in f, f"A-01 商号：{ANSWERS['A-01']}")
    address = ANSWERS["B-01"].split("。")[0]
    report(f"本店{address}" in f, f"B-01 本店：{address}")
    y, m, d = map(int, find("A-04", r"(\d{4})年(\d+)月(\d+)日").groups())
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
    shares = ans("A-07", r"発行した株は(\d+)株")
    report(reg["shares"] == shares, f"A-07 発行済株式の総数：回答表 {shares}株 ／ PDF {reg['shares']}株")
    president = president_name()
    director = director_name()
    report(f"代表取締役{president}" in f, f"A-08 代表取締役：{president}")
    report(f"取締役{president}" in f and f"取締役{director}" in f, f"A-09 取締役：{president}、{director}")
    report("監査役" not in f, "A-09 監査役はいない（PDF に監査役の記録がない）")
    issued = seireki(re.search(r"発行日\s*((?:令和)\d+年\d+月\d+日)", text)[1])
    report(issued == (2026, 10, 22), f"発行日 2026年10月22日 ／ PDF {'%d-%02d-%02d' % issued}")
    report(reg["reappointed"] <= issued, f"重任の日 {'%d-%02d-%02d' % reg['reappointed']} は発行日より前")


def check_tax_certificate() -> None:
    text = "\n".join(read_pages("納税証明書_その2.pdf"))
    f = flat(text)
    print("\n■ 納税証明書（その2）：回答表と照らす")
    report(ANSWERS["A-01"] in f, f"A-01 名称：{ANSWERS['A-01']}")
    report(ANSWERS["B-01"].split("。")[0] in f, "B-01 所在地")
    rows = re.findall(r"((?:令和)\d+年4月1日)〜((?:令和)\d+年3月31日)\s+([\d,]+)", text)
    periods = []
    for start, _end, income in rows:
        period = period_of(start)
        periods.append(period)
        compare("F-08", f"第{period}期 所得金額", ans_period("F-08", period), int(income.replace(",", "")))
    report(periods == [34, 35, 36], f"直近3期分（第34期〜第36期）がある：{periods}")
    issued = seireki(re.search(r"発行日\s*((?:令和)\d+年\d+月\d+日)", text)[1])
    report(issued == (2026, 10, 23), f"発行日 2026年10月23日 ／ PDF {'%d-%02d-%02d' % issued}")


def check_overview(p36: dict[str, str]) -> None:
    pages = read_pages("法人事業概況説明書_第36期.pdf")
    text = "\n".join(pages)
    f = flat(text)
    print("\n■ 法人事業概況説明書（第36期）：回答表と決算書と照らす")
    report(ANSWERS["A-01"] in f and ANSWERS["A-03"] in f, "A-01 法人名、A-03 法人番号")
    report(ANSWERS["B-01"].split("。")[0] in f, "B-01 納税地")
    employees = re.search(r"従業員\s+(\d+)人（正社員\s*(\d+)人、パート\s*(\d+)人）", text)
    c01 = find("C-01", r"^(\d+)人。正社員(\d+)人とパート(\d+)人").groups()
    report(
        employees is not None and employees.groups() == c01,
        f"C-01 従業員：回答表 {c01[0]}人（正社員{c01[1]}人、パート{c01[2]}人） ／ PDF {employees.groups() if employees else 'なし'}",
    )
    officers = re.search(r"役員\s+(\d+)人", text)
    a09 = find("A-09", r"の(\d+)人。")[1]
    report(officers is not None and officers[1] == a09, f"A-09 役員：回答表 {a09}人 ／ PDF {officers[1] if officers else 'なし'}人")
    report("常勤役員" not in f, "取締役が常勤かは回答表にないので、「常勤役員」と書いていない")
    report(not re.search(r"(合計|計)\s+20人", text), "役員と従業員を足した人数（20人）を書いていない（C-01 の18人と紛れない）")

    def k(label: str) -> int:
        return amount(text, label) * 1000

    bs, pl, mfg, sga = p36["bs"], p36["pl"], p36["mfg"], p36["sga"]
    for label, from_statements in [
        ("売上高", amount(pl, "売上高")),
        ("売上原価", amount(pl, "売上原価")),
        ("うち原材料仕入高", amount(mfg, "当期原材料仕入高")),
        ("うち労務費", amount(mfg, "当期労務費")),
        ("うち外注加工費", amount(mfg, "外注加工費")),
        ("売上総利益", amount(pl, "売上総利益")),
        ("役員報酬", amount(sga, "役員報酬")),
        ("地代家賃", amount(mfg, "地代家賃")),
        ("営業利益", amount(pl, "営業利益")),
        ("経常利益", amount(pl, "経常利益")),
        ("税引前当期純利益", amount(pl, "税引前当期純利益")),
        ("当期純利益", amount(pl, "当期純利益")),
        ("現金及び預金", amount(bs, "現金及び預金")),
        ("受取手形・売掛金", amount(bs, "受取手形") + amount(bs, "売掛金")),
        ("棚卸資産", amount(bs, "原材料") + amount(bs, "仕掛品")),
        ("買掛金", amount(bs, "買掛金")),
        ("借入金", amount(bs, "1年内返済予定の長期借入金") + amount(bs, "長期借入金")),
        ("純資産", amount(bs, "純資産合計")),
    ]:
        equals(f"主要科目 {label}（法人事業概況説明書 ／ 決算書）", k(label), from_statements)
    compare("D-03", "従業員給料", ans("D-03", r"^([\d,]+)千円"), k("従業員給料（製造原価の賃金給与を含む）"))
    compare("D-05", "代表者に対する報酬", ans("D-05", r"社長([\d,]+)千円"), k("うち代表者に対する報酬"))
    compare("F-06", "減価償却費", ans_period("F-06", 36), k("減価償却費"))
    compare("F-07", "法定福利費", ans_period("F-07", 36), k("法定福利費"))
    compare("F-14", "借入金", ans("F-14", r"([\d,]+)千円"), k("借入金"))
    months = re.findall(r"^\s*((?:令和\d+年)?\d+月)\s+([\d,]+)\s*$", pages[-1], re.M)
    monthly = sum(int(v.replace(",", "")) for _, v in months) * 1000
    report(len(months) == 12, f"月別の売上高が12か月ある：{len(months)}か月")
    compare("F-01", "月別の売上高の12か月の合計", ans_period("F-01", 36), monthly)
    compare("F-01", "月別の売上高の「計」", ans_period("F-01", 36), k("計"))


# ---------------------------------------------------------------------------
# 名簿
# ---------------------------------------------------------------------------


def docx_text(name: str) -> tuple[list[list[list[str]]], str, str, str]:
    doc = Document(str(HERE / name))
    tables = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
    body = "\n".join(p.text for p in doc.paragraphs)
    head = "\n".join(p.text for s in doc.sections for p in s.header.paragraphs)
    foot = "\n".join(p.text for s in doc.sections for p in s.footer.paragraphs)
    return tables, body, head, foot


def check_officers(reg: dict) -> dict[str, str]:
    print(f"\n■ {OFFICERS}：回答表と履歴事項全部証明書と照らす")
    tables, body, head, foot = docx_text(OFFICERS)
    report(MARK in head and MARK in foot, f"{OFFICERS}：頭と足に「{MARK}」（どのページにも出る）")
    rows = tables[0][1:]
    report(len(rows) == 2, f"A-09 役員は {len(rows)} 人（回答表は2人）")
    by_role = {r[0]: r for r in rows}
    p = by_role.get("代表取締役", [""] * 7)
    d = by_role.get("取締役", [""] * 7)
    president = president_name()
    born = find("A-08", r"(\d{4})年生まれ")[1]
    report(president in flat(p[1]), f"A-08 代表取締役「{president}」")
    kana = find("A-08", r"（(\S+ \S+)）")[1]
    report(kana in p[1], f"A-08 読み「{kana}」")
    report(p[2].startswith(f"{born}年"), f"A-08 生まれた年 {born}年 ／ 名簿 {p[2]}")
    report(director_name() in flat(d[1]), f"A-09 取締役「{director_name()}」")
    report("監査役" in body and "置いていません" in body, "A-09 監査役はいない")
    report("母" in body and "別に住んで" in body and "同居" not in body, "A-09 取締役は社長の母で、別に住んでいる")
    report("経理" in d[6], "A-09 取締役の担当は経理")
    report(p[4] == reg["address"], f"代表取締役の住所 ＝ 履歴事項全部証明書（{reg['address']}）")
    report(d[4] and d[4] != p[4], f"取締役の住所は代表取締役と別（{d[4]}）")
    y, m, dd = reg["reappointed"]
    for r in rows:
        report(f"{y}年{m}月{dd}日重任" in r[5], f"{r[0]}の重任の日 ＝ 履歴事項全部証明書（{y}年{m}月{dd}日）")
    a05 = find("A-05", r"(\d{4})年に今の社長が代表を継いだ")[1]
    report(p[5].startswith(f"{a05}年"), f"A-05 代表の就任 {a05}年 ／ 名簿 {p[5]}")
    return {"president": p[4], "director": d[4]}


def check_shareholders(reg: dict, addresses: dict[str, str]) -> None:
    print(f"\n■ {SHAREHOLDERS}：回答表と履歴事項全部証明書と照らす")
    tables, body, head, foot = docx_text(SHAREHOLDERS)
    report(MARK in head and MARK in foot, f"{SHAREHOLDERS}：頭と足に「{MARK}」（どのページにも出る）")
    rows = [r for r in tables[0][1:] if r[0]]
    total_row = [r for r in tables[0][1:] if r[1] == "合計"][0]
    surname = president_name()[:2]
    want = {k: int(v) for k, v in re.findall(rf"({surname}\S+?)が(\d+)株", ANSWERS["A-07"])}
    total = ans("A-07", r"発行した株は(\d+)株")
    got = {flat(r[1]): int(re.search(r"(\d+)株", r[3])[1]) for r in rows}
    report(len(want) == 2 and got == want, f"A-07 株主と株の数：回答表 {want} ／ 名簿 {got}")
    report(sum(got.values()) == total == int(re.search(r"(\d+)株", total_row[3])[1]), f"A-07 合計 {total}株")
    report(reg["shares"] == total, f"履歴事項全部証明書の発行済株式の総数 {reg['shares']}株 ＝ 回答表 {total}株")
    report(f"総数　{total}株" in body, "名簿の頭の発行済株式の総数")
    by_name = {flat(r[1]): r[2] for r in rows}
    report(
        by_name.get(president_name()) == addresses["president"] and by_name.get(director_name()) == addresses["director"],
        "株主の住所 ＝ 役員名簿の住所",
    )
    report("ほかの会社" in body, "A-07 ほかの会社は株を持っていない")


def age(born: dt.date, on: dt.date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def check_workers() -> None:
    print(f"\n■ {WORKERS}：回答表と照らす")
    wb = load_workbook(HERE / WORKERS)
    for ws in wb.worksheets:
        report(
            MARK in str(ws["A1"].value) and MARK in ws.oddHeader.center.text and MARK in ws.oddFooter.center.text,
            f"{WORKERS}「{ws.title}」：1行目と、印刷の頭と足に「{MARK}」",
        )
    ws = wb["労働者名簿"]
    header = [c.value for c in ws[5]]
    col = {name: i for i, name in enumerate(header)}
    people = [[c.value for c in row] for row in ws.iter_rows(min_row=6) if row[0].value is not None]

    def v(p: list, key: str):
        return p[col[key]]

    total = int(find("C-01", r"^(\d+)人")[1])
    regular_n = int(find("C-01", r"正社員(\d+)人")[1])
    part_n = int(find("C-01", r"パート(\d+)人")[1])
    regular = [p for p in people if v(p, "雇用の形態") == "正社員"]
    parts = [p for p in people if v(p, "雇用の形態") == "パート"]
    report(len(people) == total, f"C-01 従業員 {total}人 ／ 名簿 {len(people)}人")
    report(len(regular) == regular_n and len(parts) == part_n, f"C-01 正社員{regular_n}人・パート{part_n}人")
    officers = {president_name(), director_name()}
    report(not any(flat(v(p, "氏名")) in officers for p in people), "C-01 役員は入れていない")
    surname = president_name()[:2]
    report(not any(flat(v(p, "氏名")).startswith(surname) for p in people), f"C-08 家族の従業員はいない（{surname}の名字の人がいない）")

    def counts(answer_id: str) -> dict[str, int]:
        text = re.sub(r"（.*?）", "", ANSWERS[answer_id])
        return {k.strip(): int(n) for k, n in re.findall(r"([^、。\d]+?)(\d+)人", text)}

    def jobs(group: list) -> dict[str, int]:
        got: dict[str, int] = {}
        for p in group:
            job = re.sub(r"（.*?）", "", v(p, "従事する業務の種類"))
            got[job] = got.get(job, 0) + 1
        return got

    report(jobs(regular) == counts("C-02"), f"C-02 正社員の内訳：回答表 {counts('C-02')} ／ 名簿 {jobs(regular)}")
    report(jobs(parts) == counts("C-03"), f"C-03 パートの内訳：回答表 {counts('C-03')} ／ 名簿 {jobs(parts)}")

    # 加工の10人の機械が、G-02 の台数（マシニングセンタ5台・うち5軸1台、NC旋盤4台、複合加工機1台）と合う
    machines = [re.search(r"（(.*?)）", v(p, "従事する業務の種類"))[1] for p in regular if v(p, "従事する業務の種類").startswith("加工")]
    mc = sum("マシニングセンタ" in m for m in machines)
    five = sum(m.startswith("5軸") for m in machines)
    lathe = machines.count("NC旋盤")
    multi = machines.count("複合加工機")
    g02 = find("G-02", r"マシニングセンタ(\d+)台（うち5軸が(\d+)台）、NC旋盤(\d+)台、複合加工機(\d+)台").groups()
    report(
        (mc, five, lathe, multi) == tuple(int(x) for x in g02),
        f"G-02 加工の人の受け持ち：マシニングセンタ{mc}人（うち5軸{five}人）・NC旋盤{lathe}人・複合加工機{multi}人 ／ 機械 {g02}",
    )

    daily, weekly = (int(x) for x in find("C-04", r"1日(\d+)時間、週(\d+)時間").groups())
    report(
        all(v(p, "1日の所定労働時間") == daily and v(p, "週の所定労働時間") == weekly
            and v(p, "1日の所定労働時間") * v(p, "週の所定労働日数") == v(p, "週の所定労働時間") for p in regular),
        f"C-04 正社員は1日{daily}時間・週{weekly}時間",
    )
    ph, pd, pw = (int(x) for x in find("C-05", r"1日(\d+)時間・週(\d+)日（週(\d+)時間）").groups())
    report(
        all((v(p, "1日の所定労働時間"), v(p, "週の所定労働日数"), v(p, "週の所定労働時間")) == (ph, pd, pw) for p in parts),
        f"C-05 パートは2人とも1日{ph}時間・週{pd}日（週{pw}時間）",
    )
    report(all(v(p, "契約の期間") == "期間の定めなし" for p in parts), "C-06 パートは2人とも期間の定めなし")
    years = int(find("C-06", r"雇ってから(\d+)年以上")[1])
    report(
        all(age(v(p, "雇入れの年月日").date(), AS_OF) >= years for p in parts),
        f"C-06 パートは2人とも雇ってから{years}年以上（{AS_OF}）",
    )
    report(all(v(p, "契約の期間") == "期間の定めなし" for p in regular), "正社員は期間の定めなし")

    ages = [age(v(p, "生年月日").date(), AS_OF) for p in regular]
    mean = sum(ages) / len(ages)
    want_mean = int(find("C-13", r"正社員の平均は(\d+)歳")[1])
    report(round(mean) == want_mean, f"C-13 正社員の平均年齢：回答表 {want_mean}歳 ／ 名簿 {mean:.1f}歳（{AS_OF}の年齢）")
    chief = [p for p in regular if v(p, "従事する業務の種類") == "工場長"][0]
    chief_age = int(find("C-13", r"工場長は(\d+)歳")[1])
    report(age(v(chief, "生年月日").date(), AS_OF) == chief_age, f"C-13 工場長は{chief_age}歳")

    # 期末の人数（L-16）と、試用期間中の人がいない（C-07）、1年採用できていない（C-11）
    hired = [v(p, "雇入れの年月日").date() for p in people]
    end34 = sum(h <= dt.date(2024, 3, 31) for h in hired)
    end35 = sum(h <= dt.date(2025, 3, 31) for h in hired)
    n34 = int(find("L-16", r"第34期末は(\d+)人")[1])
    n35 = int(find("L-16", r"第35期末は(\d+)人")[1])
    report(end34 == n34 and end35 == n35, f"L-16 雇入れの日から数えた期末の人数：第34期末 {end34}人・第35期末 {end35}人（回答表 {n34}人・{n35}人）")
    report(max(hired) <= dt.date(2025, 3, 31), f"C-07・C-11 第36期の初めより後に雇った人はいない（いちばん新しい雇入れ {max(hired)}）")
    report(all(not v(p, "退職・死亡の年月日と事由") for p in people), "在籍している人だけ（退職の日が空いている）")


# ---------------------------------------------------------------------------


def main() -> int:
    print("■ 書類の一覧（種類・形式・ページ数）と、どのページにも「架空のテスト用データ」があるか")
    for name, kind in DOCUMENTS:
        pages = read_pages(name)
        marked = [i for i, t in enumerate(pages, start=1) if flat(t).count(MARK) >= 2]
        report(
            len(marked) == len(pages),
            f"{kind}｜PDF｜{len(pages)}ページ｜{name}（頭と足に印のあるページ {len(marked)}/{len(pages)}）",
        )

    p34 = check_statements(34)
    p35 = check_statements(35)
    p36 = check_statements(36)
    check_across_periods(p34, p35, 35)
    check_across_periods(p35, p36, 36)
    check_registry()
    check_tax_certificate()
    check_overview(p36)

    reg = registry_facts()
    addresses = check_officers(reg)
    check_shareholders(reg, addresses)
    check_workers()

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
        for f in failures:
            print(f"  × {f}")
        return 1
    print("すべて合いました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
