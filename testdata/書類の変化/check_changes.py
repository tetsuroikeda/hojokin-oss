# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pillow==13.0.0", "pypdf>=4"]
# ///
"""書類の変化と整理の材料（TASKS D6）を確かめる。

確かめること：
1. 材料のフォルダに、書類だけがある（スクリプトや答えの文書がない）。どこにも「原本/」などツールの置き場がない。
2. T5-3：前と後で、足した1件・書き換えた1件・動かした1件・名前を変えた1件のほかは、同じ場所・同じバイト列。
   動かしたもの・名前を変えたものは前と同じバイト列で、中身のハッシュで見ると「変わっていない」になる。
   中身のハッシュで見つけると、足したものと書き換えたものの2件だけが出る。書き換えた労働者名簿は、決めた2か所だけが違う。
3. T5-4：11件（種類が分かる8件、分からない2件、同じ中身の1件）。8件は元の書類と同じバイト列で、
   正解の種類と日付が中身にある。名前はどれも決まった形でない。同じ中身の1件はバイト列まで同じ。
   分からない2件は、ほかのどれとも違い、表題・日付・相手先がない。置き場所が5か所以上に散らばる。
4. T5-6：取り直した納税証明書は、古い原本と発行日だけが違う（期と所得金額は同じ）。古い発行日で作り直すと、D2a と同じバイト列。
5. T13-8：会社概要の従業員数は18名で、会社の記録（回答表 C-01、労働者名簿の15人）と違う。役員2人を足しても合わない。
   ほかの事実（社名・代表者・所在地・設立・資本金）は回答表と同じ。
6. どのファイルにも「架空のテスト用データ」がある（写真とスキャンは、作った元で見る）。
7. 正解.json が作り方と合う。作り直すと、どのファイルも同じバイト列になる。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/書類の変化/check_changes.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_changes as mc  # noqa: E402

MARK = "架空のテスト用データ"
ANSWER_SHEET = mc.REPO / "testdata" / "デモの会社" / "回答表.md"
TOOL_DIRS = (mc.ORIGINALS_DIR, "記録", "案件", ".hojokin", ".claude", ".git", "見るだけ")
DOC_SUFFIXES = {".pdf", ".jpg", ".docx", ".xlsx"}
FIXED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_")
# 種類の名前と、書類の中の見出しが違うもの（種類 → 見出し）
KIND_TITLES = {"決算書（第18期）": "第18期決算報告書", "カタログ": "製品のご案内"}

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_under(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def pdf_text(path: Path) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    for section in doc.sections:
        parts.extend(p.text for p in section.header.paragraphs)
        parts.extend(p.text for p in section.footer.paragraphs)
    return "\n".join(parts)


def xlsx_cells(path: Path) -> list[list]:
    wb = load_workbook(str(path))
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
    return rows


def xlsx_text(path: Path) -> str:
    return "\n".join(str(v) for row in xlsx_cells(path) for v in row if v is not None)


def text_of(path: Path) -> str:
    return {".pdf": pdf_text, ".docx": docx_text, ".xlsx": xlsx_text}.get(path.suffix, lambda _: "")(path)


def date_forms(iso: str) -> list[str]:
    """2026-10-20 → 「2026年10月20日」「令和8年10月20日」。"""
    y, m, d = (int(x) for x in iso.split("-"))
    return [f"{y}年{m}月{d}日", f"令和{y - 2018}年{m}月{d}日"]


# ---------------------------------------------------------------------------


def check_material_dirs() -> None:
    for d in mc.MATERIAL_DIRS:
        check(d.is_dir(), f"材料のフォルダ {d.name}/ がある")
        found = files_under(d)
        others = [p for p in found if Path(p).suffix not in DOC_SUFFIXES]
        check(not others, f"{d.name}/ に書類のほかのファイル（スクリプト・答え）がない {others or ''}")
    for root in (mc.BEFORE_DIR, mc.AFTER_DIR, mc.SCATTER_DIR):
        bad = [p for p in files_under(root) if p.split("/")[0] in TOOL_DIRS]
        check(not bad, f"{root.relative_to(HERE)}/ で、原本・記録・案件などツールの置き場に書類を置いていない {bad or ''}")
    check(mc.ANSWER_FILE.is_file(), "正解.json がある（材料のフォルダの外）")


def check_open() -> None:
    before = files_under(mc.BEFORE_DIR)
    after = files_under(mc.AFTER_DIR)
    want_before = set(mc.BEFORE_FILES)
    want_after = (want_before - {mc.MOVED[0], mc.RENAMED[0]}) | {mc.ADDED[0], mc.MOVED[1], mc.RENAMED[1]}
    check(set(before) == want_before, f"T5-3 前の書類が決めた{len(want_before)}件だけ")
    check(set(after) == want_after, f"T5-3 後の書類が決めた{len(want_after)}件だけ")
    for place, src in mc.BEFORE_FILES.items():
        if place in before:
            check(sha(before[place]) == sha(src), f"T5-3 前の {place} は元の書類と同じバイト列")
    if set(before) != want_before or set(after) != want_after:
        return

    unchanged = want_before - {mc.MOVED[0], mc.RENAMED[0], mc.REWRITTEN}
    for place in sorted(unchanged):
        check(sha(before[place]) == sha(after[place]), f"T5-3 変えていない {place} は前後で同じバイト列")

    # 足し
    check(mc.ADDED[0] not in before, "T5-3 足したものは前にない")
    check(sha(after[mc.ADDED[0]]) not in {sha(p) for p in before.values()}, "T5-3 足したものは、前のどの書類とも中身が違う")
    check(sha(after[mc.ADDED[0]]) == sha(mc.ADDED[1]), "T5-3 足したものは D2b の見積書（ほしみ機工）と同じバイト列")

    # 動かし
    m0, m1 = Path(mc.MOVED[0]), Path(mc.MOVED[1])
    check(m0.name == m1.name and m0.parent != m1.parent, "T5-3 動かしたものは、名前が同じで場所が違う")
    check(mc.MOVED[0] not in after, "T5-3 動かしたものは、元の場所に残っていない")
    check(sha(before[mc.MOVED[0]]) == sha(after[mc.MOVED[1]]), "T5-3 動かしたものは前と同じバイト列")

    # 名前を変え
    r0, r1 = Path(mc.RENAMED[0]), Path(mc.RENAMED[1])
    check(r0.parent == r1.parent and r0.name != r1.name, "T5-3 名前を変えたものは、場所が同じで名前が違う")
    check(mc.RENAMED[0] not in after, "T5-3 名前を変えたものは、元の名前で残っていない")
    check(sha(before[mc.RENAMED[0]]) == sha(after[mc.RENAMED[1]]), "T5-3 名前を変えたものは前と同じバイト列")

    # 書き換え
    old, new = before[mc.REWRITTEN], after[mc.REWRITTEN]
    check(sha(old) != sha(new), "T5-3 書き換えたものは、同じ場所で中身が違う")
    old_cells, new_cells = xlsx_cells(old), xlsx_cells(new)
    diffs = []
    for r, (a, b) in enumerate(zip(old_cells, new_cells), start=1):
        for c, (x, y) in enumerate(zip(a, b), start=1):
            if x != y:
                diffs.append((r, c, x, y))
    same_shape = len(old_cells) == len(new_cells) and all(len(a) == len(b) for a, b in zip(old_cells, new_cells))
    check(same_shape, "T5-3 書き換えた労働者名簿は、行と列の数が同じ（人数は変えていない）")
    want = {mc.REWRITE_AS_OF, mc.REWRITE_ADDRESS}
    got = {d[3] for d in diffs}
    check(
        len(diffs) == 2 and any(mc.REWRITE_AS_OF in str(v) for v in got) and mc.REWRITE_ADDRESS in got,
        f"T5-3 書き換えた労働者名簿は「現在」の日と {mc.REWRITE_WORKER} の住所の2か所だけが違う（{len(diffs)}か所。{want}）",
    )
    people = [row for row in new_cells if isinstance(row[0], int)]
    check(len(people) == mc.RECORD_EMPLOYEES, f"T5-3 書き換えた労働者名簿も{mc.RECORD_EMPLOYEES}人のまま")
    with tempfile.TemporaryDirectory() as tmp:
        again = Path(tmp) / "労働者名簿.xlsx"
        mc.build_worker_list(again, mc.d2b.AS_OF, list(mc.d2b.WORKERS))
        check(sha(again) == sha(mc.DOCS / "労働者名簿.xlsx"),
              "T5-3 書き換えの作り方は、値を変えなければ D2b の労働者名簿と同じバイト列（変えたのは決めた値だけ）")

    # 中身のハッシュで見つける（SPEC F5：移しただけ・名前を変えただけは変わったとしない）
    before_hashes = {sha(p) for p in before.values()}
    check(len(before_hashes) == len(before), "T5-3 前の書類は、どれも中身が違う（ハッシュで見分けられる）")
    check(len({sha(p) for p in after.values()}) == len(after), "T5-3 後の書類は、どれも中身が違う（ハッシュで見分けられる）")
    added = sorted(p for p, f in after.items() if sha(f) not in before_hashes and p not in before)
    rewritten = sorted(p for p, f in after.items() if sha(f) not in before_hashes and p in before)
    check(added == [mc.ADDED[0]], f"T5-3 中身のハッシュで「足した」と出るのは {mc.ADDED[0]} だけ（{added}）")
    check(rewritten == [mc.REWRITTEN], f"T5-3 中身のハッシュで「書き換えた」と出るのは {mc.REWRITTEN} だけ（{rewritten}）")


def check_scattered() -> None:
    found = files_under(mc.SCATTER_DIR)
    identifiable = {place: (src, form, kind, dates, party, area) for place, src, form, kind, dates, party, area in mc.IDENTIFIABLE}
    unknown = {place: (form, why) for place, form, why in mc.UNKNOWN}
    want = set(identifiable) | set(unknown) | {mc.DUPLICATE[0]}
    check(len(found) == 11 and set(found) == want, f"T5-4 散らばった書類が11件（{len(found)}件）")
    check(len(identifiable) == 8 and len(unknown) == 2, "T5-4 内訳は、種類が分かる8件・分からない2件・同じ中身1件")
    if set(found) != want:
        return

    parents = {str(Path(p).parent) for p in found}
    check(len(parents) >= 5, f"T5-4 置き場所が5か所以上に散らばる（{len(parents)}か所：{sorted(parents)}）")
    fixed = [p for p in found if FIXED_NAME.match(Path(p).name)]
    check(not fixed, f"T5-4 どの名前も決まった形（日付_種類_相手先）でない {fixed or ''}")

    # 種類が分かる8件
    for place, (src, form, kind, dates, party, area) in identifiable.items():
        path = found[place]
        check(sha(path) == sha(src), f"T5-4 {place} は元の書類（{src.name}）と同じバイト列")
        check(area in mc.ORIGINAL_KINDS, f"T5-4 {place} の行き先「{area}」は、会社のフォルダの原本の区分にある")
        # 正解の種類と日付が中身にあるか。写真とスキャンは文字がないので、作った元（D2a の PDF）で見る
        origin = {"履歴事項全部証明書.pdf": mc.DOCS / "履歴事項全部証明書.pdf",
                  "納税証明書_その2.jpg": mc.DOCS / "納税証明書_その2.pdf"}.get(src.name, src)
        text = re.sub(r"\s", "", text_of(origin))
        title = KIND_TITLES.get(kind, kind.split("（")[0])
        check(title in text, f"T5-4 {place} の中身に、種類「{kind}」が分かる見出し「{title}」がある")
        for label, value in dates.items():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                ok = any(f in text for f in date_forms(value))
            else:
                ok = value in text
            check(ok, f"T5-4 {place} の中身に {label}（{value}）がある")
        if party:
            name = party.split("（")[0]
            check(name in text, f"T5-4 {place} の中身に相手先「{name}」がある")
        check(MARK in text, f"T5-4 {place} に「{MARK}」がある（写真とスキャンは作った元で見る）")
    forms = {form for _, _, form, *_ in mc.IDENTIFIABLE}
    check({"PDF", "スキャンした PDF", "写真", "Word", "Excel"} <= forms, f"T5-4 形式に PDF・スキャン・写真・Word・Excel がそろう（{sorted(forms)}）")
    scan = found[f"{mc.INBOX_DIR}/scan0001.pdf"]
    check(pdf_text(scan).strip() == "", "T5-4 スキャンした PDF には文字の層がない")

    # 同じ中身の1件
    check(sha(found[mc.DUPLICATE[0]]) == sha(found[mc.DUPLICATE[1]]), "T5-4 同じ中身の1件は、相手とバイト列まで同じ")
    check(Path(mc.DUPLICATE[0]).name != Path(mc.DUPLICATE[1]).name
          and Path(mc.DUPLICATE[0]).parent != Path(mc.DUPLICATE[1]).parent,
          "T5-4 同じ中身の1件は、相手と名前も場所も違う")
    hashes = [sha(p) for p in found.values()]
    check(len(set(hashes)) == 10, f"T5-4 同じ中身の組は1組だけ（中身の種類 {len(set(hashes))}／11件）")

    # 分からない2件
    others = {sha(found[p]) for p in found if p not in unknown}
    for place in unknown:
        check(sha(found[place]) not in others, f"T5-4 分からない {place} は、ほかのどの書類とも中身が違う")
    table = xlsx_cells(found[mc.UNKNOWN_TABLE])
    strings = {v for row in table for v in row if isinstance(v, str)}
    numbers = [v for row in table for v in row if isinstance(v, (int, float))]
    check(strings == {mc.MARK} and len(numbers) == 3 * len(mc.UNKNOWN_ROWS),
          "T5-4 分からない表は、架空の印のほかに文字（表題・項目の名前・日付・相手先）がなく、数だけ")
    with Image.open(found[mc.UNKNOWN_PHOTO]) as img:
        check(img.format == "JPEG", "T5-4 分からないメモは写真（JPEG）")
    # 写真の文字は読み取れないので、描いた文字（作り方の MEMO_LINES）で見る
    check(not any(re.search(r"\d{4}年|\d+月\d+日|御中|様|株式会社|見積|請求|納品|証明|名簿|決算", s) for s in mc.MEMO_LINES),
          "T5-4 分からないメモの文字には、表題・日付・相手先がない")


def check_reissue() -> None:
    new = mc.REISSUE_DIR / mc.REISSUE_FILE
    old = mc.OLD_TAX_CERTIFICATE
    check(files_under(mc.REISSUE_DIR) == {mc.REISSUE_FILE: new}, "T5-6 取り直した納税証明書の1件だけがある")
    if not new.is_file():
        return
    check(sha(new) != sha(old), "T5-6 取り直したものは、古い原本と中身が違う（新しい原本になる）")
    new_lines = [s for s in pdf_text(new).splitlines() if s.strip()]
    old_lines = [s for s in pdf_text(old).splitlines() if s.strip()]
    diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    check(len(old_lines) == len(new_lines) and len(diff) == 1,
          f"T5-6 古い原本と違う行は1行だけ（{len(diff)}行）")
    check(diff == [(f"発行日　{mc.OLD_ISSUED}", f"発行日　{mc.NEW_ISSUED}")],
          f"T5-6 違うのは発行日だけ（{mc.OLD_ISSUED} → {mc.NEW_ISSUED}）")
    text = re.sub(r"\s", "", "".join(new_lines))
    for start, end, income in mc.d2a.TAXABLE_INCOME:
        check(f"{start}〜{end}" in text and mc.d2a.yen(income) in text,
              f"T5-6 期 {start}〜{end} と所得金額が古い原本と同じ")
    check(MARK in text and mc.d2a.COMPANY in text and mc.d2a.ADDRESS in text, "T5-6 架空の印・社名・所在地がある")
    with tempfile.TemporaryDirectory() as tmp:
        again = Path(tmp) / "納税証明書_その2.pdf"
        mc.build_tax_certificate(again, mc.OLD_ISSUED)
        check(sha(again) == sha(old), "T5-6 古い発行日で作り直すと D2a の納税証明書と同じバイト列（変えたのは発行日だけ）")


def check_mismatch() -> None:
    path = mc.MISMATCH_DIR / mc.MISMATCH_FILE
    check(files_under(mc.MISMATCH_DIR) == {mc.MISMATCH_FILE: path}, "T13-8 会社概要の1件だけがある")
    if not path.is_file():
        return
    text = docx_text(path)
    flat = re.sub(r"\s", "", text)
    sheet = ANSWER_SHEET.read_text(encoding="utf-8")
    m = re.search(r"^\| C-01 \| 従業員の数 \| (\d+)人", sheet, re.M)
    record = int(m.group(1)) if m else None
    check(record == mc.RECORD_EMPLOYEES, f"T13-8 回答表 C-01 の従業員数は {mc.RECORD_EMPLOYEES}人（{record}）")
    workers = [row for row in xlsx_cells(mc.DOCS / "労働者名簿.xlsx") if isinstance(row[0], int)]
    check(len(workers) == mc.RECORD_EMPLOYEES, f"T13-8 D2b の労働者名簿も {mc.RECORD_EMPLOYEES}人（{len(workers)}人）")
    check(f"従業員数{mc.DOC_EMPLOYEES}名" in flat or f"{mc.DOC_EMPLOYEES}名（" in flat,
          f"T13-8 会社概要の従業員数は {mc.DOC_EMPLOYEES}名")
    check(f"{mc.RECORD_EMPLOYEES}名" not in flat and f"{mc.RECORD_EMPLOYEES}人" not in flat,
          f"T13-8 会社概要に記録の {mc.RECORD_EMPLOYEES} という人数は出てこない（どちらが正しいかを書類から決められない）")
    check(mc.DOC_EMPLOYEES not in (mc.RECORD_EMPLOYEES, mc.RECORD_EMPLOYEES + 2),
          "T13-8 書類の人数は、記録とも、記録に役員2人を足した数とも違う")
    check(mc.MISMATCH_DATE in flat, f"T13-8 会社概要に日付（{mc.MISMATCH_DATE}）がある（出典として示せる）")
    flat_sheet = re.sub(r"\s", "", sheet)
    # (何か, 会社概要の書き方, 回答表の書き方)
    for what, in_doc, in_sheet in [
        ("社名（A-01）", "株式会社やまぶき惣菜", "|A-01|社名|株式会社やまぶき惣菜|"),
        ("代表者（A-08）", "代表取締役沢村宏之", "代表取締役沢村宏之"),
        ("所在地（B-01）", "東京都大田区東糀谷八丁目12番5号", "|B-01|本店と工場の所在地|東京都大田区東糀谷八丁目12番5号"),
        ("郵便番号（B-02）", "144-0033", "|B-02|郵便番号|144-0033|"),
        ("設立（A-04）", "2008年4月1日", "|A-04|設立|2008年4月1日"),
        ("資本金（A-06）", "1,000万円", "|A-06|資本金|10,000千円|"),
    ]:
        check(in_doc in flat and in_sheet in flat_sheet, f"T13-8 会社概要の{what}は回答表と同じ（{in_doc}）")
    check(MARK in text, f"T13-8 会社概要に「{MARK}」がある")


def check_marks() -> None:
    for root in (mc.BEFORE_DIR, mc.AFTER_DIR):
        for place, path in files_under(root).items():
            check(MARK in text_of(path), f"{root.relative_to(HERE)}/{place} に「{MARK}」がある")


def check_answers_and_rebuild() -> None:
    saved = json.loads(mc.ANSWER_FILE.read_text(encoding="utf-8"))
    check(saved == mc.answers(), "正解.json が作り方の答えと同じ")
    t54 = saved["T5-4 散らばった書類"]
    check(t54["件数"] == {"種類が分かる": 8, "分からない": 2, "同じ中身": 1}, "正解.json の11件の内訳が 8・2・1")
    areas = {item["原本の区分"].split("/", 1)[1] for item in t54["種類が分かる"]}
    check(areas <= set(mc.ORIGINAL_KINDS), "正解.json の原本の区分は lib/company_init.py の区分の名前")
    t53 = saved["T5-3 開いたときの確認"]
    check([o["操作"] for o in t53["操作"]] == ["足し", "書き換え", "動かし", "名前を変え"], "正解.json の T5-3 の操作が4つ")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        mc.build(out)
        for d in mc.MATERIAL_DIRS:
            mine, again = files_under(d), files_under(out / d.name)
            check(set(mine) == set(again), f"作り直すと {d.name}/ に同じファイルがそろう")
            for place in sorted(set(mine) & set(again)):
                check(sha(mine[place]) == sha(again[place]), f"作り直すと {d.name}/{place} が同じバイト列")
        check(sha(out / mc.ANSWER_FILE.name) == sha(mc.ANSWER_FILE), "作り直すと 正解.json が同じバイト列")


def main() -> None:
    check_material_dirs()
    check_open()
    check_scattered()
    check_reissue()
    check_mismatch()
    check_marks()
    check_answers_and_rebuild()
    bad = [what for ok, what in results if not ok]
    for ok, what in results:
        print(("○ " if ok else "× ") + what)
    print(f"\n○{len(results) - len(bad)}件、×{len(bad)}件")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
