# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の会社の資料を、回答表と照らす。

できたファイル（PDF・Word）から取り出した文字を、回答表.md の文と照らす。議事録に出る人は、
../書類/労働者名簿.xlsx の役目と同じ名前かを確かめる。議事録にしか出てこない事実が、回答表にないことも確かめる。
どのページにも「架空のテスト用データ」があることも確かめる。合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社_町工場/会社の資料/check_materials.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ANSWER_SHEET = HERE.parent / "回答表.md"
WORKERS = HERE.parent / "書類" / "労働者名簿.xlsx"
MARK = "架空のテスト用データ"

PROFILE = "会社案内.pdf"
MINUTES = "議事録_2026-09-30_見積の困りごと.docx"
DRAWING = "図面の例_ブラケット.pdf"

failures: list[str] = []


def report(ok: bool, text: str) -> None:
    print(f"  {'○' if ok else '×'} {text}")
    if not ok:
        failures.append(text)


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


def flat(text: str) -> str:
    return re.sub(r"[ 　\n]", "", text)


def pdf_pages(name: str) -> list[str]:
    return [p.extract_text(extraction_mode="layout") for p in PdfReader(str(HERE / name)).pages]


def check_marks(name: str, pages: list[str]) -> None:
    missing = [i for i, text in enumerate(pages, start=1) if flat(text).count(MARK) < 2]
    report(not missing, f"{name}：PDF {len(pages)}ページ。すべての頭と足に「{MARK}」（足りないページ：{missing or 'なし'}）")


def roles() -> dict[str, str]:
    """労働者名簿から、役目ごとの名前（空白を除く）を取る。"""
    ws = load_workbook(WORKERS)["労働者名簿"]
    header = [c.value for c in ws[5]]
    name_col, job_col = header.index("氏名"), header.index("従事する業務の種類")
    got = {}
    for row in ws.iter_rows(min_row=6, values_only=True):
        if row[0] is not None:
            got.setdefault(row[job_col], flat(row[name_col]))
    return got


def check_profile() -> None:
    print(f"\n■ {PROFILE}")
    pages = pdf_pages(PROFILE)
    check_marks(PROFILE, pages)
    report(len(pages) == 2, f"2ページ：{len(pages)}ページ")
    f = flat("\n".join(pages))
    president = find("A-08", r"代表取締役\s*(\S+\s?\S+)（")[1].replace(" ", "")
    report(ANSWERS["A-01"] in f and f"（{ANSWERS['A-02']}）" in f, "A-01 社名、A-02 読み")
    report(f"代表取締役{president}" in f, f"A-08 代表者 {president}")
    y, m, d = find("A-04", r"(\d{4})年(\d+)月(\d+)日").groups()
    report(f"{y}年{m}月{d}日" in f, f"A-04 設立 {y}年{m}月{d}日")
    for year in re.findall(r"(\d{4})年", ANSWERS["A-05"]):
        report(f"{year}年" in f, f"A-05 沿革に {year}年")
    report("先代（今の社長の父）が、個人で旋盤の加工を始める" in f, "A-05 先代が個人で旋盤の加工を始めた")
    capital = int(find("A-06", r"^([\d,]+)千円")[1].replace(",", ""))
    report(f"{capital // 10:,}万円" in f, f"A-06 資本金 {capital // 10:,}万円")
    c01 = find("C-01", r"^(\d+)人。正社員(\d+)人とパート(\d+)人").groups()
    report(f"{c01[0]}人（正社員{c01[1]}人、パート{c01[2]}人）" in f, f"C-01 従業員 {c01[0]}人（正社員{c01[1]}人、パート{c01[2]}人）")
    address = ANSWERS["B-01"].split("。")[0]
    report(f"〒{ANSWERS['B-02']}" in f and address in f, "B-01・B-02 所在地と郵便番号")
    area = find("G-01", r"約(\d+)㎡")[1]
    report(f"約{area}㎡" in f, f"G-01 延べ床面積 約{area}㎡")
    report("https://www.example.com/" in f and "info@example.com" in f, "A-13 サイトとメール")
    report(ANSWERS["A-15"].split("（")[0] in f, "A-15 電話（架空の番号）")
    for product in ("半導体の製造装置", "産業用ロボット・工作機械", "医療機器"):
        report(product in ANSWERS["A-12"] and product in f, f"A-12 製品：{product}")
    lot = find("A-12", r"（(1個から\d+個くらい)）")[1]
    report(lot in f, f"A-12 試作と小ロット（{lot}）")
    for words in ("アルミ・ステンレス・チタン", "1000分の1ミリ", "三次元測定機で測った検査の成績書"):
        report(words in ANSWERS["E-03"] and words in f, f"E-03 強み：{words}")
    text = "\n".join(pages)
    g02 = find("G-02", r"マシニングセンタ(\d+)台（うち5軸が(\d+)台）、NC旋盤(\d+)台、複合加工機(\d+)台、三次元測定機(\d+)台。CAM のソフトが(\d+)本").groups()
    got = (
        re.search(r"マシニングセンタ（うち5軸\s*(\d+)台）\s+(\d+)台", text),
        re.search(r"NC旋盤\s+(\d+)台", text),
        re.search(r"複合加工機\s+(\d+)台", text),
        re.search(r"三次元測定機\s+(\d+)台", text),
        re.search(r"CAM のソフト\s+(\d+)本", text),
    )
    values = None
    if all(got):
        values = (got[0][2], got[0][1], got[1][1], got[2][1], got[3][1], got[4][1])
    report(values == g02, f"G-02 設備の台数：回答表 {g02} ／ 会社案内 {values}")
    partners = find("E-01", r"約(\d+)社")[1]
    report(f"約{partners}社" in f, f"E-01 取引のある会社 約{partners}社")
    report("ISO" not in f, "E-08 ISO 9001 は取っていないので書いていない")


def check_minutes() -> None:
    print(f"\n■ {MINUTES}")
    doc = Document(str(HERE / MINUTES))
    head = "\n".join(p.text for s in doc.sections for p in s.header.paragraphs)
    foot = "\n".join(p.text for s in doc.sections for p in s.footer.paragraphs)
    report(MARK in head and MARK in foot, f"{MINUTES}：頭と足に「{MARK}」（どのページにも出る）")
    tables = ["\n".join(c.text for row in t.rows for c in row.cells) for t in doc.tables]
    body = "\n".join(p.text for p in doc.paragraphs)
    f = flat(body + "\n" + "\n".join(tables))
    report("2026年9月30日" in f, "日付 2026年9月30日")
    names = roles()
    president = find("A-08", r"代表取締役\s*(\S+\s?\S+)（")[1].replace(" ", "")
    for role, label in (("工場長", "工場長"), ("事務", "事務"), ("営業", "営業")):
        report(f"{label}（{names[role]}）" in f, f"出た人の{label}「{names[role]}」＝ 労働者名簿の{role}")
    report(f"社長（{president}）" in f, f"出た人の社長「{president}」＝ A-08")
    # L-01：見積1件の時間の内訳
    l01 = find("L-01", r"約(\d+)分。図面を読んで形・寸法・精度・材料を拾うのに約(\d+)分、工程と段取りを考えるのに約(\d+)分、"
               r"材料と外注（めっき・熱処理）の値段を調べるのに約(\d+)分、加工の時間を見積もるのに約(\d+)分、見積書を作って送るのに約(\d+)分").groups()
    report(f"平均約{l01[0]}分" in f, f"L-01 1件 平均約{l01[0]}分")
    report(int(l01[0]) == sum(int(x) for x in l01[1:]), f"L-01 内訳の和 {'＋'.join(l01[1:])} ＝ {l01[0]}分")
    for minutes_, words in zip(l01[1:], ("材料を拾うのに", "段取りを考えるのに", "値段を調べるのに", "見積もるのに", "作って送るのに")):
        report(f"{words}約{minutes_}分" in f, f"L-01 {words}約{minutes_}分")
    report("9月に2週間" in f, "L-01 2026年9月に2週間記録した")
    g04 = find("G-04", r"約(\d+)件の見積を、社長（約(\d+)件）と工場長（約(\d+)件）.*月に約(\d+)時間").groups()
    report(f"月に約{g04[0]}件（社長が約{g04[1]}件、工場長が約{g04[2]}件）" in f and f"月に約{g04[3]}時間" in f, f"G-04 月 約{g04[0]}件・約{g04[3]}時間")
    for words, what in (
        ("工程の組み直し（急ぎの割り込みのたびに）を工場長が約1.5時間", "L-02 工程の組み直し 1日約1.5時間"),
        ("納期の問い合わせ（1日に約12件）への返事を社長と事務で約1.5時間", "L-02 問い合わせ 1日約1.5時間"),
        ("事務が約1時間", "L-02 日報と原価の集計 1日約1時間"),
    ):
        report(words in f, what)
    g06 = find("G-06", r"平均で(\d+)日（営業日）.*客は(\d+)日以内.*月に約(\d+)件").groups()
    report(f"平均で{g06[0]}日（営業日）" in f and f"{g06[1]}日以内" in f, f"G-06 返事は平均{g06[0]}日、客は{g06[1]}日以内を望む")
    l06 = find("L-06", r"月に約(\d+)件あった。急ぎの見積は、月に(\d+)件ほど断った").groups()
    report(f"月に約{l06[0]}件" in f and f"月に{l06[1]}件ほど断った" in f, f"L-06 失注 月約{l06[0]}件、急ぎ 月{l06[1]}件断った")
    report("市販の生産管理のソフトを2つ試した" in f and "Excelに戻った" in f, "L-18 市販のソフトが合わなかった")
    report("値段を決めること、検査の合否、客へ送ること" in f, "L-04 AI に任せないこと")
    report("社長か工場長が確かめてから使う" in f, "L-04 AI の案は社長か工場長が確かめる")
    report("客の図面は外に出してはいけないもの" in f and "学習に使わない契約の、国内のクラウドだけ" in f, "K-05・L-14 客の図面の守り方")
    l19 = find("L-19", r"\d{4}年(\d+)月(\d+)日に、同じ要件の資料（見積依頼書）を(\d)社").groups()
    report(f"{l19[0]}月{l19[1]}日に{l19[2]}社に渡して" in f, f"L-19 {l19[0]}月{l19[1]}日に{l19[2]}社に見積を頼む")
    # 議事録にしか出てこない事実
    report("手帳" in f and "約200項目" in f, "議事録にしかない事実：工場長が見積の決まりを手帳に約200項目書きためている")
    report("手帳" not in ANSWER_SHEET.read_text(encoding="utf-8"), "その事実（手帳）は回答表にない")


def check_drawing() -> None:
    print(f"\n■ {DRAWING}")
    pages = pdf_pages(DRAWING)
    check_marks(DRAWING, pages)
    report(len(pages) == 1, f"1ページ：{len(pages)}ページ")
    f = flat("\n".join(pages))
    for words, what in (
        ("ブラケット", "品名"),
        ("A5052", "材料 A5052"),
        ("白アルマイト処理", "表面処理"),
        ("20個", "数量"),
        ("φ10H7", "はめあいの公差（φ10H7）"),
        ("80±0.05", "寸法の公差（80±0.05）"),
        ("50±0.02", "穴のピッチの公差（50±0.02）"),
        ("普通公差", "普通公差"),
        ("正面図", "正面図"),
        ("平面図", "平面図"),
        ("右側面図", "右側面図"),
    ):
        report(words in f, f"図面に{what}がある")
    report("架空の客先（テスト用）" in f, "客先は架空（実在の会社名を書いていない）")


def main() -> None:
    check_profile()
    check_minutes()
    check_drawing()
    print()
    if failures:
        print(f"合わないもの：{len(failures)}件")
        for f in failures:
            print(f"  × {f}")
        sys.exit(1)
    print("すべて合いました。")


if __name__ == "__main__":
    main()
