"""章ごとの読み取りの結果を1つの制度データにまとめ、確かめ、段階のフォルダを作る（SPEC F3、DESIGN 4.5・9章・9.2、TASKS M2c）。

流れ：
1. まとめる（merge）
   - 読む：`記録/制度データ/読み取り/<案件>/` の章ごとの結果のうち、1回目のもの（lib/urakadori.py が置いたもの）。
     2回目（重要な項目を別の呼び出しで初めから読み直したもの）は、値には使わず、1回目との突き合わせだけに使う（TASKS B25。下の 1b）。
   - 章の順番は、読んだページのはじめ（資料の一覧の順と、ページ）で決める。
   - 項目ごとに合わせる。
     - 配列の項目（補助額・書類など）は、章の順につなぐ（まったく同じ件は1つにする）。
     - { } の項目（加点・申請画面・提出するファイルの決まり・支援者の欄）は、欄ごとに合わせる。
       配列の欄はつなぎ、同じ欄を2つの章が違う値で読んでいたら、前の章の値を使い、そのことを結果に書く。
   - 「スキーマの版」「制度」「資料」は、案件の `資料の一覧.json`（lib/official_docs.py が作るもの）から入れる。
     制度の「公募回」は、制度データを作った資料の回（直近回の資料に基づくときは、その回。lib/official_docs.round_notices と同じ決め方）。
   - どの章も読んでいない項目は、推測で埋めない。配列は空、{ } の項目は必須の欄を「読み取れない」にし、
     「読み取れなかった項目」に「どの章でも読み取っていない」と書く。
     「読み取れない」の値も、場所と理由を「読み取れなかった項目」に並べる（問い合わせ文の案は Claude が足す）。
   - まとめたものを lib/urakadori.run に渡す。全体の形を確かめ、どの値も裏取りし直して、
     `記録/制度データ/<制度の略称>_<公募回>.json` に置く（置き場所は lib/urakadori が決める。DESIGN 9章）。
1b. 2回の読み取りの突き合わせ（SPEC F3「重要な項目は2回独立に読み取り、食い違えば要確認」・T3-8、DESIGN 9.2）
   - 重要な項目の値を、名前で決まる場所（決まった期日「締切」の日時、補助額「区分」の上限・補助率・特例の値、
     申請の段階の期限、数値の要件「名前」の基準、必須書類「名前」、補助の対象にならない経費「名前」の内容・上限）で並べ、
     2回目の章と、同じ名前の1回目の章とで比べる（同じ章の1回目がなければ、まとめた全体と比べる）。
   - 比べ方：値の中の数（万・億は円に直す。日付と時刻、割合も数として見る）が同じか。文の言い回しの違いは見ない
     （2回の読み取りで言い方が変わるのはふつうなので）。必須書類は、件があるかだけを見る。一方だけが「読み取れない」も食い違い。
   - 食い違った値は、まとめた制度データで「要確認」にし、「2回の読み取り：」の注記に両方の値を書く（状態は下げるだけ。
     裏取りの道具の「裏取り：」の注記とは別なので、裏取りし直しても戻らない）。
   - 1回目にあって、同じ章の2回目にない重要な項目の件も「要確認」にする（2回目が、その項目そのものを読んでいないときは比べない）。
     2回目にだけある件は、まとめに入れず、結果に並べる（その章を読み直させる）。
2. 確かめる（check）
   - 形（スキーマ）が合うか。
   - 重要な項目（SPEC F3・DESIGN 9.2 の、締切・補助上限・補助率・数値の要件・必須書類・補助の対象にならない経費）が、
     1件以上あり、どの値も「値」か「要確認」で埋まっているか（「読み取れない」や、値が空の確認済み・資料で食い違いは、埋まっていない。
     空は null・空白だけの文字・[]・{}・中の値がどれも空のもの。読み取り役が「読み取れない」にせず空の値を返したときに、
     確認済みの空欄のまま社長に渡さないため）。
     - ただし、スキーマで任意の欄（数値の要件の計算式・元の数字の決め方・満たせないとき、必須書類の有効期限・期数、
       補助の対象にならない経費の上限・例外）が「読み取れない」のときは、埋まっていないに数えない（11/5 の作者の決定。
       M2c の基本要件④の満たせないとき）。「任意の欄で読み取れない値」として別に数えて示し、問い合わせ文の案に回す。
       必須の欄（締切の日時、補助額の上限・補助率・特例の値、数値の要件の基準、必須書類と経費の内容）は、今のまま数える。
       任意の欄でも、値が空の確認済み・資料で食い違いは、埋まっていないに数える（読み取り役の返し方の誤りのため）。
   - 読み取れない値ごとに、「読み取れなかった項目」に同じ項目の問い合わせ文の案があるか。ないものを一覧に出す
     （終了コードには響かせない。問い合わせ文の案は、読み取り役か Claude が作る）。
   - 出典のない値の数。読み取れないでない値のうち、出典か根拠の文がないもの、出典の資料が「資料」にないもの。
   - 名前の参照（M2c の直し・波2）。書類の「手続き」が手続きの段階の id にないもの、手続きの段階の「様式」が様式の名前にないものを、
     当たらない名前ごとに数え、足りないに数える（仮）。「1_申請」のようなフォルダの名前を書いた書類は、段階の id で書類を引く道具
     （概要と流れ.docx の必要書類、段階ごとの書類の一覧）から落ちるため。読み直させるときに渡せるよう、当たる名前の一覧も出す。
   - 欄も押してよいボタンもない申請画面（電子申請マニュアルの流れのページだけを読んだ形）。足りないに数える（波3）。
     いちばん後ろの確認・提出の画面は数えない（提出のボタンしかなければ、空が正しい形）。
     入力シートに欄ができず、画面入力の守りが一時保存も次へも拒むため。2つの章が申請画面を読んで画面が二重になったら、まとめの結果に書く。
3. 段階のフォルダを作る（make_stage_folders）
   - 制度データの「手続きの段階」のうち「フォルダ」のある段階から作る（DESIGN 4.5）。中は「申請書」と「添付する書類」。
   - はじめは、いちばん前の段階（申請）だけを作る。採択後に次の段階へ進むときは、その段階の名前を渡して作る（M10）（仮）。
   - 段階のフォルダの名前が、段階の順に 1 から数えた「1_申請」「2_交付申請」…でなければ、どのフォルダも作らない（仮）。
     読み取り役が申請の段階を落とすと、いちばん前のフォルダが「2_採択発表」のようになるため。

場所の確かめ（DESIGN 5章。確かめは lib/places.py）：読む材料（案件の資料の一覧、章ごとの読み取りの結果とそのフォルダ、
制度データ）は、別名と「..」をたどった後に会社のフォルダの中にあるときだけ読む。外なら読まずに、MergeError か DataMissing で
断る（何も書かない）。段階のフォルダは、作る先の途中に別名があれば作らない（lib/case_folder.py）。
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import case_folder, place_text, urakadori
from lib.official_docs import LIST_FILE, RECORDS_DIR, TEXT_DIR, round_number

SCHEMA_VERSION = 1
FIRST_ROUND = 1
SECOND_ROUND = 2
DOUBLE_PREFIX = "2回の読み取り："
# 「制度」「資料」と同じく、まとめる道具が入れる項目（章の読み取りからは取らない）
OWN_KEYS = ("スキーマの版", "制度", "資料")
# どの章も読んでいなくても「読み取れなかった項目」に書かない項目（空でよいもの）
MAY_BE_EMPTY = ("資料どうしの食い違い", "読み取れなかった項目")
NOT_READ = "どの章の読み取りにもありません（資料に書かれていないか、まだ読んでいない章にあります）"

CONFIRMED = urakadori.CONFIRMED
CHECK = urakadori.CHECK
CONFLICT = urakadori.CONFLICT
UNREADABLE = urakadori.UNREADABLE

# 重要な項目（SPEC F3、DESIGN 9.2）。名前と、制度データのどの値を見るか（下の _important_values）
IMPORTANT = ("締切", "補助上限", "補助率", "数値の要件", "必須書類", "補助の対象にならない経費")
DEADLINE_WORD = "締切"


class MergeError(ValueError):
    """まとめられない（読み取りの結果がない、資料の一覧が読めない など）。何も書かない。"""


class DataMissing(ValueError):
    """確かめる制度データがない。"""


@dataclass
class MergeResult:
    chapters: List[Tuple[str, List[str]]] = field(default_factory=list)  # 章の名前と、その章が読んだ項目
    skipped: List[str] = field(default_factory=list)                      # 使わなかった結果（2回目など）
    conflicts: List[str] = field(default_factory=list)                    # 2つの章が違う値で読んだ欄
    duplicates: List[str] = field(default_factory=list)                   # 同じ名前の件が2つ以上ある項目
    not_read: List[str] = field(default_factory=list)                     # どの章も読んでいない項目
    data_round: str = ""
    second_chapters: List[str] = field(default_factory=list)              # 2回目の読み取りがあった章（B25）
    double_compared: int = 0                                              # 2回の読み取りで比べた重要な値の数
    double_diffs: List[Tuple[str, str]] = field(default_factory=list)     # 食い違って要確認にした値（場所、わけ）
    second_only: List[str] = field(default_factory=list)                  # 2回目にだけある重要な項目の件


@dataclass
class ImportantItem:
    name: str
    entries: int = 0
    values: int = 0
    filled: int = 0
    unfilled: List[str] = field(default_factory=list)  # 埋まっていない値の場所
    optional_unreadable: List[str] = field(default_factory=list)  # 任意の欄で読み取れない値の場所（埋まっていないに数えない）

    @property
    def ok(self) -> bool:
        return self.entries > 0 and not self.unfilled


@dataclass
class CheckResult:
    schema_errors: List[str] = field(default_factory=list)
    important: List[ImportantItem] = field(default_factory=list)
    unsourced: List[str] = field(default_factory=list)  # 出典のない値の場所と理由
    values: int = 0
    states: Dict[str, int] = field(default_factory=dict)
    downgraded: int = 0          # 裏取りの道具が要確認にした値
    unreadable_items: List[str] = field(default_factory=list)
    unread_listed: int = 0       # 「読み取れなかった項目」の件数
    unread_with_question: int = 0  # そのうち、問い合わせ文の案があるもの
    question_missing: List[str] = field(default_factory=list)  # 読み取れない値のうち、同じ項目の問い合わせ文の案がないもの
    bad_refs: List[str] = field(default_factory=list)   # 手続きの段階の id・様式の名前に当たらない名前（足りないに数える）
    ref_known: List[str] = field(default_factory=list)  # そのときに当たる名前の一覧（読み直させるときに渡す）
    empty_screens: List[str] = field(default_factory=list)  # 欄も押してよいボタンもない申請画面（足りないに数える）

    @property
    def ok(self) -> bool:
        return (not self.schema_errors and all(i.ok for i in self.important) and not self.unsourced
                and not self.bad_refs and not self.empty_screens)


# ---- 場所 ----


def reading_dir(company: Path, case: str) -> Path:
    return urakadori.seido_dir(company) / urakadori.READING_DIR / case_folder.safe_name(case)


def doc_list_path(company: Path, case: str) -> Path:
    return company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case) / LIST_FILE


def _outside_problem(company: Path, path: Path, what: str) -> Optional[str]:
    """path が、別名と「..」をたどった後も会社のフォルダの中なら None。外なら断る文（lib/places.py。DESIGN 5章）。"""
    return place_text.read_problem(company, path, f"{what}（{path.relative_to(company).as_posix()}）")


def load_doc_list(company: Path, case: str) -> Dict:
    path = doc_list_path(company, case)
    problem = _outside_problem(company, path, "案件の資料の一覧")
    if problem:  # 外の一覧は読まない（制度データの置き場所も、外の一覧で決めない）
        raise MergeError(problem)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise MergeError(f"案件の資料の一覧（{path.relative_to(company)}）が読めません（{type(e).__name__}）。"
                         "先に公式資料を取ってください") from e
    if not isinstance(data, dict) or not isinstance(data.get("制度"), dict) or not isinstance(data.get("資料"), list):
        raise MergeError(f"案件の資料の一覧（{path.relative_to(company)}）の形が違います。公式資料を取り直してください")
    return data


def data_round(listed: Dict) -> str:
    """制度データの公募回：制度データを作った資料の回（lib/official_docs.round_notices と同じ決め方）。

    案件の回の資料があればその回。なければ（直近回の資料に基づくとき）、案件の回より前でいちばん新しい資料の回。
    """
    target = str(listed["制度"].get("公募回") or listed.get("案件の回") or "")
    target_n = round_number(target)
    rounds = sorted({n for n in (round_number(str(d.get("公募回", ""))) for d in listed["資料"] if isinstance(d, dict))
                     if n is not None})
    if target_n is None or not rounds or target_n in rounds:
        return target
    earlier = [n for n in rounds if n < target_n]
    return f"第{max(earlier) if earlier else max(rounds)}回"


def seido_path(company: Path, case: str) -> Path:
    """この案件の制度データの置き場所（lib/urakadori.full_out_path と同じ）。"""
    listed = load_doc_list(company, case)
    return urakadori.full_out_path(company, case, {"制度": seido_part(listed)})


def seido_part(listed: Dict) -> Dict:
    src = listed["制度"]
    out = {"名前": src.get("名前")}
    if src.get("枠"):
        out["枠"] = src["枠"]
    out["種類"] = src.get("種類")
    out["公募回"] = data_round(listed)
    return out


def docs_part(listed: Dict, schema: Dict) -> List[Dict]:
    allowed = set(schema["properties"]["資料"]["items"]["properties"])
    return [{k: v for k, v in d.items() if k in allowed} for d in listed["資料"] if isinstance(d, dict)]


# ---- まとめる ----


def _first_page(chapter: Dict, order: Dict[str, int]) -> Tuple[int, int]:
    pages = (chapter.get("読み取り") or {}).get("読んだページ") or []
    if not pages or not isinstance(pages[0], dict):
        return (len(order), 0)
    first = pages[0]
    page = first.get("ページ") if isinstance(first.get("ページ"), int) else 0
    return (order.get(first.get("資料"), len(order)), page)


def load_chapters(company: Path, case: str, order: Dict[str, int], result: MergeResult) -> List[Dict]:
    base = reading_dir(company, case)
    problem = _outside_problem(company, base, "章ごとの読み取りの結果")
    if problem:
        raise MergeError(problem)
    if not base.is_dir():
        raise MergeError(f"章ごとの読み取りの結果（{base.relative_to(company)}/）がありません。"
                         "先に、読み取り役に章ごとに読ませ、裏取りの道具に通してください")
    chapters = []
    for path in sorted(base.glob("*.json")):
        problem = _outside_problem(company, path, "章ごとの読み取りの結果")
        if problem:  # 1つでも外を指すものがあれば、どれもまとめない（外の結果を、まとめた制度データに入れない）
            raise MergeError(problem)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result.skipped.append(f"{path.name}（読めない）")
            continue
        info = data.get("読み取り") if isinstance(data, dict) else None
        if not isinstance(info, dict) or not isinstance(data.get("制度データ"), dict):
            result.skipped.append(f"{path.name}（形が違う）")
            continue
        if info.get("回目", FIRST_ROUND) == SECOND_ROUND:
            continue  # 2回目は、突き合わせ（load_second_readings・compare_readings）だけに使う
        if info.get("回目", FIRST_ROUND) != FIRST_ROUND:
            result.skipped.append(f"{path.name}（{info.get('回目')}回目。使うのは1回目と2回目だけ）")
            continue
        chapters.append(data)
    if not chapters:
        raise MergeError(f"1回目の読み取りの結果が、{base.relative_to(company)}/ に1つもありません")
    chapters.sort(key=lambda c: (_first_page(c, order), str(c["読み取り"].get("章"))))
    return chapters


def load_second_readings(company: Path, case: str) -> List[Dict]:
    """2回目の読み取りの結果（lib/urakadori.py が置いたもの）。場所の確かめは load_chapters が先に済ませている。"""
    base = reading_dir(company, case)
    out = []
    for path in sorted(base.glob("*.json")) if base.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        info = data.get("読み取り") if isinstance(data, dict) else None
        if isinstance(info, dict) and info.get("回目") == SECOND_ROUND and isinstance(data.get("制度データ"), dict):
            out.append(data)
    return out


# ---- 2回の読み取りの突き合わせ（B25） ----

_SPACES = re.compile(r"\s+")
_NUMBER = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(億|万)?")


def _name_key(text: Any) -> str:
    return _SPACES.sub("", unicodedata.normalize("NFKC", str(text or "")))


def important_keyed(part: Dict) -> Dict[Tuple[str, ...], Tuple[List[Any], Any, bool]]:
    """重要な項目の値を、名前で決まる場所で並べる。（場所の鍵）→（データの中の道、出典つき値、件があるかだけを見るか）。"""
    out: Dict[Tuple[str, ...], Tuple[List[Any], Any, bool]] = {}
    for i, d in enumerate(part.get("決まった期日") or []):
        if isinstance(d, dict) and DEADLINE_WORD in str(d.get("名前", "")):
            out[("決まった期日", _name_key(d.get("名前")), "日時")] = (["決まった期日", i, "日時"], d.get("日時"), False)
    for i, a in enumerate(part.get("補助額") or []):
        if not isinstance(a, dict):
            continue
        k = _name_key(a.get("区分"))
        for leaf in ("上限", "補助率"):
            if leaf in a:
                out[("補助額", k, leaf)] = (["補助額", i, leaf], a.get(leaf), False)
        for j, s in enumerate(a.get("特例") or []):
            if isinstance(s, dict) and "値" in s:
                out[("補助額", k, "特例", _name_key(s.get("名前")))] = (["補助額", i, "特例", j, "値"], s.get("値"), False)
    stages = [(i, s) for i, s in enumerate(part.get("手続きの段階") or []) if isinstance(s, dict)]
    if stages:
        i, first = min(stages, key=lambda x: x[1].get("順番") if isinstance(x[1].get("順番"), int) else 10 ** 6)
        if "期限" in first:
            out[("手続きの段階", _name_key(first.get("id") or first.get("名前")), "期限")] = (["手続きの段階", i, "期限"],
                                                                                    first.get("期限"), False)
    for i, r in enumerate(part.get("数値の要件") or []):
        if isinstance(r, dict) and "基準" in r:
            out[("数値の要件", _name_key(r.get("名前")), "基準")] = (["数値の要件", i, "基準"], r.get("基準"), False)
    for i, d in enumerate(part.get("書類") or []):
        if isinstance(d, dict) and d.get("区分") == "必須":
            out[("書類", _name_key(d.get("名前")), "内容")] = (["書類", i, "内容"], d.get("内容"), True)
    for i, c in enumerate(part.get("補助の対象にならない経費") or []):
        if not isinstance(c, dict):
            continue
        k = _name_key(c.get("名前") or c.get("区分") or i)
        out[("補助の対象にならない経費", k, "内容")] = (["補助の対象にならない経費", i, "内容"], c.get("内容"), False)
        if "上限" in c:
            out[("補助の対象にならない経費", k, "上限")] = (["補助の対象にならない経費", i, "上限"], c.get("上限"), False)
    return out


def numbers_in(value: Any) -> set:
    """値の中の数（万・億は円に直す）。日付・時刻・割合の数字も、それぞれ数として拾う。"""
    if value is None:
        return set()
    text = unicodedata.normalize("NFKC", json.dumps(value, ensure_ascii=False)).replace(",", "")
    found = set()
    for m in _NUMBER.finditer(text):
        n = float(m.group(1))
        if m.group(2) == "万":
            n *= 10000
        elif m.group(2) == "億":
            n *= 100000000
        found.add(int(n) if n == int(n) else n)
    return found


def _show(node: Any) -> str:
    if not _is_sourced(node):
        return "（なし）"
    if node.get("状態") == UNREADABLE:
        return "読み取れない"
    text = json.dumps(node.get("値"), ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + "…"


def readings_differ(first: Any, second: Any, presence_only: bool) -> Optional[str]:
    """2回の読み取りの値が食い違うか。食い違えば、わけの文。"""
    if presence_only:
        return None
    a_unread = not _is_sourced(first) or first.get("状態") == UNREADABLE
    b_unread = not _is_sourced(second) or second.get("状態") == UNREADABLE
    if a_unread and b_unread:
        return None
    if a_unread != b_unread or numbers_in(first.get("値")) != numbers_in(second.get("値")):
        return f"1回目は {_show(first)}、2回目は {_show(second)}"
    return None


def _downgrade(node: Any, why: str) -> bool:
    if not _is_sourced(node):
        return False
    note = DOUBLE_PREFIX + why.replace(urakadori.NOTE_SEP, "/")
    existing = node.get("注記")
    if not existing:
        node["注記"] = note
    elif note not in existing:
        node["注記"] = existing + urakadori.NOTE_SEP + note
    if node.get("状態") in (CONFIRMED, CONFLICT):
        node["状態"] = CHECK
        return True
    return node.get("状態") == CHECK


def compare_readings(full: Dict, chapters: List[Dict], seconds: List[Dict], result: MergeResult) -> None:
    """2回目の読み取りと1回目を、重要な項目で比べ、食い違った値をまとめた制度データで要確認にする（その場で直す）。"""
    by_name = {str(c["読み取り"].get("章")): c for c in chapters}
    full_keys = important_keyed(full)
    for second in seconds:
        name = str(second["読み取り"].get("章"))
        result.second_chapters.append(name)
        sec_part = second["制度データ"]
        first = by_name.get(name)
        ref_part = first["制度データ"] if first else full
        sec_keys = important_keyed(sec_part)
        ref_keys = important_keyed(ref_part)
        for key, (path, node2, presence) in sec_keys.items():
            if key not in ref_keys:
                result.second_only.append(f"{name}：{urakadori.readable(path, sec_part)}")
                continue
            result.double_compared += 1
            why = readings_differ(ref_keys[key][1], node2, presence)
            if why and key in full_keys:
                full_path, full_node, _ = full_keys[key]
                _downgrade(full_node, why)
                result.double_diffs.append((urakadori.readable(full_path, full), why))
        if first is None:
            continue
        read_tops = {k for k in sec_part}
        for key, (path, _node1, _presence) in ref_keys.items():
            if key in sec_keys or key[0] not in read_tops or key not in full_keys:
                continue
            full_path, full_node, _ = full_keys[key]
            why = "2回目の読み取りに、この件がありません"
            _downgrade(full_node, why)
            result.double_diffs.append((urakadori.readable(full_path, full), why))


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def _extend(target: List, items: List) -> None:
    for item in items:
        if not any(_same(item, t) for t in target):
            target.append(copy.deepcopy(item))


def _merge_object(key: str, target: Dict, part: Dict, chapter: str, result: MergeResult) -> None:
    for sub, value in part.items():
        if sub not in target:
            target[sub] = copy.deepcopy(value)
        elif isinstance(target[sub], list) and isinstance(value, list):
            _extend(target[sub], value)
        elif not _same(target[sub], value):
            result.conflicts.append(f"「{key}」の「{sub}」を2つ以上の章が違う値で読んでいます（前の章の値を使い、章「{chapter}」の値は使っていません）")


def _unread(reason: str) -> Dict:
    return {"値": None, "状態": UNREADABLE, "理由": reason}


def _empty_value(key: str, schema_prop: Dict) -> Any:
    """どの章も読んでいない項目の、空の形（推測で埋めない）。"""
    if schema_prop.get("type") == "array":
        return []
    if key == "支援者の欄":
        return None
    out: Dict[str, Any] = {}
    for sub in schema_prop.get("required", []):
        sub_schema = schema_prop["properties"][sub]
        out[sub] = [] if sub_schema.get("type") == "array" else _unread(NOT_READ)
    return out


def _fill_object(key: str, value: Dict, schema_prop: Dict, result: MergeResult) -> None:
    """{ } の項目で、必須の欄をどの章も読んでいなければ「読み取れない」にする。"""
    for sub in schema_prop.get("required", []):
        if sub not in value:
            sub_schema = schema_prop["properties"][sub]
            value[sub] = [] if sub_schema.get("type") == "array" else _unread(NOT_READ)
            result.not_read.append(f"{key}の{sub}")


def _duplicates(key: str, items: List) -> Optional[str]:
    names: Dict[str, int] = {}
    for item in items:
        if isinstance(item, dict):
            name = item.get("名前") or item.get("区分") or item.get("id") or item.get("項目")
            if isinstance(name, str):
                names[name] = names.get(name, 0) + 1
    dup = sorted(n for n, c in names.items() if c > 1)
    return f"{key}：{'・'.join(dup)}" if dup else None


def _unreadable_entries(data: Dict) -> List[Dict]:
    """「読み取れない」の値の、場所と理由（「読み取れなかった項目」に並べる）。"""
    out: List[Dict] = []

    def visit(node: Any, path: List[Any]) -> None:
        if isinstance(node, dict) and "値" in node and "状態" in node:
            if node["状態"] == UNREADABLE:
                out.append({"項目": urakadori.readable(path, data), "理由": node.get("理由") or NOT_READ})
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い", "読み取れなかった項目"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(data, [])
    return out


def merge(company: Path, case: str) -> Tuple[Dict, MergeResult]:
    """章ごとの読み取りの結果（1回目）を、1つの制度データにまとめる（まだ書かない）。"""
    result = MergeResult()
    schema = urakadori.load_schema()
    props = schema["properties"]
    listed = load_doc_list(company, case)
    order = {d.get("id"): i for i, d in enumerate(listed["資料"]) if isinstance(d, dict)}
    chapters = load_chapters(company, case, order, result)

    merged: Dict[str, Any] = {}
    for chapter in chapters:
        name = str(chapter["読み取り"].get("章"))
        part = chapter["制度データ"]
        result.chapters.append((name, [k for k in part if k in props and k not in OWN_KEYS]))
        for key, value in part.items():
            if key not in props or key in OWN_KEYS:
                continue  # 形の確かめ（urakadori）で、制度データにない項目は通らない
            if isinstance(value, list):
                _extend(merged.setdefault(key, []), value)
            elif isinstance(value, dict):
                if not isinstance(merged.get(key), dict):
                    merged[key] = {}
                _merge_object(key, merged[key], value, name, result)
            elif value is None:
                merged.setdefault(key, None)

    full: Dict[str, Any] = {"スキーマの版": SCHEMA_VERSION, "制度": seido_part(listed), "資料": docs_part(listed, schema)}
    result.data_round = full["制度"]["公募回"]
    for key, prop in props.items():
        if key in OWN_KEYS:
            continue
        if key in merged:
            full[key] = merged[key]
            if isinstance(full[key], dict) and prop.get("type") == "object":
                _fill_object(key, full[key], prop, result)
        else:
            full[key] = _empty_value(key, prop)
            if key not in MAY_BE_EMPTY:
                result.not_read.append(key)
        if isinstance(full[key], list):
            dup = _duplicates(key, full[key])
            if dup:
                result.duplicates.append(dup)
    screens = full.get("申請画面", {}).get("画面") if isinstance(full.get("申請画面"), dict) else None
    if isinstance(screens, list):  # 2つの章が申請画面を読むと、画面がつながって二重になる
        dup = _duplicates("申請画面の画面", screens)
        if dup:
            result.duplicates.append(dup)

    # 重要な項目の2回の読み取りの突き合わせ（B25）
    compare_readings(full, chapters, load_second_readings(company, case), result)

    # 読み取れなかった項目：章が書いたもの、どの章も読んでいない項目、読み取れないの値
    unread = list(full.get("読み取れなかった項目") or [])
    for key in result.not_read:
        unread.append({"項目": key, "理由": NOT_READ})
    for entry in _unreadable_entries(full):
        if not any(isinstance(u, dict) and u.get("項目") == entry["項目"] for u in unread):
            unread.append(entry)
    full["読み取れなかった項目"] = unread
    return full, result


def merge_and_save(company: Path, case: str) -> Tuple[Dict, MergeResult, urakadori.Result]:
    """まとめて、裏取りし直して、`記録/制度データ/<略称>_<公募回>.json` に置く。

    形が合わなければ urakadori.InputError（何も書かない）。
    """
    full, merged = merge(company, case)
    verified, saved = urakadori.run(company, case, full)
    return saved, merged, verified


# ---- 確かめる ----


def _is_sourced(node: Any) -> bool:
    return isinstance(node, dict) and "値" in node and "状態" in node


def _important_values(data: Dict) -> Dict[str, Tuple[int, List[Tuple[str, Any, bool]]]]:
    """重要な項目ごとの（件数、（場所、出典つき値、必須の欄か）の一覧）。

    必須の欄か任意の欄かは、制度データのスキーマの required のとおり（決まった期日：日時、補助額：上限・補助率、
    特例：値、数値の要件：基準、書類：内容、補助の対象にならない経費：内容が必須。ほかは任意の欄）。
    任意の欄は、件にその欄があるときだけ見る。
    """

    def where(*path: Any) -> str:
        return urakadori.readable(list(path), data)

    def fields(name: str, items: List[Tuple[int, Dict]], required: str, optional: Tuple[str, ...]) -> List[Tuple[str, Any, bool]]:
        return [(where(name, i, k), item.get(k), k == required) for i, item in items
                for k in (required,) + optional if k == required or k in item]

    out: Dict[str, Tuple[int, List[Tuple[str, Any, bool]]]] = {}
    deadlines = [(i, d) for i, d in enumerate(data.get("決まった期日") or [])
                 if isinstance(d, dict) and DEADLINE_WORD in str(d.get("名前", ""))]
    out["締切"] = (len(deadlines), [(where("決まった期日", i, "日時"), d.get("日時"), True) for i, d in deadlines])

    caps: List[Tuple[str, Any, bool]] = []
    rates: List[Tuple[str, Any, bool]] = []
    amounts = [a for a in data.get("補助額") or [] if isinstance(a, dict)]
    for i, a in enumerate(data.get("補助額") or []):
        if not isinstance(a, dict):
            continue
        caps.append((where("補助額", i, "上限"), a.get("上限"), True))
        rates.append((where("補助額", i, "補助率"), a.get("補助率"), True))
        for j, s in enumerate(a.get("特例") or []):
            if not isinstance(s, dict):
                continue
            target = rates if s.get("種類") == "補助率の置き換え" else caps
            target.append((where("補助額", i, "特例", j, "値"), s.get("値"), True))
    out["補助上限"] = (len(amounts), caps)
    out["補助率"] = (len(amounts), rates)

    reqs = [(i, r) for i, r in enumerate(data.get("数値の要件") or []) if isinstance(r, dict)]
    out["数値の要件"] = (len(reqs), fields("数値の要件", reqs, "基準", ("計算式", "元の数字の決め方", "満たせないとき")))

    docs = [(i, d) for i, d in enumerate(data.get("書類") or []) if isinstance(d, dict) and d.get("区分") == "必須"]
    out["必須書類"] = (len(docs), fields("書類", docs, "内容", ("有効期限", "期数")))

    costs = [(i, c) for i, c in enumerate(data.get("補助の対象にならない経費") or []) if isinstance(c, dict)]
    out["補助の対象にならない経費"] = (len(costs), fields("補助の対象にならない経費", costs, "内容", ("上限", "例外")))
    return out


def _is_empty(value: Any) -> bool:
    """値が空か：null、空白だけの文字、[]、{}、中の値がどれも空の [ ] や { }（{"日時": ""} など）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(_is_empty(v) for v in value)
    if isinstance(value, dict):
        return all(_is_empty(v) for v in value.values())
    return False


def _filled(node: Any) -> bool:
    """値で埋まっているか。確認済み・資料で食い違いは、値が空でないこと。要確認は、社長に確かめてもらう印なので埋まっているに数える。"""
    if not _is_sourced(node):
        return False
    if node["状態"] == CHECK:
        return True
    return node["状態"] in (CONFIRMED, CONFLICT) and not _is_empty(node.get("値"))


def _unfilled_reason(node: Any) -> str:
    if not _is_sourced(node):
        return "値がない"
    if node["状態"] in (CONFIRMED, CONFLICT):
        return "値が空"  # 「読み取れない」にせず、空の値を確認済みで返した（読み取り直すか、読み取れないにする）
    return str(node["状態"])


def _source_problems(item: Dict, doc_ids: set) -> List[str]:
    problems = []
    sources = item.get("出典")
    if not isinstance(sources, list) or not sources:
        problems.append("出典がありません")
    else:
        for s in sources:
            doc = s.get("資料") if isinstance(s, dict) else None
            if doc not in doc_ids:
                problems.append(f"出典の資料「{doc}」が、制度データの「資料」にありません")
    if not isinstance(item.get("根拠の文"), str) or not item.get("根拠の文", "").strip():
        problems.append("根拠の文がありません")
    return problems


def _names(items: Any, key: str) -> List[str]:
    out: List[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get(key), str) and item[key] not in out:
            out.append(item[key])
    return out


def _known_line(what: str, names: List[str]) -> str:
    return f"{what}：{'・'.join(names) if names else '（ありません）'}"


def reference_problems(data: Dict) -> Tuple[List[str], List[str]]:
    """名前の参照を照らす。返すのは（当たらない名前の一覧、当たる名前の一覧（当たらなかった種類の分だけ））。

    - 書類の「手続き」は、手続きの段階の id（スキーマの説明「使う手続きの段階の id」）。
    - 手続きの段階の「様式」は、制度データの「様式」の名前。
    当たらない名前1つごとに1件。
    """
    problems: List[str] = []
    known: List[str] = []
    stages = data.get("手続きの段階") if isinstance(data.get("手続きの段階"), list) else []
    stage_ids = _names(stages, "id")
    found = 0
    for i, doc in enumerate(data.get("書類") if isinstance(data.get("書類"), list) else []):
        names = doc.get("手続き") if isinstance(doc, dict) else None
        for name in names if isinstance(names, list) else []:
            if name not in stage_ids:
                problems.append(f"{urakadori.readable(['書類', i, '手続き'], data)}「{name}」が、手続きの段階の id にありません")
                found += 1
    if found:
        known.append(_known_line("手続きの段階の id", stage_ids))
    form_names = _names(data.get("様式"), "名前")
    found = 0
    for i, stage in enumerate(stages):
        names = stage.get("様式") if isinstance(stage, dict) else None
        for name in names if isinstance(names, list) else []:
            if name not in form_names:
                problems.append(f"{urakadori.readable(['手続きの段階', i, '様式'], data)}「{name}」が、様式の名前にありません")
                found += 1
    if found:
        known.append(_known_line("様式の名前", form_names))
    return problems, known


def empty_screens(data: Dict) -> List[str]:
    """欄も押してよいボタンもない申請画面の名前（電子申請マニュアルの流れのページだけを読んだときの形）。

    このままでは、入力シートに欄ができず、画面入力の守りが一時保存も次へも拒む（F10、DESIGN 5章）。
    画面が1つもないのは、流れが「読み取れない」なら読み取れなかった項目に回し、読めているなら足りないに数える。
    いちばん後ろの画面（確認・提出の画面）は数えない。提出のボタンしかない画面は、提出を押してよいボタンに入れないので、
    欄もボタンも空になるのが正しい形のため（数えると、読み直しても直らない）。
    """
    part = data.get("申請画面")
    if not isinstance(part, dict):
        return []
    screens = [s for s in part.get("画面") or [] if isinstance(s, dict)]
    flow = part.get("流れ")
    if not screens:
        read = isinstance(flow, dict) and flow.get("状態") != UNREADABLE
        return ["（画面が1つもありません）"] if read else []
    last = max(screens, key=lambda s: s.get("順番") if isinstance(s.get("順番"), int) else 0)
    return [str(s.get("名前") or f"{s.get('順番')}つ目の画面") for s in screens
            if s is not last and not s.get("欄") and not s.get("押してよいボタン")]


def check(data: Any) -> CheckResult:
    """制度データの全体を確かめる（形、重要な項目、出典のない値、名前の参照、欄もボタンもない申請画面）。"""
    result = CheckResult()
    if not isinstance(data, dict):
        result.schema_errors = ["（全体）：いちばん外側を { } の形にしてください"]
        return result
    result.schema_errors = urakadori.shape_errors(data)
    doc_ids = {d.get("id") for d in data.get("資料") or [] if isinstance(d, dict)}

    def visit(node: Any, path: List[Any]) -> None:
        if _is_sourced(node):
            result.values += 1
            state = node["状態"]
            result.states[state] = result.states.get(state, 0) + 1
            if isinstance(node.get("注記"), str) and urakadori.NOTE_PREFIX in node["注記"]:
                result.downgraded += 1
            if state == UNREADABLE:
                result.unreadable_items.append(urakadori.readable(path, data))
            else:
                for p in _source_problems(node, doc_ids):
                    result.unsourced.append(f"{urakadori.readable(path, data)}：{p}")
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い", "読み取れなかった項目"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(data, [])
    for i, entry in enumerate(data.get("資料どうしの食い違い") or []):
        if not isinstance(entry, dict):
            continue
        for j, item in enumerate(entry.get("値") or []):
            if isinstance(item, dict):
                for p in _source_problems(item, doc_ids):
                    result.unsourced.append(f"資料どうしの食い違い「{entry.get('項目')}」の{j + 1}つ目の値：{p}")

    result.bad_refs, result.ref_known = reference_problems(data)
    result.empty_screens = empty_screens(data)

    listed =[u for u in data.get("読み取れなかった項目") or [] if isinstance(u, dict)]
    result.unread_listed = len(listed)
    result.unread_with_question = sum(1 for u in listed if _has_question(u))
    # 読み取れない値の場所と、まとめの道具が「読み取れなかった項目」に書く項目の名前は、同じ書き方（urakadori.readable）
    asked = {u.get("項目") for u in listed if _has_question(u)}
    result.question_missing = [p for p in result.unreadable_items if p not in asked]

    found = _important_values(data)
    for name in IMPORTANT:
        entries, nodes = found.get(name, (0, []))
        item = ImportantItem(name=name, entries=entries, values=len(nodes))
        for place, node, required in nodes:
            if _filled(node):
                item.filled += 1
            elif not required and _is_sourced(node) and node["状態"] == UNREADABLE:
                item.optional_unreadable.append(place)  # 任意の欄の読み取れないは数えず、問い合わせ文の案に回す
            else:
                item.unfilled.append(f"{place}（{_unfilled_reason(node)}）")
        result.important.append(item)
    return result


def _has_question(entry: Dict) -> bool:
    return bool(str(entry.get("問い合わせ文の案") or "").strip())


def load_data(company: Path, case: str) -> Tuple[Path, Any]:
    """この案件の制度データ（場所、中身）。ない・読めない・会社のフォルダの外を指すときは DataMissing（外は読まない）。"""
    path = seido_path(company, case)
    problem = _outside_problem(company, path, "制度データ")
    if problem:
        raise DataMissing(problem)
    if not path.is_file():
        raise DataMissing(f"制度データ（{path.relative_to(company)}）がありません。先に章ごとの読み取りをまとめてください")
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise DataMissing(f"制度データ（{path.relative_to(company)}）が JSON として読めません（{e}）") from e


# ---- 段階のフォルダ ----


def numbering_problems(folders: List[str]) -> List[str]:
    """段階のフォルダの名前（段階の順）が、1 から順に数えた「<番号>_<名前>」か（DESIGN 4.5：1_申請・2_交付申請・3_実績報告…）。

    読み取り役が、申請の段階を落としたり、書類を出さない段階にもフォルダを付けたりすると、
    いちばん前の段階のフォルダが「2_採択発表」のようになり、社長に見えるフォルダが崩れる（仮の決まり。M2c の差し戻し1回目）。
    """
    problems = []
    for i, name in enumerate(folders, start=1):
        head = name.split("_", 1)[0]
        if not head.isdigit() or int(head) != i:
            problems.append(f"{i}つ目の段階のフォルダが「{name}」です")
    return problems


def make_stage_folders(company: Path, case: str, data: Dict, only: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
    """制度データの手続きの段階から、段階のフォルダを作る。返すのは（作ったフォルダ、対象にした段階のフォルダの名前）。

    only がなければ、いちばん前の段階（申請）のフォルダだけ。名前のない段階を渡されたら case_folder.CaseError。
    """
    folders = case_folder.stage_folders([s for s in data.get("手続きの段階") or [] if isinstance(s, dict)])
    if not folders:
        raise case_folder.CaseError("制度データの手続きの段階に、フォルダの名前（1_申請 など）のある段階がありません")
    numbering = numbering_problems(folders)
    if numbering:
        raise case_folder.CaseError("段階のフォルダの名前が、書類を出す段階を順に数えた「1_申請」「2_交付申請」…の形になっていません"
                                    f"（{'。'.join(numbering)}）。手続きの段階を読み取り役に読ませ直してください")
    wanted = list(only) if only else [folders[0]]
    unknown = [w for w in wanted if w not in folders]
    if unknown:
        raise case_folder.CaseError(f"手続きの段階にないフォルダの名前です：{'・'.join(unknown)}（段階のフォルダは {'・'.join(folders)}）")
    made = case_folder.ensure_stage_folders(company, case, folders, only=wanted)
    return made, wanted


# ---- 結果の文 ----


def _states_line(states: Dict[str, int]) -> str:
    return "、".join(f"{s} {states.get(s, 0)}" for s in (CONFIRMED, CHECK, CONFLICT, UNREADABLE))


def check_report(result: CheckResult, rel: str) -> str:
    lines = [f"制度データを確かめました（{rel}）。", ""]
    if result.schema_errors:
        lines.append(f"- 形（スキーマ）：合いません（{len(result.schema_errors)} か所）")
        lines += [f"  - {e}" for e in result.schema_errors[:20]]
        if len(result.schema_errors) > 20:
            lines.append(f"  - ほかに {len(result.schema_errors) - 20} か所")
    else:
        lines.append("- 形（スキーマ）：合っています")
    lines.append(f"- 出典つき値：{result.values}（{_states_line(result.states)}）。"
                 f"要確認のうち、裏取りで外れた値 {result.downgraded}")
    lines.append(f"- 出典のない値：{len(result.unsourced)}")
    lines += [f"  - {u}" for u in result.unsourced[:20]]
    lines.append(f"- 手続きの段階・様式に当たらない名前：{len(result.bad_refs)}")
    lines += [f"  - {u}" for u in result.bad_refs[:30]]
    if len(result.bad_refs) > 30:
        lines.append(f"  - ほかに {len(result.bad_refs) - 30} か所")
    lines += [f"  - 当たる名前（{k}）" for k in result.ref_known]
    lines.append(f"- 欄も押してよいボタンもない申請画面：{len(result.empty_screens)}")
    if result.empty_screens:
        lines.append(f"  - {'・'.join(result.empty_screens)}（電子申請マニュアルの、その画面のページを読み取り役に読ませる）")
    lines += ["", "重要な項目（締切・補助上限・補助率・数値の要件・必須書類・補助の対象にならない経費）：", "",
              "| 項目 | 件数 | 値 | 値か要確認で埋まった値 | 埋まっていない値 | 任意の欄で読み取れない値（数えない） |",
              "|---|---|---|---|---|---|"]
    for item in result.important:
        lines.append(f"| {item.name} | {item.entries} | {item.values} | {item.filled} | {len(item.unfilled)} "
                     f"| {len(item.optional_unreadable)} |")
    for item in result.important:
        if item.entries == 0:
            lines.append(f"- {item.name}：1件もありません。読み取り役に、その章を読ませてください")
        for u in item.unfilled[:10]:
            lines.append(f"- {item.name}の埋まっていない値：{u}")
    for item in result.important:
        for u in item.optional_unreadable[:10]:
            lines.append(f"- {item.name}の任意の欄で読み取れない値：{u}（埋まっていないに数えず、空けたまま社長に伝え、問い合わせ文の案を作る）")
    if result.unreadable_items:
        lines += ["", f"読み取れない値：{len(result.unreadable_items)}（空けたまま社長に伝え、問い合わせ文の案を作る）"]
        lines += [f"- {u}" for u in result.unreadable_items[:30]]
    lines += ["", f"読み取れなかった項目：{result.unread_listed}（問い合わせ文の案があるもの {result.unread_with_question}）"]
    if result.question_missing:
        lines.append(f"- 読み取れない値のうち、同じ項目の問い合わせ文の案がまだないもの：{len(result.question_missing)}")
        lines += [f"  - {u}" for u in result.question_missing[:30]]
    lines.append("")
    if result.ok:
        optional = sum(len(i.optional_unreadable) for i in result.important)
        lines.append("結果：形が合い、重要な項目はすべて値か「要確認」で埋まり、出典のない値は0件です。"
                     "書類の手続きと段階の様式は、どれも手続きの段階の id・様式の名前に当たります。"
                     + (f"重要な項目の任意の欄で読み取れない値 {optional} は、埋まっていないに数えず、問い合わせ文の案に回します。"
                        if optional else ""))
    else:
        lines.append("結果：まだ足りないところがあります（上の一覧）。")
    return "\n".join(lines) + "\n"


def merge_report(case: str, merged: MergeResult, verified: urakadori.Result, rel: str) -> str:
    lines = [f"章ごとの読み取りを、1つの制度データにまとめました（案件：{case}、制度データの公募回：{merged.data_round}）。", ""]
    lines.append(f"- まとめた章：{len(merged.chapters)}")
    for name, keys in merged.chapters:
        lines.append(f"  - {name}：{'・'.join(keys) if keys else '（項目なし）'}")
    if merged.skipped:
        lines.append(f"- 使わなかった結果：{'、'.join(merged.skipped)}")
    if merged.not_read:
        lines.append(f"- どの章でも読み取っていない項目（「読み取れなかった項目」に入れました）：{'・'.join(merged.not_read)}")
    for c in merged.conflicts:
        lines.append(f"- {c}")
    for d in merged.duplicates:
        lines.append(f"- 同じ名前の件が2つ以上あります（章をまたいで重ねて読んでいないか確かめる）：{d}")
    if merged.second_chapters:
        lines.append(f"- 重要な項目の2回目の読み取り：{'、'.join(merged.second_chapters)}（比べた値 {merged.double_compared}、"
                     f"食い違って要確認にした値 {len(merged.double_diffs)}）")
    else:
        lines.append("- 重要な項目の2回目の読み取り：まだありません（締切・補助上限・補助率・数値の要件・必須書類・"
                     "補助の対象にならない経費を含む章を、読み取り役にもう一度、初めから読ませてください）")
    if merged.double_diffs:
        lines += ["", "2回の読み取りで食い違った値（要確認にしました）：", "", "| 場所 | わけ |", "|---|---|"]
        for where, why in merged.double_diffs:
            lines.append(f"| {where} | {why} |")
        lines.append("")
    if merged.second_only:
        lines.append(f"- 2回目の読み取りにだけある件（まとめには入れていません。その章を読み直させる）：{'、'.join(merged.second_only)}")
    lines.append(f"- 裏取りし直した値：{verified.checked}（出典つき値 {verified.values}：{_states_line(verified.states)}）")
    if verified.downgraded or verified.conflicts_flagged:
        lines += ["", "裏取りで外れた値（要確認にしました）：", "", "| 場所 | 理由 |", "|---|---|"]
        for f in verified.downgraded + verified.conflicts_flagged:
            lines.append(f"| {f.where} | {'。'.join(f.problems)} |")
    lines.append(f"- 置き場所：{rel}")
    return "\n".join(lines) + "\n"


__all__ = [
    "IMPORTANT", "CheckResult", "DataMissing", "ImportantItem", "MergeError", "MergeResult", "check", "check_report",
    "data_round", "load_data", "make_stage_folders", "merge", "merge_and_save", "merge_report", "reference_problems",
    "seido_path",
]
