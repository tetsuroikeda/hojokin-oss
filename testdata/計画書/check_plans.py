# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1", "pillow>=10", "pypdf>=4"]
# ///
"""計画書の材料（TASKS D9）を確かめ、中身の一覧を出す。

確かめること：
1. `材料/` に決めた19のファイルだけがあり、`正解.json` がある。公式の様式から作る Word は Git の外（作ったもの/）にあり、
   コミットされていない。
2. 正しい計画書：項目の名前が制度データの様式の項目にあり、書き込む位置が M6 の形。根拠対照表のどの行も、記述が本文にあり、
   出典の元（回答表の行・書類の文字・財務モデルの値・計算）に、その数字や語が本当にある。仮の印・空欄・本文の出典の書き込み・
   記号の残り・である調・100字を超える文・文体の基準 B の言い回しがない。
3. 食い違い（T9-2）：7つとも、基の文が正しい計画書に1つだけあり、混ぜた計画書ではそれが混ぜた文になっている。回答表の行には
   正しい語があり、混ぜた語がない。ほかの所は正しい計画書と同じ。根拠対照表の出典は同じまま（コードの確かめは通る形）。
4. 社長の答えが要る指摘（T9-7）：足した事実の語が、回答表・設定・会社の資料・デモの会社の書類・正しい計画書のどこにもない。
   足した記述にも根拠対照表の行と出典がある（コードの確かめは通る形）。
5. 手直し（T13-14）：直す言い回しが正しい計画書に1つだけあり、回答表・会社の資料・文体の基準にない。downloads/ に公式の様式が
   あれば Word を作り直し、ツールが書いた版は書いてよい範囲の外が様式と同じで、項目の文字が本文と同じこと、社長が直した版は
   1-1 現状分析のほかが同じで、範囲の外も同じことを確かめる。作ったもの/ の Word が作り直したものと同じことも見る。
6. 差し戻し（T12-2・T13-5）：5件のファイルがあり、文には申請番号と箇所を指す語がある（曜日も正しい）。提出版に、その誤りが
   本当にある（見積書の有効期限、税込の金額、番地、目標値、名称と型番）。直した後の値が書類・回答表・計画書と合い、取り直した
   見積書の有効期限が出し直す日より後。不備の型が knowledge/不備の型.json にある。日付が testdata/期限 の流れと合う。
7. 計画と実績（T12-4）：財務モデルの指定の基準年度が回答表の決算と合う（営業利益 4,800千円）。計画の1年目を lib/zaimu.py で、
   実績の指標を lib/youken.py（様式の別紙4 と同じ計算）で出し直し、正解の差と要件の判定・返還の条件と合わせる。
8. 公式の様式の文（15字以上の段落）が、材料のどこにも写っていない（downloads/ があるときだけ）。
9. 作り直すと、材料と正解.json が同じバイト列（画面の写真を除く）。

合わないものがあれば、終了コード1で終わる。最後に、材料の一覧と、混ぜた食い違い・社長の答えが要る指摘・差し戻し5件・
計画を下回る実績の中身を出す。

動かし方：uv run --script testdata/計画書/check_plans.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_plans as mk  # noqa: E402

from lib import xml_spans, youken  # noqa: E402
from lib import yoshiki_word as yw  # noqa: E402
from lib.doc_text import word_text  # noqa: E402

REPO = mk.REPO
DOCS = mk.DOCS_DIR
MAT = HERE / mk.MATERIAL
ANSWER = json.loads((HERE / mk.ANSWER_FILE).read_text(encoding="utf-8"))
SEIDO = json.loads(mk.SEIDO_FILE.read_text(encoding="utf-8"))
DUTIES = {d["id"]: d for d in json.loads(mk.DUTY_FILE.read_text(encoding="utf-8"))["項目"]}
DEADLINES = json.loads(mk.DEADLINE_FILE.read_text(encoding="utf-8"))
DEFECT_TYPES = {t["id"] for t in json.loads((REPO / "knowledge" / "不備の型.json").read_text(encoding="utf-8"))["型"]}
STYLE = (REPO / "docs" / "style-criteria.md").read_text(encoding="utf-8")
SHEET_TEXT = mk.ANSWER_SHEET.read_text(encoding="utf-8")
SETTING_TEXT = (REPO / "testdata" / "デモの会社" / "設定.md").read_text(encoding="utf-8")

EXPECTED = sorted(
    [f"{k}/{n}" for k in (mk.PLAN_CORRECT, mk.PLAN_MIXED, mk.PLAN_QUESTION) for n in ("本文.json", "本文.md", "根拠対照表.json")]
    + [f"{mk.SENDBACK}/{e['ファイル']}" for e in mk.SENDBACKS]
    + [f"{mk.SENDBACK}/提出版/交付申請の入力.json",
       f"{mk.SENDBACK}/届いた書類/見積書_つばさ台フードシステム_2027年6月.pdf",
       f"{mk.SENDBACK}/届いた書類/見積書_ほしみ機工_2027年6月.pdf",
       f"{mk.RESULTS}/財務モデルの指定.json", f"{mk.RESULTS}/実績_1年目.json"]
)

results: List[tuple] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))


def flat(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def pdf_text(path: Path) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def doc_texts() -> Dict[str, str]:
    """回答表のほかに、会社のフォルダに入りうる材料の文字（会社の資料、デモの会社の書類）。"""
    out: Dict[str, str] = {}
    for folder in (REPO / "testdata" / "会社の資料" / "材料", DOCS):
        for p in sorted(folder.iterdir()):
            if p.suffix == ".pdf":
                out[p.name] = pdf_text(p)
            elif p.suffix == ".docx":
                out[p.name] = word_text(p)
    return out


DOC_TEXTS = doc_texts()
VARIANTS = mk.plan_variants()
BASE = VARIANTS[mk.PLAN_CORRECT]
BY_NAME = {it["名前"]: it for it in BASE}
MODEL = mk.model_values()
_N = mk.model_numbers()
CALC = {  # 計算の行：記述 → 出し直した値と合うか
    "約24時間": 38 - 14 == 24,
    "約7,200時間": 24 * 300 == 7200,
    "約1,000パック": 4500 - 3500 == 1000,
    "15,000千円": min(22_500 * 2 // 3, 15_000) == 15_000,
    # 組11 で足した行（回答表 C-16 の名簿の約29時間から少なめに見た効果、補助上限、財務モデルからの差と割合、表の年）
    "約15時間": 29 - 14 == 15,
    "約4,500時間": 15 * 300 == 4500,
    "1,500万円": "1,500万円" in SETTING_TEXT and "6〜20人" in SETTING_TEXT,  # 設定.md の制度の行（第8回の要領で確かめた）
    mk.thousand_round(_N["付加価値額_5年目"] - _N["付加価値額_基準年度"]): True,
    mk.thousand_round(_N["給与支給総額_5年目"] - _N["給与支給総額_基準年度"]): True,
    "2年目": 2 <= 5,
    "4年目": 4 <= 5,
    "3倍以上": _N["営業利益_5年目"] >= 3 * _N["営業利益_基準年度"],
}


def answer_of(row_id: str) -> str:
    return flat(mk.ANSWERS[row_id][1])


# ---------------------------------------------------------------------------
# 1. ファイル
# ---------------------------------------------------------------------------


def check_files() -> None:
    found = sorted(p.relative_to(MAT).as_posix() for p in MAT.rglob("*") if p.is_file())
    check(found == EXPECTED, f"材料/ にあるのは決めた{len(EXPECTED)}のファイルだけ（違い：{sorted(set(found) ^ set(EXPECTED))}）")
    check((HERE / mk.ANSWER_FILE).exists(), "正解.json がある（材料/ の外）")
    check("作ったもの/" in (HERE / ".gitignore").read_text(encoding="utf-8"), ".gitignore が 作ったもの/ を Git の外にしている")
    tracked = subprocess.run(["git", "ls-files", "--", str(HERE)], capture_output=True, text=True, cwd=REPO).stdout.splitlines()
    bad = [t for t in tracked if t.endswith((".docx", ".xlsx")) or "/作ったもの/" in t]
    check(not bad, f"公式の様式から作った Word・Excel はコミットされていない（{bad}）")
    for rel in EXPECTED:
        p = MAT / rel
        if p.suffix in (".json", ".md", ".txt"):
            text = p.read_text(encoding="utf-8")
            if rel.endswith("根拠対照表.json"):
                continue  # kakunin.py konkyo に渡す形（「行」だけ）。印は 本文.json と 本文.md にある
            check(mk.MARK in text, f"{rel} に「{mk.MARK}」がある")
        elif p.suffix == ".pdf":
            check(mk.MARK in pdf_text(p), f"{rel} に「{mk.MARK}」がある")


# ---------------------------------------------------------------------------
# 2. 正しい計画書
# ---------------------------------------------------------------------------

B_SKIP = ("〇〇", "「", "（", "毎回")


def style_b_patterns() -> List[str]:
    """文体の基準 B の「避ける表現」を、文の中で探す正規表現にする（「〜」は間の何文字か）。"""
    m = re.search(r"^## B\..*?(?=^## |\Z)", STYLE, flags=re.M | re.S)
    out = []
    for line in m.group(0).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("区分", "---") or set(cells[0]) <= {"-"}:
            continue
        for part in re.split(r"[、，]", cells[1]):
            part = re.sub(r"（.*?）", "", part).strip()
            chunks = [c for c in part.split("〜") if c]
            if not chunks or any(s in part for s in B_SKIP) or max(len(c) for c in chunks) <= 2:
                continue
            out.append("[^。\n]*?".join(re.escape(c) for c in chunks))
    return out


def check_rows(items, label: str, allow_owner: bool = False, expect_mismatch: frozenset = frozenset()) -> None:
    """expect_mismatch の記述は、出典の元にその語が「ない」ことを確かめる（混ぜた食い違い）。"""
    seen, dup = set(), []
    for it in items:
        text = flat(mk.item_text(it))
        for r in it["根拠"]:
            key = (r["記述"], it["名前"])
            if key in seen:
                dup.append(key)
            seen.add(key)
            if flat(r["記述"]) not in text:
                check(False, f"{label}：記述「{r['記述']}」が「{it['名前']}」の本文にある")
                continue
            kind, _, rest = r["出典の元"].partition(":")
            if kind == "回答表":
                ok = rest in mk.ANSWERS and all(flat(p) in answer_of(rest) for p in r["照らす語"])
            elif kind == "書類":
                ok = all(flat(p) in flat(DOC_TEXTS.get(rest, "")) for p in r["照らす語"])
            elif kind == "モデル":
                ok = MODEL.get(rest) in r["照らす語"] or MODEL.get(rest) == r["記述"]
            elif kind == "計算":
                ok = CALC.get(r["記述"], False)
            elif kind == "社長":
                ok = allow_owner
            else:
                ok = False
            if r["記述"] in expect_mismatch:
                check(not ok, f"{label}：混ぜた「{r['記述']}」は、根拠対照表の出典（{r['出典の元']}）と食い違う（審査役が照らせば見つかる）")
            elif not ok:
                check(False, f"{label}：「{r['記述']}」（{it['名前']}）の出典の元 {r['出典の元']} に、その語がある")
    check(not dup, f"{label}：根拠対照表の行（記述と書いた場所の組）が重ならない（{dup}）")
    check(True, f"{label}：根拠対照表の{sum(len(it['根拠']) for it in items)}行の記述が本文にあり、出典の元で確かめられる（× がなければ）")


def check_base() -> None:
    names = [i["名前"] for i in SEIDO["様式"][0]["項目"]]
    check(all(it["名前"] in names for it in BASE), "正しい計画書の項目の名前が、制度データの様式の項目にある")
    form = mk.FORM.read_bytes() if mk.FORM.exists() else None
    if form:
        root = xml_spans.parse(yw.read_parts(form)[1][yw.DOC])
        bad = []
        for it in BASE:
            try:
                yw.check_position(root, it["書き込む位置"], it["名前"])
            except yw.FormError as e:
                bad.append(f"{it['名前']}：{e}")
        check(not bad, f"書き込む位置が公式の様式で見つかる（{bad}）")
    check_rows(BASE, "正しい計画書")
    body = "\n".join(mk.item_text(it) for it in BASE)
    check(not re.search(r"【\s*(仮|空欄)", body), "正しい計画書に仮の印・空欄がない")
    check(not any(s in body for s in ("**", "##", "回答表", "出典", ".pdf", "見積書_")), "本文に記号の残りと出典の書き込みがない")
    check(not re.search(r"(である|だ)。", body), "です・ます調にそろっている（である調がない）")
    sentences = [s for s in re.split(r"(?<=。)|\n", body) if s]
    long = [s for s in sentences if len(s) > 100]
    check(not long, f"100字を超える文がない（文体の基準 A の要修正。{[s[:20] for s in long]}）")
    hits = sorted({p for p in style_b_patterns() if re.search(p, body)})
    check(not hits, f"文体の基準 B の避ける言い回しがない（{hits}）")
    title = mk.item_text(BY_NAME["（2）事業計画名"])
    summary = mk.item_text(BY_NAME["（3）事業計画の概要"])
    check(len(title) <= 32, f"事業計画名が30字程度（{len(title)}字）")
    check(80 <= len(summary) <= 100, f"事業計画の概要が100字以内（目安100字。{len(summary)}字）")
    for v in (mk.PLAN_CORRECT, mk.PLAN_MIXED, mk.PLAN_QUESTION):
        data = json.loads((MAT / v / "本文.json").read_text(encoding="utf-8"))
        check([i["本文"] for i in data["項目"]] == [mk.item_text(it) for it in VARIANTS[v]], f"{v}/本文.json が作る元と同じ")
        rows = json.loads((MAT / v / "根拠対照表.json").read_text(encoding="utf-8"))["行"]
        from lib import konkyo

        check(len(konkyo.normalize_rows({"行": rows})) == len(rows) and not konkyo.unsupported(konkyo.normalize_rows({"行": rows})),
              f"{v}/根拠対照表.json は kakunin.py konkyo に渡せる形で、出典のない行がない（{len(rows)}行）")


# ---------------------------------------------------------------------------
# 3. 食い違い（T9-2）
# ---------------------------------------------------------------------------


def check_mixed() -> None:
    mixed = {it["名前"]: it for it in VARIANTS[mk.PLAN_MIXED]}
    touched = {ov["項目"] for ov in mk.MIXED}
    check(len(mk.MIXED) == 7 and len({ov["種類"] for ov in mk.MIXED}) >= 4, "混ぜた食い違いは7つで、種類（数字・事実・固有名詞・日付・方針）が4つ以上")
    for ov in mk.MIXED:
        base_text, new_text = mk.item_text(BY_NAME[ov["項目"]]), mk.item_text(mixed[ov["項目"]])
        check(base_text.count(ov["基の文"]) == 1 and ov["混ぜた文"] in new_text and ov["基の文"] not in new_text,
              f"{ov['id']}：「{ov['項目']}」の基の文が、混ぜた文に置き換わっている")
        ans = answer_of(ov["回答表"])
        check(all(flat(w) in ans for w in ov["正しい語"]) and not any(flat(w) in ans for w in ov["混ぜた語"]),
              f"{ov['id']}：回答表 {ov['回答表']} に正しい語があり、混ぜた語がない")
        check(not any(flat(w) in flat(base_text) for w in ov["混ぜた語"]), f"{ov['id']}：混ぜた語は正しい計画書の同じ項目にない")
    same = all(mk.item_text(it) == mk.item_text(mixed[it["名前"]]) for it in BASE if it["名前"] not in touched)
    check(same, "食い違いを混ぜた計画書の、ほかの項目は正しい計画書と同じ")
    replaced = frozenset(new for ov in mk.MIXED for _old, new in ov["根拠の置き換え"])
    check_rows(VARIANTS[mk.PLAN_MIXED], "食い違いを混ぜた計画書", expect_mismatch=replaced)


# ---------------------------------------------------------------------------
# 4. 社長の答えが要る指摘（T9-7）
# ---------------------------------------------------------------------------


def check_needs_answer() -> None:
    variant = {it["名前"]: it for it in VARIANTS[mk.PLAN_QUESTION]}
    base_body = flat("\n".join(mk.item_text(it) for it in BASE))
    pool = {"回答表": flat(SHEET_TEXT), "設定.md": flat(SETTING_TEXT)}
    pool.update({k: flat(v) for k, v in DOC_TEXTS.items()})
    for ov in mk.NEEDS_ANSWER:
        text = mk.item_text(variant[ov["項目"]])
        check(ov["混ぜた文"] in text, f"{ov['id']}：「{ov['項目']}」に足した文がある")
        for w in ov["どの材料にもない語"]:
            where = [k for k, v in pool.items() if flat(w) in v]
            check(not where and flat(w) not in base_body, f"{ov['id']}：「{w}」は回答表・設定・会社の資料・書類・正しい計画書のどこにもない（{where}）")
        for r in ov["足す根拠"]:
            rows = [x for x in variant[ov["項目"]]["根拠"] if x["記述"] == r["記述"]]
            check(len(rows) == 1 and mk.source_text(rows[0]["出典の元"]), f"{ov['id']}：「{r['記述']}」に根拠対照表の行と出典がある")
    body = "\n".join(mk.item_text(it) for it in VARIANTS[mk.PLAN_QUESTION])
    check(not re.search(r"【\s*(仮|空欄)", body), "社長の答えが要る計画書に仮の印・空欄がない（コードの確かめは通る形）")
    check_rows(VARIANTS[mk.PLAN_QUESTION], "社長の答えが要る計画書", allow_owner=True)


# ---------------------------------------------------------------------------
# 5. 手直し（T13-14）
# ---------------------------------------------------------------------------


def check_hand_edit() -> None:
    h = mk.HAND_EDIT
    base = mk.item_text(BY_NAME[h["項目"]])
    check(base.count(h["ツールが書いた言い回し"]) == 1, "直す言い回しが、正しい計画書の 1-1 現状分析に1つだけある")
    edited = base.replace(h["ツールが書いた言い回し"], h["社長が直した言い回し"])
    check(ANSWER["手直し（T13-14）"]["直した後の1-1の文"] in edited, "直した後の文が正解と同じ")
    check(not any(p in edited for p in h["2件目に出てはいけない言い回し"]), "直した後の 1-1 に、出てはいけない言い回しが残っていない")
    pool = [flat(SHEET_TEXT), flat(STYLE)] + [flat(v) for v in DOC_TEXTS.values()]
    check(not any(flat(p) in t for p in h["2件目に出てはいけない言い回し"] for t in pool),
          "出てはいけない言い回しは、回答表・会社の資料・書類・文体の基準のどこにもない（ツールが材料から写すことがない）")
    if not mk.FORM.exists():
        check(True, "公式の様式が downloads/ にないので、Word の確かめは飛ばした")
        return
    form = mk.FORM.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        made = mk.build_words(Path(tmp))
        check(len(made) == 8, f"Word と根拠対照表を8つ作り直せた（{len(made)}）")
        for rel in made:
            kept = HERE / mk.MADE / rel
            check(kept.exists() and kept.read_bytes() == (Path(tmp) / rel).read_bytes(), f"{mk.MADE}/{rel} が作り直したものと同じバイト列")
        tool = (Path(tmp) / mk.PLAN_EDITED / "その1・2_ツールが書いた版.docx").read_bytes()
        hand = (Path(tmp) / mk.PLAN_EDITED / "その1・2_社長が直した版.docx").read_bytes()
    positions = [(it["名前"], it["書き込む位置"]) for it in BASE]
    check(yw.compare_docx(form, tool, positions) == [], "ツールが書いた版は、書いてよい範囲の外が公式の様式と同じ")
    check(all(yw.item_text(tool, it["書き込む位置"]) == mk.item_text(it) for it in BASE), "ツールが書いた版の項目の文字が、正しい計画書の本文と同じ")
    diff_items = [it["名前"] for it in BASE if yw.item_text(tool, it["書き込む位置"]) != yw.item_text(hand, it["書き込む位置"])]
    check(diff_items == [h["項目"]], f"社長が直した版で文字が変わったのは 1-1 現状分析だけ（{diff_items}）")
    check(yw.item_text(hand, BY_NAME[h["項目"]]["書き込む位置"]) == edited, "社長が直した版の 1-1 が、言い回しを1つ打ち替えた文")
    check(yw.compare_docx(tool, hand, [(h["項目"], BY_NAME[h["項目"]]["書き込む位置"])]) == [], "社長が直した版は、1-1 のほかがツールが書いた版と同じ")
    # 公式の様式の文を写していないか（15字以上の段落。書き込む位置に使う見出し＝欄の名前は除く）
    root = xml_spans.parse(yw.read_parts(form)[1][yw.DOC])
    headings = {flat(it["書き込む位置"]["見出し"]) for it in BASE}
    form_lines = {flat(e["文字"]) for e in yw.outline(root) if len(flat(e.get("文字", ""))) >= 15} - headings
    ours = flat("".join((MAT / rel).read_text(encoding="utf-8") for rel in EXPECTED if rel.endswith((".json", ".md", ".txt"))))
    copied = [t[:20] for t in form_lines if t in ours]
    check(not copied, f"公式の様式の15字以上の文が、材料に写っていない（{copied}）")


# ---------------------------------------------------------------------------
# 6. 差し戻し（T12-2・T13-5）
# ---------------------------------------------------------------------------


def weekday_ok(text: str) -> bool:
    for m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日（(.)）", text):
        d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if mk.WEEKDAYS[d.weekday()] != m.group(4):
            return False
    return True


def check_sendbacks() -> None:
    from PIL import Image

    sb = MAT / mk.SENDBACK
    sub = json.loads((sb / "提出版" / "交付申請の入力.json").read_text(encoding="utf-8"))
    entries = ANSWER["差し戻し（T12-2・T13-5）"]["5件"]
    check(len(entries) == 5 and len({e["形"] for e in entries}) == 2, "差し戻しは5件で、貼り付けた文と画面の写真の両方がある")
    for e in mk.SENDBACKS:
        path = sb / e["ファイル"]
        if e["形"] == "画面の写真":
            img = Image.open(path)
            check(img.format == "PNG" and img.size[0] >= 1200 and img.size[1] >= 900, f"差し戻し{e['番号']}：画面の写真が開ける（{img.size}）")
        else:
            text = path.read_text(encoding="utf-8")
            check(mk.APPLICATION_NO in text and all(w in text for w in e["照らす語"]), f"差し戻し{e['番号']}：申請番号と、箇所を指す語がある")
            check(weekday_ok(text), f"差し戻し{e['番号']}：日付の曜日が正しい")
            check(not any(w in text for w in ("正解", "直し方", "テストで", "不備の型")), f"差し戻し{e['番号']}：文に答えやテストの事情を書いていない")
        check(any(e["不備の型"].startswith(t) for t in DEFECT_TYPES), f"差し戻し{e['番号']}：不備の型が knowledge/不備の型.json にある")
    rows = {r["番号"]: r for r in sub["経費の内訳"]}
    quote_t = flat(DOC_TEXTS[mk.QUOTE_T])
    quote_h = flat(DOC_TEXTS["見積書_ほしみ機工.pdf"])
    # 1 見積書の有効期限
    check("2027年1月31日" in quote_t and "2027年1月31日" in quote_h and dt.date.fromisoformat(sub["交付申請日"]) > dt.date(2027, 1, 31),
          "差し戻し1：提出版に添付した見積書2通の有効期限（2027-01-31）が、交付申請日より前")
    for file, subtotal in (("見積書_つばさ台フードシステム_2027年6月.pdf", "22,500,000"), ("見積書_ほしみ機工_2027年6月.pdf", "24,100,000")):
        t = flat(pdf_text(sb / "届いた書類" / file))
        check("2027年9月30日" in t and "2027年6月7日" in t and subtotal in t and "株式会社やまぶき惣菜" in t and mk.MARK in t,
              f"差し戻し1：取り直した {file} の有効期限・発行日・小計・宛名が合う")
    notice = next(n for n in DEADLINES["通知"] if n["種類"] == "交付決定通知書" and n["申請番号"] == mk.APPLICATION_NO)
    apply_by = next(e for e in DEADLINES["期限"]["省力化（一般型）第9回"] if e["名前"] == "交付申請の期限")["日付"]
    check(notice["交付申請日"] == sub["交付申請日"] and mk.SENT_BACK < mk.REQUOTE_DATE < mk.RESUBMIT <= mk.FIX_BY
          and mk.RESUBMIT <= dt.date.fromisoformat(apply_by) and mk.FIX_BY < dt.date.fromisoformat(notice["日付"])
          and mk.REQUOTE_VALID > mk.RESUBMIT,
          "差し戻しの日付が testdata/期限 の流れと合う（交付申請 → 差し戻し → 取り直し → 出し直し ≦ 交付申請の期限、交付決定の前）")
    # 2 税込の金額
    right_total = sum(q * p for _n, _m, q, p in mk.TSUBASA_ITEMS)
    check(rows[5]["金額（税抜）"] == 1_900_000 * 110 // 100 and "1,900,000" in quote_t and sub["補助対象経費の合計（税抜）"] == right_total + 190_000,
          "差し戻し2：提出版の番号5が税込の2,090,000円で、合計が190,000円多い")
    check(right_total == 22_500_000 and "22,500千円" in mk.ANSWERS["H-02"][1] and min(right_total * 2 // 3, 15_000_000) == 15_000_000,
          "差し戻し2：直した後の合計22,500,000円が見積書と回答表 H-02 と合い、補助金の申請額は15,000,000円のまま")
    # 3 番地
    reg = flat(DOC_TEXTS["履歴事項全部証明書.pdf"])
    check(sub["補助事業の実施場所"] != mk.ADDRESS_RIGHT and flat(mk.ADDRESS_RIGHT) in answer_of("B-01") and flat("八丁目12番5号") in reg,
          "差し戻し3：提出版の番地が、回答表 B-01・履歴事項全部証明書（12番5号）と違う")
    # 4 目標値
    check(sub["1人当たり給与支給総額の年平均成長率の目標値"] == "3.5%" and "目標値を4.0%とします" in mk.item_text(BY_NAME["3-1 労働生産性と1人当たり給与支給総額等の向上"])
          and "G52" in DUTIES, "差し戻し4：提出版の目標値3.5%が、応募の計画書 3-1 の4.0%と違う（目標値は変えられない：G52）")
    # 5 名称と型番
    check(rows[3]["名称"] == "包装機" and rows[3]["型番"] == "" and "トップシール包装機" in quote_t and "TF-TS60" in quote_t,
          "差し戻し5：提出版の番号3の名称と型番が、見積書（トップシール包装機、TF-TS60）と違う")
    others = [r for n, r in rows.items() if n not in (3, 5)]
    check(all(flat(r["名称"]) in quote_t and flat(r["型番"]) in quote_t and f"{r['金額（税抜）']:,}" in quote_t for r in others),
          "提出版のほかの行は、見積書と合う（差し戻しの5件のほかに誤りを仕込んでいない）")
    # T13-5
    first = entries[0]
    jizoku = next(e for e in DEADLINES["期限"]["持続化（通常枠）第20回"] if e["名前"].startswith("見積書等の提出"))
    check(first["不備の型"].startswith("不備-01") and first["2件目で前もって注意すること（T13-5）"]
          and first["2件目の見積書等の提出期限（testdata/期限）"] == jizoku["日付"],
          "T13-5：1件目は見積書の型（期限切れ）で、2件目の見積書等の提出で前もって注意することが書いてある")


# ---------------------------------------------------------------------------
# 7. 計画と実績（T12-4）
# ---------------------------------------------------------------------------


def check_results() -> None:
    spec = json.loads((MAT / mk.RESULTS / "財務モデルの指定.json").read_text(encoding="utf-8"))
    base = {k: (v["値"] if isinstance(v, dict) else v) for k, v in spec["基準年度"].items()}
    costs = base["原材料費"] + base["給与支給総額"] + base["その他の人件費"] + base["減価償却費"] + base["その他の経費"]
    check(base["売上"] - costs == 4_800_000 and "4,800千円" in mk.ANSWERS["F-03"][1], "財務モデルの基準年度の営業利益が4,800千円で、回答表 F-03 と合う")
    check(costs == (148_200 + 48_600) * 1000 and "148,200千円" in mk.ANSWERS["F-09"][1] and "48,600千円" in mk.ANSWERS["F-10"][1],
          "基準年度の経費の合計が、売上原価148,200千円＋販管費48,600千円（回答表 F-09・F-10）")
    check(base["給与支給総額"] == 41_600_000 and "41,600千円" in mk.ANSWERS["D-03"][1], "基準年度の給与支給総額が回答表 D-03 と合う")
    check(base["その他の人件費"] == (7_900 + 10_800 + 600) * 1000, "基準年度のその他の人件費が、法定福利費・役員報酬・福利厚生費の和")
    check(len(spec["前提"]) <= 20, f"前提は20個まで（{len(spec['前提'])}個）")
    s = mk.model_summary()
    ans = ANSWER["計画と実績（T12-4）"]
    actual = {k: v["値"] for k, v in json.loads((MAT / mk.RESULTS / "実績_1年目.json").read_text(encoding="utf-8"))["実績"].items()}
    labor = actual["給与支給総額"] + actual["その他の人件費"]
    op = actual["売上"] - actual["原材料費"] - labor - actual["減価償却費"] - actual["その他の経費"]
    for k in ("売上", "原材料費", "給与支給総額", "その他の人件費", "減価償却費", "その他の経費"):
        row = ans["行ごとの差（円）"][k]
        check(row["計画"] == round(s["合算"][k][1]) and row["実績"] == actual[k] and row["差"] == actual[k] - row["計画"],
              f"計画と実績：{k}の計画（財務モデルの1年目）・実績・差が合う")
    check(ans["行ごとの差（円）"]["営業利益"]["実績"] == op and ans["行ごとの差（円）"]["売上"]["差"] < 0 and ans["行ごとの差（円）"]["給与支給総額"]["差"] < 0,
          "実績は計画を下回る（売上・給与支給総額・営業利益）")
    va = op + labor + actual["減価償却費"]
    prod = youken.productivity(va, actual["役員数"] + actual["常勤従業員数"])
    pp = youken.pay_per_person(actual["給与支給総額"], actual["給与を受けた従業員数"])
    prod_g = youken.growth_plain(prod, s["指標"]["労働生産性"][0], 1)
    pp_g = youken.growth_pay(pp, s["指標"]["1人当たり給与"][0], 1)
    req = {r["名前"]: r for r in ans["要件"]}
    r1 = req["労働生産性の年平均成長率（基本要件①）"]
    check(r1["実績の伸び（1年目）"] == prod_g and prod_g < 4.0 and r1["判定"].startswith("満たさない") and "G34" in r1["返還の条件"]
          and r1["出典"] == [f"{x['資料']} p.{x['ページ']}" for x in DUTIES["G34"]["出典"]],
          f"労働生産性の伸び（実績 {prod_g}%）が4.0%を下回り、返還の定めが読み取れないこと（G34）が示される")
    r2 = req["1人当たり給与支給総額の年平均成長率（基本要件②）"]
    target = float(r2["目標値"].rstrip("%"))
    need = ((s["指標"]["1人当たり給与"][0] * (1 + target / 100) ** 5 / pp) ** 0.25 - 1) * 100
    rate = Decimal(str(pp_g)) / Decimal(str(target))
    check(r2["実績の伸び（1年目まで）"] == pp_g and pp_g < target and round(need, 2) == r2["目標に届くのに要る伸び（残りの4年、毎年）"],
          f"1人当たり給与支給総額の伸び（実績 {pp_g}%）が目標値{target}%を下回り、残りの4年に要る伸び（{round(need, 2)}%）が合う")
    ex = r2["返還額の例（最終年度まで同じ伸びなら）"]
    check(r2["返還の条件"] == DUTIES["G35"]["値"] and ex["返還額"] == int((mk.GRANT - mk.RAISE_OF_CAP) * (1 - rate)) == 10_500_000,
          "満たせない見込みの要件に、返還の条件（G35）と返還額の例（10,500,000円）が付く")
    check("4.0%" in mk.item_text(BY_NAME["3-1 労働生産性と1人当たり給与支給総額等の向上"]) and target == float(mk.TARGET_PAY_GROWTH),
          "目標値（4.0%）が応募の計画書 3-1 と同じ")


# ---------------------------------------------------------------------------
# 9. 作り直し
# ---------------------------------------------------------------------------


def check_rebuild() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mk.build_all(Path(tmp), with_words=False)
        diff = [rel for rel in EXPECTED if not rel.endswith(".png") and (Path(tmp) / mk.MATERIAL / rel).read_bytes() != (MAT / rel).read_bytes()]
        check(not diff, f"作り直すと、材料（画面の写真を除く）が同じバイト列（違うもの：{diff}）")
        check((Path(tmp) / mk.ANSWER_FILE).read_bytes() == (HERE / mk.ANSWER_FILE).read_bytes(), "作り直すと、正解.json が同じバイト列")


# ---------------------------------------------------------------------------
# 中身の一覧
# ---------------------------------------------------------------------------


def report() -> None:
    print("\n== 材料の一覧（材料/ の中。会社のフォルダに写すのはここだけ） ==")
    for rel in EXPECTED:
        print(f"- {rel}（{(MAT / rel).stat().st_size:,}バイト）")
    if (HERE / mk.MADE).exists():
        print(f"- {mk.MADE}/（Git の外。公式の様式から作った Word と根拠対照表）："
              + "、".join(sorted(p.relative_to(HERE / mk.MADE).as_posix() for p in (HERE / mk.MADE).rglob("*") if p.is_file())))
    print("\n== 混ぜた食い違い（T9-2、2_食い違いを混ぜた計画書） ==")
    for ov in mk.MIXED:
        print(f"- {ov['id']}［{ov['種類']}］{ov['項目']}：「{ov['混ぜた文']}」← 聞き取り（回答表 {ov['回答表']}）は「{'・'.join(ov['正しい語'])}」")
    print("\n== 社長の答えがないと直せない指摘（T9-7、3_社長の答えが要る計画書） ==")
    for ov in mk.NEEDS_ANSWER:
        print(f"- {ov['id']}［{ov['種類']}］{ov['項目']}：足した文「{ov['混ぜた文'].replace(ov['基の文'], '')}」")
        print(f"  指摘：{ov['指摘の中身']}")
    h = mk.HAND_EDIT
    print("\n== 社長が手で直した Word（T13-14） ==")
    print(f"- {h['項目']}：「{h['ツールが書いた言い回し']}」→「{h['社長が直した言い回し']}」。2件目に出てはいけない：{'、'.join(h['2件目に出てはいけない言い回し'])}")
    print("\n== 差し戻し5件（T12-2。1件目は T13-5 の先回りの型） ==")
    for e in ANSWER["差し戻し（T12-2・T13-5）"]["5件"]:
        print(f"- {e['番号']}. {e['ファイル']}（{e['形']}）［{e['件名']}］")
        print(f"  箇所：{e['提出版の箇所']['どこ']}（提出版：{e['提出版の箇所']['提出版の値']}）")
        print(f"  直し方：{e['直し方']}")
        print(f"  不備の型：{e['不備の型']}")
    ans = ANSWER["計画と実績（T12-4）"]
    print("\n== 計画を下回る実績（T12-4、事業計画の1年目） ==")
    for k, r in ans["行ごとの差（円）"].items():
        print(f"- {k}：計画 {r['計画']:,} ／ 実績 {r['実績']:,} ／ 差 {r['差']:,}（{r['差の割合（%）']}%）")
    for r in ans["要件"]:
        got = r.get("実績の伸び（1年目）", r.get("実績の伸び（1年目まで）"))
        print(f"- {r['名前']}：実績 {got}% → {r['判定']}")
        if "返還額の例（最終年度まで同じ伸びなら）" in r:
            ex = r["返還額の例（最終年度まで同じ伸びなら）"]
            print(f"  残りの4年に要る伸び {r['目標に届くのに要る伸び（残りの4年、毎年）']}%。返還の条件（{'、'.join(r['出典'])}）。"
                  f"このままなら達成率 {ex['達成率']} で返還額 {ex['返還額']:,}円")
        elif "返還の条件" in r:
            print(f"  {r['返還の条件']}")


def main() -> None:
    check_files()
    check_base()
    check_mixed()
    check_needs_answer()
    check_hand_edit()
    check_sendbacks()
    check_results()
    check_rebuild()
    for ok, what in results:
        print(("○ " if ok else "× ") + what)
    failed = [w for ok, w in results if not ok]
    report()
    print(f"\n○ {len(results) - len(failed)}件、× {len(failed)}件")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
