# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""制度データと資料の材料（TASKS D10）を作る。

使うテスト：T3-8（出典の裏取り）、T4-2（引用の照合）、T7-1（改訂と新しい回）。
どれも、省力化 第8回の公募要領（要領8）と応募申請の手引き（応募手引8）から作ります（evals/状態/ と、
testdata/正解/省力化_第8回.json と同じ回）。

公募要領の文は、リポに入れません（SPEC 5.4、DESIGN 11章・14章）。そのため、材料を2つに分けます。
- リポに入れるもの（このスクリプトが書く）：混ぜ方と正解。値・ページ・場所と、行を探すための短い語（値や見出しの語）だけ。
  わざと作った架空の文（どの資料にもない文）は、公式の文の写しではないので入れます。
  1. 混ぜたものの一覧.json：T3-8 と T4-2 の正解（何を、どう混ぜたか）。
  2. 新旧2版の正解.json：T7-1 の正解（書き換えた箇所と、影響する制度データの項目・自社の項目）。
  3. 材料の一覧.md：上の2つを人が読む形にしたもの。
- テストのときに作るもの（`--build <場所>`。downloads/ が要る）：根拠の文と引用は、downloads/ の PDF の文字から、
  決めたページの決めた語を含む行を切り出して入れます。新旧2版は、要領8 の文字（ページごとの文字。lib/doc_text.py の形）を
  写し、決めた箇所を決めた形に書き換えて作ります（pypdf では PDF の文字を書き換えられないため、文字の段で作る）。

`--build <場所>` で作るもの（<場所> は tmp_path など、リポの外にする）：
- `T3-8/会社/記録/資料の本文/<案件>/要領8/` と `応募手引8/`：資料の本文（lib/doc_text.py の形）と `資料の一覧.json`。
- `T3-8/読み取り_1回目.json`・`T3-8/読み取り_2回目.json`：読み取り役が返す形（lib/urakadori.py の CHAPTER_FORM）の、
  同じ章の2回の読み取り。lib/urakadori.run(<場所>/T3-8/会社, CASE, その中身) に渡せる。
- `T4-2/答え.json`：引用つきの答え6件（3件はそのページにない引用）。`T4-2/会社/` は T3-8 と同じ資料の本文。
- `T7-1/変更あり/会社/記録/資料の本文/<案件>/` に、前の版（要領8）と後の版（要領8_書き換え）の本文と、
  後の版を「資料」、前の版を「前の回の資料」に置いた `資料の一覧.json`（lib/kaitei.py の doc_pairs が対にする形）。
- `T7-1/変更なし/会社/...`：同じ形で、後の版が前の版と同じ文字のもの（「変更なし」の組）。

同じ中身なら、何度作っても同じバイト列になります（リポに入れる3つのファイル）。

動かし方：
  uv run --script testdata/制度データ/make_materials.py            # 正解と一覧を書く（downloads/ は要らない）
  uv run --script testdata/制度データ/make_materials.py --build DIR  # テストの材料を DIR に作る（downloads/ が要る）
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import unicodedata
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
MIXED_FILE = HERE / "混ぜたものの一覧.json"
VERSIONS_FILE = HERE / "新旧2版の正解.json"
LIST_FILE = HERE / "材料の一覧.md"

MARK = "架空のテスト用データ"
MADE_BY = "TASKS D10（2026-11-05）"
CASE = "省力化（一般型）第8回"
CHAPTER = "1-4 補助対象事業と公募期間"
NO_COPY = "（正解では資料の文を写さない。DESIGN 14章）"

DOWNLOADS = REPO / "downloads" / "shoryokuka_ippan"
DOCS = {
    "要領8": {"ファイル": "application_guidelines_ippan_08.pdf", "名前": "公募要領", "公募回": "第8回",
              "版": "2026年8月（2026年9月18日改訂）",
              "URL": "https://shoryokuka.smrj.go.jp/assets/pdf/application_guidelines_ippan_08.pdf"},
    "応募手引8": {"ファイル": "oubo_manual_ippan_08.pdf", "名前": "応募申請の手引き", "公募回": "第8回",
                 "URL": "https://shoryokuka.smrj.go.jp/assets/pdf/oubo_manual_ippan_08.pdf"},
}
SEIDO = {"名前": "中小企業省力化投資補助金", "枠": "一般型", "種類": "補助金", "公募回": "第8回", "略称": "省力化"}

# 混ぜ方の種類（SPEC T3-8 の3つ）
WRONG_VALUE = "出典のページと違う値"
OTHER_PAGE = "そのページにない根拠の文"
TWO_READINGS = "2回の読み取りで食い違う重要な項目"
CONTROL = "混ぜていない（確認済みのまま残る）"


def src(doc: str, page: int) -> Dict:
    return {"資料": doc, "ページ": page}


# ---- T3-8：同じ章の2回の読み取り ----
# 値ごとに、場所、2回の値、出典、根拠の文の探し方を決める。
# 根拠の文の探し方：「探す語」をすべて含む、出典のページの最初の行（テストのときに downloads/ の文字から切り出す）。
#   「根拠の文を取るページ」があれば、そのページから切り出す（出典のページにない文になる）。
#   「架空の文」があれば、それをそのまま根拠の文にする（どの資料にもない文。わざと作った）。
# 1回目と2回目で、根拠の文の探し方が同じなら書かない（2回目は、混ぜていない根拠の文）。
RATE_LINE = ["中小企業", "1/2"]
T3_8_VALUES: List[Dict] = [
    {"場所": ["補助額", 0, "上限"], "区分": "従業員5人以下", "1回目": 7500000, "2回目": 7500000,
     "出典": [src("要領8", 9)], "探す語": ["5人以下", "750万円"], "混ぜ方": CONTROL},
    {"場所": ["補助額", 0, "補助率"], "区分": "従業員5人以下", "1回目": "1/2", "2回目": "1/2",
     "出典": [src("要領8", 9)], "探す語": RATE_LINE, "混ぜ方": CONTROL},
    {"場所": ["補助額", 1, "上限"], "区分": "従業員6〜20人", "1回目": 15000000, "2回目": 20000000,
     "出典": [src("要領8", 9)], "探す語": ["6~20人", "1,500万円"], "混ぜ方": TWO_READINGS,
     "説明": "2回目は、同じ行のカッコ内（特例の上限）を読んだ。どちらの値も根拠の文にあるので、ページの裏取りは通る"},
    {"場所": ["補助額", 1, "補助率"], "区分": "従業員6〜20人", "1回目": "1/2", "2回目": "1/2",
     "出典": [src("要領8", 9)], "探す語": RATE_LINE, "混ぜ方": CONTROL},
    {"場所": ["補助額", 2, "上限"], "区分": "従業員21〜50人", "1回目": 36000000, "2回目": 30000000,
     "出典": [src("要領8", 9)], "探す語": ["21~50人", "3,000万円"], "混ぜ方": WRONG_VALUE,
     "説明": "1回目の値（3,600万円）は、根拠の文（3,000万円の行）にない"},
    {"場所": ["補助額", 2, "補助率"], "区分": "従業員21〜50人", "1回目": "1/3", "2回目": "1/2",
     "出典": [src("要領8", 9)], "探す語": RATE_LINE, "混ぜ方": WRONG_VALUE,
     "説明": "1回目の値（1/3）は、根拠の文（1/2 と 2/3 の行）にない"},
    {"場所": ["補助額", 3, "上限"], "区分": "従業員51〜100人", "1回目": 50000000, "2回目": 50000000,
     "出典": [src("要領8", 9)], "探す語": ["51~100人", "5,000万円"], "混ぜ方": OTHER_PAGE,
     "1回目の根拠の文を取るページ": src("要領8", 15), "1回目の探す語": ["小売業", "5,000万円", "50人"],
     "説明": "1回目の根拠の文は、要領8 p.15（中小企業の定義の表）の行。値（5,000万円）は文にあるが、出典の p.9 にない"},
    {"場所": ["補助額", 3, "補助率"], "区分": "従業員51〜100人", "1回目": "1/2", "2回目": "1/2",
     "出典": [src("要領8", 9)], "探す語": RATE_LINE, "混ぜ方": OTHER_PAGE,
     "1回目の架空の文": "従業員51人から100人までの事業者の補助率は1/2とする",
     "説明": "1回目の根拠の文は、わざと作った架空の文（どの資料にもない）"},
    {"場所": ["補助額", 4, "上限"], "区分": "従業員101人以上", "1回目": 80000000, "2回目": 80000000,
     "出典": [src("要領8", 9)], "探す語": ["101人以上", "8,000万円"], "混ぜ方": CONTROL},
    {"場所": ["補助額", 4, "補助率"], "区分": "従業員101人以上", "1回目": "1/2", "2回目": "2/3",
     "出典": [src("要領8", 9)], "探す語": RATE_LINE, "混ぜ方": TWO_READINGS,
     "説明": "2回目は、同じ行のカッコ内（特例の補助率）を読んだ。どちらの値も根拠の文にある"},
    {"場所": ["決まった期日", 0, "日時"], "名前": "公募開始", "1回目": {"日時": "2026-08-18"}, "2回目": {"日時": "2026-08-18"},
     "出典": [src("応募手引8", 7)], "探す語": ["第8回", "8月18日"], "混ぜ方": CONTROL},
    {"場所": ["決まった期日", 1, "日時"], "名前": "申請受付開始", "1回目": {"日時": "2026-09-19"}, "2回目": {"日時": "2026-09-18"},
     "出典": [src("応募手引8", 7)], "探す語": ["申請受付開始", "9月18日"], "混ぜ方": WRONG_VALUE,
     "説明": "1回目の日付（9月19日）は、根拠の文（9月18日の行）にない"},
    {"場所": ["決まった期日", 2, "日時"], "名前": "締切",
     "1回目": {"日時": "2026-10-16T17:00+09:00"}, "2回目": {"日時": "2026-08-18T17:00+09:00"},
     "出典": [src("応募手引8", 7)], "探す語": ["第8回", "10月16日"], "混ぜ方": TWO_READINGS,
     "説明": "2回目は、同じ行の公募の始まりの日（8月18日）を締切と読んだ。月日と時刻は根拠の文にあるので、ページの裏取りは通る"},
]

# ---- T4-2：引用つきの答え ----
# 答えの形は DESIGN 9.2（結論 → 根拠（資料名・ページ・どの回の資料かと、短い引用）→ 注意）。引用は「」で囲み、資料名とページを添える。
# 「{引用}」の所に、テストのときに切り出した行（か架空の文）が入る。
ANSWERS: List[Dict] = [
    {"番": 1, "質問": "従業員が15人だと、補助の上限はいくらですか",
     "答え": "1,500万円です。根拠：公募要領（第8回）p.9「{引用}」。注意：特例に当たると上限が上がります。",
     "引用": {"資料": "要領8", "ページ": 9, "探す語": ["6~20人", "1,500万円"]}, "混ぜた": False},
    {"番": 2, "質問": "事業場内最低賃金の要件は何ですか",
     "答え": "地域別最低賃金より30円以上高くする必要があります。根拠：公募要領（第8回）p.11「{引用}」。注意：特例の事業者には当たりません。",
     "引用": {"資料": "要領8", "ページ": 11, "探す語": ["③", "+30円"]}, "混ぜた": False},
    {"番": 3, "質問": "申請の締切はいつですか",
     "答え": "2026年10月16日（金）17:00です。根拠：応募申請の手引き（第8回）p.7「{引用}」。注意：締切の後は受け付けられません。",
     "引用": {"資料": "応募手引8", "ページ": 7, "探す語": ["第8回", "10月16日"]}, "混ぜた": False},
    {"番": 4, "質問": "補助率はいくらですか",
     "答え": "中小企業は1/2です。根拠：公募要領（第8回）p.10「{引用}」。注意：小規模企業者は2/3です。",
     "引用": {"資料": "要領8", "ページ": 10, "取るページ": 9, "探す語": RATE_LINE}, "混ぜた": True,
     "混ぜ方": "引用は p.9 の行で、示したページ（p.10）にない"},
    {"番": 5, "質問": "中古の機械も補助の対象になりますか",
     "答え": "なります。根拠：公募要領（第8回）p.23「{引用}」。注意：保証書を残してください。",
     "引用": {"資料": "要領8", "ページ": 23, "架空の文": "中古品であっても、販売店の保証があるものは補助の対象とする"}, "混ぜた": True,
     "混ぜ方": "引用は、わざと作った架空の文（どの資料にもない。中身も資料と違う）"},
    {"番": 6, "質問": "うちは従業員15人です。補助の上限を教えてください",
     "答え": "1,800万円です。根拠：公募要領（第8回）p.9「{引用}」。",
     "引用": {"資料": "要領8", "ページ": 9, "探す語": ["6~20人", "1,500万円"], "書き換え": ["1,500", "1,800"]}, "混ぜた": True,
     "混ぜ方": "引用は p.9 の行の数字を書き換えたもの（1,500 → 1,800）。そのページにない"},
]

# ---- T7-1：公募要領の新旧2版 ----
# 前の版は要領8 の文字。後の版は、決めたページの決めた語を含む行で、「前」を「後」に書き換えたもの。
NEW_ID = "要領8_書き換え"
REWRITES: List[Dict] = [
    {"番": 1, "ページ": 9, "探す語": ["6~20人", "1,500万円"], "前": "1,500 万円", "後": "1,800 万円",
     "変わったこと": "補助上限額（従業員6〜20人）が1,500万円から1,800万円になる",
     "制度データの項目": ["補助額「従業員6〜20人」の上限"],
     "自社の項目": ["回答表 C-01（従業員15人で、6〜20人の区分）", "回答表 H-02（投資額22,500千円。補助額の見込み）"]},
    {"番": 2, "ページ": 9, "探す語": ["再生事業者", "2/3"], "前": "2/3", "後": "3/4",
     "変わったこと": "小規模企業者・小規模事業者と再生事業者の補助率が2/3から3/4になる",
     "制度データの項目": ["補助額の特例「小規模企業者・小規模事業者」の値"],
     "自社の項目": ["回答表 C-01（製造業で20人以下なので小規模企業者）", "回答表 H-02（補助額の見込み：22,500千円 × 3/4 ＝ 16,875千円。上限1,800万円の内）"]},
    {"番": 3, "ページ": 11, "探す語": ["③", "+30円"], "前": "+30 円", "後": "+60 円",
     "変わったこと": "事業場内最低賃金の要件が、地域別最低賃金+30円以上から+60円以上になる",
     "制度データの項目": ["数値の要件「事業場内最低賃金」の基準"],
     "自社の項目": ["回答表 D-01（いちばん低い時給1,330円）", "回答表 B-01（所在地の地域別最低賃金）", "回答表 D-08（これからの賃上げ）"]},
    {"番": 4, "ページ": 11, "探す語": ["+30円", "とすることが必要"], "前": "+30 円", "後": "+60 円",
     "変わったこと": "同じ要件の説明の文（3 と同じ変更）",
     "制度データの項目": ["数値の要件「事業場内最低賃金」の基準"],
     "自社の項目": ["回答表 D-01"]},
]


# ---- 文字の形 ----


def norm(text: str) -> str:
    """比べるための形。NFKC、波線を1つに、空白と改行を除く（lib/urakadori.py の normalize に近い形）。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({c: "~" for c in "〜～∼"}))
    return re.sub(r"\s+", "", text)


class BuildError(RuntimeError):
    """downloads/ の文字から、決めた行が見つからない（資料が変わったか、取り出し方が変わった）。"""


def find_line(page_text: str, words: List[str], where: str) -> str:
    for line in page_text.splitlines():
        if all(norm(w) in norm(line) for w in words):
            return line.strip()
    raise BuildError(f"{where} に、語 {words} を含む行がない")


# ---- リポに入れる正解 ----


def place_label(v: Dict) -> str:
    """lib/urakadori.py の readable と同じ書き方（例：補助額「従業員6〜20人」の上限）。"""
    top, _i, leaf = v["場所"]
    name = v.get("区分") or v.get("名前")
    return f"{top}「{name}」の{leaf}"


def mixed_answer() -> Dict:
    values = []
    for v in T3_8_VALUES:
        entry = {"場所": place_label(v), "混ぜ方": v["混ぜ方"], "1回目の値": v["1回目"], "2回目の値": v["2回目"],
                 "出典": v["出典"]}
        for key in ("説明", "1回目の根拠の文を取るページ", "1回目の架空の文"):
            if key in v:
                entry[key] = v[key]
        values.append(entry)
    return {
        "印": MARK,
        "作ったタスク": MADE_BY,
        "説明": "T3-8 と T4-2 の材料で、何をどう混ぜたかの一覧（正解）。根拠の文と引用は、テストのときに downloads/ から作る（make_materials.py --build）",
        "案件": CASE,
        "T3-8": {
            "合格ライン": "混ぜたものをすべて「要確認」にする",
            "章": CHAPTER,
            "読み取り": ["T3-8/読み取り_1回目.json", "T3-8/読み取り_2回目.json"],
            "値": values,
            "要確認になるべき場所": sorted({place_label(v) for v in T3_8_VALUES if v["混ぜ方"] != CONTROL}),
            "確認済みのまま残るべき場所": sorted({place_label(v) for v in T3_8_VALUES if v["混ぜ方"] == CONTROL}),
            "注記": "出典のページと違う値・そのページにない根拠の文は、1回目の読み取りをページで裏取りすると見つかる（lib/urakadori.py）。"
                    "2回の読み取りで食い違う重要な項目は、どちらの読み取りもページの裏取りを通るので、1回目と2回目を比べないと見つからない（B25 で足す）。"
                    "出典のページと違う値の項目は、2回目の値が正しいので、2回の比べでも食い違う",
        },
        "T4-2": {
            "合格ライン": "混ぜたものをすべて見つける",
            "答え": "T4-2/答え.json",
            "混ぜた答え": [a["番"] for a in ANSWERS if a["混ぜた"]],
            "混ぜていない答え": [a["番"] for a in ANSWERS if not a["混ぜた"]],
            "混ぜ方": {str(a["番"]): a["混ぜ方"] for a in ANSWERS if a["混ぜた"]},
            "示したページ": {str(a["番"]): {"資料": a["引用"]["資料"], "ページ": a["引用"]["ページ"]} for a in ANSWERS},
        },
    }


def versions_answer() -> Dict:
    return {
        "印": MARK,
        "作ったタスク": MADE_BY,
        "説明": "T7-1 の公募要領の新旧2版で、書き換えた箇所の一覧（正解）。新旧2版そのものは、テストのときに downloads/ から作る（make_materials.py --build）",
        "合格ライン": "変わった点と影響する自社の項目を挙げ、制度データが新しい版になる。変更がなければ「変更なし」",
        "前の版": {"資料": "要領8", **{k: DOCS["要領8"][k] for k in ("名前", "公募回", "版", "URL")}},
        "後の版": {"資料": NEW_ID, "名前": DOCS["要領8"]["名前"], "公募回": "第8回", "版": "テスト用に書き換えた版（架空）"},
        "変更あり": {
            "場所": "T7-1/変更あり/会社",
            "書き換え": [{k: r[k] for k in ("番", "ページ", "前", "後", "変わったこと", "制度データの項目", "自社の項目")} for r in REWRITES],
            "変わったページ": sorted({r["ページ"] for r in REWRITES}),
        },
        "変更なし": {
            "場所": "T7-1/変更なし/会社",
            "書き換え": [],
            "変わったページ": [],
            "期待する答え": "変更なし",
        },
        "B28 への申し送り": [
            "後の版は PDF ではなく、資料の本文（ページごとの文字）だけで作る。PDF から文字を作り直す道（lib/official_docs.py の fetch_one → make_text）を通すと、"
            "後の版が前の版の文字で上書きされるので、eval の scaffold は資料の本文と資料の一覧.json を置き、公式サイトを確かめる道は記録した応答か、通信なしの扱いにする（B28 で決める）",
            "lib/kaitei.py の doc_pairs は、資料の一覧.json の「前の回の資料」と「資料」を名前で対にする。同じ回の改訂でも、前の版を「前の回の資料」に置けば対になる",
            "後の版のハッシュは、書き換えた後の文字から作った架空の値（前の版と違う）。変更なしの組は、前の版と同じハッシュ",
        ],
    }


def list_text(mixed: Dict, versions: Dict) -> str:
    lines = [
        "# 制度データと資料の材料の一覧（架空）",
        "",
        f"T3-8・T4-2・T7-1 の材料です（SPEC F14、{MADE_BY}）。{MARK}です。",
        "",
        "- このファイルは `make_materials.py` が作ります。手で直さず、`make_materials.py` を直して作り直してください。",
        "- 公募要領の文は、リポに入れていません。根拠の文・引用・新旧2版は、テストのときに downloads/ から作ります"
        "（`make_materials.py --build <場所>`。DESIGN 11章）。リポにあるのは、値・ページ・場所と、行を探すための短い語と、わざと作った架空の文だけです。",
        "- 使う資料：省力化 第8回の公募要領（要領8）と応募申請の手引き（応募手引8）。evals/状態/ と testdata/正解/省力化_第8回.json と同じ回です。",
        "",
        "## ファイル",
        "",
        "| ファイル | 中身 | 使うテスト |",
        "|---|---|---|",
        "| 混ぜたものの一覧.json | T3-8 の値ごとの混ぜ方と、T4-2 の答えごとの混ぜ方（正解） | T3-8、T4-2 |",
        "| 新旧2版の正解.json | T7-1 の書き換えた箇所と、影響する制度データの項目・自社の項目（正解） | T7-1 |",
        "| make_materials.py | 中身の正本。正解を書き、`--build` でテストの材料を作る | — |",
        "| check_materials.py | 材料を作って、今の道具（lib/urakadori.py、lib/kaitei.py）で照らし、混ぜたものの一覧と変わった箇所を出す | — |",
        "",
        "## 作り方と確かめ方",
        "",
        "```bash",
        "uv run --script testdata/制度データ/make_materials.py",
        "uv run --script testdata/制度データ/check_materials.py",
        "```",
        "",
        "- `check_materials.py` は、downloads/ がなければ、材料を作る確かめを飛ばします。合わないものがあれば終了コード1で終わります。",
        "",
        "## T3-8：出典の裏取り（同じ章の2回の読み取り）",
        "",
        f"章「{CHAPTER}」を2回読んだ結果です。合格ライン：{mixed['T3-8']['合格ライン']}。",
        "",
        "| 場所 | 混ぜ方 | 1回目の値 | 2回目の値 | 出典 | 説明 |",
        "|---|---|---|---|---|---|",
    ]

    def show(x: Any) -> str:
        return json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x)

    for v in mixed["T3-8"]["値"]:
        where = "、".join(f"{s['資料']} p.{s['ページ']}" for s in v["出典"])
        lines.append(f"| {v['場所']} | {v['混ぜ方']} | {show(v['1回目の値'])} | {show(v['2回目の値'])} | {where} | {v.get('説明', '')} |")
    lines += [
        "",
        f"- 要確認になるべき場所：{len(mixed['T3-8']['要確認になるべき場所'])}（{'、'.join(mixed['T3-8']['要確認になるべき場所'])}）",
        f"- 確認済みのまま残るべき場所：{len(mixed['T3-8']['確認済みのまま残るべき場所'])}",
        f"- {mixed['T3-8']['注記']}",
        "",
        "## T4-2：引用の照合",
        "",
        f"合格ライン：{mixed['T4-2']['合格ライン']}。",
        "",
        "| 番 | 質問 | 示したページ | 混ぜたか | 混ぜ方 |",
        "|---|---|---|---|---|",
    ]
    for a in ANSWERS:
        lines.append(f"| {a['番']} | {a['質問']} | {a['引用']['資料']} p.{a['引用']['ページ']} | {'混ぜた' if a['混ぜた'] else '—'} | {a.get('混ぜ方', '')} |")
    lines += [
        "",
        "## T7-1：公募要領の新旧2版",
        "",
        f"合格ライン：{versions['合格ライン']}。前の版は要領8、後の版は要領8 の文字を書き換えた架空の版（{NEW_ID}）です。",
        "",
        "| 番 | ページ | 前 → 後 | 変わったこと | 制度データの項目 | 自社の項目 |",
        "|---|---|---|---|---|---|",
    ]
    for r in versions["変更あり"]["書き換え"]:
        lines.append(f"| {r['番']} | {r['ページ']} | {r['前']} → {r['後']} | {r['変わったこと']} | {'、'.join(r['制度データの項目'])} | {'、'.join(r['自社の項目'])} |")
    lines += [
        "",
        "- 変更なしの組：後の版を前の版と同じ文字にしたもの。期待する答えは「変更なし」。",
        "",
        "### B28 への申し送り",
        "",
    ]
    lines += [f"- {s}" for s in versions["B28 への申し送り"]]
    lines.append("")
    return "\n".join(lines)


def answers() -> Dict[Path, str]:
    mixed = mixed_answer()
    versions = versions_answer()
    return {
        MIXED_FILE: json.dumps(mixed, ensure_ascii=False, indent=2) + "\n",
        VERSIONS_FILE: json.dumps(versions, ensure_ascii=False, indent=2) + "\n",
        LIST_FILE: list_text(mixed, versions),
    }


# ---- テストのときに作る材料 ----


def _doc_text():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from lib import doc_text  # 同梱の pypdf で文字にする

    return doc_text


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def have_downloads(downloads: Path = DOWNLOADS) -> bool:
    return all((downloads / d["ファイル"]).is_file() for d in DOCS.values())


def _text_root(company: Path) -> Path:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from lib import case_folder

    return company / "記録" / "資料の本文" / case_folder.safe_name(CASE)


def _list_entry(doc_id: str, info: Dict, sha: str) -> Dict:
    entry = {"id": doc_id, "名前": info["名前"], "公募回": info["公募回"]}
    if info.get("版"):
        entry["版"] = info["版"]
    entry["URL"] = info.get("URL", "")
    entry["取得日"] = "2026-11-03"
    entry["ハッシュ"] = sha
    entry["ページのずれ"] = 0
    return entry


def write_texts(company: Path, downloads: Path = DOWNLOADS) -> Dict[str, Path]:
    """要領8 と応募手引8 の資料の本文と、資料の一覧.json を company に置く。"""
    doc_text = _doc_text()
    root = _text_root(company)
    out = {}
    entries = []
    for doc_id, info in DOCS.items():
        pdf = downloads / info["ファイル"]
        sha = _sha(pdf)
        doc = {"id": doc_id, "名前": info["名前"], "公募回": info["公募回"], "ハッシュ": sha}
        doc_text.write_text(pdf, root / doc_id, doc, f"公式資料/{info['ファイル']}")
        out[doc_id] = root / doc_id
        entries.append(_list_entry(doc_id, info, sha))
    listed = {"案件": CASE, "制度": SEIDO, "案件の回": "第8回", "直近回の資料に基づく": False, "案内": [], "資料": entries}
    (root / "資料の一覧.json").write_text(json.dumps(listed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _page(doc_dirs: Dict[str, Path], doc_id: str, page: int) -> str:
    text = _doc_text().page_text(doc_dirs[doc_id], printed_page=page)
    if text is None:
        raise BuildError(f"{doc_id} に p.{page} がない")
    return text


def _sourced(value: Any, sources: List[Dict], sentence: str) -> Dict:
    return {"値": value, "出典": copy.deepcopy(sources), "根拠の文": sentence, "状態": "確認済み"}


def build_readings(doc_dirs: Dict[str, Path]) -> Dict[int, Dict]:
    """T3-8 の2回の読み取り（読み取り役が返す形）。"""
    out = {}
    for n in (1, 2):
        rates: Dict[int, Dict] = {}
        dates: Dict[int, Dict] = {}
        pages = []
        for v in T3_8_VALUES:
            top, i, leaf = v["場所"]
            first = v["出典"][0]
            if n == 1 and "1回目の架空の文" in v:
                sentence = v["1回目の架空の文"]
            elif n == 1 and "1回目の根拠の文を取るページ" in v:
                other = v["1回目の根拠の文を取るページ"]
                sentence = find_line(_page(doc_dirs, other["資料"], other["ページ"]), v["1回目の探す語"],
                                     f"{other['資料']} p.{other['ページ']}")
            else:
                sentence = find_line(_page(doc_dirs, first["資料"], first["ページ"]), v["探す語"],
                                     f"{first['資料']} p.{first['ページ']}")
            item = _sourced(v[f"{n}回目"], v["出典"], sentence)
            if top == "補助額":
                rates.setdefault(i, {"区分": v["区分"]})[leaf] = item
            else:
                dates[i] = {"名前": v["名前"], leaf: item}
            for s in v["出典"]:
                if s not in pages:
                    pages.append(s)
        out[n] = {
            "読み取り": {"章": CHAPTER, "読んだページ": pages, "回目": n, "案件": CASE},
            "制度データ": {
                "補助額": [rates[i] for i in sorted(rates)],
                "決まった期日": [dates[i] for i in sorted(dates)],
            },
            "メモ": [f"{MARK}（{MADE_BY}）。T3-8 の材料で、わざと混ぜた値がある。混ぜ方は testdata/制度データ/混ぜたものの一覧.json"],
        }
    return out


def build_answers(doc_dirs: Dict[str, Path]) -> List[Dict]:
    out = []
    for a in ANSWERS:
        q = a["引用"]
        if "架空の文" in q:
            quote = q["架空の文"]
        else:
            page = q.get("取るページ", q["ページ"])
            quote = find_line(_page(doc_dirs, q["資料"], page), q["探す語"], f"{q['資料']} p.{page}")
            if "書き換え" in q:
                old, new = q["書き換え"]
                if old not in quote:
                    raise BuildError(f"答え{a['番']}：引用に「{old}」がない")
                quote = quote.replace(old, new, 1)
        out.append({"番": a["番"], "質問": a["質問"], "答え": a["答え"].replace("{引用}", quote),
                    "引用": {"資料": q["資料"], "ページ": q["ページ"], "文": quote}})
    return out


def build_versions(base: Path, doc_dirs: Dict[str, Path]) -> Dict[str, Path]:
    """T7-1 の新旧2版。変更ありと変更なしの2組を、それぞれ会社のフォルダの形で置く。"""
    doc_text = _doc_text()
    old_dir = doc_dirs["要領8"]
    old_index = doc_text.load_index(old_dir)
    out = {}
    for kind in ("変更あり", "変更なし"):
        company = base / "T7-1" / kind / "会社"
        root = _text_root(company)
        if root.exists():
            shutil.rmtree(root)
        shutil.copytree(old_dir, root / "要領8")
        new_dir = root / NEW_ID
        shutil.copytree(old_dir, new_dir)
        index = copy.deepcopy(old_index)
        if kind == "変更あり":
            for r in REWRITES:
                info = doc_text.find_page(index, printed_page=r["ページ"])
                path = new_dir / info["ファイル"]
                lines = path.read_text(encoding="utf-8").split("\n")
                target = find_line(doc_text.read_page(new_dir, info), r["探す語"], f"要領8 p.{r['ページ']}")
                hit = [k for k, line in enumerate(lines) if line.strip() == target]
                if not hit or r["前"] not in lines[hit[0]]:
                    raise BuildError(f"書き換え{r['番']}：p.{r['ページ']} の行に「{r['前']}」がない")
                lines[hit[0]] = lines[hit[0]].replace(r["前"], r["後"], 1)
                path.write_text("\n".join(lines), encoding="utf-8")
            digest = hashlib.sha256()
            for info in index["ページ"]:
                digest.update((new_dir / info["ファイル"]).read_bytes())
            index["ハッシュ"] = digest.hexdigest()
        index["資料"] = NEW_ID
        (new_dir / doc_text.INDEX_FILE).write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        older = _list_entry("要領8", DOCS["要領8"], old_index["ハッシュ"])
        newer = _list_entry(NEW_ID, dict(DOCS["要領8"], 版="テスト用に書き換えた版（架空）"), index["ハッシュ"])
        listed = {"案件": CASE, "制度": SEIDO, "案件の回": "第8回", "直近回の資料に基づく": False, "案内": [],
                  "資料": [newer], "前の回の資料": [older]}
        (root / "資料の一覧.json").write_text(json.dumps(listed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out[kind] = company
    return out


def build(base: Path, downloads: Path = DOWNLOADS) -> Dict[str, Any]:
    """テストの材料を base（リポの外。tmp_path など）に作る。downloads/ がなければ BuildError。"""
    if not have_downloads(downloads):
        raise BuildError(f"downloads/ に省力化 第8回の資料がない（{downloads}）")
    company = base / "T3-8" / "会社"
    doc_dirs = write_texts(company, downloads)
    readings = build_readings(doc_dirs)
    for n, data in readings.items():
        (base / "T3-8" / f"読み取り_{n}回目.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    quoted = build_answers(doc_dirs)
    (base / "T4-2").mkdir(parents=True, exist_ok=True)
    (base / "T4-2" / "答え.json").write_text(json.dumps(quoted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t4_company = base / "T4-2" / "会社"
    if t4_company.exists():
        shutil.rmtree(t4_company)
    shutil.copytree(company, t4_company)
    versions = build_versions(base, doc_dirs)
    return {"T3-8": company, "読み取り": readings, "T4-2": quoted, "T7-1": versions, "資料の本文": doc_dirs}


def main(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--build":
        base = Path(argv[1]).resolve()
        if base == REPO or REPO in base.parents:
            print("材料は公募要領の文を含むので、リポの外に作ってください")
            return 1
        build(base)
        print(f"作った：{base}")
        return 0
    for path, text in answers().items():
        path.write_text(text, encoding="utf-8")
        print(f"書いた：{path.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
