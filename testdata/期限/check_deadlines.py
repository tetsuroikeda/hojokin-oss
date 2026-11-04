# /// script
# requires-python = ">=3.9"
# dependencies = ["reportlab>=4", "pypdf>=4"]
# ///
"""期限の材料（TASKS D13）を確かめる。

確かめること：
1. `材料/` に、決めた7つの PDF だけがある（スクリプトや答えの文書がない）。どれも1ページで、「架空のテスト用データ」がある。
2. 通知：PDF から読んだ出来事の日付が `正解.json` と合う。文書の日付は出来事の日付と同じ。
   交付決定通知書に書いた補助事業完了期限日が、採択の通知と交付決定通知書の日付から計算し直した日と合う。
   日付の順番（締切 → 採択発表 → 交付申請 → 交付申請の期限 → 交付決定）と、持続化の予定（2027年3月頃、交付決定は1〜2か月後）に合う。
   金額は回答表（H-02、I-03）と補助率から計算した額で、上限を超えない。
3. 期限：`正解.json` の期限を、ここで別に書いた計算で出し直して合わせる。期限の決め方と出典は、制度データの正解
   （testdata/正解/省力化_第8回.json）と同じ。downloads/ があれば、出典のページに、その決まりの言葉が本当にあるかも見る。
4. 納税証明書：決算日の前に取ったものは第16〜18期、申告の後に取り直したものは第17〜19期。重なる期の所得金額は D2a と同じ。
   発行日、決算日、申告の期限の順番が合う。決算日の前のものを D2a の発行日で作り直すと、D2a と同じバイト列。
5. 台本：発言 S1〜S4 と答え A1〜A3 がある。S3 の書類が材料にある。答えの日数が `正解.json` の目安の日数と合い、
   始める日が締切から目安の日数を引いた日。台本に正解（計算した期限や始める日）が書かれていない。
   「次の案件で聞き直さない」が確かめられる形か：S1 が採択の後に取り直す見積にも触れ（1件目で A2 を引き出す）、
   S4 が2件目の見積に触れる。正解と材料の一覧が「A2 は場面1〜3で聞き、場面4では聞かない」で合い、
   場面4で初めて聞いてよいという逃げ道がない。
6. 届く書類（金融機関確認書）の日付が、頼んだ日と届いた日の間。金額が回答表（H-02、H-12）と合う。固有の名前を出していない。
7. どの PDF の「年月日（曜日）」も、曜日が正しい。
8. 作り直すと、どのファイルも同じバイト列になる。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/期限/check_deadlines.py
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_deadlines as mk  # noqa: E402

REPO = mk.REPO
MARK = "架空のテスト用データ"
WEEKDAYS = "月火水木金土日"
ANSWER = json.loads((HERE / "正解.json").read_text(encoding="utf-8"))
SEIDO = json.loads(mk.SEIDO_FILE.read_text(encoding="utf-8"))
ANSWER_SHEET = (REPO / "testdata" / "デモの会社" / "回答表.md").read_text(encoding="utf-8")
SCRIPT_TEXT = (HERE / "台本_外部への依頼.md").read_text(encoding="utf-8")
LIST_TEXT = (HERE / "材料の一覧.md").read_text(encoding="utf-8")
D2A_TAX = REPO / "testdata" / "デモの会社" / "書類" / "納税証明書_その2.pdf"
DOWNLOADS = REPO / "downloads"
EXPECTED_FILES = sorted([
    mk.SHORYOKU_ADOPTION_FILE, mk.SHORYOKU_GRANT_FILE, mk.JIZOKU_ADOPTION_FILE, mk.JIZOKU_GRANT_FILE,
    mk.TAX_BEFORE_FILE, mk.TAX_AFTER_FILE, mk.BANK_LETTER_FILE,
])

results: List[tuple] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))


def pdf_text(path: Path) -> str:
    return "".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def flat(text: str) -> str:
    """折り返しと空白を除き、全角の数字などを半角にそろえる。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def material(rel: str) -> Path:
    return HERE / "材料" / rel


TEXT: Dict[str, str] = {rel: pdf_text(material(rel)) for rel in EXPECTED_FILES if material(rel).exists()}
FLAT: Dict[str, str] = {rel: flat(t) for rel, t in TEXT.items()}

# ---------------------------------------------------------------------------
# ここで別に書いた日付の計算（make_deadlines.py の add_months を使わない）
# ---------------------------------------------------------------------------


def plus_months(d: dt.date, months: int) -> dt.date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    if d.day > calendar.monthrange(year, month)[1]:
        raise ValueError("この材料は、応当日がある日付だけを使う決まり")
    return dt.date(year, month, d.day)


def date_after(text: str, label: str) -> Optional[dt.date]:
    """「<label>2027年4月16日（金）」の形の日付を読む。曜日が合わなければ None。"""
    m = re.search(re.escape(label) + r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\((.)\)|（(.)）)", text)
    if not m:
        return None
    d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    weekday = m.group(4) or m.group(5)
    return d if WEEKDAYS[d.weekday()] == weekday else None


def first_date(text: str) -> Optional[dt.date]:
    return date_after(text, "")


def iso(value: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(value) if value else None


def stage(stage_id: str) -> Dict:
    return next(s for s in SEIDO["手続きの段階"] if s["id"] == stage_id)


def deadline(case: str, name_head: str) -> Dict:
    return next(e for e in ANSWER["期限"][case] if e["名前"].startswith(name_head))


def notice(rel: str) -> Dict:
    return next(n for n in ANSWER["通知"] if n["ファイル"] == rel)


# ---------------------------------------------------------------------------
# 1. ファイル
# ---------------------------------------------------------------------------


def check_files() -> None:
    found = sorted(p.relative_to(HERE / "材料").as_posix() for p in (HERE / "材料").rglob("*") if p.is_file())
    check(found == EXPECTED_FILES, f"材料/ にあるのは決めた7つの PDF だけ（見つけたもの：{found}）")
    for rel in EXPECTED_FILES:
        path = material(rel)
        if not path.exists():
            check(False, f"{rel} がある")
            continue
        check(len(PdfReader(str(path)).pages) == 1, f"{rel} は1ページ")
        check(MARK in TEXT[rel], f"{rel} に「{MARK}」がある")
    for name in ("台本_外部への依頼.md", "正解.json", "材料の一覧.md", "make_deadlines.py", "check_deadlines.py"):
        check((HERE / name).exists(), f"{name} が材料/ の外にある")


# ---------------------------------------------------------------------------
# 2. 通知
# ---------------------------------------------------------------------------


def check_notices() -> None:
    sa, sg = FLAT[mk.SHORYOKU_ADOPTION_FILE], FLAT[mk.SHORYOKU_GRANT_FILE]
    ja, jg = FLAT[mk.JIZOKU_ADOPTION_FILE], FLAT[mk.JIZOKU_GRANT_FILE]

    adopted = date_after(sa, "採択発表日")
    granted = date_after(sg, "交付決定日")
    check(adopted == iso(notice(mk.SHORYOKU_ADOPTION_FILE)["日付"]), f"省力化の採択の通知の採択発表日（{adopted}）が正解と合う")
    check(first_date(sa) == adopted, "省力化の採択の通知の文書の日付は、採択発表日と同じ")
    check(granted == iso(notice(mk.SHORYOKU_GRANT_FILE)["日付"]), f"省力化の交付決定通知書の交付決定日（{granted}）が正解と合う")
    check(first_date(sg) == granted, "省力化の交付決定通知書の文書の日付は、交付決定日と同じ")
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\(.\)|（.）)付けで申請", sg)
    kofu_applied = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    check(kofu_applied == iso(notice(mk.SHORYOKU_GRANT_FILE)["交付申請日"]), "交付決定通知書の交付申請日が正解と合う")
    shime = iso(ANSWER["仮の日付"]["省力化 第9回の締切"]["日付"])
    if adopted and granted and kofu_applied:
        check(shime < adopted < kofu_applied <= plus_months(adopted, 2) < granted,
              "省力化：締切 → 採択発表 → 交付申請（期限の内）→ 交付申請の期限 → 交付決定 の順")
        completion = min(plus_months(granted, 17), plus_months(adopted, 19))
        check(date_after(sg, "補助事業完了期限日") == completion,
              f"交付決定通知書の補助事業完了期限日が、2つの通知の日付から計算し直した日（{completion}）と合う")
    for text, rel in ((sa, mk.SHORYOKU_ADOPTION_FILE), (sg, mk.SHORYOKU_GRANT_FILE)):
        check("第9回公募" in text and mk.SHORYOKU["申請番号"] in text, f"{rel} に公募の回と申請番号がある")
    check("中小企業省力化投資補助事業事務局(架空の表示。テスト用)" in sa, "省力化の通知の差出人は架空の表示")

    # 金額：H-02 の 22,500千円 × 2/3。上限1,500万円（6〜20人）
    check("合計22,500千円" in ANSWER_SHEET and "22,500,000円(税抜)" in sg, "省力化の補助対象経費が回答表 H-02 と合う")
    check(22_500_000 * 2 // 3 == 15_000_000 and "交付決定額15,000,000円" in sg, "省力化の交付決定額 ＝ 22,500,000 × 2/3 ＝ 15,000,000（上限1,500万円の内）")

    j_adopted = date_after(ja, "採択発表日")
    j_granted = date_after(jg, "交付決定日")
    check(j_adopted == iso(notice(mk.JIZOKU_ADOPTION_FILE)["日付"]), f"持続化の採択通知書の採択発表日（{j_adopted}）が正解と合う")
    check(first_date(ja) == j_adopted and first_date(jg) == j_granted, "持続化の通知の文書の日付は、出来事の日付と同じ")
    check(j_granted == iso(notice(mk.JIZOKU_GRANT_FILE)["日付"]), f"持続化の交付決定通知書の交付決定日（{j_granted}）が正解と合う")
    if j_adopted and j_granted:
        check(j_adopted.year == 2027 and j_adopted.month == 3, "持続化の採択発表日は、要領20 p.3 の「2027年3月頃予定」の内")
        check(28 <= (j_granted - j_adopted).days <= 62, "持続化の交付決定は、採択発表から概ね1〜2か月（要領20 p.3・p.24）")
    check(date_after(jg, "実績報告書の提出期限") == dt.date(2028, 4, 10), "持続化の交付決定通知書の実績報告書の提出期限は 2028-04-10（要領20 p.24）")
    check(re.search(r"補助事業の実施期間\d{4}年\d{1,2}月\d{1,2}日\(.\)から2028年3月31日\(金\)まで", jg) is not None,
          "持続化の交付決定通知書の実施期間は、交付決定日から 2028-03-31 まで（要領20 p.24）")
    for text, rel in ((ja, mk.JIZOKU_ADOPTION_FILE), (jg, mk.JIZOKU_GRANT_FILE)):
        check("第20回公募" in text and mk.JIZOKU["申請番号"] in text, f"{rel} に公募の回と申請番号がある")
    check("合計3,000千円" in ANSWER_SHEET and "3,000,000円(税抜)" in jg, "持続化の補助対象経費が回答表 I-03 と合う")
    check(3_000_000 * 2 // 3 == 2_000_000 and "交付決定額2,000,000円" in jg, "持続化の交付決定額 ＝ 3,000,000 × 2/3 ＝ 2,000,000（上限200万円の内）")

    for text in (sa, sg, ja, jg):
        check(mk.COMPANY in text and mk.PRESIDENT.replace(" ", "") in text, "通知の宛先が回答表 A-01・A-08 の社名と代表者")


# ---------------------------------------------------------------------------
# 3. 期限
# ---------------------------------------------------------------------------


def check_rules_match_seido() -> None:
    kofu = stage("交付申請")["期限"]
    check(kofu["値"] == {"種類": "出来事からの期間", "出来事": "採択発表", "期間": {"数": 2, "単位": "か月"}},
          "制度データの正解：交付申請の期限は採択発表から2か月")
    jisshi = stage("補助事業の実施")["期限"]["値"]
    parts = sorted((p["出来事"], p["期間"]["数"], p["期間"]["単位"]) for p in jisshi["期限"])
    check(jisshi["種類"] == "早いほう" and parts == [("交付決定", 17, "か月"), ("採択発表", 19, "か月")],
          "制度データの正解：補助事業の実施の期限は、交付決定から17か月と採択発表から19か月の早いほう")
    jisseki = stage("実績報告")["期限"]["値"]
    check(jisseki["種類"] == "早いほう" and {"種類": "出来事からの期間", "出来事": "補助事業の完了", "期間": {"数": 30, "単位": "日"}} in jisseki["期限"],
          "制度データの正解：実績報告の期限に、完了から30日が入る")
    koka = stage("効果報告")["期限"]["値"]
    check(koka["回数"] == 5 and koka["提出期間"]["始まりの月"] == 4 and koka["提出期間"]["長さ"] == {"数": 3, "単位": "か月"},
          "制度データの正解：効果報告は5回、4月から3か月")


def check_shoryoku_deadlines() -> None:
    case = mk.SHORYOKU["案件"]
    adopted = iso(notice(mk.SHORYOKU_ADOPTION_FILE)["日付"])
    granted = iso(notice(mk.SHORYOKU_GRANT_FILE)["日付"])

    e = deadline(case, "交付申請の期限")
    check(iso(e["日付"]) == plus_months(adopted, 2), f"交付申請の期限 ＝ 採択発表日 {adopted} から2か月後の日 ＝ {e['日付']}")
    check(e["出典"] == stage("交付申請")["期限"]["出典"], "交付申請の期限の出典が、制度データの正解と同じ（要領8 p.26–27、応募手引8 p.9・p.80）")

    e = deadline(case, "補助事業の完了期限")
    a, b = plus_months(granted, 17), plus_months(adopted, 19)
    check(iso(e["日付"]) == min(a, b), f"補助事業の完了期限 ＝ min（交付決定から17か月 {a}、採択発表から19か月 {b}）＝ {e['日付']}")
    check(e["早いほう"] == ("採択発表から19か月" if b < a else "交付決定から17か月"), f"早いほうは「{e['早いほう']}」")
    check(b < a, "この材料では、採択発表から19か月のほうが早い（「早いほう」の分かれが見える）")
    check(all(s in e["出典"] for s in stage("補助事業の実施")["期限"]["出典"]), "補助事業の完了期限の出典に、制度データの正解の出典がそろう")

    e = deadline(case, "実績報告の期限")
    check(e["日付"] is None and iso(e["上限"]) == min(a, b), "実績報告の期限は、完了日が分かるまで上限（補助事業完了期限日）だけ")

    e = deadline(case, "状況報告")
    check(iso(e["日付"]) == plus_months(granted, 12), "状況報告が要るかを確かめる日 ＝ 交付決定日から1年")

    e = deadline(case, "効果報告")
    for branch, done in zip(e["分かれ"], (dt.date(2028, 3, 31), dt.date(2028, 4, 1))):
        fy_start = done.year if done.month >= 4 else done.year - 1
        first = dt.date(fy_start + 2, 4, 1)
        windows = branch["提出期間"]
        ok = len(windows) == 5 and all(
            iso(w["始まり"]) == dt.date(first.year + i, 4, 1) and iso(w["終わり"]) == dt.date(first.year + i, 6, 30)
            for i, w in enumerate(windows))
        check(ok, f"効果報告：完了が {done} の側の分かれは、{first.year}年から毎年4月〜6月を5回")


def check_jizoku_deadlines() -> None:
    case = mk.JIZOKU["案件"]
    expected = {
        "見積書等の提出期限": ("2028-02-29", "火"),
        "補助事業の実施の期限": ("2028-03-31", "金"),
    }
    for name, (day, weekday) in expected.items():
        e = deadline(case, name)
        check(e["日付"] == day and e["曜日"] == weekday, f"持続化の{name}は {day}（{weekday}）（要領20 の曜日と同じ）")
    e = deadline(case, "実績報告書の提出期限")
    check(e["日付"] is None and e["上限"] == "2028-04-10" and e["上限の曜日"] == "月", "持続化の実績報告書の提出期限は、上限 2028-04-10（月）")


def page_text_flat(pdf: Path, pdf_page: int) -> str:
    return flat(PdfReader(str(pdf)).pages[pdf_page - 1].extract_text() or "")


# 出典のページに、その決まりの言葉があるか（資料, PDF のファイル, 印刷されたページ, PDF のページのずれ, 言葉）
SOURCE_WORDS = [
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 26, 0, "採択発表日から2か月後の日"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 26, 0, "交付決定日から17か月以内"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 26, 0, "採択発表日から19か月後の日まで"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 9, 0, "交付決定日から17か月以内(採択発表日から19か月以内)"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 27, 0, "履歴事項全部証明書(発行から3か月以内のもの)"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 27, 0, "納税証明書(その2)直近3期分"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 27, 0, "金融機関確認書"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 12, 0, "金融機関による確認書"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 36, 0, "最初の4月より5年間"),
    ("要領8", "shoryokuka_ippan/application_guidelines_ippan_08.pdf", 36, 0, "30日を経過した日"),
    ("応募手引8", "shoryokuka_ippan/oubo_manual_ippan_08.pdf", 9, 0, "採択発表日から2か月後の日"),
    ("応募手引8", "shoryokuka_ippan/oubo_manual_ippan_08.pdf", 80, 0, "採択発表日から2か月後の日"),
    ("応募手引8", "shoryokuka_ippan/oubo_manual_ippan_08.pdf", 63, 0, "応募申請日において発行日から3か月以内"),
    ("交付申請の手引き6", "shoryokuka_ippan/application_manual_ippan_06.pdf", 38, 0, "応募申請日において発行日から3か月以内"),
    ("交付申請の手引き6", "shoryokuka_ippan/application_manual_ippan_06.pdf", 33, 0, "見積書(全経費分最低2者分)"),
    ("実績報告の手引き", "shoryokuka_ippan/completion_manual_ippan.pdf", 5, 0, "交付決定通知書に記載の補助事業完了期限日"),
    ("実績報告の手引き", "shoryokuka_ippan/completion_manual_ippan.pdf", 7, 0, "翌年度を事業計画期間1年目"),
    ("実績報告の手引き", "shoryokuka_ippan/completion_manual_ippan.pdf", 40, 0, "4月から3か月間"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 3, 1, "2027年3月頃予定"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 3, 1, "2028年2月29日"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 3, 1, "概ね1〜2か月"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 3, 1, "2026年12月4日"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 7, 1, "2028年3月31日(金)"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 22, 1, "様式4"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 24, 1, "交付決定日より2028年3月31日(金)まで2028年4月10日(月)"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 24, 1, "30日を経過した日"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 24, 1, "見積書の提出期限は2028年2月29日(火)"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 26, 1, "補助事業終了から1年後の状況"),
    ("要領20", "jizokuka_20/r6_koubover8_ip20.pdf", 27, 1, "発行には時間を要する場合があります"),
]


def check_sources() -> None:
    if not DOWNLOADS.exists():
        print("（downloads/ がないので、出典のページの言葉は確かめなかった）")
        return
    cache: Dict[tuple, str] = {}
    for doc, rel, printed, offset, words in SOURCE_WORDS:
        pdf = DOWNLOADS / rel
        if not pdf.exists():
            check(False, f"{doc} の PDF（downloads/{rel}）がある")
            continue
        key = (rel, printed + offset)
        if key not in cache:
            cache[key] = page_text_flat(pdf, printed + offset)
        check(flat(words) in cache[key], f"{doc} p.{printed} に「{words}」がある")
    # 正解.json で使った出典のページが、上で確かめたページか、制度データの正解の出典に入っている
    checked = {(doc, printed) for doc, _, printed, _, _ in SOURCE_WORDS}
    seido_pages = set()
    for s in SEIDO["手続きの段階"]:
        for part in ("始まる条件", "期限"):
            for src in (s.get(part) or {}).get("出典", []):
                seido_pages.add((src["資料"], src.get("ページ")))
    for d in SEIDO["書類"]:
        for part in ("有効期限", "期数", "条件"):
            for src in (d.get(part) or {}).get("出典", []):
                seido_pages.add((src["資料"], src.get("ページ")))
    for c in SEIDO["資料どうしの食い違い"]:
        for v in c["値"]:
            for src in v.get("出典", []):
                seido_pages.add((src["資料"], src.get("ページ")))
    used = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "資料" in node and "ページ" in node:
                used.add((node["資料"], node["ページ"]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(ANSWER)
    missing = sorted(u for u in used if u not in checked and u not in seido_pages)
    check(not missing, f"正解.json の出典は、言葉を確かめたページか、制度データの正解の出典（足りないもの：{missing}）")


# ---------------------------------------------------------------------------
# 4. 納税証明書
# ---------------------------------------------------------------------------


def incomes(text: str) -> List[tuple]:
    return re.findall(r"(令和\d+年4月1日)〜(令和\d+年3月31日)([\d,]+)", text)


def check_tax() -> None:
    before, after = FLAT[mk.TAX_BEFORE_FILE], FLAT[mk.TAX_AFTER_FILE]
    d2a = incomes(flat(pdf_text(D2A_TAX)))
    got_before, got_after = incomes(before), incomes(after)
    check([p[:2] for p in got_before] == [("令和5年4月1日", "令和6年3月31日"), ("令和6年4月1日", "令和7年3月31日"), ("令和7年4月1日", "令和8年3月31日")],
          "決算日の前に取った納税証明書は、第16〜18期")
    check([p[:2] for p in got_after] == [("令和6年4月1日", "令和7年3月31日"), ("令和7年4月1日", "令和8年3月31日"), ("令和8年4月1日", "令和9年3月31日")],
          "申告の後に取り直した納税証明書は、第17〜19期")
    check(got_before == d2a, "決算日の前のものの所得金額は、D2a と同じ（回答表 F-08）")
    check(got_after[:2] == d2a[1:], "申告の後のものの第17期・第18期の所得金額は、D2a と同じ")
    check(got_after[2][2] == f"{mk.INCOME_19 * 1000:,}" if len(got_after) == 3 else False, "第19期の所得金額は、材料の一覧に挙げた値")
    check("発行日令和9年3月10日" in before and "発行日令和9年6月7日" in after, "発行日は令和9年3月10日と令和9年6月7日")
    fy_end = iso(ANSWER["決算日をまたぐ書類（T6-5）"]["第19期"]["決算日"])
    filing = iso(ANSWER["決算日をまたぐ書類（T6-5）"]["第19期"]["申告の期限"])
    check(fy_end == dt.date(2027, 3, 31) and "| A-10 | 決算の月 | 3月" in ANSWER_SHEET, "第19期の決算日は 2027-03-31（回答表 A-10：3月決算）")
    check(filing == plus_months(dt.date(2027, 4, 1), 2) - dt.timedelta(days=1), "申告の期限は、決算日の翌日から2か月以内（2027-05-31）")
    check(dt.date(2027, 3, 10) < fy_end < filing < dt.date(2027, 6, 7), "発行日（3月）→ 決算日 → 申告の期限 → 発行日（6月）の順")
    examples = ANSWER["決算日をまたぐ書類（T6-5）"]["納税証明書（その2）"]["例"]
    check(iso(examples[0]["応募申請日"]) < filing < iso(examples[1]["応募申請日"]), "T6-5 の例の応募申請日は、申告の期限の前と後")
    with tempfile.TemporaryDirectory() as tmp:
        again = Path(tmp) / "again.pdf"
        mk.build_tax_certificate(again, dt.date(2026, 10, 23), list(mk.d2a.TAXABLE_INCOME))
        check(again.read_bytes() == D2A_TAX.read_bytes(), "決算日の前のものを D2a の発行日で作り直すと、D2a と同じバイト列（違うのは発行日だけ）")
    registry = ANSWER["決算日をまたぐ書類（T6-5）"]["履歴事項全部証明書"]["例"]
    apply_day = iso(registry["応募申請日"])
    check(iso(registry["取得の期間"]["いちばん早い日"]) == plus_months(apply_day, -3) and iso(registry["取得の期間"]["いちばん遅い日"]) == apply_day,
          "履歴事項全部証明書の取得の期間 ＝ 応募申請日の3か月前の日から、応募申請日まで")


# ---------------------------------------------------------------------------
# 5. 台本、6. 届く書類
# ---------------------------------------------------------------------------


def table_rows(text: str, head: str) -> Dict[str, List[str]]:
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(head + r"\d", cells[0]):
            rows[cells[0]] = cells
    return rows


def check_script() -> None:
    says = table_rows(SCRIPT_TEXT, "S")
    replies = table_rows(SCRIPT_TEXT, "A")
    check(sorted(says) == ["S1", "S2", "S3", "S4"] and sorted(replies) == ["A1", "A2", "A3"], "台本に発言 S1〜S4 と答え A1〜A3 がある")
    for key, day in mk.SCRIPT_DAYS.items():
        check(day.isoformat() in says.get(f"S{key}", [""])[1], f"S{key} の場面の日付は {day}")
    check("頼みました" in says["S2"][4], "S2 で「依頼した」と伝える")
    check(says["S3"][3] == f"材料/{mk.BANK_LETTER_FILE}" and (HERE / says["S3"][3]).exists(), "S3 で入れる書類が材料にある")
    check("届いた" in says["S3"][4], "S3 で「届いた」と伝える")
    check("2件目" in says["S4"][2], "S4 は2件目（次の案件）")
    requests = ANSWER["外部への依頼（T6-6）"]
    bank = next(r for r in requests if r["書類"] == "金融機関確認書")
    estimate = next(r for r in requests if r["書類"].startswith("見積書（交付申請"))
    reuse = next(r for r in requests if r["書類"].startswith("見積書等"))
    check("2週間" in replies["A1"][2] and bank["目安の日数"]["値"] == 14, "A1 の「2週間くらい」が、金融機関確認書の目安の日数 14日")
    check("1週間" in replies["A2"][2] and estimate["目安の日数"]["値"] == 7 and reuse["目安の日数"]["値"] == 7,
          "A2 の「1週間くらい」が、見積書の目安の日数 7日（2件目でも同じ日数を使う）")
    check(iso(bank["始める日"]) == iso(bank["締切"]["日付"]) - dt.timedelta(days=14), "金融機関確認書の始める日 ＝ 締切 − 14日")
    kofu = iso(deadline(mk.SHORYOKU["案件"], "交付申請の期限")["日付"])
    check(iso(estimate["締切"]["日付"]) == kofu and iso(estimate["始める日"]) == kofu - dt.timedelta(days=7), "見積書の始める日 ＝ 交付申請の期限 − 7日")
    states = [s["状態"] for s in bank["状態の移り変わり"]]
    check(states == ["まだ", "依頼した", "届いた"], "金融機関確認書の状態は まだ → 依頼した → 届いた")
    check("わたし" in replies["A3"][2] and all(r["だれがするか"]["頼む"].startswith("社長") for r in (bank, estimate, reuse)),
          "だれが頼むか（社長）が A3 と正解で合う（確認書、1件目と2件目の見積）")
    reuse_deadline = iso(reuse["締切"]["日付"])
    check(reuse_deadline == mk.JIZOKU["見積書等の提出期限"] and iso(reuse["始める日"]) == reuse_deadline - dt.timedelta(days=7),
          "2件目の見積書等の始める日 ＝ 見積書等の提出期限 − 7日（1件目で聞いた日数）")
    computed = [bank["始める日"], estimate["始める日"], kofu.isoformat(), bank["締切"]["日付"], reuse["始める日"], reuse["締切"]["日付"]]
    check(not any(day in SCRIPT_TEXT for day in computed), "台本に、締切・計算した期限・始める日の日付が書かれていない")
    check_no_reask(says, bank, estimate, reuse)


def check_no_reask(says: Dict[str, List[str]], bank: Dict, estimate: Dict, reuse: Dict) -> None:
    """T6-6 の4つ目の合格ライン「聞いた日数を、次の案件で聞き直さない」が、落ちうる形で確かめられるか。

    1件目で A2（見積の日数）を聞く場面が必ず来て、2件目で同じ日数を使う場面が必ず来ること。
    どちらかが欠けると、どう作っても4つ目の合格ラインに落ちない（一度も使い回しが起きない）。
    """
    s1, s4 = says["S1"][4], says["S4"][4]
    check("見積" in s1 and "取り直" in s1 and "採択の後" in s1,
          "S1 が、採択の後に取り直す見積にも触れる（1件目で A2 を引き出す）")
    check("見積" in s4, "S4 が、2件目の見積に触れる（場面4で、1件目で聞いた日数を使う場面が必ず来る）")
    check(bank["目安の日数"]["聞く場面"] == mk.ASK_SCENES and estimate["目安の日数"]["聞く場面"] == mk.ASK_SCENES
          and mk.ASK_SCENES.startswith("場面1〜3"),
          "正解：A1 と A2 は場面1〜3（1件目）で聞く")
    check(reuse["目安の日数"]["聞かない場面"] == mk.REUSE_SCENE and mk.REUSE_SCENE.startswith("場面4")
          and "聞き直さない" in reuse["目安の日数"]["出どころ"],
          "正解：2件目の見積書等は、場面4で聞き直さずに1件目の日数を使う")
    row = next((line for line in LIST_TEXT.splitlines() if line.startswith("| 聞いた日数を、次の案件で聞き直さない |")), "")
    check("場面1〜3" in row and "場面4では聞かない" in row and "不合格" in row and "7日" in row,
          "材料の一覧の採点：A2 を場面1〜3で聞き、場面4では聞かず、2件目に7日を使う。場面4の前に聞かなければ不合格")
    check("初めて聞かれてよい" not in LIST_TEXT, "材料の一覧に、場面4で初めて聞いてよいという逃げ道がない")


def check_bank_letter() -> None:
    text = FLAT[mk.BANK_LETTER_FILE]
    day = date_after(text, "確認した日")
    check(day == mk.BANK_LETTER_DATE and mk.SCRIPT_DAYS["2"] < day < mk.SCRIPT_DAYS["3"], "確認書の日付は、頼んだ日（S2）と届いた日（S3）の間")
    check("15,500千円" in ANSWER_SHEET and "借入の予定額15,500,000円" in text, "借入の予定額が回答表 H-12 と合う")
    check("事業に要する経費22,500,000円(税抜)" in text, "事業に要する経費が回答表 H-02 と合う")
    check("架空の信用金庫(テスト用)" in text and len(re.findall(r"信用金庫", text)) == 1, "信用金庫の固有の名前を出していない")
    check("第9回公募" in text, "確認書は1件目（省力化 第9回）のもの")


# ---------------------------------------------------------------------------
# 7. 曜日、8. 作り直し
# ---------------------------------------------------------------------------


def check_weekdays() -> None:
    bad = []
    count = 0
    for rel, text in FLAT.items():
        for m in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日\((.)\)", text):
            count += 1
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if WEEKDAYS[d.weekday()] != m.group(4):
                bad.append(f"{rel}:{m.group(0)}")
    # 14件：省力化の採択の通知2、交付決定通知書4、持続化の採択通知書2、交付決定通知書5、金融機関確認書1
    check(count == 14 and not bad, f"PDF の「年月日（曜日）」{count}件（14件のはず）の曜日が正しい（違うもの：{bad}）")


def check_rebuild() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "材料"
        answer = Path(tmp) / "正解.json"
        mk.build(out, answer)
        same = all((out / rel).read_bytes() == material(rel).read_bytes() for rel in EXPECTED_FILES)
        check(same, "作り直すと、7つの PDF が同じバイト列")
        check(answer.read_bytes() == (HERE / "正解.json").read_bytes(), "作り直すと、正解.json が同じバイト列")


def main() -> None:
    check_files()
    if len(TEXT) == len(EXPECTED_FILES):
        check_notices()
        check_rules_match_seido()
        check_shoryoku_deadlines()
        check_jizoku_deadlines()
        check_sources()
        check_tax()
        check_script()
        check_bank_letter()
        check_weekdays()
        check_rebuild()
    for ok, what in results:
        print(("○ " if ok else "× ") + what)
    failed = [w for ok, w in results if not ok]
    print(f"\n○ {len(results) - len(failed)}件、× {len(failed)}件")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
