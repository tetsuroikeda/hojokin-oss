# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4", "python-docx>=1.1", "openpyxl>=3.1", "pillow>=10"]
# ///
"""デモの会社の、会社の資料と過去の書類（TASKS D8、D8b）を、回答表と D2a・D2b の書類と照らす。

make_materials.py の中の数字ではなく、できたファイルから取り出した文字を照らす。
- どのページ・シート・写真にも「架空のテスト用データ」があるか
- 会社案内・商品のご案内・議事録・既存事業の内訳が、回答表と D2a の決算書・法人事業概況説明書、D2b の労働者名簿と合うか
- 過去の申請（2025年 ものづくり補助金）が J-06 に合い、第17期の数字が D2a の決算書と合うか。
  目標値の計算と、通知に理由が書かれていないこと。不採択の後の相談で受けた指摘のメモ（D8b）の指摘が、
  申請書の弱い所と対応し、議事録の振り返りと食い違わないか。相談先が実在の団体を特定しないか
- 議事録にしかない事実が、回答表・ほかの書類・ほかの材料のどこにもないか（T8-7 の材料）
合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/会社の資料/check_materials.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

SCRIPT_DIR = Path(__file__).resolve().parent
HERE = SCRIPT_DIR / "材料"  # 材料だけを置くフォルダ
COMPANY_DIR = SCRIPT_DIR.parent / "デモの会社"
DOCS_DIR = COMPANY_DIR / "書類"
ANSWER_SHEET = COMPANY_DIR / "回答表.md"
MARK = "架空のテスト用データ"

PROFILE = "会社案内.pdf"
PRODUCTS = "商品のご案内.pdf"
MINUTES = "議事録_2026-09-10_工場の会議.docx"
BREAKDOWN = "既存事業の売上と経費_第17期_第18期.xlsx"
PHOTOS = ["作業の写真_1_盛り付け.jpg", "作業の写真_2_計量.jpg", "作業の写真_3_包装.jpg", "作業の写真_4_ラベル貼りと検品.jpg"]
PAST_PLAN = "2025_ものづくり補助金_事業計画書の控え.docx"
PAST_NOTICE = "2025_ものづくり補助金_採択結果の通知.pdf"
PAST_MEMO = "2025_ものづくり補助金_不採択の後の相談のメモ.docx"

# 議事録にしかない事実（T8-7 で、計画書と根拠対照表に出てくるかを見る材料）
MINUTES_ONLY = [
    ("きざみ食とペースト食の盛り付けは、普通食の約2倍の時間（1食あたり約30秒と約15秒）", r"約30秒"),
    ("盛り付けから検品までの延べ約38時間の工程ごとの内訳（盛り付け約18時間など）", r"盛り付け約18時間"),
    ("古いシール機が、この半年で4回止まった", r"4回止まった"),
    ("2025年度のクレーム7件のうち5件は、5時から6時に作ったもの", r"7件のうち5件"),
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


def find(answer_id: str, pattern: str) -> re.Match:
    m = re.search(pattern, ANSWERS[answer_id])
    if not m:
        raise SystemExit(f"回答表の {answer_id} に「{pattern}」が見つかりません：{ANSWERS[answer_id]}")
    return m


def num(text: str) -> int:
    return int(text.replace(",", ""))


def period_value(answer_id: str, period: int) -> int:
    return num(find(answer_id, rf"第{period}期[はも]?([\d,]+)千円")[1])


def flat(text: str) -> str:
    return re.sub(r"[ 　\n]", "", text)


# ---------------------------------------------------------------------------
# ファイルから文字を取り出す
# ---------------------------------------------------------------------------


def pdf_pages(path: Path) -> list[str]:
    return [p.extract_text(extraction_mode="layout") for p in PdfReader(str(path)).pages]


def docx_parts(path: Path) -> tuple[str, list[list[list[str]]], str, str]:
    doc = Document(str(path))
    body = "\n".join(p.text for p in doc.paragraphs)
    tables = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
    head = "\n".join(p.text for s in doc.sections for p in s.header.paragraphs)
    foot = "\n".join(p.text for s in doc.sections for p in s.footer.paragraphs)
    return body, tables, head, foot


def docx_text(path: Path) -> str:
    body, tables, _, _ = docx_parts(path)
    return body + "\n" + "\n".join("\t".join(row) for t in tables for row in t)


def xlsx_text(path: Path) -> str:
    wb = load_workbook(path)
    return "\n".join(
        "\t".join("" if v is None else str(v) for v in row) for ws in wb.worksheets for row in ws.iter_rows(values_only=True)
    )


def any_text(path: Path) -> str:
    if path.suffix == ".pdf":
        return "\n".join(pdf_pages(path))
    if path.suffix == ".docx":
        return docx_text(path)
    if path.suffix == ".xlsx":
        return xlsx_text(path)
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# D2a の決算書と法人事業概況説明書
# ---------------------------------------------------------------------------


def find_page(pages: list[str], title: str) -> str:
    for text in pages:
        if re.search(rf"^\s*{re.escape(title)}\s*$", text, re.M):
            return text
    raise SystemExit(f"「{title}」のページが見つかりません")


def amount_yen(text: str, label: str) -> int:
    m = re.search(rf"^\s*{re.escape(label)}((?:\s+[\d,]+)+)\s*$", text, re.M)
    if not m:
        raise SystemExit(f"「{label}」の行が見つかりません")
    return num(m[1].split()[0])


def statement(period: int) -> dict[str, str]:
    pages = pdf_pages(DOCS_DIR / f"決算書_第{period}期.pdf")
    return {
        "pl": find_page(pages, "損益計算書"),
        "mfg": find_page(pages, "製造原価報告書"),
        "sga": find_page(pages, "販売費及び一般管理費内訳書"),
    }


# 既存事業の内訳の「科目」と、決算書のページ・行の名前
COST_SOURCES = {
    "材料費（製造原価）": ("mfg", "当期材料費"),
    "賃金給与（製造原価）": ("mfg", "賃金給与"),
    "法定福利費（製造原価）": ("mfg", "法定福利費"),
    "減価償却費（製造原価）": ("mfg", "減価償却費"),
    "水道光熱費": ("mfg", "水道光熱費"),
    "消耗品・包装材料費": ("mfg", "消耗品・包装材料費"),
    "地代家賃": ("mfg", "地代家賃"),
    "修繕費その他": ("mfg", "修繕費その他"),
    "役員報酬": ("sga", "役員報酬"),
    "給料手当": ("sga", "給料手当"),
    "法定福利費（販管費）": ("sga", "法定福利費"),
    "福利厚生費": ("sga", "福利厚生費"),
    "荷造運賃": ("sga", "荷造運賃"),
    "車両費": ("sga", "車両費"),
    "リース料": ("sga", "リース料"),
    "減価償却費（販管費）": ("sga", "減価償却費"),
    "その他（販管費）": ("sga", "その他"),
}


def monthly_sales_18() -> list[int]:
    """D2a の法人事業概況説明書の月別の売上高（千円）。"""
    text = "\n".join(pdf_pages(DOCS_DIR / "法人事業概況説明書_第18期.pdf"))
    part = text[text.index("月別の売上高") :]
    return [num(v) for v in re.findall(r"^\s*(?:令和\d+年)?\d+月\s+([\d,]+)\s*$", part, re.M)]


# ---------------------------------------------------------------------------
# 照らす
# ---------------------------------------------------------------------------


def check_materials_folder() -> None:
    print("\n■ 材料のフォルダ")
    names = sorted(p.name for p in HERE.iterdir())
    want = sorted([PROFILE, PRODUCTS, MINUTES, BREAKDOWN, PAST_PLAN, PAST_NOTICE, PAST_MEMO, *PHOTOS])
    report(names == want, f"材料/ にあるのは材料の{len(want)}ファイルだけ（スクリプト・資料の一覧・答えは入れない）")


def check_marks() -> None:
    print("\n■ 架空であることの表示")
    for path in sorted(HERE.iterdir()):
        if path.suffix == ".pdf":
            pages = pdf_pages(path)
            missing = [i for i, t in enumerate(pages, start=1) if t.count(MARK) < 2]
            report(not missing, f"{path.name}：{len(pages)}ページすべての頭と足（足りないページ：{missing or 'なし'}）")
        elif path.suffix == ".docx":
            _, _, head, foot = docx_parts(path)
            report(MARK in head and MARK in foot, f"{path.name}：頭と足（どのページにも出る）")
        elif path.suffix == ".xlsx":
            wb = load_workbook(path)
            ok = all(
                MARK in str(ws["A1"].value) and MARK in ws.oddHeader.center.text and MARK in ws.oddFooter.center.text
                for ws in wb.worksheets
            )
            report(ok, f"{path.name}：{len(wb.worksheets)}シートすべての1行目と、印刷の頭と足")
        elif path.suffix == ".jpg":
            with Image.open(path) as img:
                comment = img.info.get("comment", b"").decode("utf-8")
            report(MARK in comment, f"{path.name}：画像の帯（描き込み）と、JPEG の注記に「{MARK}」")


def check_profile() -> None:
    print(f"\n■ {PROFILE}・{PRODUCTS}：回答表と照らす")
    text = flat("\n".join(pdf_pages(HERE / PROFILE)))
    products = flat("\n".join(pdf_pages(HERE / PRODUCTS)))
    president = flat(re.search(r"代表取締役\s*(\S+\s?\S+)（", ANSWERS["A-08"])[1])
    address = flat(re.match(r"(\S+?号)", ANSWERS["B-01"])[1])
    y, m, d = find("A-04", r"(\d{4})年(\d+)月(\d+)日").groups()
    capital = num(find("A-06", r"([\d,]+)千円")[1])
    checks = [
        ("A-01 社名", ANSWERS["A-01"] in text),
        ("A-04 設立", f"{y}年{m}月{d}日" in text),
        ("A-05 1996年に先代が始め、2015年に今の社長が継いだ", "1996年" in text and "2015年" in text and "先代" in text),
        ("A-06 資本金", f"{capital // 10:,}万円" in text),
        ("A-08 代表者", president in text),
        ("B-01 所在地", address in text),
        ("C-01 15名（正社員7名、パート8名）", "15名（正社員7名、パート8名）" in text),
        ("E-01 スーパー3社（14店舗）、病院2か所、介護施設11か所", "スーパー3社（14店舗）、病院2か所、介護施設11か所" in text),
        ("E-04 約40品目・月に約120品目", "約40品目" in text and "約120品目" in text),
        ("E-05 前日15時まで・朝6時と10時", "前日15時まで" in text and "朝6時と10時" in text),
        ("E-06 1日に約3,500パック", "約3,500パック" in text),
        ("E-07 朝5時から15時", "朝5時から15時" in text),
        ("E-08 HACCP・アレルギーの二重の確かめ", "HACCP" in text and "二重に確かめ" in text),
        ("A-13 サイトとメール", "https://www.example.com/" in text and "info@example.com" in text),
        ("K-03 細かい注文を断らない・アレルギーの表示を間違えない", "断らない" in text and "間違えない" in text),
        ("E-03 商品のご案内：やわらか・きざみ・ペースト・減塩", all(w in products for w in ("やわらか食", "きざみ食", "ペースト食", "減塩"))),
        ("E-05 商品のご案内：注文とお届け", "前日15時まで" in products and "朝6時と10時" in products),
        ("E-08 商品のご案内：アレルギーの二重の確かめ", "二重に確かめ" in products),
        ("商品のご案内に価格を書いていない", "円" not in products),
    ]
    for label, ok in checks:
        report(ok, label)


def check_minutes() -> None:
    print(f"\n■ {MINUTES}：回答表と労働者名簿（D2b）と照らす")
    text = docx_text(HERE / MINUTES)
    # 出た人：名前と仕事が労働者名簿と同じか（社長と取締役は役員）
    wb = load_workbook(DOCS_DIR / "労働者名簿.xlsx")
    ws = wb["労働者名簿"]
    header = [c.value for c in ws[5]]
    jobs = {row[header.index("氏名")]: row[header.index("従事する業務の種類")] for row in ws.iter_rows(min_row=6, values_only=True) if row[0]}
    attendees = re.search(r"出た人\t(.+)", text)[1]
    for name, role in (re.match(r"(.+?)（(.+?)）", part).groups() for part in attendees.split("、")):
        if role in ("社長", "取締役"):
            report(flat(name) in flat(ANSWERS["A-09"]), f"出た人 {name}（{role}）：A-09 の役員")
        else:
            job = jobs.get(name, "（名簿にない）")
            report(role.split("・")[-1] in job or role in job, f"出た人 {name}（{role}）：労働者名簿の仕事「{job}」")
    # 工程ごとの時間の和 ＝ G-03 の延べ時間
    parts = [int(v) for v in re.findall(r"(?:盛り付け|計量|包装（シール）|ラベル貼り|検品)約(\d+)時間", text)]
    total = int(find("G-03", r"延べ約(\d+)時間")[1])
    report(len(parts) == 5 and sum(parts) == total, f"G-03 工程ごとの時間の和 {'＋'.join(map(str, parts))}＝{sum(parts)}時間 ／ 回答表 延べ約{total}時間")
    report(f"平均で約{total}時間" in text, f"G-03 測った延べ時間 約{total}時間")
    # クレームの内訳 ＝ G-04
    claims = int(find("G-04", r"クレームが(\d+)件")[1])
    weigh = int(re.search(r"計量のミス(\d+)件", text)[1])
    label = int(re.search(r"ラベルのミス(\d+)件", text)[1])
    report(weigh + label == claims, f"G-04 計量のミス{weigh}件＋ラベルのミス{label}件＝{weigh + label}件 ／ 回答表 {claims}件")
    report("アレルギー" in ANSWERS["G-04"] and "1件が、アレルギー" in text, "G-04 うち1件はアレルギーの表示の誤り")
    report("2025年度" in text and "2025年度" in ANSWERS["G-04"], "G-04 同じ年度（2025年度）")
    # 見積を頼む時期と H-04 の日付、会議の日付
    quote = find("H-04", r"(\d{4})年(\d+)月(\d+)日付け")
    report(
        "10月中に見積" in text and quote[1] == "2026" and quote[2] == "10",
        f"H-04 「10月中に見積を頼む」と、見積の日付 {quote[1]}年{quote[2]}月{quote[3]}日",
    )
    report("2026年9月10日" in text, "会議の日（2026年9月10日）は、見積の日付より前")
    report("盛り付けとラベルをカメラで確かめる" in text and "カメラ" in ANSWERS["H-01"], "H-01 カメラで盛り付けとラベルを確かめたい")
    report("信用金庫" in text and "信用金庫" in ANSWERS["H-12"], "H-12 信用金庫に相談する")
    report("去年のものづくり補助金" in text and "2025年" in ANSWERS["J-06"], "J-06 去年（2025年）のものづくり補助金の振り返り")


def check_breakdown() -> None:
    print(f"\n■ {BREAKDOWN}：回答表と D2a の決算書・法人事業概況説明書と照らす")
    wb = load_workbook(HERE / BREAKDOWN)

    def rows(sheet: str) -> list[tuple]:
        return [r for r in wb[sheet].iter_rows(min_row=6, values_only=True) if r[0] is not None]

    # 取引先の種類ごと
    data = rows("取引先の種類ごと")
    days = int(find("E-07", r"年に約(\d+)日")[1])
    for period in (17, 18):
        lines = [r for r in data if r[0] == f"第{period}期"]
        total = [r for r in data if r[0] == f"合計（第{period}期）"][0]
        sales = sum(r[2] for r in lines)
        report(sales == total[2] == period_value("F-01", period), f"F-01 第{period}期 取引先の種類ごとの売上の和 {sales:,}千円 ＝ 売上")
        packs = sum(r[3] for r in lines)
        report(packs == total[3], f"第{period}期 パック数の和 {packs:,}")
        report(all(abs(r[5] - r[2] * 1000 / r[3]) < 1 for r in lines + [total]), f"第{period}期 平均単価 ＝ 売上 ÷ パック数")
        report(all(r[4] == r[3] // days for r in lines + [total]), f"第{period}期 1日のパック数 ＝ 年間 ÷ {days}日（E-07）")
        materials = sum(r[6] for r in lines)
        want = amount_yen(statement(period)["mfg"], "当期材料費") // 1000
        report(materials == total[6] == want, f"第{period}期 材料費の和 {materials:,}千円 ＝ 決算書の当期材料費 {want:,}千円")
    want = {k: num(v) for k, v in re.findall(r"(スーパー|病院・介護施設|その他)([\d,]+)千円", ANSWERS["E-02"])}
    got = {r[1]: r[2] for r in data if r[0] == "第18期"}
    report(got == want, f"E-02 第18期の種類ごとの売上：回答表 {want} ／ 内訳 {got}")
    per_day = num(find("E-06", r"約([\d,]+)パック")[1])
    total18 = [r for r in data if r[0] == "合計（第18期）"][0]
    report(total18[4] == per_day, f"E-06 第18期の1日のパック数 {total18[4]:,} ／ 回答表 約{per_day:,}")
    report(num(find("F-09", r"材料費([\d,]+)千円")[1]) == total18[6], "F-09 第18期の材料費")

    # 商品の種類ごと
    data = rows("商品の種類ごと")
    lines = [r for r in data if r[0] != "合計"]
    report(sum(r[1] for r in lines) == period_value("F-01", 18), "F-01 第18期 商品の種類ごとの売上の和 ＝ 売上")
    report(sum(r[2] for r in lines) == total18[3], "商品の種類ごとのパック数の和 ＝ 取引先の種類ごとのパック数の和")

    # 月別
    data = rows("月別の売上")
    lines = [r for r in data if r[0] != "合計"]
    months = monthly_sales_18()
    report(len(months) == 12, f"法人事業概況説明書の月別の売上高を {len(months)} か月読めた")
    report(all(r[1] + r[2] + r[3] == r[4] for r in lines), "月ごとに、スーパー＋病院・介護施設＋その他 ＝ 計")
    report([r[4] for r in lines] == months, "月ごとの計 ＝ D2a の法人事業概況説明書の月別の売上高")
    sums = {k: sum(r[i] for r in lines) for k, i in (("スーパー", 1), ("病院・介護施設", 2), ("その他", 3))}
    report(sums == want, f"E-02 12か月の和：{sums}")

    # 経費の内訳
    data = rows("経費の内訳")
    for period, col in ((17, 2), (18, 3)):
        st = statement(period)
        wrong = []
        for r in data:
            if r[1] in COST_SOURCES:
                page, label = COST_SOURCES[r[1]]
                if amount_yen(st[page], label) != r[col] * 1000:
                    wrong.append(r[1])
        count = sum(1 for r in data if r[1] in COST_SOURCES)
        report(not wrong and count == len(COST_SOURCES), f"第{period}期 経費の科目 {count} 個が、D2a の決算書と同じ（違うもの：{wrong or 'なし'}）")
        groups = [r for r in data if str(r[0]).startswith("合計（") and r[0] != "合計（経費）"]
        cost = [r for r in data if r[0] == "合計（経費）"][0][col]
        report(sum(r[col] for r in groups) == cost, f"第{period}期 4つの区分の和 ＝ 経費の合計 {cost:,}千円")
        operating = [r for r in data if r[0] == "営業利益"][0][col]
        report(operating == period_value("F-03", period), f"F-03 第{period}期 売上 − 経費 ＝ 営業利益 {operating:,}千円")


def check_past() -> None:
    print("\n■ 過去の申請（2025年 ものづくり補助金）：J-06 と D2a の決算書と照らす")
    body, tables, _, _ = docx_parts(HERE / PAST_PLAN)
    plan = docx_text(HERE / PAST_PLAN)
    notice = "\n".join(pdf_pages(HERE / PAST_NOTICE))
    memo_body, memo_tables, _, _ = docx_parts(HERE / PAST_MEMO)
    memo = docx_text(HERE / PAST_MEMO)
    info = {r[0]: r[1] for r in tables[0][1:]}

    # J-06・J-07・C-01
    report("ものづくり" in info["申請した補助金"] and "2025年" in ANSWERS["J-06"] and "2025年7月" in info["出した日"], "J-06 2025年に、ものづくり補助金に申請")
    report("盛り付け" in info["事業計画の名前"] and "包装" in info["事業計画の名前"], "J-06 盛り付けと包装の機械を入れる計画")
    report("自分で作った" in info["作った人"] and "いない" in ANSWERS["J-07"], "J-06・J-07 社長が自分で書いた。支援者はいない")
    report(re.search(r"結果\s+不採択", notice) is not None and "不採択" in ANSWERS["J-06"], "J-06 通知の結果は不採択")
    report("採択されたことはない" in ANSWERS["J-06"] and "採択されました" not in notice, "J-06 採択されたことはない")
    report(info["従業員の数"].startswith(find("C-01", r"^(\d+)人")[1] + "人"), "C-01 従業員15人")
    number = info["申請番号"]
    title = info["事業計画の名前"]
    report(number in notice, f"申請番号 {number} が、通知でも同じ")
    report(flat(title) in flat(notice), "事業計画の名前が、通知でも同じ")
    report(
        re.search(rf"事業計画の名前\s+{re.escape(title)}\s*$", notice, re.M) is not None,
        "通知で、事業計画の名前が折り返さずに1行に収まっている",
    )
    report("2025年10月28日" in notice, "通知の日 2025年10月28日（20次締切の採択の発表の日）")
    report(flat(ANSWERS["A-01"]) in flat(notice), "A-01 通知の宛名")

    # 機械と補助金の額
    machines = tables[1][1:-1]
    cost = sum(num(r[3].rstrip("円")) for r in machines)
    report(num(tables[1][-1][3].rstrip("円")) == cost, f"機械の金額の和 {cost:,}円 ＝ 合計")
    h02 = {r[0]: num(find("H-02", rf"{r[0]}(?:\d+台)?([\d,]+)千円")[1]) for r in machines}
    report(all(num(r[3].rstrip("円")) == h02[r[0]] * 1000 for r in machines), f"機械の金額が H-02 と同じ単価（{h02}）")
    subsidy = num(info["補助金の申請額"].rstrip("円"))
    report(subsidy == min(cost * 2 // 3, 10_000_000), f"補助金の申請額 {subsidy:,}円 ＝ min（{cost:,}円 × 2/3、上限 1,000万円）")

    # 第17期の実績が D2a の決算書と同じか
    values = {r[0]: [num(v) for v in r[1:]] for r in tables[2][1:]}
    st = statement(17)
    labor = amount_yen(st["mfg"], "当期労務費")
    personnel = labor + sum(amount_yen(st["sga"], k) for k in ("役員報酬", "給料手当", "法定福利費", "福利厚生費"))
    depreciation = amount_yen(st["mfg"], "減価償却費") + amount_yen(st["sga"], "減価償却費")
    for label, want in (
        ("売上高", period_value("F-01", 17) * 1000),
        ("営業利益", period_value("F-03", 17) * 1000),
        ("減価償却費", depreciation),
        ("人件費", personnel),
        ("給与支給総額（従業員）", period_value("D-04", 17) * 1000),
        ("給与支給総額（役員）", period_value("D-05", 17) * 1000),
    ):
        report(values[label][0] * 1000 == want, f"第17期の{label} {values[label][0]:,}千円 ＝ 決算書・回答表 {want // 1000:,}千円")
    report(period_value("F-06", 17) * 1000 == depreciation, "F-06 第17期の減価償却費（製造原価＋販管費）")

    # 目標値の計算（20次締切の基本要件：付加価値額 年平均3.0%以上、給与支給総額 年平均2.0%以上）
    for i in range(5):
        report(
            values["付加価値額"][i] == values["営業利益"][i] + values["人件費"][i] + values["減価償却費"][i],
            f"{tables[2][0][i + 1]}：付加価値額 ＝ 営業利益 ＋ 人件費 ＋ 減価償却費",
        )

    def cagr(v: list[int]) -> float:
        return (v[4] / v[1]) ** (1 / 3) - 1

    added = cagr(values["付加価値額"])
    report(added >= 0.03 and f"年平均{added:.1%}" in body, f"付加価値額の年平均の伸び {added:.2%}（3.0%以上。本文の数字と同じ）")
    for label in ("給与支給総額（従業員）", "給与支給総額（役員）", "1人あたり給与支給総額（従業員）"):
        report(cagr(values[label]) >= 0.03, f"{label}の年平均の伸び {cagr(values[label]):.2%}（本文の「3.0%以上」）")
    full, part = (int(v) for v in find("C-04", r"1日(\d+)時間、週(\d+)時間").groups())
    shifts = re.findall(r"(\d+)人は1日(\d+)時間・週(\d+)日", ANSWERS["C-05"])
    regular = int(find("C-01", r"正社員(\d+)人")[1])
    fte = regular + sum(int(n) * int(h) * int(d) for n, h, d in shifts) / part
    report(f"{fte:.1f}人" in body, f"1人あたりで割る人数 {fte:.1f}人 ＝ 正社員{regular}人 ＋ パートを週{part}時間に換算（C-04・C-05）")
    report(
        all(abs(p - g / fte) < 1 for p, g in zip(values["1人あたり給与支給総額（従業員）"], values["給与支給総額（従業員）"])),
        "1人あたり給与支給総額 ＝ 給与支給総額（従業員）÷ 人数",
    )

    check_memo(plan, notice, memo_body, memo_tables, memo)


def jp_date(text: str) -> tuple[int, int, int]:
    m = re.search(r"(\d{4})年(\d+)月(\d+)日", text)
    if not m:
        raise SystemExit(f"日付が見つかりません：{text}")
    return int(m[1]), int(m[2]), int(m[3])


def check_memo(plan: str, notice: str, memo_body: str, memo_tables: list, memo: str) -> None:
    """不採択の後の相談で受けた指摘のメモ（TASKS D8b、T13-9 の材料）。"""
    print(f"\n■ {PAST_MEMO}：通知・申請書・議事録・回答表と照らす（D8b）")
    meta = {r[0]: r[1] for r in memo_tables[0][1:]}
    minutes = docx_text(HERE / MINUTES)

    # 通知に理由がない（ものづくり補助金は採択結果の理由を開示しない）
    notice_flat = flat(notice)
    report(
        all(w not in notice_flat for w in ("審査のコメント", "別紙", "指摘")),
        "通知に、審査のコメント・別紙・指摘が書かれていない（理由は開示されない）",
    )
    report("理由" in notice_flat and "お答えしていません" in notice_flat, "通知に、理由の問い合わせには答えないとある")

    # メモの形：社長が書き留めた、不採択の後の相談のメモ
    president = flat(re.search(r"代表取締役\s*(\S+\s?\S+)（", ANSWERS["A-08"])[1])
    report(president in flat(meta.get("書いた人", "")) and "書き留めた" in meta.get("書いた人", ""), "メモを書いたのは社長（A-08）で、相談の後に書き留めた形")
    report("ものづくり補助金" in memo and "2025年" in memo and "不採択" in memo, "J-06 2025年のものづくり補助金の不採択についてのメモ")
    report("理由が書かれていなかった" in memo, "メモに、通知に理由が書かれていなかったとある")

    # 日付：通知（2025年10月28日）の後、議事録の会議（2026年9月10日。「去年の11月」）の前
    memo_date = jp_date(meta["相談した日"])
    notice_date = jp_date(notice[notice.index("2025年10月28日") :])
    meeting_date = jp_date(re.search(r"日時\t(.+)", minutes)[1])
    report(notice_date < memo_date < meeting_date, f"相談の日 {memo_date} は、通知 {notice_date} の後、議事録の会議 {meeting_date} の前")
    report(memo_date[0] == meeting_date[0] - 1 and f"去年の{memo_date[1]}月" in minutes, f"議事録の「去年の{memo_date[1]}月」に相談した、と合う")

    # 相談先は一般の呼び方。実在の団体や人を特定しない。商工会議所・商工会ではない（J-03）
    place = meta["相談した所"]
    report("公的な経営相談の窓口" in place, f"相談先は一般の呼び方：{place}")
    named = ["商工会議所", "商工会", "よろず支援拠点", "中小企業診断士", "認定支援機関", "中小機構", "協会", "財団", "振興", "株式会社", "先生", "さん"]
    found = [w for w in named if w in memo.replace(president, "")]
    report(not found, f"メモに、団体の名前・資格・人の名前を書いていない（あったもの：{found or 'なし'}）")
    report("相談に行ったこともない" in ANSWERS["J-03"], "J-03 商工会議所に相談に行ったことはない（相談先は商工会議所ではない）")
    report("メモ" in ANSWERS["J-06"] and "審査のコメント" not in ANSWERS["J-06"], "J-06 回答表は、審査のコメントではなく相談のメモを指す")

    # 計画への指摘（6つ）が、申請書の弱い所とそのとおり対応しているか
    points = re.findall(r"^(\d)．(.+?)：(.+)$", memo_body, re.M)
    report([p[0] for p in points] == ["1", "2", "3", "4", "5", "6"], f"計画への指摘が6つ（{[p[1] for p in points]}）")
    text = {p[1]: p[2] for p in points}
    pairs = [
        (
            "効果の根拠",
            "業者の説明" in text.get("効果の根拠", "") and "工程ごと" in text.get("効果の根拠", ""),
            "業者の説明" in plan and "工程ごと" not in plan and not re.search(r"約\d+時間", plan),
        ),
        (
            "ミスを防ぐ仕組み",
            "検品" in text.get("ミスを防ぐ仕組み", "") and "ラベル" in text.get("ミスを防ぐ仕組み", ""),
            "ラベルの貼り間違い" in plan and all(w not in plan for w in ("検品", "カメラ", "画像検査", "重量チェッカー")),
        ),
        (
            "浮いた人手の使い道",
            "浮いた人手で、注文の増加に応えます" in text.get("浮いた人手の使い道", ""),
            "浮いた人手で、注文の増加に応えます" in plan and all(w not in plan for w in ("品質管理", "冷凍")),
        ),
        (
            "数値目標の組み立て",
            "取引先の種類ごと" in text.get("数値目標の組み立て", ""),
            "種類ごと" not in plan and "根拠" not in plan,
        ),
        (
            "お金の用意",
            "金融機関には、これから相談します" in text.get("お金の用意", ""),
            "金融機関には、これから相談します" in plan and "信用金庫" not in plan,
        ),
        (
            "動かす人と日程",
            "工場長と盛り付け・包装の担当で機械を動かします" in text.get("動かす人と日程", "") and "研修" in text.get("動かす人と日程", ""),
            "工場長と盛り付け・包装の担当で機械を動かします" in plan and "研修" not in plan,
        ),
    ]
    for label, in_memo, in_plan in pairs:
        report(in_memo and in_plan, f"指摘「{label}」：メモにあり、申請書がそのとおりになっている")

    # 指摘に応える事実が、回答表にある（省力化の計画書で応えられる。対応の見込みは資料の一覧.md）
    answers = [
        ("効果の根拠", "G-03 今の延べ時間と H-09 入れた後の時間", "延べ約" in ANSWERS["G-03"] and "延べ約" in ANSWERS["H-09"]),
        ("ミスを防ぐ仕組み", "H-02 画像検査装置と重量チェッカー・ラベラー", "画像検査装置" in ANSWERS["H-02"] and "重量チェッカー" in ANSWERS["H-02"]),
        ("浮いた人手の使い道", "H-09 浮いた4人の行き先", "浮いた4人" in ANSWERS["H-09"]),
        ("数値目標の組み立て", "E-02 取引先の種類ごとの売上と H-10・H-11", "スーパー" in ANSWERS["E-02"] and "パック" in ANSWERS["H-10"] and "千円" in ANSWERS["H-11"]),
        ("お金の用意", "H-12 自己資金と信用金庫の借入", "自己資金" in ANSWERS["H-12"] and "信用金庫" in ANSWERS["H-12"]),
        ("動かす人と日程", "C-12 研修と H-07 納期", "研修" in ANSWERS["C-12"] and "か月" in ANSWERS["H-07"]),
    ]
    for label, source, ok in answers:
        report(ok, f"指摘「{label}」に応える事実が回答表にある：{source}")

    # 議事録の振り返り（作業時間・検品とラベルのミス・お金の用意）が、メモの指摘と食い違わない
    reflection = re.search(r"相談では、(.+?)などを指摘された", minutes)
    report(reflection is not None, "議事録の振り返りに、相談で指摘されたことがある")
    if reflection:
        said = reflection[1]
        report(
            "作業時間" in said and "効果の根拠" in text
            and "検品とラベルのミス" in said and "ミスを防ぐ仕組み" in text
            and "お金の用意" in said and "お金の用意" in text,
            "議事録が挙げた3つ（作業時間、検品とラベルのミス、お金の用意）が、メモの指摘にある",
        )
    report("審査のコメント" not in minutes, "議事録に「審査のコメント」と書いていない")

    # 計画への指摘ではない話（制度の選び方）は、別の見出しに分けてある
    cut = memo_body.find("そのほかに言われたこと")
    before, after = (memo_body[:cut], memo_body[cut:]) if cut >= 0 else (memo_body, "")
    report("省力化" in after and "省力化" not in before, "制度の選び方の話は「そのほかに言われたこと」に分け、計画への指摘に混ぜていない")


def check_minutes_only() -> None:
    print("\n■ 議事録にしかない事実（T8-7 の材料）")
    # 資料の一覧.md と check_materials.py は、この事実を答えとして書いているので数えない（材料/ の外にある）
    others = [ANSWER_SHEET, COMPANY_DIR / "設定.md", DOCS_DIR / "書類の一覧.md"]
    others += [p for p in sorted(DOCS_DIR.iterdir()) if p.suffix in {".pdf", ".docx", ".xlsx"}]
    others += [p for p in sorted(HERE.iterdir()) if p.suffix in {".pdf", ".docx", ".xlsx"} and p.name != MINUTES]
    texts = {p.name: flat(any_text(p)) for p in others}
    minutes = flat(docx_text(HERE / MINUTES))
    for label, pattern in MINUTES_ONLY:
        found = [name for name, text in texts.items() if re.search(pattern, text)]
        report(
            re.search(pattern, minutes) is not None and not found,
            f"「{label}」：議事録にあり、ほかの{len(texts)}ファイルにない（あったファイル：{found or 'なし'}）",
        )


def main() -> None:
    check_materials_folder()
    check_marks()
    check_profile()
    check_minutes()
    check_breakdown()
    check_past()
    check_minutes_only()
    print()
    if failures:
        print(f"合わないもの：{len(failures)}件")
        for f in failures:
            print(f"  × {f}")
        sys.exit(1)
    print("すべて合いました。")


if __name__ == "__main__":
    main()
