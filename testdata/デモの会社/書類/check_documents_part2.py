# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社の書類の後半（TASKS D2b）を、回答表と照らす。

make_documents_part2.py の中の数字ではなく、できたファイル（PDF・Word・Excel）から取り出した文字を、
回答表.md の文と照らす。見積書は「数量 × 単価 ＝ 金額」、明細の和 ＝ 小計、小計の10% ＝ 消費税、
小計 ＋ 消費税 ＝ 合計を確かめる。名簿は D2a の履歴事項全部証明書とも照らす。
どのページ・どのシートにも「架空のテスト用データ」があることも確かめる。
合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社/書類/check_documents_part2.py
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

QUOTES = [
    # (ファイル, 回答表の金額を取る ID と書き方, 発行者)
    ("見積書_つばさ台フードシステム.pdf", "株式会社つばさ台フードシステム"),
    ("見積書_ほしみ機工.pdf", "株式会社ほしみ機工"),
]
CATALOG = "カタログ_つばさ台フードシステム.pdf"
OFFICERS = "役員名簿.docx"
SHAREHOLDERS = "株主名簿.docx"
WORKERS = "労働者名簿.xlsx"
REGISTRY = "履歴事項全部証明書.pdf"  # D2a

# H-02 の6つの区分に、見積の行を当てる言葉（上から順に当てる）
GROUP_WORDS = [r"盛り?付け?ロボット", r"計量機", r"トップシール", r"画像検査", r"ラベラー", r"コンベヤ|据付"]

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


def counts(answer_id: str) -> dict[str, int]:
    """「工場長1人、調理3人…」から、仕事ごとの人数を取る。"""
    return {k: int(v) for k, v in re.findall(r"([^、。\d]+?)(\d+)人", ANSWERS[answer_id])}


def flat(text: str) -> str:
    return re.sub(r"[ 　\n]", "", text)


# ---------------------------------------------------------------------------
# ファイルから文字を取り出す
# ---------------------------------------------------------------------------


def pdf_pages(name: str) -> list[str]:
    return [p.extract_text(extraction_mode="layout") for p in PdfReader(str(HERE / name)).pages]


def check_pdf_marks(name: str, pages: list[str]) -> None:
    missing = [i for i, text in enumerate(pages, start=1) if text.count(MARK) < 2]
    report(not missing, f"{name}：{len(pages)}ページすべての頭と足に「{MARK}」（足りないページ：{missing or 'なし'}）")


def docx_text(name: str) -> tuple[list[list[list[str]]], str, str, str]:
    """表（表ごとの行ごとのセル）、本文、頭、足を返す。"""
    doc = Document(str(HERE / name))
    tables = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
    body = "\n".join(p.text for p in doc.paragraphs)
    sections = doc.sections
    head = "\n".join(p.text for s in sections for p in s.header.paragraphs)
    foot = "\n".join(p.text for s in sections for p in s.footer.paragraphs)
    return tables, body, head, foot


# ---------------------------------------------------------------------------
# 見積書
# ---------------------------------------------------------------------------

ROW = re.compile(r"^\s*(\d+)\s+(.+?)\s+(\S+)\s+(\d+)\s+(台|式)\s+([\d,]+)\s+([\d,]+)\s*$", re.M)


def h02_groups() -> list[tuple[str, int, int]]:
    """H-02 の区分（名前、台数、千円）。"""
    groups = []
    for part in ANSWERS["H-02"].split("、"):
        m = re.match(r"(.+?)(?:(\d+)台)?([\d,]+)千円", part)
        if m:
            groups.append((m[1], int(m[2] or 1), num(m[3])))
    return groups


def group_of(item: str) -> int:
    for i, pattern in enumerate(GROUP_WORDS):
        if re.search(pattern, item):
            return i
    raise SystemExit(f"見積の行「{item}」が、H-02 のどの区分にも当たりません")


def check_quote(name: str, issuer: str) -> list[tuple[int, int, int]]:
    """1通の見積書を照らし、区分ごとの（台数、金額）を返す。"""
    print(f"\n■ {name}")
    pages = pdf_pages(name)
    check_pdf_marks(name, pages)
    text = "\n".join(pages)
    rows = [
        (int(m[1]), m[2], m[3], int(m[4]), m[5], num(m[6]), num(m[7]))
        for m in ROW.finditer(text)
    ]
    report(len(rows) >= 6, f"明細の行を {len(rows)} 行読めた")
    for no, item, model, qty, unit, price, amount in rows:
        report(
            qty * price == amount,
            f"{no}. {item}（{model}）：{qty}{unit} × {price:,}円 ＝ {qty * price:,}円 ／ 書いてある金額 {amount:,}円",
        )
    subtotal = int(re.search(r"小計（税抜）\s+([\d,]+)", text)[1].replace(",", ""))
    tax = int(re.search(r"消費税（10%）\s+([\d,]+)", text)[1].replace(",", ""))
    grand = int(re.search(r"合計（税込）\s+([\d,]+)", text)[1].replace(",", ""))
    shown = int(re.search(r"見積金額（税込）\s+([\d,]+)円", text)[1].replace(",", ""))
    items_sum = sum(r[6] for r in rows)
    report(items_sum == subtotal, f"明細の和 {items_sum:,}円 ＝ 小計（税抜） {subtotal:,}円")
    report(subtotal * 10 // 100 == tax, f"小計の10% {subtotal * 10 // 100:,}円 ＝ 消費税 {tax:,}円")
    report(subtotal + tax == grand, f"小計 ＋ 消費税 {subtotal + tax:,}円 ＝ 合計（税込） {grand:,}円")
    report(shown == grand, f"上の見積金額（税込） {shown:,}円 ＝ 合計（税込） {grand:,}円")
    report("税抜" in text and "税込" in text, "税抜と税込の別が書いてある")

    # 回答表と照らす
    if "つばさ台" in name:
        want = num(find("H-02", r"合計([\d,]+)千円")[1])
        report(subtotal == want * 1000, f"H-02 小計（税抜）：回答表 {want:,}千円 ／ 見積書 {subtotal:,}円")
    else:
        want = num(find("H-03", r"ほしみ機工（([\d,]+)千円")[1])
        report(subtotal == want * 1000, f"H-03 ほしみ機工の小計（税抜）：回答表 {want:,}千円 ／ 見積書 {subtotal:,}円")
    m = find("H-04", r"(\d{4})年(\d+)月(\d+)日付け。有効期限は(\d{4})年(\d+)月(\d+)日")
    issued = f"{m[1]}年{m[2]}月{m[3]}日"
    valid = f"{m[4]}年{m[5]}月{m[6]}日"
    report(re.search(rf"発行日\s+{issued}", text) is not None, f"H-04 発行日 {issued}")
    report(re.search(rf"有効期限\s+{valid}", text) is not None, f"H-04 有効期限 {valid}")
    company = ANSWERS["A-01"]
    president = re.search(r"代表取締役\s*(\S+\s?\S+)（", ANSWERS["A-08"])[1].replace(" ", "")
    report(f"{company}御中" in flat(text), f"A-01 宛名「{company} 御中」")
    report(president in flat(text), f"A-08 宛名の代表者「{president}」")
    report(issuer in flat(text) and issuer.replace("株式会社", "") in ANSWERS["H-03"], f"H-03 発行者「{issuer}」")
    report("電気工事は含みません" in flat(text), "H-08 電気工事は含まない")
    report(re.search(r"約5か月", text) is not None and re.search(r"約1か月", text) is not None, "H-07 納期 約5か月＋据付と調整 約1か月")

    # H-02 の区分ごとの、行の（数量、単位）の並びと金額
    groups: list[list] = [[[], 0] for _ in GROUP_WORDS]
    for _, item, _, qty, unit, _, amount in rows:
        g = group_of(item)
        groups[g][0].append(f"{qty}{unit}")
        groups[g][1] += amount
    return [(i, sorted(q), a) for i, (q, a) in enumerate(groups)]


def check_quotes() -> None:
    expected = h02_groups()
    report(len(expected) == len(GROUP_WORDS), f"H-02 の区分を {len(expected)} つ読めた")
    results = {name: check_quote(name, issuer) for name, issuer in QUOTES}
    print("\n■ 見積書：H-02 の内訳と照らす")
    tsubasa = results[QUOTES[0][0]]
    hoshimi = results[QUOTES[1][0]]
    for (label, units, thousand), (_, q1, a1), (_, q2, _) in zip(expected, tsubasa, hoshimi):
        report(a1 == thousand * 1000, f"H-02 {label}：回答表 {thousand:,}千円 ／ つばさ台 {a1:,}円")
        # 台数を書いているのは盛り付けロボット（2台）だけ。ほかの区分は、回答表に台数がない
        if units > 1:
            report(q1 == [f"{units}台"], f"H-02 {label}：回答表 {units}台 ／ つばさ台 {'・'.join(q1)}")
        report(q1 == q2, f"H-03 同じ構成：{label} つばさ台 {'・'.join(q1)} ／ ほしみ機工 {'・'.join(q2)}")


# ---------------------------------------------------------------------------
# カタログ
# ---------------------------------------------------------------------------


def check_catalog() -> None:
    print(f"\n■ {CATALOG}")
    pages = pdf_pages(CATALOG)
    check_pdf_marks(CATALOG, pages)
    text = "\n".join(pages)
    quote_text = "\n".join(pdf_pages(QUOTES[0][0]))
    models = [m[3] for m in ROW.finditer(quote_text) if m[3] != "—"]
    missing = [m for m in models if m not in text]
    report(not missing, f"つばさ台の見積書の型番 {len(models)} 個が、カタログにある（ないもの：{missing or 'なし'}）")
    per_minute = int(re.search(r"毎分最大(\d+)パック（1時間に最大([\d,]+)パック）", text)[1])
    per_hour = num(re.search(r"毎分最大(\d+)パック（1時間に最大([\d,]+)パック）", text)[2])
    report(per_minute * 60 == per_hour, f"ラインの能力：毎分{per_minute} × 60 ＝ 1時間{per_hour:,}パック")
    packs = num(find("H-10", r"約([\d,]+)パック")[1])
    m = re.search(rf"1日{packs:,}パックのとき\s+ラインの稼働は約(\d+)時間(\d+)分", text)
    report(m is not None, f"H-10 1日{packs:,}パックのときの稼働時間が書いてある")
    if m:
        minutes = int(m[1]) * 60 + int(m[2])
        report(minutes == packs * 60 // per_hour, f"{packs:,} ÷ {per_hour:,} ＝ {packs * 60 // per_hour}分 ／ カタログ {minutes}分")
        start, end = (int(v) for v in find("E-07", r"朝(\d+)時から(\d+)時まで").groups())
        report(minutes <= (end - start) * 60, f"E-07 工場が動く{end - start}時間の内に収まる（{minutes}分）")
    staff = int(find("H-09", r"盛り付けから検品までを(\d+)人")[1])
    report(re.search(rf"ラインに付く人の目安\s+{staff}人", text) is not None, f"H-09 ラインに付く人 {staff}人")
    report("基礎工事は要りません" in flat(text), "H-08 据付は床に固定するだけ（基礎工事なし）")
    report("円" not in text, "カタログに価格を書いていない")


# ---------------------------------------------------------------------------
# 名簿
# ---------------------------------------------------------------------------


def registry_facts() -> tuple[str, str, int]:
    """D2a の履歴事項全部証明書から、代表取締役の住所・重任の日・発行済株式の総数を取る。"""
    text = flat("\n".join(pdf_pages(REGISTRY)))
    address = re.search(r"(東京都大田区東糀谷.丁目\d+番\d+号)代表取締役", text)[1]
    reappointed = re.search(r"令和(\d+)年(\d+)月(\d+)日重任", text)
    date = f"{2018 + int(reappointed[1])}年{int(reappointed[2])}月{int(reappointed[3])}日"
    shares = int(re.search(r"発行済株式の総数(\d+)株", text)[1])
    return address, date, shares


def check_docx_marks(name: str, head: str, foot: str) -> None:
    report(MARK in head and MARK in foot, f"{name}：頭と足に「{MARK}」（どのページにも出る）")


def check_officers(address: str, reappointed: str) -> None:
    print(f"\n■ {OFFICERS}")
    tables, body, head, foot = docx_text(OFFICERS)
    check_docx_marks(OFFICERS, head, foot)
    rows = tables[0][1:]
    report(len(rows) == 2, f"A-09 役員は {len(rows)} 人（回答表は2人）")
    president = re.search(r"代表取締役\s*(\S+\s?\S+)（", ANSWERS["A-08"])[1]
    born = find("A-08", r"(\d{4})年生まれ")[1]
    director = re.search(r"と、取締役の(\S+?)（", ANSWERS["A-09"])[1]
    by_role = {r[0]: r for r in rows}
    p = by_role.get("代表取締役", [""] * 7)
    d = by_role.get("取締役", [""] * 7)
    report(flat(president) in flat(p[1]), f"A-08 代表取締役「{president}」")
    report(p[2].startswith(f"{born}年"), f"A-08 生まれた年 {born}年 ／ 名簿 {p[2]}")
    report(flat(director) in flat(d[1]), f"A-09 取締役「{director}」")
    report("監査役" in body and "置いていません" in body, "A-09 監査役はいない")
    report("同居" in body, "A-09 取締役は同居")
    report("経理" in d[6] and "総務" in d[6], "A-09 取締役の担当は経理と総務")
    for r in rows:
        report(r[4] == address, f"{r[0]}の住所 ＝ 履歴事項全部証明書の代表取締役の住所（{address}）")
        report(reappointed in r[5], f"{r[0]}の重任の日 ＝ 履歴事項全部証明書（{reappointed}）")


def check_shareholders(address: str, issued: int) -> None:
    print(f"\n■ {SHAREHOLDERS}")
    tables, body, head, foot = docx_text(SHAREHOLDERS)
    check_docx_marks(SHAREHOLDERS, head, foot)
    rows = [r for r in tables[0][1:] if r[0]]
    total_row = [r for r in tables[0][1:] if r[1] == "合計"][0]
    want = {flat(k): int(v) for k, v in re.findall(r"(沢村\S+?)が(\d+)株", ANSWERS["A-07"])}
    total = int(find("A-07", r"発行した株は(\d+)株")[1])
    got = {flat(r[1]): int(re.search(r"(\d+)株", r[3])[1]) for r in rows}
    report(got == want, f"A-07 株主と株の数：回答表 {want} ／ 名簿 {got}")
    report(sum(got.values()) == total == int(re.search(r"(\d+)株", total_row[3])[1]), f"A-07 合計 {total}株")
    report(issued == total, f"履歴事項全部証明書の発行済株式の総数 {issued}株 ＝ 回答表 {total}株")
    report(f"総数　{total}株" in body, "名簿の頭の発行済株式の総数")
    report(all(r[2] == address for r in rows), f"株主の住所 ＝ 履歴事項全部証明書（{address}）")
    report("ほかの会社" in body, "A-07 ほかの会社は株を持っていない")


def age(born: dt.date, on: dt.date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def check_workers() -> None:
    print(f"\n■ {WORKERS}")
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

    total = int(find("C-01", r"^(\d+)人")[1])
    regular = int(find("C-01", r"正社員(\d+)人")[1])
    part = int(find("C-01", r"パート(\d+)人")[1])
    kinds = [p[col["雇用の形態"]] for p in people]
    report(len(people) == total, f"C-01 従業員 {total}人 ／ 名簿 {len(people)}人")
    report(kinds.count("正社員") == regular and kinds.count("パート") == part, f"C-01 正社員{regular}人・パート{part}人")
    officers = re.findall(r"沢村\s?\S{2,3}", ANSWERS["A-09"])
    report(not any(flat(p[col["氏名"]]) in map(flat, officers) for p in people), "C-01 役員は入れていない")

    def jobs(kind: str) -> dict[str, int]:
        got: dict[str, int] = {}
        for p in people:
            if p[col["雇用の形態"]] == kind:
                job = re.sub(r"（.*?）", "", p[col["従事する業務の種類"]])
                got[job] = got.get(job, 0) + 1
        return got

    report(jobs("正社員") == counts("C-02"), f"C-02 正社員の内訳：回答表 {counts('C-02')} ／ 名簿 {jobs('正社員')}")
    report(jobs("パート") == counts("C-03"), f"C-03 パートの内訳：回答表 {counts('C-03')} ／ 名簿 {jobs('パート')}")

    hours = {(p[col["1日の所定労働時間"]], p[col["週の所定労働日数"]], p[col["週の所定労働時間"]]) for p in people if p[col["雇用の形態"]] == "正社員"}
    daily, weekly = (int(v) for v in find("C-04", r"1日(\d+)時間、週(\d+)時間").groups())
    report(all(h[0] == daily and h[2] == weekly and h[0] * h[1] == h[2] for h in hours), f"C-04 正社員は1日{daily}時間・週{weekly}時間")
    part_hours: dict[tuple[int, int], int] = {}
    for p in people:
        if p[col["雇用の形態"]] == "パート":
            key = (p[col["1日の所定労働時間"]], p[col["週の所定労働日数"]])
            part_hours[key] = part_hours.get(key, 0) + 1
    want = {(int(h), int(d)): int(n) for n, h, d in re.findall(r"(\d+)人は1日(\d+)時間・週(\d+)日", ANSWERS["C-05"])}
    report(part_hours == want, f"C-05 パートの働く時間：回答表 {want} ／ 名簿 {part_hours}")

    # 盛り付けから検品までの人の時間（G-03 の今と、H-09 の機械を入れた後）
    team = [p for p in people if p[col["従事する業務の種類"]].startswith("盛り付け")]
    team_regular = [p[col["1日の所定労働時間"]] for p in team if p[col["雇用の形態"]] == "正社員"]
    team_part = [p[col["1日の所定労働時間"]] for p in team if p[col["雇用の形態"]] == "パート"]
    g03 = find("G-03", r"正社員(\d+)人とパート(\d+)人の\d+人で、1日に延べ約(\d+)時間")
    report(
        len(team_regular) == int(g03[1]) and len(team_part) == int(g03[2]),
        f"G-03 盛り付けから検品まで：回答表 正社員{g03[1]}人・パート{g03[2]}人 ／ 名簿 正社員{len(team_regular)}人・パート{len(team_part)}人",
    )
    report(
        sum(team_regular) + sum(team_part) == int(g03[3]),
        f"G-03 その{len(team)}人の1日の所定労働時間の和 {sum(team_regular) + sum(team_part)}時間 ＝ 延べ約{g03[3]}時間",
    )
    h09 = find("H-09", r"\d+人（正社員(\d+)人とパート(\d+)人）で、1日に延べ約(\d+)時間")
    after = int(h09[1]) * max(team_regular) + int(h09[2]) * max(team_part)
    report(
        len(set(team_part)) == 1 and after == int(h09[3]),
        f"H-09 機械を入れた後の正社員{h09[1]}人とパート{h09[2]}人の時間の和 {after}時間 ＝ 延べ約{h09[3]}時間",
    )

    terms = [p[col["契約の期間"]] for p in people if p[col["雇用の形態"]] == "パート"]
    open_ended = int(find("C-06", r"(\d+)人は期間の定めなし")[1])
    yearly = int(find("C-06", r"(\d+)人は1年ごとの契約")[1])
    report(
        terms.count("期間の定めなし") == open_ended and sum("1年ごと" in t for t in terms) == yearly,
        f"C-06 期間の定めなし{open_ended}人・1年ごとの契約{yearly}人",
    )
    hired = {p[col["氏名"]]: p[col["雇入れの年月日"]] for p in people}
    parts = [p for p in people if p[col["雇用の形態"]] == "パート"]
    report(
        all(age(hired[p[col["氏名"]]].date(), AS_OF) >= 1 for p in parts),
        "C-06 パートは8人とも雇ってから1年以上",
    )
    report(
        all(age(hired[p[col["氏名"]]].date(), AS_OF) >= 2 for p in parts if "1年ごと" in p[col["契約の期間"]]),
        "C-06 1年ごとの契約の3人は、2年以上続けて更新",
    )
    seniors = sum(age(p[col["生年月日"]].date(), AS_OF) >= 60 for p in parts)
    report(seniors * 2 == len(parts), f"C-15 パートの半分が60歳以上（{seniors}人／{len(parts)}人。{AS_OF}の年齢）")
    report(
        all(not p[col["退職・死亡の年月日と事由"]] for p in people),
        "在籍している人だけ（C-13 の辞めた人は入れていない）",
    )


# ---------------------------------------------------------------------------


def main() -> None:
    check_quotes()
    check_catalog()
    address, reappointed, issued = registry_facts()
    check_officers(address, reappointed)
    check_shareholders(address, issued)
    check_workers()
    print()
    if failures:
        print(f"合わないもの：{len(failures)}件")
        for f in failures:
            print(f"  × {f}")
        sys.exit(1)
    print("すべて合いました。")


if __name__ == "__main__":
    main()
