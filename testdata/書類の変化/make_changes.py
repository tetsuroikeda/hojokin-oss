# /// script
# requires-python = ">=3.10"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pillow==13.0.0"]
# ///
"""書類の変化と整理の材料（TASKS D6）を作る。

作るもの（どれもこのフォルダの中）：
1. 開いたときの確認/前/・後/（T5-3）：会社のフォルダの中の書類の、閉じる前と開く前の形。
   後は、前から「1つ足し・1つ書き換え・1つ動かし・1つ名前を変え」た形。
2. 散らばった書類/（T5-4）：会社のフォルダのあちこちに入れた11件。
   種類が分かる8件、何の書類か分からない2件、8件のうちの1件と同じ中身の1件。
3. 取り直した納税証明書/（T5-6）：D2a の納税証明書（その2）を、発行日だけ新しくして取り直したもの。
4. 従業員数の食い違い/（T13-8）：会社の記録（15人）と違う従業員数を書いた会社概要。
5. 正解.json：上の答え（どれを足した・書き換えたか、11件の種類と行き先など）。会社のフォルダには写さない。

書類は D2a・D2b（testdata/デモの会社/書類/）、D5a（testdata/書類セット/正しいセット/）、
D8（testdata/会社の資料/材料/）のものを使う。元のファイルは読むだけで、変えない。
書き換えた労働者名簿と取り直した納税証明書は、D2a・D2b の作り方の関数を、日付などの値だけ差し替えて呼んで作る。
（make_documents.py・make_documents_part2.py は直さない。）

同じ元の書類と同じ版のライブラリからなら、何度作っても同じバイト列になる。
ただし、分からない書類の写真は手元の日本語の書体で描くので、別の機械で作るとバイト列が変わることがある。

動かし方：uv run --script testdata/書類の変化/make_changes.py
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCS = REPO / "testdata" / "デモの会社" / "書類"
CORRECT_SET = REPO / "testdata" / "書類セット" / "正しいセット"
COMPANY_MATERIALS = REPO / "testdata" / "会社の資料" / "材料"

sys.path.insert(0, str(DOCS))
sys.path.insert(0, str(REPO))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Font  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

import make_documents as d2a  # noqa: E402
import make_documents_part2 as d2b  # noqa: E402
from lib.company_init import INBOX_DIR, ORIGINAL_KINDS, ORIGINALS_DIR  # noqa: E402

OPEN_DIR = HERE / "開いたときの確認"
BEFORE_DIR = OPEN_DIR / "前"
AFTER_DIR = OPEN_DIR / "後"
SCATTER_DIR = HERE / "散らばった書類"
REISSUE_DIR = HERE / "取り直した納税証明書"
MISMATCH_DIR = HERE / "従業員数の食い違い"
ANSWER_FILE = HERE / "正解.json"
MATERIAL_DIRS = (OPEN_DIR, SCATTER_DIR, REISSUE_DIR, MISMATCH_DIR)

MARK = "架空のテスト用データ（hojokin-oss）"
KIND_REGISTRY, KIND_TAX, KIND_QUOTE, KIND_NOTICE, KIND_COMPANY, KIND_CATALOG = ORIGINAL_KINDS

# ---------------------------------------------------------------------------
# 1. 開いたときの確認（T5-3）
# ---------------------------------------------------------------------------
# 場所は会社のフォルダの中の相対の場所。今はどれも「原本/」の外に置く。
# これは仮の配置で、作者の決定を待っている（材料の一覧.md 1章の A・B・C）。
# 確認が済めば種類の分かる書類は原本へ動く（SPEC F5）ので、この形は前回の確認の後には残らない。
# 一方、原本の中で書き換えると、履歴から戻して知らせる流れになる（DESIGN 4.7 の2、5章）。

# 閉じる前（仮の配置）。場所 → 元の書類
BEFORE_FILES = {
    f"{INBOX_DIR}/決算書_第18期.pdf": DOCS / "決算書_第18期.pdf",
    f"{INBOX_DIR}/見積書_つばさ台フードシステム.pdf": DOCS / "見積書_つばさ台フードシステム.pdf",
    f"{INBOX_DIR}/労働者名簿.xlsx": DOCS / "労働者名簿.xlsx",
    f"{INBOX_DIR}/役員名簿.docx": DOCS / "役員名簿.docx",
    "社長の書類/カタログ_つばさ台フードシステム.pdf": DOCS / "カタログ_つばさ台フードシステム.pdf",
    "社長の書類/株主名簿.docx": DOCS / "株主名簿.docx",
}
# 4つの操作
ADDED = (f"{INBOX_DIR}/見積書_ほしみ機工.pdf", DOCS / "見積書_ほしみ機工.pdf")
REWRITTEN = f"{INBOX_DIR}/労働者名簿.xlsx"
MOVED = ("社長の書類/カタログ_つばさ台フードシステム.pdf", "社長の書類/機械/カタログ_つばさ台フードシステム.pdf")
RENAMED = (f"{INBOX_DIR}/役員名簿.docx", f"{INBOX_DIR}/役員の名簿_2026.docx")

# 書き換え：社長が労働者名簿を開いて、1人の住所を直し、「現在」の日を新しくして上書きした。
# 人数（15人）・働く時間・雇用の形態は変えない（会社の記録の事実と食い違わないように）。
REWRITE_AS_OF = "2026年11月15日現在"
REWRITE_WORKER = "西村 春江"
REWRITE_ADDRESS = "東京都大田区東糀谷七丁目10番3号"  # 東糀谷に七丁目はない（D2b と同じ考えの架空の番地）


def rewritten_workers() -> list[tuple]:
    rows = []
    found = 0
    for w in d2b.WORKERS:
        if w[0] == REWRITE_WORKER:
            w = w[:4] + (REWRITE_ADDRESS,) + w[5:]
            found += 1
        rows.append(w)
    if found != 1:
        raise SystemExit(f"労働者名簿に {REWRITE_WORKER} が1人だけいるはずが、{found}人でした")
    return rows


def build_worker_list(path: Path, as_of: str, workers: list[tuple]) -> None:
    """D2b の worker_list を、「現在」の日と人の並びだけ差し替えて呼ぶ。"""
    saved = (d2b.AS_OF, d2b.WORKERS)
    d2b.AS_OF, d2b.WORKERS = as_of, workers
    try:
        d2b.worker_list(path)
    finally:
        d2b.AS_OF, d2b.WORKERS = saved


def build_open_check(root: Path) -> None:
    before, after = root / "前", root / "後"
    for place, src in BEFORE_FILES.items():
        copy(src, before / place)
    # 後：前を写してから、4つの操作をする
    for place, src in BEFORE_FILES.items():
        if place in (MOVED[0], RENAMED[0]):
            continue
        copy(src, after / place)
    copy(ADDED[1], after / ADDED[0])
    build_worker_list(after / REWRITTEN, REWRITE_AS_OF, rewritten_workers())
    copy(BEFORE_FILES[MOVED[0]], after / MOVED[1])
    copy(BEFORE_FILES[RENAMED[0]], after / RENAMED[1])


# ---------------------------------------------------------------------------
# 2. 散らばった書類 11件（T5-4）
# ---------------------------------------------------------------------------
# 名前はばらばらにし、どれも決まった形（「2026-10-20_見積書_〇〇機械.pdf」）ではない。
# 置き場所は、会社のフォルダの根、入れ口とその下、社長が作ったフォルダ。原本・記録・案件・目印の中には置かない。

UNKNOWN_PHOTO = f"{INBOX_DIR}/IMG_2091.jpg"
UNKNOWN_TABLE = "社長/Book1.xlsx"

# (場所, 元の書類, 区分, 種類, 書類にある日付, 相手先, 原本の区分)
IDENTIFIABLE = [
    (f"{INBOX_DIR}/scan0001.pdf", CORRECT_SET / "履歴事項全部証明書.pdf", "スキャンした PDF",
     "履歴事項全部証明書", {"発行日": "2026-10-22"}, "架空の登記所（発行した所）", KIND_REGISTRY),
    (f"{INBOX_DIR}/IMG_2087.jpg", CORRECT_SET / "納税証明書_その2.jpg", "写真",
     "納税証明書（その2）", {"発行日": "2026-10-23"}, "架空の税務署（発行した所）", KIND_TAX),
    ("決算書18.pdf", DOCS / "決算書_第18期.pdf", "PDF",
     "決算書（第18期）", {"事業年度の始め": "2025-04-01", "決算日": "2026-03-31"}, None, KIND_TAX),
    ("社長/見積もり（つばさ台）.pdf", DOCS / "見積書_つばさ台フードシステム.pdf", "PDF",
     "見積書", {"発行日": "2026-10-20", "有効期限": "2027-01-31"}, "つばさ台フードシステム", KIND_QUOTE),
    ("新しいフォルダ/doc04512.pdf", DOCS / "カタログ_つばさ台フードシステム.pdf", "PDF",
     "カタログ", {"版": "2026年版"}, "つばさ台フードシステム", KIND_CATALOG),
    ("事務/名簿.docx", DOCS / "役員名簿.docx", "Word",
     "役員名簿", {"現在の日": "2026-11-01"}, None, KIND_REGISTRY),
    (f"{INBOX_DIR}/10月/Book2.xlsx", DOCS / "労働者名簿.xlsx", "Excel",
     "労働者名簿", {"現在の日": "2026-11-01"}, None, KIND_REGISTRY),
    ("社長/会議のメモ.docx", COMPANY_MATERIALS / "議事録_2026-09-10_工場の会議.docx", "Word",
     "議事録（工場の会議）", {"会議の日": "2026-09-10"}, None, KIND_COMPANY),
]
# (場所, 形式, なぜ分からないか)
UNKNOWN = [
    (UNKNOWN_PHOTO, "写真",
     "手書きのメモを撮った写真。記号と数と「金曜まで」だけで、表題・日付・相手先がない。何の書類か、どの案件で使うかが読み取れない"),
    (UNKNOWN_TABLE, "Excel",
     "見出しのない数の表。表題・項目の名前・日付・相手先がなく、何の数かが読み取れない"),
]
# 同じ中身（バイト列まで同じ）。(場所, 同じ中身の書類の場所)
DUPLICATE = ("メール添付/見積書_つばさ台.pdf", "社長/見積もり（つばさ台）.pdf")

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W5.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit("日本語の書体が見つかりません。FONT_CANDIDATES に書体のファイルを足してください")


# メモに描く文字（空の行は1行あける）
MEMO_LINES = ["A-3　×2", "C-12　×5", "B-7　×1", "", "金曜まで", "→ 確認"]


def memo_photo(path: Path) -> None:
    """机の上の付箋のような紙に、手で書いたようなメモ。表題・日付・相手先はない。"""
    size = (1600, 1200)
    img = Image.new("RGB", size, (120, 98, 76))
    d = ImageDraw.Draw(img)
    # 机の木目（決まった種から）
    rng = random.Random(6061)
    for _ in range(90):
        y = rng.randrange(0, size[1])
        shade = rng.randrange(100, 140)
        d.line([(0, y), (size[0], y + rng.randrange(-30, 30))], fill=(shade, shade - 20, shade - 42), width=rng.randrange(1, 4))
    # 紙（少し傾けて貼る）
    paper = Image.new("RGB", (900, 820), (252, 240, 160))
    p = ImageDraw.Draw(paper)
    y = 90
    for i, text in enumerate(MEMO_LINES):
        if text:
            p.text((90 + (i % 2) * 14, y), text, font=font(76), fill=(40, 46, 110))
        y += 105
    p.text((40, 770), MARK, font=font(22), fill=(120, 110, 70))
    paper = paper.rotate(4.0, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0))
    mask = Image.new("L", (900, 820), 255).rotate(4.0, resample=Image.Resampling.BICUBIC, expand=True)
    shadow = Image.new("L", size, 0)
    x0, y0 = (size[0] - paper.size[0]) // 2, (size[1] - paper.size[1]) // 2
    shadow.paste(mask, (x0 + 16, y0 + 20))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img = Image.composite(Image.new("RGB", size, (40, 30, 22)), img, shadow)
    img.paste(paper, (x0, y0), mask)
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img.save(path, "JPEG", quality=87)


# 見出しのない数の表（行ごとに3つの数）
UNKNOWN_ROWS = [
    (12, 4, 0.8),
    (15, 6, 0.75),
    (9, 3, 0.9),
    (21, 8, 0.7),
    (18, 5, 0.85),
    (11, 4, 0.8),
]


def number_table(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.cell(1, 1, MARK).font = Font(size=9)
    for r, row in enumerate(UNKNOWN_ROWS, start=3):
        for c, value in enumerate(row, start=1):
            ws.cell(r, c, value)
    ws.oddHeader.center.text = MARK
    wb.properties.creator = "hojokin-oss のテスト用データ"
    wb.properties.lastModifiedBy = "hojokin-oss のテスト用データ"
    wb.properties.created = wb.properties.modified = d2b.FIXED_TIME
    wb.save(path)
    d2b.normalize_office(path)


def build_scattered(root: Path) -> None:
    for place, src, *_ in IDENTIFIABLE:
        copy(src, root / place)
    (root / UNKNOWN_PHOTO).parent.mkdir(parents=True, exist_ok=True)
    memo_photo(root / UNKNOWN_PHOTO)
    (root / UNKNOWN_TABLE).parent.mkdir(parents=True, exist_ok=True)
    number_table(root / UNKNOWN_TABLE)
    copy(root / DUPLICATE[1], root / DUPLICATE[0])


# ---------------------------------------------------------------------------
# 3. 取り直した納税証明書（T5-6）
# ---------------------------------------------------------------------------
# 古い原本：D2a の 納税証明書_その2.pdf（発行日 令和8年10月23日。D5a の正しいセットでは、それを撮った写真）。
# 取り直したもの：同じ期（第16期〜第18期）・同じ所得金額で、発行日だけが新しい。

REISSUE_FILE = "納税証明書_その2_11月.pdf"
OLD_TAX_CERTIFICATE = DOCS / "納税証明書_その2.pdf"
OLD_ISSUED = "令和8年10月23日"
NEW_ISSUED = "令和8年11月16日"
TAX_DOC_NAME = "納税証明書（その2）"  # D2a の DOCUMENTS と同じ


def build_tax_certificate(path: Path, issued: str) -> None:
    """D2a の tax_certificate を、発行日だけ差し替えて描く。"""
    saved = d2a.TAX_CERTIFICATE_ISSUED
    d2a.TAX_CERTIFICATE_ISSUED = issued
    try:
        d2a.render(path, TAX_DOC_NAME, d2a.tax_certificate())
    finally:
        d2a.TAX_CERTIFICATE_ISSUED = saved


# ---------------------------------------------------------------------------
# 4. 従業員数の食い違い（T13-8）
# ---------------------------------------------------------------------------
# 会社の記録の従業員数は15人（回答表 C-01。出典は労働者名簿・法人事業概況説明書、どちらも2026年11月1日現在までのもの）。
# 会社概要（取引先に出すために社長が作った Word）には18名と書いてある。役員2人を足しても17人で、説明がつかない。
# 従業員数のほかは、回答表と同じにする（食い違いは従業員数の1つだけ）。

MISMATCH_FILE = "会社概要_2026年11月.docx"
MISMATCH_DATE = "2026年11月10日"
RECORD_EMPLOYEES = 15  # 回答表 C-01
DOC_EMPLOYEES = 18
DOC_EMPLOYEES_TEXT = "18名（正社員8名、パート10名）"
PROFILE_ROWS = [
    ["項目", "内容"],
    ["社名", d2a.COMPANY],  # A-01
    ["代表者", f"代表取締役　{d2a.PRESIDENT}"],  # A-08
    ["所在地", f"〒144-0033　{d2a.ADDRESS}（本店・工場）"],  # B-01、B-02
    ["設立", "2008年4月1日"],  # A-04
    ["資本金", "1,000万円"],  # A-06
    ["事業の内容", "惣菜の製造と販売（スーパー、病院、介護施設向けの煮物、焼き物、和え物、揚げ物など）"],  # A-11、A-12
    ["従業員数", DOC_EMPLOYEES_TEXT],
    ["連絡先", "info@example.com"],  # A-13
]


def build_company_profile(path: Path) -> None:
    saved = d2b.AS_OF
    d2b.AS_OF = MISMATCH_DATE
    try:
        doc = d2b.new_document("会社概要")
        d2b.add_title(doc, "会社概要")
    finally:
        d2b.AS_OF = saved
    doc.add_paragraph("お取引先の皆さまへ。当社の概要をお知らせします。")
    d2b.add_table(doc, PROFILE_ROWS, [40, 130])
    doc.add_paragraph()
    doc.add_paragraph("病院・介護施設ごとのやわらか食や減塩の注文と、スーパーの日替わりの注文にお応えしています。")
    doc.core_properties.title = "会社概要（架空のテスト用データ）"
    doc.save(path)
    d2b.normalize_office(path)


# ---------------------------------------------------------------------------
# 正解
# ---------------------------------------------------------------------------


def name_example(kind: str, dates: dict, party: str | None, suffix: str) -> str:
    """名前の形の例（SPEC F5 の「2026-10-20_見積書_〇〇機械.pdf」）。決まった形は B9 で決める。"""
    date = next(iter(dates.values()))
    if not date[:4].isdigit() or len(date) != 10:
        date = "（日付）"
    parts = [date, kind.split("（")[0]]
    if party and "（" not in party:
        parts.append(party)
    return "_".join(parts) + suffix


def answers() -> dict:
    after_paths = sorted(
        [p for p in BEFORE_FILES if p not in (MOVED[0], RENAMED[0])] + [ADDED[0], MOVED[1], RENAMED[1]]
    )
    return {
        "説明": "TASKS D6 の材料の答え。会社のフォルダには写さない。場所は、会社のフォルダの中の相対の場所。",
        "T5-3 開いたときの確認": {
            "前": "開いたときの確認/前",
            "後": "開いたときの確認/後",
            "前の書類": sorted(BEFORE_FILES),
            "後の書類": after_paths,
            "操作": [
                {"操作": "足し", "後": ADDED[0], "中身": "見積書（ほしみ機工）。D2b のものをそのまま"},
                {
                    "操作": "書き換え",
                    "場所": REWRITTEN,
                    "中身": f"労働者名簿。{REWRITE_WORKER} の住所を直し、「{REWRITE_AS_OF}」にした。人数・働く時間は同じ",
                },
                {"操作": "動かし", "前": MOVED[0], "後": MOVED[1], "中身": "同じバイト列"},
                {"操作": "名前を変え", "前": RENAMED[0], "後": RENAMED[1], "中身": "同じバイト列"},
            ],
            "確かめるもの": sorted([ADDED[0], REWRITTEN]),
            "確かめないもの": sorted(
                [p for p in after_paths if p not in (ADDED[0], REWRITTEN)]
            ),
        },
        "T5-4 散らばった書類": {
            "フォルダ": "散らばった書類",
            "件数": {"種類が分かる": len(IDENTIFIABLE), "分からない": len(UNKNOWN), "同じ中身": 1},
            "原本の置き場": ORIGINALS_DIR,
            "種類が分かる": [
                {
                    "元の場所": place,
                    "形式": form,
                    "種類": kind,
                    "日付": dates,
                    "相手先": party,
                    "原本の区分": f"{ORIGINALS_DIR}/{area}",
                    "名前の例": name_example(kind, dates, party, Path(place).suffix),
                    "作った元": str(src.relative_to(REPO)),
                }
                for place, src, form, kind, dates, party, area in IDENTIFIABLE
            ],
            "分からない": [
                {"元の場所": place, "形式": form, "なぜ分からないか": why} for place, form, why in UNKNOWN
            ],
            "同じ中身": {
                "元の場所": DUPLICATE[0],
                "同じ中身の書類": DUPLICATE[1],
                "見分け方": "バイト列まで同じ（中身のハッシュが同じ）",
            },
        },
        "T5-6 取り直した納税証明書": {
            "新しい原本": f"取り直した納税証明書/{REISSUE_FILE}",
            "新しい発行日": NEW_ISSUED,
            "古い原本": str(OLD_TAX_CERTIFICATE.relative_to(REPO)),
            "古い原本の写真": str((CORRECT_SET / "納税証明書_その2.jpg").relative_to(REPO)),
            "古い発行日": OLD_ISSUED,
            "変わったこと": "発行日だけ。期（第16期〜第18期）と所得金額は同じ",
            "テストの今日": "2026-11-16 以後にする（取り直した日より前には、この書類はない）",
        },
        "T13-8 従業員数の食い違い": {
            "書類": f"従業員数の食い違い/{MISMATCH_FILE}",
            "書類の日付": MISMATCH_DATE,
            "書類の値": DOC_EMPLOYEES_TEXT,
            "書類の人数": DOC_EMPLOYEES,
            "記録の値": f"{RECORD_EMPLOYEES}人（正社員7人、パート8人）",
            "記録の出典": [
                "回答表 C-01",
                "testdata/デモの会社/書類/労働者名簿.xlsx（2026年11月1日現在、15人）",
                "testdata/デモの会社/書類/法人事業概況説明書_第18期.pdf（従業員15人）",
            ],
            "食い違うのは": "従業員数だけ。社名・代表者・所在地・設立・資本金・事業の内容は回答表と同じ",
        },
    }


# ---------------------------------------------------------------------------


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def build(out: Path) -> None:
    """out に、材料のフォルダ4つと正解.json を作る。中にあったものは消してから作る。"""
    for d in MATERIAL_DIRS:
        target = out / d.name
        if target.exists():
            shutil.rmtree(target)
    build_open_check(out / OPEN_DIR.name)
    build_scattered(out / SCATTER_DIR.name)
    (out / REISSUE_DIR.name).mkdir(parents=True)
    build_tax_certificate(out / REISSUE_DIR.name / REISSUE_FILE, NEW_ISSUED)
    (out / MISMATCH_DIR.name).mkdir(parents=True)
    build_company_profile(out / MISMATCH_DIR.name / MISMATCH_FILE)
    text = json.dumps(answers(), ensure_ascii=False, indent=2) + "\n"
    (out / ANSWER_FILE.name).write_text(text, encoding="utf-8")


def main() -> None:
    sources = list(BEFORE_FILES.values()) + [ADDED[1], OLD_TAX_CERTIFICATE] + [s for _, s, *_ in IDENTIFIABLE]
    missing = [str(p.relative_to(REPO)) for p in sources if not p.is_file()]
    if missing:
        sys.exit(f"元の書類がありません（D2a・D2b・D5a・D8 を先に作る）：{missing}")
    build(HERE)
    for d in MATERIAL_DIRS:
        for path in sorted(p for p in d.rglob("*") if p.is_file()):
            print(f"{path.relative_to(HERE)}  {path.stat().st_size:,} バイト")
    print(ANSWER_FILE.relative_to(HERE))


if __name__ == "__main__":
    main()
