# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf>=4", "pillow==13.0.0", "reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""スキャンの材料（TASKS D7）と、その正解を確かめる。

make_scans.py の計算には頼らず、正解.json と 経費明細の正解.json の数字を、ここで計算し直して照らす。

確かめること：
1. 材料/ に、正解にある書類と経費のメモだけがある。PDF は文字のない画像だけの PDF、写真は JPEG。
2. 正解のどの書類でも、明細ごとの「数量 × 単価 ＝ 金額」、明細の和 ＝ 小計、税率ごとの対象額と消費税、小計 ＋ 消費税 ＝ 合計が合う。
3. D2b の見積書2通の正解が、make_documents_part2.py の明細と、D2b の PDF の文字と合う。回答表（H-02〜H-05、A-01、A-08）とも合う。
4. このスクリプトの外で描いた書類（概算見積・納品書・請求書）の正解が、元の書類/ のきれいな PDF の文字と合う。
5. 日付の順（概算 → 正式の見積、納品 → 請求）、納品書と請求書の明細の一致、登録番号が実在の番号と重ならないこと。
6. 請求書の隠れた所が1か所で、正しい値が明細と合う。
7. 経費明細の正解：見積書の行が 2026年10月20日 のつばさ台の見積の明細と合い、相見積と概算見積を使っていない。
   メモの行に仮の印があり、金額がメモの書き方と合う。補助の対象にならない経費が1つだけで、制度データの正解の項目とページに合う。
8. DESIGN 8.4 の読み取る項目が、どの書類の正解にもそろっている。ファイルの名前に公式資料らしい語がない（T0-4）。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/スキャン/check_scans.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCS_DIR = HERE.parent / "デモの会社" / "書類"
sys.path.insert(0, str(DOCS_DIR))

from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402

import make_documents_part2 as d2b  # noqa: E402

MATERIAL_DIR = HERE / "材料"
ORIGINAL_DIR = HERE / "元の書類"
ANSWER = HERE / "正解.json"
EXPENSE_ANSWER = HERE / "経費明細の正解.json"
ANSWER_SHEET = HERE.parent / "デモの会社" / "回答表.md"
SEIDO = HERE.parent / "正解" / "省力化_第8回.json"
DOWNLOADS = {
    "要領8": REPO / "downloads" / "shoryokuka_ippan" / "application_guidelines_ippan_08.pdf",
    "応募手引8": REPO / "downloads" / "shoryokuka_ippan" / "oubo_manual_ippan_08.pdf",
}
MARK = "架空のテスト用データ"
MATERIAL_DAY = dt.date(2026, 11, 4)  # 材料を作った日（社長がスキャンした日）
OFFICIAL_NAME_WORDS = re.compile(r"公募要領|様式|手引き|交付規程|事務局マニュアル|koubo|yoshiki|tebiki|guideline|manual",
                                 re.IGNORECASE)

ok_count = 0
ng_count = 0


def check(cond: bool, label: str, detail: str = "") -> bool:
    global ok_count, ng_count
    if cond:
        ok_count += 1
        print(f"○ {label}")
    else:
        ng_count += 1
        print(f"× {label}{'：' + detail if detail else ''}")
    return cond


def yen(v: int) -> str:
    return f"{v:,}"


def jdate(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def pdf_text(path: Path) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


# ---------------------------------------------------------------------------


def show_materials(answer: dict, expense: dict) -> None:
    print("## 材料の一覧（材料/）")
    print("| ファイル | 中身 | 形 | 読みにくさ | 使うテスト |")
    print("|---|---|---|---|---|")
    for doc in answer["書類"]:
        what = f"{doc['種類']}（{doc['発行者']}、{doc['番号']}）"
        print(f"| {doc['ファイル']} | {what} | {doc['形']} | {doc['読みにくさ']} | {'、'.join(doc['使うテスト'])} |")
    memo = expense["経費のメモ"]
    print(f"| {memo['ファイル']} | 経費のメモ（社長の手書き、{memo['書いた日']}） | {memo['形']} | 読める | T8-13 |")
    print()


def check_files(answer: dict, expense: dict) -> None:
    print("## 1. 材料のファイル")
    listed = {Path(d["ファイル"]).name for d in answer["書類"]} | {Path(expense["経費のメモ"]["ファイル"]).name}
    present = {p.name for p in MATERIAL_DIR.iterdir() if not p.name.startswith(".")}
    check(listed == present, f"材料/ には、正解にある6つのファイルだけがある（{len(present)}件）",
          f"正解にだけある：{sorted(listed - present)}、材料にだけある：{sorted(present - listed)}")
    for name in sorted(present):
        path = MATERIAL_DIR / name
        if name.endswith(".pdf"):
            reader = PdfReader(str(path))
            text = flat("".join(page.extract_text() or "" for page in reader.pages))
            images = sum(len(page.images) for page in reader.pages)
            check(len(reader.pages) == 1 and text == "" and images == 1,
                  f"{name}：1ページで、文字がなく、画像だけの PDF", f"ページ {len(reader.pages)}、文字 {len(text)}字、画像 {images}")
        else:
            with Image.open(path) as img:
                check(img.format == "JPEG" and img.size[0] >= 1000, f"{name}：JPEG の写真（{img.size[0]}×{img.size[1]}）",
                      f"形式 {img.format}")
    originals = sorted(p.name for p in ORIGINAL_DIR.iterdir() if p.suffix == ".pdf")
    check(len(originals) == 3, f"元の書類/ に、描いた書類のきれいな PDF が3つある（{'、'.join(originals)}）")
    bad = [p.name for p in HERE.rglob("*") if OFFICIAL_NAME_WORDS.search(p.name)]
    check(not bad, "ファイルの名前に、公式資料らしい語（様式・手引き など）がない（T0-4）", f"{bad}")
    print()


REQUIRED = ["種類", "番号", "宛名", "発行者", "税込か税抜か", "明細", "小計", "消費税", "合計"]
REQUIRED_BY_KIND = {"見積書": ["発行日", "有効期限"], "納品書": ["納品日", "登録番号"], "請求書": ["請求日", "登録番号", "支払期限"]}


def check_arithmetic(answer: dict) -> None:
    print("## 2. 正解の金額の計算（数量 × 単価 ＝ 金額、明細の和 ＝ 小計、税率ごとの消費税、小計 ＋ 消費税 ＝ 合計）")
    for doc in answer["書類"]:
        name = f"{Path(doc['ファイル']).name}（{doc['種類']} {doc['番号']}）"
        need = REQUIRED + REQUIRED_BY_KIND[doc["種類"]]
        missing = [k for k in need if doc.get(k) in (None, "", [])]
        check(not missing, f"{name}：DESIGN 8.4 の読み取る項目がそろっている", f"ない項目：{missing}")
        rows = doc["明細"]
        bad_rows = [r["品名"] for r in rows if r["数量"] * r["単価"] != r["金額"]]
        check(not bad_rows, f"{name}：明細{len(rows)}行のどれも 数量 × 単価 ＝ 金額", f"{bad_rows}")
        for r in rows:
            for key in ("品名", "数量", "単位", "単価", "金額", "税率"):
                if r.get(key) in (None, ""):
                    check(False, f"{name}：明細の {key} がある", r["品名"])
        rates = {r["税率"] for r in rows}
        check(rates <= {8, 10}, f"{name}：税率は 8% か 10%（{'・'.join(f'{x}%' for x in sorted(rates))}）")
        total = sum(r["金額"] for r in rows)
        check(total == doc["小計"], f"{name}：明細の和 {yen(total)} ＝ 小計 {yen(doc['小計'])}")
        tax_sum = 0
        for rate in sorted(rates, reverse=True):
            base = sum(r["金額"] for r in rows if r["税率"] == rate)
            entry = next((t for t in doc["税率ごと"] if t["税率"] == rate), None)
            tax = base * rate // 100  # 1円未満は切り捨て
            if doc["端数の処理"] is None:
                check(base * rate % 100 == 0, f"{name}：{rate}% の消費税に端数がない（端数の処理を書いていない書類）")
            ok = entry is not None and entry["対象額"] == base and entry["消費税"] == tax
            check(ok, f"{name}：{rate}%対象 {yen(base)} の消費税 {yen(tax)}（切り捨て）が正解と合う", f"{entry}")
            tax_sum += tax
        check(len(doc["税率ごと"]) == len(rates), f"{name}：税率ごとの欄が、明細にある税率の数だけある")
        check(tax_sum == doc["消費税"], f"{name}：税率ごとの消費税の和 {yen(tax_sum)} ＝ 消費税 {yen(doc['消費税'])}")
        check(doc["小計"] + doc["消費税"] == doc["合計"],
              f"{name}：小計 {yen(doc['小計'])} ＋ 消費税 {yen(doc['消費税'])} ＝ 合計 {yen(doc['合計'])}")
    print()


def check_d2b(answer: dict) -> None:
    print("## 3. D2b の見積書2通と、回答表")
    sheet = ANSWER_SHEET.read_text(encoding="utf-8")
    by_number = {d["番号"]: d for d in answer["書類"]}
    for key, file in (("つばさ台フードシステム", "見積書_つばさ台フードシステム.pdf"), ("ほしみ機工", "見積書_ほしみ機工.pdf")):
        q = d2b.QUOTES[key]
        doc = by_number.get(q["number"])
        if not check(doc is not None, f"{key}：正解に見積番号 {q['number']} の書類がある"):
            continue
        want = [(n, m, qty, u, p, qty * p) for n, m, qty, u, p, _ in q["items"]]
        got = [(r["品名"], r["型番"], r["数量"], r["単位"], r["単価"], r["金額"]) for r in doc["明細"]]
        check(want == got, f"{key}：正解の明細7行が make_documents_part2.py の明細と同じ")
        check(doc["発行者"] == q["issuer"] and jdate(doc["発行日"]) == d2b.QUOTE_DATE
              and jdate(doc["有効期限"]) == d2b.QUOTE_VALID_UNTIL and doc["件名"] == d2b.SUBJECT,
              f"{key}：発行者・発行日・有効期限・件名が D2b と同じ")
        text = flat(pdf_text(DOCS_DIR / file))
        missing = [v for v in [yen(r["金額"]) for r in doc["明細"]] + [yen(r["単価"]) for r in doc["明細"]]
                   + [yen(doc["小計"]), yen(doc["消費税"]), yen(doc["合計"]), q["number"]] if v not in text]
        check(not missing, f"{key}：正解の単価・金額・小計・消費税・合計・見積番号が、D2b の PDF の文字にある", f"{missing}")
    tsubasa = by_number[d2b.QUOTES["つばさ台フードシステム"]["number"]]
    hoshimi = by_number[d2b.QUOTES["ほしみ機工"]["number"]]
    check(f"合計{tsubasa['小計'] // 1000:,}千円（税抜）" in sheet, f"回答表 H-02：つばさ台の小計 {yen(tsubasa['小計'])}円 ＝ 合計22,500千円")
    check(f"株式会社ほしみ機工（{hoshimi['小計'] // 1000:,}千円" in sheet, f"回答表 H-03：ほしみ機工の小計 {yen(hoshimi['小計'])}円 ＝ 24,100千円")
    check(f"どちらも{jdate(tsubasa['発行日'])}付け。有効期限は{jdate(tsubasa['有効期限'])}" in sheet, "回答表 H-04：2通の発行日と有効期限")
    check("安いほうの株式会社つばさ台フードシステム" in sheet and tsubasa["小計"] < hoshimi["小計"], "回答表 H-05：頼むのは安いほうのつばさ台")
    names = {d["宛名"] for d in answer["書類"]}
    check(names == {"株式会社やまぶき惣菜"} and "| A-01 | 社名 | 株式会社やまぶき惣菜 |" in sheet, "どの書類の宛名も回答表 A-01 の社名")
    people = {d["宛名の人"] for d in answer["書類"] if d["宛名の人"]}
    check(people == {"代表取締役 沢村 宏之"} and "代表取締役 沢村 宏之" in sheet, "見積書の宛名の人は回答表 A-08 の代表者")
    print()


def check_originals(answer: dict) -> None:
    print("## 4. このスクリプトの外で描いた書類（元の書類/ のきれいな PDF）と正解")
    for doc in answer["書類"]:
        source = doc["元"]
        if not source.startswith("元の書類/"):
            continue
        path = HERE / source.split("（")[0]
        name = path.name
        if not check(path.is_file(), f"{name}：元の書類がある"):
            continue
        text = flat(pdf_text(path))
        values = [doc["番号"], doc["宛名"], doc["発行者"], yen(doc["小計"]), yen(doc["消費税"]), yen(doc["合計"])]
        for key in ("発行日", "有効期限", "納品日", "請求日", "支払期限"):
            if doc.get(key):
                values.append(jdate(doc[key]))
        if doc["登録番号"]:
            values.append(doc["登録番号"])
        for r in doc["明細"]:
            values += [flat(r["品名"]), yen(r["単価"]), yen(r["金額"])]
            if r["型番"]:
                values.append(r["型番"])
        for t in doc["税率ごと"]:
            values += [yen(t["対象額"]), yen(t["消費税"])]
        missing = [v for v in values if flat(v) not in text]
        check(not missing, f"{name}：正解の番号・日付・宛名・発行者・品名・単価・金額・税率ごとの額・合計が、PDF の文字にある（{len(values)}項目）",
              f"{missing}")
        check(MARK in text, f"{name}：「{MARK}」の表示がある")
    print()


def check_relations(answer: dict) -> None:
    print("## 5. 書類どうしのつながり")
    docs = answer["書類"]
    tsubasa = next(d for d in docs if d["番号"] == d2b.QUOTES["つばさ台フードシステム"]["number"])
    rough = next(d for d in docs if d["種類"] == "見積書" and d["発行者"] == tsubasa["発行者"] and d is not tsubasa)
    check(rough["発行日"] < tsubasa["発行日"], f"概算見積（{rough['発行日']}）は、正式の見積（{tsubasa['発行日']}）より前")
    check(rough["有効期限"] < MATERIAL_DAY.isoformat(),
          f"概算見積の有効期限（{rough['有効期限']}）は、材料を作った日（{MATERIAL_DAY}）には切れている")
    same_shape = [(r["品名"], r["型番"], r["数量"]) for r in rough["明細"]] == [(r["品名"], r["型番"], r["数量"]) for r in tsubasa["明細"]]
    check(same_shape and rough["小計"] > tsubasa["小計"], "概算見積は、正式の見積と同じ品名・型番・数量で、小計が高い")
    note = next(d for d in docs if d["種類"] == "納品書")
    invoice = next(d for d in docs if d["種類"] == "請求書")
    check(note["納品日"] <= invoice["請求日"], f"納品（{note['納品日']}）→ 請求（{invoice['請求日']}）の順")
    start, end = invoice["対象期間"]
    check(all(start <= r["納品日"] <= end for r in invoice["明細"]), "請求書の明細の納品日が、どれも対象期間の中")
    lines = [(r["品名"], r["数量"], r["単価"], r["金額"], r["税率"]) for r in note["明細"]]
    billed = [(r["品名"], r["数量"], r["単価"], r["金額"], r["税率"]) for r in invoice["明細"] if r["納品書番号"] == note["番号"]]
    check(lines == billed, f"納品書 {note['番号']} の明細が、請求書の同じ納品書番号の明細と同じ")
    check(note["発行者"] == invoice["発行者"] and note["登録番号"] == invoice["登録番号"], "納品書と請求書の発行者と登録番号が同じ")
    reg = invoice["登録番号"]
    # 法人番号の検査用の数字（先頭）は 9 − (和 mod 9) なので 1〜9 にしかならない。0 なら実在の法人の番号ではない
    check(re.fullmatch(r"T0\d{12}", reg) is not None, f"登録番号 {reg} は先頭の数字が0で、実在の法人の番号と重ならない")
    print()


def check_hidden(answer: dict) -> None:
    print("## 6. 読めない所")
    hidden = [(d, h) for d in answer["書類"] for h in d["隠れた箇所"]]
    check(len(hidden) == 1, f"隠れた所は1か所だけ（{len(hidden)}か所）")
    for doc, h in hidden:
        row = next((r for r in doc["明細"] if r["品名"] == h["明細"]), None)
        ok = row is not None and h["欄"] == "単価" and row["単価"] == h["正しい値"] and row["数量"] * h["正しい値"] == row["金額"]
        check(ok, f"{Path(doc['ファイル']).name}：「{h['明細']}」の{h['欄']}の正しい値 {yen(h['正しい値'])} が明細と合い、数量 × 単価 ＝ 金額")
        check("社長に確かめる" in h["望む振る舞い"] and "埋めて済ませない" in h["望む振る舞い"], "望む振る舞いは、推測で埋めず社長に確かめること")
    print()


def check_expense(answer: dict, expense: dict) -> None:
    print("## 7. 経費明細の正解（T8-13）")
    docs = {d["ファイル"]: d for d in answer["書類"]}
    tsubasa = next(d for d in answer["書類"] if d["番号"] == d2b.QUOTES["つばさ台フードシステム"]["number"])
    rows = expense["行"]
    quote_rows = [r for r in rows if r["根拠の種類"] == "見積書"]
    memo_rows = [r for r in rows if r["根拠の種類"] == "メモ"]
    check(len(quote_rows) + len(memo_rows) == len(rows), "どの行も、根拠の種類が見積書かメモ")
    quotes_used = [f for f in expense["材料"] if f in docs and docs[f]["種類"] == "見積書"]
    check(len(quotes_used) == 3 and expense["経費のメモ"]["ファイル"] in expense["材料"],
          f"材料は、スキャンした見積書3通と経費のメモ1枚（{'、'.join(Path(f).name for f in expense['材料'])}）")
    for r in quote_rows:
        if r["数量"] * r["単価"] != r["金額（税抜）"]:
            check(False, f"見積書の行「{r['品名']}」の 数量 × 単価 ＝ 金額")
    want = [(x["品名"], x["型番"], x["数量"], x["単価"], x["金額"]) for x in tsubasa["明細"]]
    got = [(r["品名"], r["型番"], r["数量"], r["単価"], r["金額（税抜）"]) for r in quote_rows]
    check(want == got, f"見積書の行{len(got)}行が、2026年10月20日のつばさ台の見積（{tsubasa['番号']}）の明細と同じ")
    check(all(Path(tsubasa["ファイル"]).name in r["出典"] for r in quote_rows) and not any(r["仮の印"] for r in quote_rows),
          "見積書の行の出典はどれもその見積で、仮の印がない")
    quote_total = sum(r["金額（税抜）"] for r in quote_rows)
    check(quote_total == tsubasa["小計"] and quote_total != tsubasa["合計"],
          f"見積書の行の和 {yen(quote_total)} ＝ 見積の小計（税抜）。消費税を入れた {yen(tsubasa['合計'])} ではない")
    unused = {u["ファイル"] for u in expense["使わない見積"]}
    others = {f for f in quotes_used if f != tsubasa["ファイル"]}
    check(unused == others, f"使わない見積は、ほしみ機工の相見積とつばさ台の概算見積（{'、'.join(Path(f).name for f in sorted(unused))}）")
    check(not any(Path(f).name in r["出典"] for r in rows for f in unused), "使わない見積から取った行がない")
    sheet = ANSWER_SHEET.read_text(encoding="utf-8")
    groups = {}
    for r in quote_rows:
        groups[r["回答表の区分（H-02）"]] = groups.get(r["回答表の区分（H-02）"], 0) + r["金額（税抜）"]
    h02 = {"盛り付けロボット": "盛り付けロボット2台", "自動計量機": "自動計量機", "トップシール包装機": "トップシール包装機",
           "画像検査装置": "画像検査装置（盛り付けとラベル）", "重量チェッカーとラベラー": "重量チェッカーとラベラー",
           "コンベヤと据え付け・調整": "つなぐコンベヤと据え付け・調整"}
    bad = [g for g, v in groups.items() if f"{h02[g]}{v // 1000:,}千円" not in sheet]
    check(not bad, "見積書の行を H-02 の6つの区分にまとめた額が、回答表 H-02 と合う（まとめた形でも照らせる）", f"{bad}")

    memo = expense["経費のメモ"]
    memo_text = "".join(memo["文面"])
    check("10/20" in memo_text and "ほしみは比べる用" in memo_text, "メモに「つばさ台の 10/20 の見積でいく」「ほしみは比べる用」がある")
    for r in memo_rows:
        entry = next((e for e in memo["経費"] if e["品名"] == r["品名"]), None)
        if not check(entry is not None, f"メモの行「{r['品名']}」が、メモの経費にある"):
            continue
        m = re.match(r"(\d+)万", entry["書き方"])
        amount = int(m[1]) * 10_000 if m else None
        check(entry["書き方"] in memo_text and amount == entry["金額"] == r["金額（税抜）"] and "くらい" in entry["書き方"],
              f"メモの行「{r['品名']}」：メモの「{entry['書き方']}」＝ {yen(r['金額（税抜）'])}円")
        check(r["仮の印"] is True and Path(memo["ファイル"]).name in r["出典"], f"メモの行「{r['品名']}」に仮の印があり、出典がメモ")
    check(len(memo_rows) == len(memo["経費"]), f"メモの経費{len(memo['経費'])}つが、どれも行になっている")

    seido = json.loads(SEIDO.read_text(encoding="utf-8"))
    excluded = {x["名前"]: x for x in seido["補助の対象にならない経費"]}
    eligible = {x["名前"] for x in seido["補助の対象になる経費"]}
    flagged = [r for r in rows if r["要確認"]]
    check(len(flagged) == 1 and flagged[0]["根拠の種類"] == "メモ", "要確認の行は1つだけで、メモから取った行（補助の対象にならない経費を1つ含む）")
    for r in flagged:
        item = r["要確認"]["制度データの項目"].split("／")[1].split("（")[0]
        x = excluded.get(item)
        if not check(x is not None and x["種類"] == "対象外", f"要確認の「{r['品名']}」は、制度データの正解の対象外の項目「{item}」"):
            continue
        pages = [(p["資料"], p["ページ"]) for p in x["内容"]["出典"]]
        flagged_pages = [(p["資料"], p["ページ"]) for p in r["要確認"]["資料のページ"]]
        check(flagged_pages == pages, f"要確認の資料のページ（{flagged_pages}）が、制度データの正解の出典と同じ")
        for doc_id, page in flagged_pages:
            pdf = DOWNLOADS.get(doc_id)
            if pdf is None or not pdf.is_file():
                print(f"－ {doc_id} の {page}ページは、downloads/ に資料がないので確かめなかった")
                continue
            text = flat(PdfReader(str(pdf)).pages[page - 1].extract_text() or "")
            check("試運転" in text, f"{doc_id} の {page}ページ（{pdf.name}）に「試運転」の文がある")
    for r in rows:
        if r["区分（参考）"]:
            check(r["区分（参考）"].split("（")[0] in eligible, f"区分（参考）「{r['区分（参考）']}」は、制度データの補助の対象になる経費の区分",
                  r["品名"])
            break
    total = expense["合計"]
    check(total["見積書から（仮の印なし）"] == quote_total
          and total["メモから（仮の印あり、要確認を除く）"] == sum(r["金額（税抜）"] for r in memo_rows if not r["要確認"])
          and total["要確認（対象にならない見込み）"] == sum(r["金額（税抜）"] for r in flagged),
          f"合計の欄（見積書から {yen(total['見積書から（仮の印なし）'])}、メモから {yen(total['メモから（仮の印あり、要確認を除く）'])}、"
          f"要確認 {yen(total['要確認（対象にならない見込み）'])}）が行と合う")
    print()


def show_answers(answer: dict, expense: dict) -> None:
    print("## 正解の金額（円）")
    print("| 書類 | 明細 | 小計（税抜） | 消費税 | 合計（税込） |")
    print("|---|---|---|---|---|")
    for d in answer["書類"]:
        taxes = "、".join(f"{t['税率']}% {yen(t['消費税'])}" for t in d["税率ごと"])
        print(f"| {d['種類']} {d['番号']}（{d['発行者']}） | {len(d['明細'])}行 | {yen(d['小計'])} | {yen(d['消費税'])}（{taxes}） | {yen(d['合計'])} |")
    print()
    print("## 経費明細の正解（T8-13、1件目の省力化）")
    print("| 品名 | 金額（税抜） | 根拠 | 仮の印 | 要確認 |")
    print("|---|---|---|---|---|")
    for r in expense["行"]:
        flag = "要確認（" + "・".join(f"{p['資料']} p.{p['ページ']}" for p in r["要確認"]["資料のページ"]) + "）" if r["要確認"] else ""
        print(f"| {r['品名']} | {yen(r['金額（税抜）'])} | {r['根拠の種類']} | {'あり' if r['仮の印'] else ''} | {flag} |")
    print()


def main() -> None:
    answer = json.loads(ANSWER.read_text(encoding="utf-8"))
    expense = json.loads(EXPENSE_ANSWER.read_text(encoding="utf-8"))
    show_materials(answer, expense)
    check_files(answer, expense)
    check_arithmetic(answer)
    check_d2b(answer)
    check_originals(answer)
    check_relations(answer)
    check_hidden(answer)
    check_expense(answer, expense)
    show_answers(answer, expense)
    print(f"結果：○{ok_count}件、×{ng_count}件")
    sys.exit(1 if ng_count else 0)


if __name__ == "__main__":
    main()
