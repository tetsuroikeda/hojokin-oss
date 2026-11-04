# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pypdfium2==5.14.0", "pillow==13.0.0", "pypdf>=4"]
# ///
"""不備を仕込んだ書類セット（TASKS D5b）に、一覧のとおりの不備が入っていて、ほかの不備がないことを確かめる。

T5-1 は「重大な不備の見逃し0件、ほかは90%以上を検出」を、仕込んだ不備の一覧と突き合わせて見る（DESIGN 11章）。
そのため、一覧の不備がどれも本当にセットの書類にあり、一覧にない不備がないことを、ここで確かめる。

確かめること：
1. セットのフォルダに、決まった書類だけがある（スクリプトや答えの文書がない）。
2. PDF（文字の入ったもの）、スキャンした PDF、写真、Word、Excel がそろい、どの形式にも不備がある。
3. 作り直すと同じバイト列になる（セットと一覧が、スクリプトから作ったもの）。
4. 不備を仕込んだのと同じ道筋で、値を差し替えずに描くと、D2a・D2b の元の書類と同じバイト列になる。
   正しいセットのまま写した書類は、正しいセットと同じバイト列。
5. 作り直した書類の文字は、正しい書類の文字に、仕込んだ値の差し替えだけをしたものと同じ（ほかに変わった所がない）。
6. 一覧の不備を1つずつ、書類の文字・数字・日付から機械的に見つける。
7. 一覧にない不備がない（名義、見積書の計算、日付、従業員数、事前着手を、セットのすべての書類で見る）。
8. 一覧の形：種類が15以上、型が knowledge/不備の型.json にあり重さが合う、SPEC の重大の5つがそろう、どの不備にも直し方がある。
9. 正しいセットの確かめ（D5a の check_correct_set.py）が通る。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/書類セット/check_defect_set.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import check_correct_set as cc  # noqa: E402
import make_defect_set as m  # noqa: E402

REPO = m.REPO
DOCS = m.DOCS
SET_DIR = m.SET_DIR
CORRECT_DIR = m.CORRECT_DIR
KNOWLEDGE = json.loads((REPO / "knowledge" / "不備の型.json").read_text(encoding="utf-8"))
SEIKAI = json.loads((REPO / "testdata" / "正解" / "省力化_第8回.json").read_text(encoding="utf-8"))

MARK = cc.MARK
COMPANY = cc.COMPANY
ADDRESS = cc.ADDRESS
PRESIDENT = cc.PRESIDENT  # 空白を除いた形
APPLY_FROM = dt.date.fromisoformat(m.APPLY_FROM)
APPLY_UNTIL = dt.date.fromisoformat(m.APPLY_UNTIL)
SPEC_CRITICAL = ["期限切れ", "期数不足", "金額の不一致", "名義の不一致", "事前着手"]
QUOTE_FILES = ["見積書_つばさ台フードシステム.pdf", "見積書_ほしみ機工.pdf", "見積書_つばさ台フードシステム_ライン管理端末.pdf"]
MAIN_QUOTE = "見積書_つばさ台フードシステム.pdf"
TERMINAL_QUOTE = "見積書_つばさ台フードシステム_ライン管理端末.pdf"
GAIKYO = "法人事業概況説明書_第18期.pdf"

failures: list[str] = []
found: dict[str, bool] = {}  # 不備の id → 機械的に見つかったか
SRC: Path  # 写真とスキャンの元にした PDF（作り直したもの）を置く場所。main で決める


def report(ok: bool, text: str) -> None:
    print(f"  {'○' if ok else '×'} {text}")
    if not ok:
        failures.append(text)


def detect(defect_id: str, ok: bool, text: str) -> None:
    """一覧の不備を見つけたかを記録する。"""
    report(ok, f"{defect_id}：{text}")
    found[defect_id] = found.get(defect_id, True) and ok


flat = cc.flat
wareki = cc.wareki


def read_text(path: Path) -> str:
    if path.suffix == ".pdf":
        return "\n".join(cc.pdf_pages(path))
    if path.suffix == ".docx":
        return cc.docx_text(path)
    return cc.xlsx_text(path)


def source_of(name: str) -> str | None:
    return m.PHOTO_SOURCES.get(name) or m.SCAN_SOURCES.get(name)


def set_text(name: str) -> str:
    """セットの書類の文字。写真とスキャンは、元にした PDF（作り直して同じバイト列になったもの）の文字。"""
    src = source_of(name)
    return read_text(SRC / src if src else SET_DIR / name)


def correct_text(name: str) -> str:
    """正しいセットの同じ書類の文字。写真とスキャンは、D2a の元の PDF の文字。"""
    src = source_of(name)
    return read_text(DOCS / src if src else CORRECT_DIR / name)


def ymd(text: str, label: str) -> dt.date:
    mm = re.search(label + r"\s*(\d{4})年(\d+)月(\d+)日", text)
    return dt.date(*map(int, mm.groups()))


def defects_of(name: str) -> list[str]:
    return [d["id"] for d in m.DEFECTS if name in d["書類"] or name in d.get("抜いた書類", [])]


# ---------------------------------------------------------------------------
# 1〜4. ファイル、形式、作り直し、元の書類との関係
# ---------------------------------------------------------------------------


def check_files() -> None:
    print("\n■ セットのファイル")
    found_names = sorted(p.name for p in SET_DIR.iterdir())
    want = sorted(name for name, *_ in m.FILES)
    report(found_names == want, f"セットのフォルダに決まった {len(want)} 件だけがある（余分：{sorted(set(found_names) - set(want)) or 'なし'}、足りない：{sorted(set(want) - set(found_names)) or 'なし'}）")
    report(not any(p.suffix in (".py", ".json", ".md") for p in SET_DIR.iterdir()), "スクリプトと答えの文書は、セットのフォルダの外にある")
    for name, _ in m.REMOVED:
        report(not (SET_DIR / name).exists() and (CORRECT_DIR / name).is_file(), f"{name}：正しいセットにあり、このセットにない（抜いた書類）")


def check_formats() -> None:
    print("\n■ 形式（どの形式にも不備がある）")
    groups: dict[str, list[str]] = {"文字の入った PDF": [], "スキャンした PDF": [], "写真": [], "Word": [], "Excel": []}
    for path in sorted(SET_DIR.iterdir()):
        if path.suffix == ".pdf":
            has_text = any(t.strip() for t in cc.pdf_pages(path))
            groups["文字の入った PDF" if has_text else "スキャンした PDF"].append(path.name)
        elif path.suffix == ".jpg":
            with Image.open(path) as img:
                ok = img.format == "JPEG" and img.size[0] >= 1000 and not img.getexif()
                size = img.size
            report(ok, f"{path.name}：JPEG、{size[0]}×{size[1]}、向きの印（EXIF）なし")
            groups["写真"].append(path.name)
        elif path.suffix == ".docx":
            groups["Word"].append(path.name)
        elif path.suffix == ".xlsx":
            groups["Excel"].append(path.name)
    report(groups["スキャンした PDF"] == list(m.SCAN_SOURCES), f"スキャンした PDF（文字のない、画像だけの PDF）：{groups['スキャンした PDF']}")
    report(groups["写真"] == list(m.PHOTO_SOURCES), f"写真：{groups['写真']}")
    for form, names in groups.items():
        ids = sorted({i for n in names for i in defects_of(n)})
        report(bool(names) and bool(ids), f"{form} {len(names)}件。仕込んだ不備：{'、'.join(ids) or 'なし'}")


def check_rebuild(tmp: Path) -> None:
    print("\n■ 作り直し（セットと一覧が、スクリプトから作ったもの）")
    rebuilt = tmp / "set"
    m.build(rebuilt, src_dir=SRC)
    for path in sorted(SET_DIR.iterdir()):
        same = (rebuilt / path.name).read_bytes() == path.read_bytes()
        report(same, f"{path.name}：作り直すと同じバイト列")
    m.write_list(tmp / "list.json")
    report((tmp / "list.json").read_text(encoding="utf-8") == m.LIST_FILE.read_text(encoding="utf-8"), f"{m.LIST_FILE.name}：作り直すと同じ中身")


def check_sources(tmp: Path) -> None:
    print("\n■ 元の書類との関係（違いは仕込んだ値だけ）")
    made = m.build_with_correct_values(tmp / "correct")
    for name, path in made.items():
        same = path.read_bytes() == (DOCS / name).read_bytes()
        report(same, f"{name}：同じ道筋で値を差し替えずに描くと、D2a・D2b の元の書類と同じバイト列")
    for name in m.UNCHANGED:
        same = (SET_DIR / name).read_bytes() == (CORRECT_DIR / name).read_bytes()
        report(same and not defects_of(name), f"{name}：正しいセットと同じバイト列で、不備を仕込んでいない")
    for name, _, _, how in m.FILES:
        if how == m.CHANGED:
            differs = (SET_DIR / name).read_bytes() != (CORRECT_DIR / name).read_bytes()
            report(differs and bool(defects_of(name)), f"{name}：正しいセットから作り直した（不備：{'、'.join(defects_of(name))}）")
        elif how == m.ADDED:
            report(not (CORRECT_DIR / name).exists() and bool(defects_of(name)), f"{name}：足した書類（不備：{'、'.join(defects_of(name))}）")
    for name in m.PHOTO_SOURCES | m.SCAN_SOURCES:
        pages = cc.pdf_pages(SRC / source_of(name))
        report(len(pages) == 1 and pages[0].count(MARK) >= 2, f"{name}：元の PDF の頭と足に「{MARK}」（写真とスキャンにも写っている）")
    for path in sorted(SET_DIR.iterdir()):
        if path.suffix == ".pdf" and not source_of(path.name):
            pages = cc.pdf_pages(path)
            report(all(t.count(MARK) >= 2 for t in pages), f"{path.name}：{len(pages)}ページすべての頭と足に「{MARK}」")
        elif path.suffix in (".docx", ".xlsx"):
            report(MARK in read_text(path), f"{path.name}：「{MARK}」がある")


# 作り直した書類の、正しい書類からの差し替え（空白を除いた文字で、前 → 後）
REPLACEMENTS = {
    "決算書_第18期.pdf": [(flat(m.d2a.ADDRESS), flat(m.WRONG_ADDRESS))],
    GAIKYO: [(flat(m.d2a.PRESIDENT), flat(m.WRONG_PRESIDENT))],
    "納税証明書_その2.jpg": [("令和5年4月1日〜令和6年3月31日2,500,000", "")],
    "履歴事項全部証明書.pdf": [(f"発行日{m.d2a.REGISTRY_ISSUED}", f"発行日{m.OLD_REGISTRY_ISSUED}")],
    MAIN_QUOTE: [
        (m.d2b.QUOTES[m.TSUBASA_KEY]["number"], m.MAIN_QUOTE_NUMBER),
        (f"発行日{m.d2b.QUOTE_DATE}", f"発行日{m.MAIN_QUOTE_DATE}"),
        (f"有効期限{m.d2b.QUOTE_VALID_UNTIL}", f"有効期限{m.MAIN_QUOTE_VALID_UNTIL}"),
        ("TF-TS601台4,800,0004,800,000", "TF-TS601台4,600,0004,800,000"),
    ],
    "見積書_ほしみ機工.pdf": [(f"{COMPANY}御中", f"{m.WRONG_ADDRESSEE}御中")],
    "役員名簿.docx": [(COMPANY, m.WRONG_COMPANY)],
}


def check_diffs() -> None:
    print("\n■ 作り直した書類の文字（正しい書類に、仕込んだ値の差し替えだけをしたものと同じ）")
    for name, pairs in REPLACEMENTS.items():
        before, after = flat(correct_text(name)), flat(set_text(name))
        expected = before
        counts = []
        for old, new in pairs:
            counts.append(expected.count(old))
            expected = expected.replace(old, new)
        shown = "、".join(f"「{o}」→「{n or '（消す）'}」{c}か所" for (o, n), c in zip(pairs, counts))
        report(all(counts) and expected == after, f"{name}：{shown}。ほかに変わった所はない")
    # 労働者名簿は、行で比べる
    correct_rows = worker_rows(CORRECT_DIR / "労働者名簿.xlsx")
    rows = worker_rows(SET_DIR / "労働者名簿.xlsx")
    dropped = [r for r in correct_rows if r[1] not in {x[1] for x in rows}]
    report(
        rows == [r for r in correct_rows if r[1] != m.OMITTED_WORKER] and [r[1] for r in dropped] == [m.OMITTED_WORKER],
        f"労働者名簿.xlsx：正しい名簿から {m.OMITTED_WORKER} の行だけを抜いたもの（ほかの {len(rows)} 行は同じ）",
    )
    head_ok = cc.xlsx_text(SET_DIR / "労働者名簿.xlsx").split("\n")[:4] == cc.xlsx_text(CORRECT_DIR / "労働者名簿.xlsx").split("\n")[:4]
    report(head_ok, "労働者名簿.xlsx：表題と「2026年11月1日現在」の行は正しい名簿と同じ")


def worker_rows(path: Path) -> list[tuple]:
    ws = load_workbook(path).worksheets[0]
    return [tuple(r) for r in ws.iter_rows(values_only=True) if isinstance(r[0], int)]


# ---------------------------------------------------------------------------
# 6〜7. 不備を見つける。一覧にない不備がないことも見る
# ---------------------------------------------------------------------------


def check_dates() -> None:
    print(f"\n■ 期限（申請の日の範囲 {APPLY_FROM}〜{APPLY_UNTIL}）")
    registry = set_text("履歴事項全部証明書.pdf")
    issued = wareki(re.search(r"発行日\s*(令和\S+日)", registry)[1])
    valid_until = cc.add_months(issued, 3) - dt.timedelta(days=1)
    detect("仕込み-01", valid_until < APPLY_FROM, f"履歴事項全部証明書（スキャン）：発行日 {issued}、発行から3か月以内は {valid_until} まで。範囲の始め {APPLY_FROM} で、もう切れている")
    for name in QUOTE_FILES:
        text = set_text(name)
        q_issued, q_valid = ymd(text, "発行日"), ymd(text, "有効期限")
        report(q_issued <= APPLY_FROM, f"{name}：発行日 {q_issued} は範囲の始めより前（未来の日付でない）")
        if name == MAIN_QUOTE:
            detect("仕込み-02", q_valid < APPLY_FROM, f"{name}：有効期限 {q_valid} は範囲の始め {APPLY_FROM} より前")
        else:
            report(q_valid >= APPLY_UNTIL, f"{name}：有効期限 {q_valid} は範囲の終わり {APPLY_UNTIL} より後（切れていない。一覧にない期限切れはない）")
    for name, label in ((m.ORDER_FILE, "注文日"), (m.LAYOUT_FILE, "作成日"), (m.EXPENSE_FILE, "")):
        day = ymd(set_text(name), label)
        report(day <= APPLY_FROM, f"{name}：{label or '日付'} {day} は範囲の始めより前（未来の日付でない）")


def fiscal_periods(text: str) -> list[tuple[dt.date, dt.date]]:
    return [(wareki(a), wareki(b)) for a, b in re.findall(r"自\s*(令和\d+年\d+月\d+日)\s*至\s*(令和\d+年\d+月\d+日)", text)]


def check_periods() -> None:
    print("\n■ 期数（決算書は直近2期、納税証明書は直近3期）")
    latest = cc.latest_closed_year_end(APPLY_FROM)
    report(latest == cc.latest_closed_year_end(APPLY_UNTIL) == dt.date(2026, 3, 31), f"申請の日の範囲で、直近の決算は {latest}（範囲の中で変わらない）")
    statements = sorted(p.name for p in SET_DIR.iterdir() if p.name.startswith("決算書"))
    ends = sorted({e for n in statements for _, e in fiscal_periods(set_text(n))[:1]})
    want = [dt.date(2025, 3, 31), dt.date(2026, 3, 31)]
    lacking = "・".join(str(e) for e in sorted(set(want) - set(ends)))
    detect("仕込み-03", ends == [dt.date(2026, 3, 31)], f"決算書は {statements}（{'・'.join(map(str, ends))} に終わる期）だけ。直近2期のうち {lacking} に終わる第17期がない")
    tax = set_text("納税証明書_その2.jpg")
    years = sorted(wareki(b) for _, b in re.findall(r"(令和\d+年\d+月\d+日)〜(令和\d+年\d+月\d+日)", tax))
    detect("仕込み-04", years == want, f"納税証明書（その2、写真）は {len(years)}期分（{'・'.join(map(str, years))} に終わる期）。直近3期のうち 2024-03-31 に終わる第16期がない")
    issued = wareki(re.search(r"発行日\s*(令和\S+日)", tax)[1])
    report(issued > dt.date(2026, 5, 31), f"納税証明書の発行日 {issued} は第18期の申告の期限より後（足りないのは第16期だけ）")


NAME_RE = re.compile(r"(?:株式会社)?(?:やまぶき|山吹|ヤマブキ)(?:惣菜|総菜|そうざい|食品)(?:株式会社)?")
ADDRESS_RE = re.compile(r"東京都大田区東糀谷八丁目\d+番\d+号")
PRESIDENT_RE = re.compile(r"(?:代表取締役|代表者の?氏?名?)(沢村\S{2})")
# 名義の食い違いの答え：ファイル → (何, 書類にある値)
NAME_DEFECTS = {
    "役員名簿.docx": ("仕込み-05", "社名", m.WRONG_COMPANY),
    "決算書_第18期.pdf": ("仕込み-06", "所在地", m.WRONG_ADDRESS),
    GAIKYO: ("仕込み-07", "代表者", flat(m.WRONG_PRESIDENT)),
    "見積書_ほしみ機工.pdf": ("仕込み-08", "宛名の社名", m.WRONG_ADDRESSEE),
}
WITH_ADDRESS = ["決算書_第18期.pdf", GAIKYO, "納税証明書_その2.jpg", "履歴事項全部証明書.pdf", m.ORDER_FILE]


def check_names() -> None:
    print("\n■ 名義（社名・所在地・代表者。食い違うのは一覧の4つだけ）")
    for name, *_ in m.FILES:
        text = flat(set_text(name))
        names = sorted(set(NAME_RE.findall(text)))
        homes = sorted(set(ADDRESS_RE.findall(text)))
        reps = sorted(set(PRESIDENT_RE.findall(text)))
        odd = [v for v in names if v != COMPANY] + [v for v in homes if v != ADDRESS] + [v for v in reps if v != PRESIDENT]
        if name in NAME_DEFECTS:
            defect_id, what, value = NAME_DEFECTS[name]
            detect(defect_id, odd == [value], f"{name}：{what}が「{value}」で、ほかの書類と違う（この書類の食い違いはこれだけ：{odd}）")
            continue
        report(not odd, f"{name}：社名・所在地・代表者の食い違いがない（社名 {names or '－'}、所在地 {len(homes)}か所、代表者 {reps or '－'}）")
        if not name.startswith("カタログ"):
            report(COMPANY in text, f"{name}：社名「{COMPANY}」がある")
        if name in WITH_ADDRESS:
            report(ADDRESS in text, f"{name}：本店の所在地「{ADDRESS}」がある")


ROW_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s+(\S+)\s+(\d+)\s+(台|式|本)\s+([\d,]+)\s+([\d,]+)\s*$", re.M)


def num(s: str) -> int:
    return int(s.replace(",", ""))


def quote_rows(name: str) -> list[dict]:
    return [
        {"no": int(r[0]), "name": r[1], "model": r[2], "qty": int(r[3]), "price": num(r[5]), "amount": num(r[6])}
        for r in ROW_RE.findall(set_text(name))
    ]


def quote_sums(name: str) -> dict:
    text = set_text(name)
    return {
        key: num(re.search(label + r"\s+([\d,]+)", text)[1])
        for key, label in (("subtotal", r"小計（税抜）"), ("tax", r"消費税（10%）"), ("total", r"合計（税込）"), ("header", r"見積金額（税込）"))
    }


def check_quotes() -> None:
    print("\n■ 見積書の計算（数量 × 単価 ＝ 金額、明細の合計 ＝ 小計、小計 × 10% ＝ 消費税、小計 ＋ 消費税 ＝ 合計）")
    for name in QUOTE_FILES:
        rows, s = quote_rows(name), quote_sums(name)
        bad_rows = [r["no"] for r in rows if r["qty"] * r["price"] != r["amount"]]
        sum_ok = sum(r["amount"] for r in rows) == s["subtotal"]
        tax_ok = s["subtotal"] * 10 // 100 == s["tax"]
        total_ok = s["subtotal"] + s["tax"] == s["total"] == s["header"]
        summary = f"{len(rows)}行、小計 {s['subtotal']:,}、消費税 {s['tax']:,}、合計 {s['total']:,}"
        if name == MAIN_QUOTE:
            r3 = rows[m.MISPRICED_ROW]
            detect("仕込み-09", bad_rows == [3] and sum_ok and tax_ok and total_ok, f"{name}：合わないのは3行目だけ（{r3['name']} {r3['qty']} × {r3['price']:,} ≠ {r3['amount']:,}）。{summary} は合う")
        elif name == TERMINAL_QUOTE:
            detect("仕込み-10", not bad_rows and sum_ok and not tax_ok and total_ok, f"{name}：消費税 {s['tax']:,} ≠ 小計 {s['subtotal']:,} × 10% ＝ {s['subtotal'] // 10:,}。明細・小計・合計どうしは合う（{summary}）")
        else:
            report(not bad_rows and sum_ok and tax_ok and total_ok, f"{name}：計算はどれも合う（{summary}）")
    main_rows = quote_rows(MAIN_QUOTE)
    hoshimi = quote_sums("見積書_ほしみ機工.pdf")["subtotal"]
    report(quote_sums(MAIN_QUOTE)["subtotal"] < hoshimi, f"頼むつもりの会社が最も安い（{quote_sums(MAIN_QUOTE)['subtotal']:,} ＜ ほしみ機工 {hoshimi:,}）")
    catalog = flat(set_text("カタログ_つばさ台フードシステム.pdf"))
    models = sorted({r["model"] for name in QUOTE_FILES for r in quote_rows(name) if r["model"].startswith("TF-")})
    report(all(x in catalog for x in models) and len(models) >= 6, f"つばさ台の見積書の型番 {len(models)} 種が、どれもカタログに載る（足した見積書の行は型番「—」）")
    terminal = quote_rows(TERMINAL_QUOTE)
    report([r["model"] for r in terminal] == ["—", "—"], "ライン管理端末の見積書に、カタログにない型番を書いていない")
    pc = [r for r in terminal if "パソコン" in r["name"]]
    generic = [x for x in SEIKAI["補助の対象にならない経費"] if x["名前"] == "汎用性があり目的外に使えるもの"]
    note = "事務の仕事にもお使いいただけます" in flat(set_text(TERMINAL_QUOTE))
    detect(
        "仕込み-15",
        len(pc) == 1 and bool(generic) and "パソコン" in generic[0]["内容"]["値"] and note,
        f"{TERMINAL_QUOTE}：明細に「{pc[0]['name'] if pc else '?'}」{pc[0]['amount'] if pc else 0:,}円。正解の対象外「{generic[0]['名前'] if generic else '?'}」（事務用のパソコンなど）に当たる。備考に事務にも使えるとある",
    )
    robots = next(r for r in main_rows if r["model"] == "TF-MR200")
    layout = flat(set_text(m.LAYOUT_FILE))
    drawn = int(re.search(r"盛り付けロボットTF-MR200(\d+)台", layout)[1])
    boxes = len(re.findall(r"TF-MR200", layout)) - 1  # 図の箱の数（一覧の行を除く）
    detect(
        "仕込み-18",
        # カタログの構成図の箱「盛り付けロボット（2台）」は2行に折り返して描かれるので、「（2台）」で探す
        drawn == boxes == m.LAYOUT_ROBOTS != robots["qty"] and "（2台）" in catalog,
        f"{m.LAYOUT_FILE}：盛り付けロボット {drawn}台（図の箱も {boxes}つ）。見積書は {robots['qty']}台、カタログも2台",
    )
    for key in ("自動計量機", "トップシール包装機", "画像検査", "重量チェッカー", "搬送コンベヤ"):
        report(key in layout, f"{m.LAYOUT_FILE}：{key}は見積書と同じく1台（1式）")


def check_order() -> None:
    print("\n■ 事前着手（発注・契約などの書類は、注文書だけ）")
    hits = []
    for name, *_ in m.FILES:
        title = flat(set_text(name)).replace(flat(m.d2a.BANNER), "")[:120]
        if cc.ORDER_WORDS.search(title) or cc.ORDER_WORDS.search(name):
            hits.append(name)
    order = set_text(m.ORDER_FILE)
    day = ymd(order, "注文日")
    item = re.search(r"盛り付けロボット\s*TF-MR200\s*(\d+)台\s*([\d,]+)円\s*([\d,]+)円", order)
    detect(
        "仕込み-16",
        hits == [m.ORDER_FILE] and day < APPLY_FROM and item is not None,
        f"発注・契約などの書類は {hits}。注文日 {day}（申請の前で、交付決定はまだない）。注文したのは盛り付けロボット {item and item[1]}台 {item and item[3]}円",
    )
    main_row = next(r for r in quote_rows(MAIN_QUOTE) if r["model"] == "TF-MR200")
    report(item is not None and num(item[2]) == main_row["price"] and num(item[3]) == main_row["amount"], "注文書の単価と金額は、見積書の1行目と同じ（注文書に計算の不備はない）")
    sums = [num(v) for v in re.findall(r"(?:小計（税抜）|消費税（10%）|合計（税込）)\s*([\d,]+)円", order)]
    report(len(sums) == 3 and sums[0] * 10 // 100 == sums[1] and sums[0] + sums[1] == sums[2], f"注文書の小計・消費税・合計が合う（{sums}）")


def expense_rows() -> tuple[list[dict], dict]:
    ws = load_workbook(SET_DIR / m.EXPENSE_FILE).worksheets[0]
    header = [c.value for c in ws[m.EXPENSE_FIRST_ROW - 1]]
    rows = []
    for r in ws.iter_rows(min_row=m.EXPENSE_FIRST_ROW, values_only=True):
        if isinstance(r[0], int):
            rows.append({"name": r[1], "qty": r[2], "amount": r[3], "quote": r[4] or "", "memo": r[5] or ""})
        elif r[1] == "合計":
            total = r[3]
    return rows, {"header": header, "total": total}


def check_expenses() -> None:
    print("\n■ 設備の費用の控え（見積書との照らし合わせ）")
    rows, info = expense_rows()
    by_name = {r["name"]: r for r in rows}
    quote = {r["model"]: r["amount"] for r in quote_rows(MAIN_QUOTE)}
    quote["—"] = next(r["amount"] for r in quote_rows(MAIN_QUOTE) if r["name"].startswith("据付"))
    report(info["header"][3] == "金額（税抜・円）", f"金額の欄の見出しは「{info['header'][3]}」")
    report(info["total"] == sum(r["amount"] for r in rows), f"合計 {info['total']:,} ＝ 明細の和（控えの中の計算は合う）")
    # 見積書の行と同じはずの行（控えの品名 → 見積書の型番）
    same = {
        "盛り付けロボット": ["TF-MR200"],
        "トップシール包装機": ["TF-TS60"],
        "重量チェッカーとラベラー": ["TF-CL10"],
        "つなぐコンベヤと据え付け・調整": ["TF-CV8", "—"],
    }
    for key, models in same.items():
        want = sum(quote[x] for x in models)
        report(by_name[key]["amount"] == want, f"控えの {key} {by_name[key]['amount']:,} ＝ 見積書 {want:,}（一覧にない食い違いはない）")
    weigher = by_name["自動計量機"]
    detect("仕込み-11", weigher["amount"] != quote["TF-AW14"] and "つばさ台" in weigher["quote"], f"控えの自動計量機 {weigher['amount']:,} ≠ つばさ台の見積書 {quote['TF-AW14']:,}")
    camera = by_name["画像検査装置（盛り付けとラベル）"]
    detect(
        "仕込み-12",
        camera["amount"] == quote["TF-VI2"] * 110 // 100 and camera["memo"] == "税込" and "税抜" in info["header"][3],
        f"控えの画像検査装置 {camera['amount']:,}（メモ「{camera['memo']}」）＝ 見積書の税抜 {quote['TF-VI2']:,} × 1.1。欄の見出しは税抜",
    )
    detector = by_name["金属検出機"]
    in_quotes = any("金属検出" in set_text(n) for n in QUOTE_FILES + ["カタログ_つばさ台フードシステム.pdf", m.LAYOUT_FILE])
    detect("仕込み-13", detector["amount"] >= 500_000 and not in_quotes and "まだ" in detector["quote"], f"控えの金属検出機 {detector['amount']:,}円（50万円以上）。見積の欄は「{detector['quote']}」で、セットのどの見積書・カタログ・配置図にもない")
    car = by_name["配送用の冷蔵車（軽）"]
    vehicles = [x for x in SEIKAI["補助の対象にならない経費"] if x["名前"] == "自動車などの車両・船舶・航空機"]
    detect("仕込み-14", bool(vehicles) and car["amount"] > 0, f"控えの {car['name']} {car['amount']:,}円。正解の対象外「{vehicles[0]['名前'] if vehicles else '?'}」に当たる")
    listed = set(same) | {"自動計量機", "画像検査装置（盛り付けとラベル）", "金属検出機", "配送用の冷蔵車（軽）"}
    report(set(by_name) == listed, f"控えの {len(rows)} 行は、上で見た行だけ")


def check_employees() -> None:
    print("\n■ 従業員数（書類どうしで同じか）")
    rows = worker_rows(SET_DIR / "労働者名簿.xlsx")
    gaikyo = set_text(GAIKYO)
    emp = int(re.search(r"従業員\s+(\d+)人", gaikyo)[1])
    officers_g = int(re.search(r"常勤役員\s+(\d+)人", gaikyo)[1])
    detect("仕込み-17", len(rows) == 14 and emp == 15, f"労働者名簿 {len(rows)}人 ≠ 法人事業概況説明書の従業員 {emp}人（落ちているのは {m.OMITTED_WORKER}）")
    officers = Document(str(SET_DIR / "役員名簿.docx")).tables[0].rows[1:]
    report(officers_g == len(officers) == 2, f"法人事業概況説明書の常勤役員 {officers_g}人 ＝ 役員名簿 {len(officers)}人（一覧にない食い違いはない）")


# ---------------------------------------------------------------------------
# 8. 一覧の形
# ---------------------------------------------------------------------------


def check_list() -> None:
    print("\n■ 仕込んだ不備の一覧の形")
    data = json.loads(m.LIST_FILE.read_text(encoding="utf-8"))
    defects = data["不備"]
    types = {t["id"]: t for t in KNOWLEDGE["型"]}
    ids = [d["id"] for d in defects]
    report(ids == [f"仕込み-{i:02d}" for i in range(1, len(ids) + 1)], f"id は 仕込み-01〜{len(ids):02d} の通し番号")
    kinds = {d["種類"] for d in defects}
    report(len(kinds) >= 15, f"不備の種類は {len(kinds)}（15以上）。不備は {len(defects)}件")
    report(len(kinds) - 1 >= 15, f"期数不足の2つ（決算書・納税証明書）を1種類とまとめても {len(kinds) - 1} 種類（15以上）")
    for d in defects:
        t = types.get(d["型"])
        ok = (
            t is not None
            and d["型の名前"] == t["名前"]
            and d["重さ"] == t["重さ"]
            and d["見つけ方"] == t["見つけ方"]
            and d["重さ"] in ("重大", "要確認", "助言")
            and bool(d["直し方"])
            and bool(d["種類"])
            and (d["SPEC の重大"] is None or d["SPEC の重大"] in SPEC_CRITICAL)
            and all((SET_DIR / n).is_file() for n in d["書類"])
            and all(not (SET_DIR / n).exists() for n in d.get("抜いた書類", []))
            and (d["書類"] or d.get("抜いた書類"))
            and len(d["採点の手がかり（案）"]) >= 2
        )
        report(ok, f"{d['id']}：型 {d['型']}（{t['名前'] if t else '?'}）、重さ {d['重さ']}（型と同じ）、直し方あり、書類 {d['書類'] or d.get('抜いた書類')}")
    for c in SPEC_CRITICAL:
        hit = [d["id"] for d in defects if d["SPEC の重大"] == c]
        report(bool(hit) and all(d["重さ"] == "重大" for d in defects if d["SPEC の重大"] == c), f"SPEC の重大「{c}」：{'、'.join(hit)}（どれも重さは重大）")
    report(sorted(found) == sorted(ids) and all(found.values()), f"一覧の {len(ids)} 件の不備が、どれもセットの書類から機械的に見つかった（見つからない：{sorted(set(ids) - {k for k, v in found.items() if v}) or 'なし'}）")
    count = data["数"]
    report(count["不備"] == len(defects) and count["種類"] == len(kinds), f"一覧の「数」が中身と合う（{count['不備']}件、{count['種類']}種類、型 {count['型']}）")
    report(cc.APPLY_FROM == APPLY_FROM and cc.APPLY_UNTIL == APPLY_UNTIL, f"申請の日の範囲は正しいセットと同じ（{APPLY_FROM}〜{APPLY_UNTIL}）")


def check_correct_set() -> None:
    print("\n■ 正しいセットの確かめ（D5a）")
    result = subprocess.run([sys.executable, str(HERE / "check_correct_set.py")], capture_output=True, text=True)
    ok_count = len(re.findall(r"^\s*○ ", result.stdout, re.M))
    ng_count = len(re.findall(r"^\s*× ", result.stdout, re.M))
    report(result.returncode == 0, f"check_correct_set.py：終了コード {result.returncode}（○{ok_count}件、×{ng_count}件）")
    if result.returncode != 0:
        print(result.stdout[-2000:], result.stderr[-2000:])


def print_list() -> None:
    print("\n■ 仕込んだ不備の一覧（種類・書類・重さ）")
    data = json.loads(m.LIST_FILE.read_text(encoding="utf-8"))
    for d in data["不備"]:
        docs = "・".join(d["書類"]) or f"（{'・'.join(d['抜いた書類'])} を抜いた）"
        spec = f"SPEC の重大：{d['SPEC の重大']}" if d["SPEC の重大"] else "SPEC の5つの外"
        print(f"  {d['id']}｜{d['種類']}｜{docs}｜{d['形式']}｜{d['重さ']}｜{d['型']} {d['型の名前']}｜{spec}")
    c = data["数"]
    print(f"  計：不備 {c['不備']}件、種類 {c['種類']}、型 {c['型']}、重さ 重大 {c['重さ']['重大']}・要確認 {c['重さ']['要確認']}・助言 {c['重さ']['助言']}")


def main() -> None:
    global SRC
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        SRC = tmp_path / "src"
        check_files()
        check_rebuild(tmp_path)  # SRC に写真とスキャンの元の PDF もできる
        check_formats()
        check_sources(tmp_path)
        check_diffs()
        check_dates()
        check_periods()
        check_names()
        check_quotes()
        check_order()
        check_expenses()
        check_employees()
        check_list()
        check_correct_set()
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
