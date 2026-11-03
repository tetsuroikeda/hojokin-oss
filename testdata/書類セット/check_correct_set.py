# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdfium2==5.14.0", "pillow==13.0.0", "pypdf>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""正しい書類セット（TASKS D5a）に、不備がないことを確かめる。

T5-2 は「不備のない書類セットを入れて、『重大』の誤指摘が0件」を見る。そのため、セットそのものに
SPEC F5 の重大な不備（期限切れ、期数不足、金額の不一致、名義の不一致、事前着手）が1つもないことを、ここで確かめる。

確かめること：
1. セットのフォルダに、決まった書類だけがある（スクリプトや答えの文書がない）。
2. PDF（文字の入ったもの）、スキャンした PDF、写真、Word、Excel がそろっている。
3. 写した書類が元の書類（D2a・D2b）と同じバイト列。写真とスキャンは、作り直すと同じバイト列になる（元の書類から作ったことの確かめ）。
4. 元の書類の確かめ（check_documents.py・check_documents_part2.py）が通る。回答表との一致、見積書の計算はそちらで見る。
5. 申請の日の範囲（APPLY_FROM〜APPLY_UNTIL）のどの日に申請しても、重大な不備がない。
6. 省力化（一般型）第8回 公募要領 4-4 ①② の書類が、どのファイルで満たされるかの対応。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/書類セット/check_correct_set.py
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from make_correct_set import COPIED, PHOTO, SCAN, SET_DIR, SOURCE_DIR, SOURCES, build  # noqa: E402

MARK = "架空のテスト用データ"
COMPANY = "株式会社やまぶき惣菜"  # 回答表 A-01
ADDRESS = "東京都大田区東糀谷八丁目12番5号"  # 回答表 B-01 の番地（D2a の書類と同じ）
PRESIDENT = "沢村宏之"  # 回答表 A-08（空白を除いた形）
EMPLOYEES = 15  # 回答表 C-01
OFFICERS = 2  # 回答表 A-09（常勤役員）

# このセットが「正しい」と言える申請の日の範囲
# 始め：いちばん新しい書類の日付（名簿の「2026年11月1日現在」）。それより前には、この形のセットはない
# 終わり：履歴事項全部証明書の発行日（2026-10-22）から3か月の前の日。見積書の有効期限（2027-01-31）より早い
APPLY_FROM = dt.date(2026, 11, 1)
APPLY_UNTIL = dt.date(2027, 1, 21)
FISCAL_YEAR_END_MONTH = 3  # 決算は3月末（回答表 A-06）

# 書類の種類（セットの名前 → 種類）
KINDS = {
    "決算書_第17期.pdf": "決算書（第17期）",
    "決算書_第18期.pdf": "決算書（第18期）",
    "法人事業概況説明書_第18期.pdf": "法人事業概況説明書（第18期）",
    "納税証明書_その2.jpg": "納税証明書（その2）第16期〜第18期",
    "履歴事項全部証明書.pdf": "履歴事項全部証明書",
    "見積書_つばさ台フードシステム.pdf": "見積書（頼むつもりの会社）",
    "見積書_ほしみ機工.pdf": "見積書（相見積）",
    "カタログ_つばさ台フードシステム.pdf": "機械のカタログ",
    "役員名簿.docx": "役員名簿（会社が持つ名簿）",
    "株主名簿.docx": "株主名簿（会社が持つ名簿）",
    "労働者名簿.xlsx": "労働者名簿",
}
# 社名が載っているはずの書類（カタログは機械の会社の資料なので、社名は載らない）
WITH_COMPANY = [name for name in KINDS if not name.startswith("カタログ")]
# 本店の所在地が載っているはずの書類
WITH_ADDRESS = [
    "決算書_第17期.pdf",
    "決算書_第18期.pdf",
    "法人事業概況説明書_第18期.pdf",
    "納税証明書_その2.jpg",
    "履歴事項全部証明書.pdf",
]
# 代表者の名前が載っているはずの書類
WITH_PRESIDENT = [
    "法人事業概況説明書_第18期.pdf",
    "納税証明書_その2.jpg",
    "履歴事項全部証明書.pdf",
    "見積書_つばさ台フードシステム.pdf",
    "見積書_ほしみ機工.pdf",
    "役員名簿.docx",
    "株主名簿.docx",
]
# 事前着手を示す書類の名前（発注・契約・納品・請求・支払い）
ORDER_WORDS = re.compile(r"注文書|発注書|注文請書|契約書|納品書|請求書|検収書|領収書|受領書")

failures: list[str] = []


def report(ok: bool, text: str) -> None:
    print(f"  {'○' if ok else '×'} {text}")
    if not ok:
        failures.append(text)


def flat(text: str) -> str:
    return re.sub(r"[ 　\n]", "", text)


def wareki(text: str) -> dt.date:
    """「令和8年10月22日」を日付にする。"""
    m = re.search(r"令和(\d+)年(\d+)月(\d+)日", text)
    return dt.date(2018 + int(m[1]), int(m[2]), int(m[3]))


def add_months(day: dt.date, months: int) -> dt.date:
    y, m = divmod(day.month - 1 + months, 12)
    return dt.date(day.year + y, m + 1, day.day)


# ---------------------------------------------------------------------------
# ファイルから文字を取り出す
# ---------------------------------------------------------------------------


def pdf_pages(path: Path) -> list[str]:
    return [p.extract_text(extraction_mode="layout") or "" for p in PdfReader(str(path)).pages]


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    parts += [c.text for t in doc.tables for row in t.rows for c in row.cells]
    parts += [p.text for s in doc.sections for p in s.header.paragraphs + s.footer.paragraphs]
    return "\n".join(parts)


def xlsx_text(path: Path) -> str:
    wb = load_workbook(path)
    parts = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            parts += [str(v) for v in row if v is not None]
    return "\n".join(parts)


def text_of(name: str) -> str:
    """セットの書類の文字。写真とスキャンは文字を取り出せないので、作った元の PDF の文字を使う
    （元の PDF から作ったことは、作り直して同じバイト列になることで確かめる）。"""
    path = SET_DIR / name if name in COPIED else SOURCE_DIR / SOURCES[name]
    if path.suffix == ".pdf":
        return "\n".join(pdf_pages(path))
    if path.suffix == ".docx":
        return docx_text(path)
    return xlsx_text(path)


# ---------------------------------------------------------------------------
# 1〜3. ファイル、形式、元の書類との関係
# ---------------------------------------------------------------------------


def check_files() -> None:
    print("\n■ セットのファイル")
    found = sorted(p.name for p in SET_DIR.iterdir())
    want = sorted(KINDS)
    report(found == want, f"セットのフォルダに決まった {len(want)} 件だけがある（余分：{sorted(set(found) - set(want)) or 'なし'}、足りない：{sorted(set(want) - set(found)) or 'なし'}）")
    report(sorted(SOURCES) == want, "作るスクリプトの書類と、確かめる書類が同じ")


def check_formats() -> None:
    print("\n■ 形式")
    text_pdfs, scanned, photos, words, excels = [], [], [], [], []
    for path in sorted(SET_DIR.iterdir()):
        if path.suffix == ".pdf":
            has_text = any(t.strip() for t in pdf_pages(path))
            (text_pdfs if has_text else scanned).append(path.name)
        elif path.suffix == ".jpg":
            with Image.open(path) as img:
                ok = img.format == "JPEG" and img.size[0] >= 1000 and not img.getexif()
            report(ok, f"{path.name}：JPEG、{img.size[0]}×{img.size[1]}、向きの印（EXIF）なし")
            photos.append(path.name)
        elif path.suffix == ".docx":
            words.append(path.name)
        elif path.suffix == ".xlsx":
            excels.append(path.name)
    report(len(text_pdfs) >= 1, f"文字の入った PDF：{len(text_pdfs)}件")
    report(scanned == [SCAN[0]], f"スキャンした PDF（文字のない、画像だけの PDF）：{scanned}")
    report(photos == [PHOTO[0]], f"写真：{photos}")
    report(len(words) >= 1, f"Word：{words}")
    report(len(excels) >= 1, f"Excel：{excels}")


def check_sources() -> None:
    print("\n■ 元の書類（testdata/デモの会社/書類/）との関係")
    for name in COPIED:
        same = (SET_DIR / name).read_bytes() == (SOURCE_DIR / name).read_bytes()
        report(same, f"{name}：元の書類と同じバイト列")
    with tempfile.TemporaryDirectory() as tmp:
        rebuilt = Path(tmp) / "set"
        build(rebuilt)
        for name in (PHOTO[0], SCAN[0]):
            same = (rebuilt / name).read_bytes() == (SET_DIR / name).read_bytes()
            report(same, f"{name}：元の {SOURCES[name]} から作り直すと同じバイト列")
    for name in (PHOTO[0], SCAN[0]):
        pages = pdf_pages(SOURCE_DIR / SOURCES[name])
        report(len(pages) == 1 and pages[0].count(MARK) >= 2, f"{name}：元の PDF の頭と足に「{MARK}」（写真とスキャンにも写っている）")


def check_source_checks() -> None:
    print("\n■ 元の書類の確かめ（D2a・D2b）")
    for script in ("check_documents.py", "check_documents_part2.py"):
        result = subprocess.run(
            [sys.executable, str(SOURCE_DIR / script)],
            capture_output=True,
            text=True,
        )
        # 行の頭の印で数える（「数量 × 単価」の × を数えないように）
        ok_count = len(re.findall(r"^\s*○ ", result.stdout, re.M))
        ng_count = len(re.findall(r"^\s*× ", result.stdout, re.M))
        report(result.returncode == 0, f"{script}：終了コード {result.returncode}（○{ok_count}件、×{ng_count}件）")
        if result.returncode != 0:
            print(result.stdout[-2000:], result.stderr[-2000:])


def check_marks() -> None:
    print("\n■ 架空であることの表示")
    for name in COPIED:
        path = SET_DIR / name
        if path.suffix == ".pdf":
            pages = pdf_pages(path)
            missing = [i for i, t in enumerate(pages, start=1) if t.count(MARK) < 2]
            report(not missing, f"{name}：{len(pages)}ページすべての頭と足に「{MARK}」")
        else:
            report(MARK in text_of(name), f"{name}：「{MARK}」がある")


# ---------------------------------------------------------------------------
# 5. 重大な不備がないこと
# ---------------------------------------------------------------------------


def latest_closed_year_end(day: dt.date) -> dt.date:
    """その日より前に終わった、いちばん新しい事業年度の末日。"""
    end = dt.date(day.year, FISCAL_YEAR_END_MONTH, 31)
    return end if end < day else dt.date(day.year - 1, FISCAL_YEAR_END_MONTH, 31)


def check_periods() -> None:
    print("\n■ 期数（決算書は直近2期、納税証明書は直近3期）")
    latest_from = latest_closed_year_end(APPLY_FROM)
    latest_until = latest_closed_year_end(APPLY_UNTIL)
    report(latest_from == latest_until == dt.date(2026, 3, 31), f"申請の日の範囲で、直近の決算は {latest_from}（範囲の中で変わらない）")

    periods = []
    for name in ("決算書_第17期.pdf", "決算書_第18期.pdf"):
        text = text_of(name)
        m = re.search(r"自\s*(令和\d+年\d+月\d+日)\s*至\s*(令和\d+年\d+月\d+日)", text)
        start, end = wareki(m[1]), wareki(m[2])
        periods.append((start, end))
        parts = ["貸借対照表", "損益計算書", "製造原価報告書", "販売費及び一般管理費", "個別注記表"]
        lacking = [p for p in parts if p not in flat(text)]
        report(not lacking, f"{name}：{start}〜{end}。4-4 ① の中身（{'・'.join(parts)}）がそろう（足りない：{lacking or 'なし'}）")
    ends = sorted(e for _, e in periods)
    report(ends == [dt.date(2025, 3, 31), dt.date(2026, 3, 31)], f"決算書は直近の2期（{ends[0]}・{ends[1]} に終わる期）")
    report(periods[1][0] == periods[0][1] + dt.timedelta(days=1), "第17期と第18期が途切れずにつながる")

    tax = text_of(PHOTO[0])
    years = [(wareki(a), wareki(b)) for a, b in re.findall(r"(令和\d+年\d+月\d+日)〜(令和\d+年\d+月\d+日)", tax)]
    tax_ends = sorted(e for _, e in years)
    report(
        tax_ends == [dt.date(2024, 3, 31), dt.date(2025, 3, 31), dt.date(2026, 3, 31)],
        f"納税証明書（その2）は直近の3期（{'・'.join(str(e) for e in tax_ends)} に終わる期）",
    )
    issued = wareki(re.search(r"発行日\s*(令和\S+日)", tax)[1])
    # 3月決算の申告の期限は5月末。発行日がそれより後なら、第18期の所得が載る
    report(issued > dt.date(2026, 5, 31), f"納税証明書の発行日 {issued} は、第18期の申告の期限（2026-05-31）より後")


def check_dates() -> None:
    print(f"\n■ 期限（申請の日の範囲 {APPLY_FROM}〜{APPLY_UNTIL}）")
    registry = text_of(SCAN[0])
    issued = wareki(re.search(r"発行日\s*(令和\S+日)", registry)[1])
    valid_until = add_months(issued, 3) - dt.timedelta(days=1)
    report(valid_until >= APPLY_UNTIL, f"履歴事項全部証明書：発行日 {issued}、発行から3か月以内は {valid_until} まで（範囲の終わり {APPLY_UNTIL} を含む）")
    report(issued <= APPLY_FROM, f"履歴事項全部証明書：発行日 {issued} は範囲の始めより前（未来の日付でない）")
    for name in ("見積書_つばさ台フードシステム.pdf", "見積書_ほしみ機工.pdf"):
        text = text_of(name)
        m_issued = re.search(r"発行日\s+(\d{4})年(\d+)月(\d+)日", text)
        m_valid = re.search(r"有効期限\s+(\d{4})年(\d+)月(\d+)日", text)
        q_issued = dt.date(*map(int, m_issued.groups()))
        q_valid = dt.date(*map(int, m_valid.groups()))
        report(q_valid >= APPLY_UNTIL, f"{name}：有効期限 {q_valid}（範囲の終わり {APPLY_UNTIL} を含む）")
        report(q_issued <= APPLY_FROM, f"{name}：発行日 {q_issued} は範囲の始めより前")


def check_names() -> None:
    print("\n■ 名義（社名・所在地・代表者が、どの書類でも同じ）")
    for name in KINDS:
        text = flat(text_of(name))
        # 「株式会社やまぶき」に続く2文字が「惣菜」でないもの（総菜、そうざい など）
        variants = sorted({v for v in re.findall(r"株式会社やまぶき\S{0,2}", text) if not v.startswith(COMPANY)})
        report(not variants, f"{name}：社名の書き違いがない（{variants or 'なし'}）")
        if name in WITH_COMPANY:
            report(COMPANY in text, f"{name}：社名「{COMPANY}」")
        homes = re.findall(r"東京都大田区東糀谷八丁目[\d０-９]+番[\d０-９]+号", text)
        report(all(h == ADDRESS for h in homes), f"{name}：本店の所在地の書き違いがない（{sorted(set(homes)) or '載っていない'}）")
        if name in WITH_ADDRESS:
            report(ADDRESS in text, f"{name}：本店の所在地「{ADDRESS}」")
        reps = re.findall(r"代表取締役(沢村\S{2})|代表者の?氏?名?(沢村\S{2})", text)
        reps = sorted({a or b for a, b in reps})
        report(all(r == PRESIDENT for r in reps), f"{name}：代表者の書き違いがない（{reps or '載っていない'}）")
        if name in WITH_PRESIDENT:
            report(PRESIDENT in text, f"{name}：代表者「{PRESIDENT}」")


def check_employees() -> None:
    print("\n■ 従業員数（書類どうしで同じ）")
    wb = load_workbook(SET_DIR / "労働者名簿.xlsx")
    ws = wb.worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True) if isinstance(r[0], int)]
    report(len(rows) == EMPLOYEES, f"労働者名簿：{len(rows)}人（回答表 C-01 {EMPLOYEES}人）")
    gaikyo = text_of("法人事業概況説明書_第18期.pdf")
    m_emp = re.search(r"従業員\s+(\d+)人", gaikyo)
    m_off = re.search(r"常勤役員\s+(\d+)人", gaikyo)
    report(m_emp is not None and int(m_emp[1]) == len(rows), f"法人事業概況説明書の従業員 {m_emp and m_emp[1]}人 ＝ 労働者名簿 {len(rows)}人")
    officers = Document(str(SET_DIR / "役員名簿.docx")).tables[0].rows[1:]
    report(m_off is not None and int(m_off[1]) == len(officers) == OFFICERS, f"法人事業概況説明書の常勤役員 {m_off and m_off[1]}人 ＝ 役員名簿 {len(officers)}人")


def quote_subtotal(name: str) -> int:
    return int(re.search(r"小計（税抜）\s+([\d,]+)", text_of(name))[1].replace(",", ""))


def check_quotes() -> None:
    print("\n■ 見積書（50万円以上の設備の見積、相見積、税込と税抜）")
    main_q, compare_q = "見積書_つばさ台フードシステム.pdf", "見積書_ほしみ機工.pdf"
    rows = re.findall(r"^\s*\d+\s+.+?\s+\S+\s+\d+\s+(?:台|式)\s+([\d,]+)\s+([\d,]+)\s*$", text_of(main_q), re.M)
    amounts = [int(a.replace(",", "")) for _, a in rows]
    big = [a for a in amounts if a >= 500_000]
    report(len(big) == len(amounts) and len(amounts) >= 6, f"{main_q}：明細 {len(amounts)} 行がどれも見積書にある（50万円以上の行 {len(big)}）")
    report(quote_subtotal(main_q) >= 500_000, f"1者あたりの見積の合計 {quote_subtotal(main_q):,}円（50万円以上なので、相見積が要る。公募要領 3-4）")
    report(quote_subtotal(main_q) < quote_subtotal(compare_q), f"頼むつもりの会社が最も安い：つばさ台 {quote_subtotal(main_q):,}円 ＜ ほしみ機工 {quote_subtotal(compare_q):,}円")
    for name in (main_q, compare_q):
        text = text_of(name)
        report(
            "単価（税抜）" in text and "金額（税抜）" in text and "小計（税抜）" in text and "合計（税込）" in text,
            f"{name}：明細と小計は税抜、合計は税込と、どの欄にも書いてある（混ざっていない）",
        )
    catalog = flat(text_of("カタログ_つばさ台フードシステム.pdf"))
    # 型番の後ろは空白で区切られている（空白を除くと数量の数字とつながるので、元の文字で探す）
    models = re.findall(r"TF-[A-Z]+\d+(?!\d)", text_of(main_q))
    lacking = sorted({m for m in models if m not in catalog})
    report(not lacking and len(set(models)) >= 6, f"見積書の型番 {len(set(models))} 種が、どれもカタログに載る（載っていない：{lacking or 'なし'}）")


def check_no_order() -> None:
    print("\n■ 事前着手（発注・契約・納品・請求の書類がない）")
    for name in KINDS:
        title = flat(text_of(name))[:200]
        hit = ORDER_WORDS.search(title)
        report(hit is None, f"{name}：発注・契約などの書類でない（{hit[0] if hit else '当たらない'}）")
    report(not any(ORDER_WORDS.search(n) for n in KINDS), "ファイルの名前にも、発注・契約などの言葉がない")


# ---------------------------------------------------------------------------
# 6. 公募要領 4-4 との対応と、セットの一覧
# ---------------------------------------------------------------------------

# 省力化（一般型）第8回 公募要領 4-4（downloads/shoryokuka_ippan/application_guidelines_ippan_08.pdf の PDF 27ページ目）
REQUIRED = [
    ("① 損益計算書 直近2期分（製造原価報告書、販管費明細、個別注記表を含む）", ["決算書_第17期.pdf", "決算書_第18期.pdf"]),
    ("① 貸借対照表 直近2期分", ["決算書_第17期.pdf", "決算書_第18期.pdf"]),
    ("① 事業計画書（その1・その2・その3）", None),
    ("① 50万円以上の機械装置の仕様・積算根拠が分かる書類（参考見積書、カタログなど）", ["見積書_つばさ台フードシステム.pdf", "見積書_ほしみ機工.pdf", "カタログ_つばさ台フードシステム.pdf"]),
    ("② 履歴事項全部証明書（発行から3か月以内）", ["履歴事項全部証明書.pdf"]),
    ("② 納税証明書（その2）直近3期分", ["納税証明書_その2.jpg"]),
    ("② 法人事業概況説明書", ["法人事業概況説明書_第18期.pdf"]),
    ("② 【指定様式】役員名簿", None),
    ("② 【指定様式】株主・出資者名簿", None),
]


def check_required() -> None:
    print("\n■ 公募要領 4-4 ①② の書類と、セットのファイル")
    for item, files in REQUIRED:
        if files is None:
            print(f"  － {item}：ツールが様式に書き込んで作る（セットに入れない）")
            continue
        missing = [f for f in files if not (SET_DIR / f).is_file()]
        report(not missing, f"{item}：{'、'.join(files)}")
    print("  － ほかに入れたもの：役員名簿.docx・株主名簿.docx（指定様式の元になる、会社が持つ名簿）、労働者名簿.xlsx（従業員数の裏付け）")


def page_count(path: Path) -> str:
    if path.suffix == ".pdf":
        return f"{len(PdfReader(str(path)).pages)}ページ"
    if path.suffix == ".jpg":
        with Image.open(path) as img:
            return f"{img.size[0]}×{img.size[1]}"
    if path.suffix == ".xlsx":
        return f"{len(load_workbook(path).worksheets)}シート"
    return "—"


def print_list() -> None:
    print("\n■ セットの書類の一覧")
    labels = {".pdf": "PDF", ".jpg": "写真（JPEG）", ".docx": "Word", ".xlsx": "Excel"}
    for path in sorted(SET_DIR.iterdir(), key=lambda p: list(KINDS).index(p.name) if p.name in KINDS else 99):
        form = labels.get(path.suffix, path.suffix)
        if path.name == SCAN[0]:
            form = "PDF（スキャン。文字なし）"
        print(f"  {path.name}｜{KINDS.get(path.name, '?')}｜{form}｜{page_count(path)}")


def main() -> None:
    check_files()
    check_formats()
    check_sources()
    check_source_checks()
    check_marks()
    check_periods()
    check_dates()
    check_names()
    check_employees()
    check_quotes()
    check_no_order()
    check_required()
    print_list()
    print()
    if failures:
        print(f"合わないもの：{len(failures)}件")
        for f in failures:
            print(f"  × {f}")
        sys.exit(1)
    print("すべて合いました。")


if __name__ == "__main__":
    main()
