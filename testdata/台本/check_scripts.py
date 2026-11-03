# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""台本（TASKS D4）を確かめる。

確かめること：
1. 台本.json・確かめること.json・台本の一覧.md が、make_scripts.py で作り直したものと同じバイト列。どれにも「架空のテスト用データ」がある。
2. 台本の使うテストが、SPEC F14 の台本の行のテスト（T0-9、T11-1、T12-3、T13-6、T13-7、T13-11）と過不足なく同じ。
   どれも SPEC 6章の表で「振る舞い」のテスト。確かめること.json の合格ラインが、SPEC の表の文と同じ。
3. 台本が指す回答表の ID が、回答表にある。
4. 社長の言葉：発言と答えに、Git やコマンドの言葉と、制度の専門用語がない。発言は100字以内。
5. 台本ごとの決まり：
   - T0-9：「計画書の前の版を見せて」「1つ前に戻して」を言う。
   - T11-1：食い違う答えが1つだけ。計画書の値（2人・延べ約14時間）は回答表 H-09 にあり、答えの値（3人・20時間）は H-09 と違う。
   - T12-3：「発注」と「契約」を聞く。業者の名前と届くまでの月数が回答表 H-05・H-07 と合う。発注していないこと（H-06）。
   - T13-6：数字・表現・書き方の方針・構成が1つずつ。数字の指摘は回答表 E-01 の値（3社・14店舗）に直すもので、
     わざと入れた誤り（14社）は回答表にない。表現・方針・構成は、次からも当てはまる言い方（うちでは・どの計画書でも・いつも）。
     避けたい言い方「高齢者向け」は、文体の基準 B・回答表・ほかの架空データ・プラグインのどこにもない。
     どの指摘にも「今回だけ」がない。
   - T13-7：「今回だけ」を含む発言が1つ、どちらとも取れる発言（今回だけ・次から・いつも などの言葉がない）が1つ。
     両方に「次からもそうするか」の答えがある。「今回だけ」で変える言い方（当社）は、文体の基準の言い換えの例にある（ふだんの書き方）。
   - T13-11：記録の手直しは「値」だけを変える。足す文の印（ゼリー食）は、回答表・ほかの架空データ・プラグインのどこにもない。
6. 確かめること.json の「発言」の番が、台本の発言にある。

合わないものがあれば、終了コード1で終わる。

動かし方：uv run --script testdata/台本/check_scripts.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import make_scripts as ms  # noqa: E402

REPO = HERE.parent.parent
ANSWER_SHEET = REPO / "testdata" / "デモの会社" / "回答表.md"
SPEC = REPO / "SPEC.md"
STYLE = REPO / "docs" / "style-criteria.md"

EXPECTED_TESTS = {"T0-9", "T11-1", "T12-3", "T13-6", "T13-7", "T13-11"}
# 社長が知らない言葉（回答表の決まり「専門用語は使いません」「補助金の制度のことは知りません」）
JARGON = ["git", "Git", "コミット", "ブランチ", "リポジトリ", "コマンド", "JSON", "交付決定", "事前着手", "補助対象", "対象経費", "制度データ", "省力化", "持続化"]
# 次からも当てはまると分かる言葉と、一度きりと分かる言葉
GENERAL_WORDS = ["うちでは", "どの計画書でも", "いつも"]
SCOPE_WORDS = ["今回だけ", "次から", "いつも", "これから", "今後", "どの計画書でも", "うちでは", "毎回"]
# 印の言葉を探すときに見るファイルの種類（PDF・Word・Excel は、作るスクリプトの側で見る）
TEXT_SUFFIXES = {".py", ".md", ".json", ".txt", ".html", ".sh", ".yaml", ".yml", ".csv"}
SKIP_DIRS = {".git", "downloads", "vendor", "__pycache__", ".venv", ".pytest_cache", "worktrees"}
MAX_LINE_LEN = 100

results: list[tuple[bool, str]] = []


def check(ok: bool, message: str) -> None:
    results.append((bool(ok), message))


def answer_sheet() -> dict[str, str]:
    """回答表の ID と答え。"""
    rows: dict[str, str] = {}
    for line in ANSWER_SHEET.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| ([A-Z]-\d{2}) \| [^|]+ \| (.+) \|$", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def spec_tests() -> dict[str, tuple[str, str, str]]:
    """SPEC 6章の表のテスト番号 → （種類、方法、合格ライン）。"""
    tests: dict[str, tuple[str, str, str]] = {}
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (T\d+-\d+b?) [^|]*\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", line)
        if m:
            tests[m.group(1)] = (m.group(2).strip(), m.group(3).strip(), m.group(4).strip())
    return tests


def spec_f14_script_tests() -> set[str]:
    """SPEC F14 の材料の表のうち、台本の行（前の版を見る・戻す…）のテスト番号。"""
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| 台本（前の版を見る・戻す"):
            return set(re.findall(r"T\d+-\d+b?", line.split("|")[2]))
    return set()


def style_b_section() -> str:
    text = STYLE.read_text(encoding="utf-8")
    start = text.index("## B.")
    end = text.index("## C.")
    return text[start:end]


def repo_text_files() -> list[Path]:
    """台本のフォルダの外にある、文字のファイル（印の言葉がないかを見る）。"""
    files = []
    for path in REPO.rglob("*"):
        rel = path.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.parts[:2] == ("testdata", "台本"):
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def files_containing(word: str, files: list[Path]) -> list[str]:
    found = []
    for path in files:
        try:
            if word in path.read_text(encoding="utf-8"):
                found.append(str(path.relative_to(REPO)))
        except UnicodeDecodeError:
            continue
    return found


def main() -> int:
    sheet = answer_sheet()
    tests = spec_tests()
    built = ms.build()
    data = json.loads(built[ms.SCRIPTS_FILE])
    checks_data = json.loads(built[ms.CHECKS_FILE])
    scripts = {s["名前"]: s for s in data["台本"]}
    checks = {c["台本"]: c for c in checks_data["確かめること"]}
    other_files = repo_text_files()

    # 1. 作り直したものと同じ。架空の印
    for path, text in built.items():
        check(path.exists() and path.read_text(encoding="utf-8") == text, f"{path.name} が make_scripts.py で作り直したものと同じ")
        check(ms.MARK in text, f"{path.name} に「{ms.MARK}」がある")
    check(len(scripts) == len(data["台本"]), "台本の名前が重ならない")
    check(set(scripts) == set(checks), "どの台本にも確かめることがあり、確かめることはどれも台本に当たる")

    # 2. SPEC のテストと照らす
    used = [t for s in data["台本"] for t in s["使うテスト"]]
    f14 = spec_f14_script_tests()
    check(f14 == EXPECTED_TESTS, f"SPEC F14 の台本の行のテストが {sorted(EXPECTED_TESTS)}（読めたもの：{sorted(f14)}）")
    check(sorted(used) == sorted(f14), f"台本の使うテストが、SPEC F14 の台本の行と過不足なく同じ（{sorted(used)}）")
    for test in used:
        check(test in tests and tests[test][0] == "振る舞い", f"{test} は SPEC 6章の表にある振る舞いのテスト")
    for name, c in checks.items():
        test = c["テスト"]
        check(test in scripts.get(name, {}).get("使うテスト", []), f"確かめること（{name}）のテスト {test} が、台本の使うテストにある")
        check(test in tests and c["SPEC の合格ライン"] == tests[test][2], f"確かめること（{name}）の合格ラインが SPEC の {test} の文と同じ")

    # 3. 回答表の ID
    for s in data["台本"]:
        ids = [i for line in s["発言"] for i in line["回答表"]] + [i for a in s["聞かれたときの答え"] for i in a["回答表"]]
        missing = [i for i in ids if i not in sheet]
        check(not missing, f"{s['名前']}：指している回答表の ID がすべて回答表にある（ないもの：{missing}）")

    # 4. 社長の言葉
    for s in data["台本"]:
        spoken = [line["発言"] for line in s["発言"]] + [a["答え"] for a in s["聞かれたときの答え"]]
        for text in spoken:
            bad = [w for w in JARGON if w in text]
            check(not bad, f"{s['名前']}：「{text[:20]}…」に、社長が知らない言葉がない（{bad}）")
        for line in s["発言"]:
            check(len(line["発言"]) <= MAX_LINE_LEN, f"{s['名前']} 発言{line['番']}：{MAX_LINE_LEN}字以内（{len(line['発言'])}字）")
        numbers = [line["番"] for line in s["発言"]]
        check(numbers == list(range(1, len(numbers) + 1)), f"{s['名前']}：発言の番が1から順に並ぶ")
        check(s["発言"][0]["いつ言うか"].startswith(ms.FIRST), f"{s['名前']}：発言1は最初の発言")

    # 5. 台本ごとの決まり
    # T0-9
    s = scripts["前の版を見る・戻す"]
    spoken = "".join(line["発言"] for line in s["発言"])
    for phrase in ("計画書の前の版を見せて", "1つ前に戻して"):
        check(phrase in spoken, f"T0-9：「{phrase}」を言う（SPEC T0-9 の方法）")
    check("見るだけ/" in "".join(s["状態に入れておくこと"]), "T0-9：始める状態で `見るだけ/` を空にしておく")

    # T11-1
    s = scripts["食い違う答え"]
    c = checks["食い違う答え"]
    conflicts = [line for line in s["発言"] if line.get("区分") == "食い違う答え"]
    check(len(conflicts) == 1, f"T11-1：食い違う答えが1つだけ（{len(conflicts)}）")
    h09 = sheet.get("H-09", "")
    plan_numbers = re.findall(r"\d+人|約?\d+時間", c["計画書の値"])
    answer_numbers = re.findall(r"\d+人|\d+時間", c["答えの値"])
    check(plan_numbers and all(n in h09 for n in ("2人", "約14時間")), f"T11-1：計画書の値（{c['計画書の値']}）が回答表 H-09 にある")
    if conflicts:
        line = conflicts[0]
        check("H-09" in line["回答表"], "T11-1：食い違う答えが回答表 H-09 を指す")
        for n in answer_numbers:
            check(n in line["発言"], f"T11-1：答えの値の「{n}」を発言で言う")
        check(not any(n in h09 for n in ("3人", "20時間")), "T11-1：答えの値（3人・20時間）は回答表 H-09 と違う")
        check(line["いつ言うか"] not in (ms.FIRST, ms.AFTER), "T11-1：食い違う答えに、言うときの条件が書いてある")
    check(any("H-09" in a["回答表"] and "14時間" in a["答え"] for a in s["聞かれたときの答え"]), "T11-1：どちらが正しいか聞かれたら、回答表 H-09 の値に戻す答えがある")

    # T12-3
    s = scripts["交付決定前の発注の相談"]
    spoken = "".join(line["発言"] for line in s["発言"])
    for phrase in ("発注", "契約"):
        check(phrase in spoken, f"T12-3：「{phrase}」を聞く")
    vendor = re.search(r"株式会社(\S+?)（", sheet.get("H-03", ""))
    check("つばさ台フードシステム" in sheet.get("H-05", "") and "つばさ台フードシステム" in spoken, "T12-3：頼む業者が回答表 H-05 と同じ")
    check(vendor is not None, "T12-3：回答表 H-03 から業者の名前が読める")
    months = re.search(r"約(\d+)か月", sheet.get("H-07", ""))
    check(months is not None and f"{months.group(1)}か月" in spoken, "T12-3：届くまでの月数が回答表 H-07 と同じ")
    check("していない" in sheet.get("H-06", ""), "T12-3：回答表 H-06 で、まだ発注していない")

    # T13-6
    s = scripts["4種類の指摘"]
    c = checks["4種類の指摘"]
    kinds = [line.get("区分") for line in s["発言"]]
    check(sorted(kinds) == sorted(["数字", "表現", "書き方の方針", "構成"]), f"T13-6：数字・表現・書き方の方針・構成が1つずつ（{kinds}）")
    by_kind = {line.get("区分"): line for line in s["発言"]}
    e01 = sheet.get("E-01", "")
    number_line = by_kind.get("数字", {}).get("発言", "")
    check("3社" in e01 and "14店舗" in e01, "T13-6：回答表 E-01 で、スーパーは3社・14店舗")
    check("3社" in number_line and "14" in number_line, "T13-6：数字の指摘は、回答表 E-01 の値（3社、14は店の数）に直す")
    check("14社" not in e01 and "14社" in "".join(s["状態に入れておくこと"]), "T13-6：わざと入れた誤り（14社）は回答表になく、始める状態に書いてある")
    for kind, word in zip(("表現", "書き方の方針", "構成"), GENERAL_WORDS):
        check(word in by_kind.get(kind, {}).get("発言", ""), f"T13-6：{kind}の指摘は、次からも当てはまると分かる言い方（「{word}」）")
    for line in s["発言"]:
        check("今回だけ" not in line["発言"], f"T13-6：発言{line['番']}に「今回だけ」がない")
    avoid = "高齢者向け"
    check(avoid in by_kind.get("表現", {}).get("発言", ""), f"T13-6：表現の指摘で「{avoid}」を避けたい言い方にする")
    check(avoid not in style_b_section(), f"T13-6：「{avoid}」は文体の基準 B にない（あるとコードの確かめで見つかり、学んだかを見分けられない）")
    found = files_containing("高齢者", other_files)
    check(not found, f"T13-6：「高齢者」は回答表・ほかの架空データ・プラグインのどこにもない（あったもの：{found}）")
    allergy_ids = [i for i in by_kind.get("書き方の方針", {}).get("回答表", []) if "アレルギー" in sheet.get(i, "")]
    check(allergy_ids, "T13-6：方針の指摘（アレルギーの表示）が、回答表のアレルギーの行を指す")
    check(all(any(k in i["出ない文字"] or k in i["出る文字"] for i in c["見ること"]) for k in ("14社", avoid, "アレルギー")), "T13-6：確かめることに、14社・高齢者向け・アレルギーの文字がある")

    # T13-7
    s = scripts["「今回だけ」の指示とどちらとも取れる指示"]
    once = [line for line in s["発言"] if "今回だけ" in line["発言"]]
    ambiguous = [line for line in s["発言"] if line.get("区分") == "どちらとも取れる"]
    check(len(once) == 1 and once[0].get("区分") == "今回だけ", f"T13-7：「今回だけ」を含む発言が1つ（{len(once)}）")
    check(len(ambiguous) == 1, f"T13-7：どちらとも取れる発言が1つ（{len(ambiguous)}）")
    if ambiguous:
        words = [w for w in SCOPE_WORDS if w in ambiguous[0]["発言"]]
        check(not words, f"T13-7：どちらとも取れる発言に、今回だけ・次からなどの言葉がない（{words}）")
    answers = [a["聞かれたこと"] for a in s["聞かれたときの答え"]]
    for line in s["発言"]:
        check(any(f"発言{line['番']}" in q and "次から" in q for q in answers), f"T13-7：発言{line['番']}に「次からもそうするか」の答えがある")
    check("当社" in once[0]["発言"] if once else False, "T13-7：「今回だけ」の指示は「当社」の書き方を変えるもの")
    check("当社" in style_b_section(), "T13-7：「当社」は文体の基準の言い換えの例にある（ふだんの書き方なので、2件目で見分けられる）")

    # T13-11
    s = scripts["記録の手直し"]
    c = checks["記録の手直し"]
    edit = s.get("記録の手直し", {})
    check(edit.get("ファイル") == "記録/会社の記録.json" and edit.get("直す欄") == "値", "T13-11：手直しは会社の記録の「値」だけを変える")
    marker = c.get("手直しの印", "")
    check(marker and marker in edit.get("足す文", ""), f"T13-11：足す文に印（{marker}）がある")
    found = files_containing("ゼリー", other_files)
    check(not found, f"T13-11：「ゼリー」は回答表・ほかの架空データ・プラグインのどこにもない（あったもの：{found}）")
    check("E-03" in edit.get("直す項目", "") and "E-03" in sheet, "T13-11：直す項目が回答表 E-03 の強みに当たる")
    edit_words = ["記録", "覚えて", "手直し", "直しておき", "直しました"]
    check(not any(w in line["発言"] for w in edit_words for line in s["発言"]), "T13-11：書かせる発言では、手直しに触れない")

    # 6. 確かめることの発言の番
    for name, c in checks.items():
        numbers = {line["番"] for line in scripts[name]["発言"]}
        for item in c["見ること"]:
            check(set(item["発言"]) <= numbers, f"確かめること（{name}）の発言の番 {item['発言']} が台本にある")

    ok = sum(1 for passed, _ in results if passed)
    ng = [message for passed, message in results if not passed]
    for message in ng:
        print(f"× {message}")
    print(f"○{ok}件、×{len(ng)}件")
    return 0 if not ng else 1


if __name__ == "__main__":
    sys.exit(main())
