# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf>=4", "reportlab>=4", "python-docx>=1.1", "openpyxl>=3.1"]
# ///
"""デモの会社（2社目・町工場）の採択後の材料を確かめる。

make_saitakugo.py の中の値ではなく、できたファイル（PDF・テキスト）から取り出した文字を、
回答表.md、1社目の日付（testdata/期限/正解.json）、別に書いた期限の計算と照らす。
あわせて、どのページにも「架空のテスト用データ」の帯と足があること、公印や本物の事務局の名前がないこと、
同じ中身なら同じバイト列になること（作り直して照らす）を確かめる。
downloads/ に公募要領があれば、期限の決まりの言葉がそのページにあることと、公式資料の文を30字続けて写していないことも見る。
合わないものがあれば終了コード1で終わる。

動かし方：uv run --script testdata/デモの会社_町工場/採択後/check_saitakugo.py
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
COMPANY_DIR = HERE.parent
REPO = COMPANY_DIR.parent.parent
ANSWER_SHEET = COMPANY_DIR / "回答表.md"
FIRST_COMPANY_ANSWER = REPO / "testdata" / "期限" / "正解.json"
QUOTE_PDF = COMPANY_DIR / "書類" / "見積書_かすみ野システム工房.pdf"
GUIDELINE_09 = REPO / "downloads" / "shoryokuka_ippan" / "application_guidelines_ippan_09.pdf"
GUIDELINE_J20 = REPO / "downloads" / "jizokuka_20" / "r6_koubover8_ip20.pdf"
MARK = "架空のテスト用データ"
WEEKDAYS = "月火水木金土日"

SHORYOKU_ADOPTION = "省力化_第9回_採択の通知.pdf"
SHORYOKU_GRANT = "省力化_第9回_交付決定通知書.pdf"
JIZOKU_ADOPTION = "持続化_第20回_採択通知書.pdf"
JIZOKU_GRANT = "持続化_第20回_交付決定通知書.pdf"
REMAND = "差し戻し_システム構築費の明細.txt"
PDFS = [SHORYOKU_ADOPTION, SHORYOKU_GRANT, JIZOKU_ADOPTION, JIZOKU_GRANT]

SHORYOKU_NUMBER = "TEST-S09-0563"
JIZOKU_NUMBER = "TEST-J20-0419"

failures: list[str] = []


def report(ok: bool, text: str) -> None:
    print(f"  {'○' if ok else '×'} {text}")
    if not ok:
        failures.append(text)


def flat(text: str) -> str:
    """NFKC にそろえ、空白と改行を除く（PDF の折り返しで切れた文をつなぐ）。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def jp(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def months_later(d: dt.date, n: int) -> dt.date:
    """make とは別に書いた応当日の計算（この材料の日付は、どれも応当日がある）。"""
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, d.day)


# ---------------------------------------------------------------------------
# 照らす相手（回答表と1社目の日付）
# ---------------------------------------------------------------------------


def load_answers() -> dict[str, str]:
    answers = {}
    for line in ANSWER_SHEET.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-L]-\d{2})\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*$", line)
        if m:
            answers[m[1]] = m[2]
    return answers


ANSWERS = load_answers()


def thousand(answer_id: str, pattern: str) -> int:
    m = re.search(pattern, ANSWERS[answer_id])
    if not m:
        raise SystemExit(f"回答表の {answer_id} に「{pattern}」が見つかりません")
    return int(m[1].replace(",", "")) * 1000


def first_company_dates() -> dict:
    data = json.loads(FIRST_COMPANY_ANSWER.read_text(encoding="utf-8"))
    out = {}
    for n in data["通知"]:
        key = ("省力化" if "省力化" in n["案件"] else "持続化", n["出来事"])
        out[key] = dt.date.fromisoformat(n["日付"])
        if "交付申請日" in n:
            out[("省力化", "交付申請")] = dt.date.fromisoformat(n["交付申請日"])
        if "持続化" in n["案件"]:
            for name, value in n.get("書いた期限", {}).items():
                out[("持続化", name)] = dt.date.fromisoformat(value)
    return out


FIRST = first_company_dates()
S_ADOPT = FIRST[("省力化", "採択発表")]
S_APPLY = FIRST[("省力化", "交付申請")]
S_GRANT = FIRST[("省力化", "交付決定")]
J_ADOPT = FIRST[("持続化", "採択発表")]
J_GRANT = FIRST[("持続化", "交付決定")]
J_END = FIRST[("持続化", "補助事業の実施の期限")]
J_REPORT = FIRST[("持続化", "実績報告書の提出期限")]

# 期限（公募要領 第9回 p.8・p.25）
S_APPLY_DEADLINE = months_later(S_ADOPT, 2)
S_CAND_GRANT = months_later(S_GRANT, 14)
S_CAND_ADOPT = months_later(S_ADOPT, 16)
S_COMPLETION = min(S_CAND_GRANT, S_CAND_ADOPT)

# 金額（回答表 H-02・I-03。千円 → 円）
# 省力化は、デモの計画書の補助申請金額（13,600,000円）に合わせ、読み取り端末とクラウドの利用料を除いた形（作者の指示）
S_SYSTEM = thousand("H-02", r"機械装置・システム構築費が([\d,]+)千円")
S_READER = thousand("H-02", r"専用の読み取り端末4台([\d,]+)千円")
S_CLOUD = thousand("H-02", r"クラウドの利用料（[^）]*）([\d,]+)千円")
S_COST = S_SYSTEM - S_READER
S_AMOUNT = S_COST * 2 // 3
S_PLAN_REQUEST = 13_600_000  # デモの計画書の補助申請金額
J_COST = thousand("I-03", r"合計([\d,]+)千円")
J_AMOUNT = J_COST * 2 // 3


def pdf_pages(name: str) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(str(HERE / name)).pages]


def main() -> None:
    company = re.search(r"株式会社\S+", ANSWERS["A-01"])[0]
    president = re.search(r"代表取締役 (\S+ [^\s（]+)", ANSWERS["A-08"])[1]
    corporate_number = ANSWERS["A-03"]

    print("ファイル")
    for name in PDFS + [REMAND]:
        report((HERE / name).exists(), f"{name} がある")
    if failures:
        sys.exit(1)

    texts = {name: "\n".join(pdf_pages(name)) for name in PDFS}
    flats = {name: flat(t) for name, t in texts.items()}
    remand = (HERE / REMAND).read_text(encoding="utf-8")
    remand_flat = flat(remand)

    print("架空の帯と足（どのページにも）")
    for name in PDFS:
        pages = pdf_pages(name)
        for i, page in enumerate(pages, start=1):
            report("架空のテスト用データ（hojokin-oss）" in page and f"{MARK}｜" in page and f"｜{i}/{len(pages)}ページ" in page,
                   f"{name} の {i}ページに帯と足がある")
        title = PdfReader(str(HERE / name)).metadata.get("/Title", "")
        report(MARK in title, f"{name} の文書の題に「{MARK}」がある")
    report(remand.startswith(f"（{MARK}。"), f"{REMAND} の1行目に「{MARK}」がある")

    print("社名・代表者・申請番号（回答表 A-01・A-03・A-08）")
    for name in PDFS:
        report(company in texts[name], f"{name} に社名「{company}」がある")
        report(f"代表取締役　{president}　様" in texts[name], f"{name} のあて名が代表取締役 {president}")
        number = SHORYOKU_NUMBER if name.startswith("省力化") else JIZOKU_NUMBER
        report(number in texts[name], f"{name} に申請番号 {number} がある")
    report(corporate_number in texts[SHORYOKU_ADOPTION], f"{SHORYOKU_ADOPTION} に法人番号 {corporate_number} がある")
    report(company in remand and SHORYOKU_NUMBER in remand, f"{REMAND} に社名と申請番号 {SHORYOKU_NUMBER} がある")
    report("TEST-S09-0421" not in remand + "".join(texts.values()) and "TEST-J20-0388" not in "".join(texts.values()),
           "1社目の申請番号を使っていない")
    report("やまぶき" not in remand + "".join(texts.values()), "1社目の社名が入っていない")

    print("日付（1社目の testdata/期限/正解.json と同じ日）")
    report(jp(S_ADOPT) in texts[SHORYOKU_ADOPTION] and texts[SHORYOKU_ADOPTION].count(jp(S_ADOPT)) >= 2,
           f"省力化の採択の通知：文書の日付と採択発表日が {jp(S_ADOPT)}")
    report(jp(S_GRANT) in texts[SHORYOKU_GRANT] and f"{jp(S_APPLY)}付けで申請" in texts[SHORYOKU_GRANT],
           f"省力化の交付決定通知書：交付決定日 {jp(S_GRANT)}、交付申請日 {jp(S_APPLY)}")
    report(jp(J_ADOPT) in texts[JIZOKU_ADOPTION], f"持続化の採択通知書：採択発表日 {jp(J_ADOPT)}")
    report(jp(J_GRANT) in texts[JIZOKU_GRANT], f"持続化の交付決定通知書：交付決定日 {jp(J_GRANT)}")
    report(f"{jp(J_GRANT)}から{jp(J_END)}まで" in texts[JIZOKU_GRANT], f"持続化の実施期間が {jp(J_GRANT)}〜{jp(J_END)}")
    report(f"実績報告書の提出期限{jp(J_REPORT)}" in flat(texts[JIZOKU_GRANT]) or
           flat(f"実績報告書の提出期限\n{jp(J_REPORT)}") in flats[JIZOKU_GRANT],
           f"持続化の実績報告書の提出期限が {jp(J_REPORT)}")
    # 採択の通知には、交付申請の期限の日付を書かない（1社目と同じ書き方）
    report(flat(jp(S_APPLY_DEADLINE)) not in flats[SHORYOKU_ADOPTION] and "公募要領と事務局の案内のとおり" in flats[SHORYOKU_ADOPTION],
           f"省力化の採択の通知は、交付申請の期限（計算すると {jp(S_APPLY_DEADLINE)}）を日付で書かず、1社目と同じく公募要領と案内によると書く")

    print("補助事業完了期限日（公募要領 第9回 p.8・p.25：交付決定日から14か月以内、採択発表日から16か月後の日まで）")
    report(S_CAND_GRANT == dt.date(2028, 8, 25) and S_CAND_ADOPT == dt.date(2028, 8, 16),
           f"候補：交付決定日から14か月 {jp(S_CAND_GRANT)}、採択発表日から16か月 {jp(S_CAND_ADOPT)}")
    report(f"補助事業完了期限日{flat(jp(S_COMPLETION))}" in flats[SHORYOKU_GRANT],
           f"交付決定通知書の補助事業完了期限日が、早いほうの {jp(S_COMPLETION)}")
    report(flat(f"{jp(S_GRANT)}から{jp(S_COMPLETION)}まで") in flats[SHORYOKU_GRANT],
           f"交付決定通知書の実施期間が {jp(S_GRANT)}〜{jp(S_COMPLETION)}")
    report(flat(jp(S_CAND_GRANT)) not in flats[SHORYOKU_GRANT], "遅いほうの候補（交付決定日から14か月）を期限に書いていない")
    report(S_GRANT < S_COMPLETION, "補助事業完了期限日が交付決定日より後")

    print("金額（回答表 H-02・I-03）")
    report(S_SYSTEM == 21_000_000 and S_READER == 600_000 and S_CLOUD == 1_200_000 and S_COST == 20_400_000,
           f"H-02：機械装置・システム構築費 {S_SYSTEM:,}円 − 読み取り端末 {S_READER:,}円 ＝ {S_COST:,}円（クラウドの利用料 {S_CLOUD:,}円も除く）")
    report(flat(f"補助対象経費{S_COST:,}円(税抜)") in flats[SHORYOKU_GRANT], f"省力化の補助対象経費が {S_COST:,}円（税抜）")
    report(flat(f"機械装置・システム構築費　{S_COST:,}円") in flats[SHORYOKU_GRANT], "省力化の経費の区分が機械装置・システム構築費だけ")
    for excluded in (S_SYSTEM, S_SYSTEM + S_CLOUD, S_CLOUD, S_READER, 14_000_000):
        # 13,600,000 の中の 600,000 を拾わないよう、前に数字とカンマがないものだけを探す
        report(re.search(rf"(?<![\d,]){re.escape(f'{excluded:,}')}(?![\d,])", texts[SHORYOKU_GRANT]) is None,f"省力化の交付決定通知書に {excluded:,} が入っていない（除いた経費と前の金額）")
    report(S_AMOUNT == 13_600_000 and flat(f"交付決定額{S_AMOUNT:,}円") in flats[SHORYOKU_GRANT],
           f"省力化の交付決定額 {S_AMOUNT:,}円 ＝ {S_COST:,}円 × 2/3")
    report(S_AMOUNT <= S_PLAN_REQUEST, f"省力化の交付決定額が、デモの計画書の補助申請金額 {S_PLAN_REQUEST:,}円を超えない")
    report(S_AMOUNT <= 15_000_000, "省力化の交付決定額が、従業員6〜20人の補助上限1,500万円の内（設定.md）")
    report(flat(f"補助対象経費{J_COST:,}円(税抜)") in flats[JIZOKU_GRANT], f"持続化の補助対象経費が {J_COST:,}円（税抜）")
    report(J_AMOUNT == 2_000_000 and flat(f"交付決定額{J_AMOUNT:,}円") in flats[JIZOKU_GRANT],
           f"持続化の交付決定額 {J_AMOUNT:,}円 ＝ {J_COST:,}円 × 2/3")
    for name in (SHORYOKU_GRANT, JIZOKU_GRANT):
        report("補助率2/3" in flats[name], f"{name} の補助率が 2/3")
    report("通常枠(賃金引上げ特例)" in flats[JIZOKU_ADOPTION], "持続化の枠が通常枠（賃金引上げ特例）（設定.md）")

    print("事業計画名（回答表 H-01・I-01・I-02）")
    for name in (SHORYOKU_ADOPTION, SHORYOKU_GRANT):
        report("AIによる図面の見積と工程管理の仕組みの導入" in flats[name], f"{name} に事業計画名（H-01 の要約）がある")
    for name in (JIZOKU_ADOPTION, JIZOKU_GRANT):
        report("医療機器・計測機器の業界に向けた加工技術の発信と試作の販路開拓" in flats[name], f"{name} に事業計画名（I-01・I-02 の要約）がある")

    print("差し戻しの文")
    m_sent = re.search(r"送った日：(\d{4})年(\d{1,2})月(\d{1,2})日（(.)）", remand)
    m_due = re.search(r"直した上で、(\d{4})年(\d{1,2})月(\d{1,2})日（(.)）までに", remand)
    report(bool(m_sent and m_due), "送った日と出し直しの期限がある")
    if m_sent and m_due:
        sent = dt.date(*map(int, m_sent.groups()[:3]))
        due = dt.date(*map(int, m_due.groups()[:3]))
        report(WEEKDAYS[sent.weekday()] == m_sent[4] and WEEKDAYS[due.weekday()] == m_due[4], "曜日が日付と合う")
        report(S_APPLY < sent < due <= S_APPLY_DEADLINE < S_GRANT,
               f"交付申請日 {S_APPLY} ＜ 送った日 {sent} ＜ 出し直しの期限 {due} ≦ 交付申請の期限 {S_APPLY_DEADLINE} ＜ 交付決定日 {S_GRANT}")
    report(f"{S_APPLY.year}年{S_APPLY.month}月{S_APPLY.day}日に出していただいた交付申請" in remand, "差し戻しの交付申請日が交付決定通知書と同じ")
    quote = flat("".join(p.extract_text() or "" for p in PdfReader(str(QUOTE_PDF)).pages))
    report("プロジェクトの管理" in quote and re.search(r"プロジェクトの管理1\.25人月", quote) is not None,
           "見積書（かすみ野システム工房）の明細に「プロジェクトの管理」1.25人月がある")
    report("株式会社かすみ野システム工房" in ANSWERS["H-03"] and "株式会社かすみ野システム工房" in remand, "差し戻しの見積の会社が H-03 の頼む会社")
    report("プロジェクトの管理」1.25人月" in remand and "システム構築費の明細" in remand and "積算の根拠" in remand,
           "差し戻しが「プロジェクトの管理」1.25人月・システム構築費の明細・積算の根拠に触れる")
    report("作業の内容" in remand and "工数（人月）の内訳" in remand and "出し直して" in remand, "直し方（作業の内容と工数の内訳の明細で出し直す）を書く")
    report("KSK-2610-0087" not in remand and "2026年10月26日" not in remand, "有効期限の切れた見積（番号・日付）を指していない")

    print("事務局の表示と、入れないもの")
    all_text = "".join(texts.values()) + remand
    for name in PDFS:
        report("（架空）" in texts[name] and "事務局（テスト用）" in texts[name], f"{name} の差出人が架空の表示")
    report(remand.rstrip().endswith("（架空）一般型 事務局（テスト用）"), "差し戻しの差出人が架空の表示")
    for word in ("公印", "職印", "㊞", "印影", "中小企業基盤整備機構", "中小機構", "商工会議所", "全国商工会連合会"):
        report(word not in all_text, f"「{word}」が入っていない")

    print("同じ中身なら同じバイト列（作り直して照らす）")
    sys.path.insert(0, str(HERE))
    import make_saitakugo  # noqa: E402

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        make_saitakugo.build(Path(a))
        make_saitakugo.build(Path(b))
        for name in PDFS + [REMAND]:
            first, second, here = (Path(a) / name).read_bytes(), (Path(b) / name).read_bytes(), (HERE / name).read_bytes()
            report(first == second == here, f"{name}：2回作って同じで、置いてあるファイルとも同じ")

    print("公募要領と照らす（downloads/ があるときだけ）")
    if GUIDELINE_09.exists():
        g = PdfReader(str(GUIDELINE_09))
        page = lambda n: flat(g.pages[n - 1].extract_text() or "")  # noqa: E731（第9回は PDF のページと刷られたページが同じ）
        report("交付決定日から14か月以内(採択発表日から16か月以内)" in page(8), "第9回 p.8 に「交付決定日から14か月以内（採択発表日から16か月以内）」がある")
        report("交付決定日から14か月以内" in page(25) and "採択発表日から16か月後の日まで" in page(25), "第9回 p.25 に実施期間の決まり（14か月・16か月後の日まで）がある")
        report("採択発表日から2か月後の日を期限" in page(25), "第9回 p.25 に交付申請の期限（採択発表日から2か月後の日）がある")
        report("システム構築費の明細" in page(37), "第9回 p.37 に交付申請の書類「システム構築費の明細」がある")
        report("30日を経過した日又は事業完了期限日のいずれか早い日" in page(35), "第9回 p.35 に実績報告の期限の決まりがある")
        official = "".join(flat(p.extract_text() or "") for p in g.pages)
        if GUIDELINE_J20.exists():
            official += "".join(flat(p.extract_text() or "") for p in PdfReader(str(GUIDELINE_J20)).pages)
        grams = {official[i:i + 30] for i in range(len(official) - 29)}
        for name, text in list(flats.items()) + [(REMAND, remand_flat)]:
            hits = [text[i:i + 30] for i in range(len(text) - 29) if text[i:i + 30] in grams]
            report(not hits, f"{name} に公式資料（第9回の要領・要領20）と30字続けて同じ文がない" + (f"（例：{hits[0]}）" if hits else ""))
    else:
        print("  - downloads/ に第9回の要領がないので、飛ばした")

    print()
    if failures:
        print(f"合わないものが {len(failures)} 件あります")
        sys.exit(1)
    print("すべて合いました")


if __name__ == "__main__":
    main()
