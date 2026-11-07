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
   - 重要な項目の値を、件ごとに並べ（決まった期日「締切」の日時、補助額「区分」の上限・補助率・特例の値、
     申請の段階の期限、数値の要件「名前」の基準、必須書類「名前」、補助の対象にならない経費「名前」の内容・上限）、
     2回目の章と、同じ名前の1回目の章とで比べる（同じ章の1回目がなければ、まとめた全体と比べる。章の名前は全角・空白をそろえる）。
   - 件の組み方（pair_items）：件名の形（NFKC・空白・かっこを除く）が同じ件を組にし、残りを件名と中身（根拠の文と値）の近さで組にする。
     件名の中の数が食い違う件は組にしない。近さで組にした件は、結果の「件名が1回目と違い…同じ件として比べた件」に並べる
     （黙って同じ件にしない）。同じ件名の件が2つあっても、別の件として比べる。
     読み取り役に1回目の件名を渡して合わせさせる手は取らない（独立に読ませる意味がなくなり、11/6 のリハーサルでは、
     1回目の件名に当たらない件を2回目が落とした）。
   - 比べ方：値の中の数（万・億は円に直す。日付と時刻、割合も数として見る）が同じか。文の言い回しの違いは見ない
     （2回の読み取りで言い方が変わるのはふつうなので）。必須書類は、件があるかだけを見る。一方だけが「読み取れない」も食い違い。
   - 食い違った値は、まとめた制度データで「要確認」にし、「2回の読み取り：」の注記に両方の値を書く（状態は下げるだけ。
     裏取りの道具の「裏取り：」の注記とは別なので、裏取りし直しても戻らない）。
   - 1回目にあって、同じ章の2回目にない重要な項目の件も「要確認」にする（2回目が、その項目そのものを読んでいないときは比べない）。
     2回目の「読んだページ」が、その件の出典のページを1つも含まないときも、2回目がその件を読んでいないので比べず、
     「2回目が出典のページを読んでいないので、比べていない件」として結果に並べる（11/6 のリハーサルで、2回目に公募要領だけを
     読ませ、手引きにある必須書類15件が「2回目の読み取りに、この件がありません」になった）。
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

from lib import case_folder, doc_text, place_text, urakadori
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
    # 件名が違い、近さで同じ件として比べた件（章、項目、1回目の件名、2回目の件名、近さ）
    near_pairs: List[Tuple[str, str, str, str, str]] = field(default_factory=list)
    # 2回目の読んだページに出典のページがなく、比べなかった1回目の件（章、件、出典のページ）
    second_unread: List[Tuple[str, str, str]] = field(default_factory=list)


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


# ---- 件の突き合わせ（2回の読み取りの突き合わせと、lib/kaitei.py の改訂の差で使う） ----
#
# 2つの読み取り（同じ回の1回目と2回目、前の回と今の回）は、同じ件を少し違う件名で書くことがある
# （「締切」と「公募締切日」、「従業員5人以下」と「中小企業（従業員数5人以下）」。11/6 のリハーサル）。
# 件名の文字がまったく同じ件で組にできないとき、件名の近さと、件の中身（根拠の文と値）の近さで組にする。
# 近さで組にした件は、どちらの道具も「近さで同じ件として比べた」と結果に出す（黙って同じ件にしない）。
# 読み取り役に1回目の件名を渡して合わせさせる手は取らない（2回目が独立でなくなり、11/6 のリハーサルでは
# 1回目の件名に当たらない件を2回目が落とした。DESIGN 9.2「別の呼び出しで初めから読ませる」）。

NEAR_NAME_MIN = 0.3   # 仮。件名の近さ（下の name_closeness）がこれより低い組は、中身が近くても組にしない
NEAR_MIN = 0.55       # 仮。件名と中身の近さの平均（中身の文字がなければ件名の近さ）の下限
NAME_STRONG = 0.7     # 仮。件名がこれ以上近ければ（片方の件名がもう片方にそのまま入るなど）、中身の近さによらず組にしてよい
#                       （回が違うと根拠の文の切り方が変わり、中身の近さが低く出る：「締切」と「公募締切日」は 0.19）
NUMBER_GAP = 0.8      # 仮。片方の件名にだけある数があるときに、件名の近さにかける数
_NAME_PUNCT = re.compile(r"[、。,.・･「」『』()\[\]【】〔〕{}<>〈〉《》:;!?\"'“”‘’※*/\-~|_=+＆&＃#]")
_NAME_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def name_form(text: Any) -> str:
    """件名を比べる形：NFKC（丸数字も数字に）、空白・句読点・かっこを除く。"""
    return _NAME_PUNCT.sub("", urakadori.normalize(str(text or "")))


def _grams(text: str) -> set:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def _in_order(short: List[str], long_: List[str]) -> bool:
    """short の並びが、long_ の中に順に（飛び飛びでよい）含まれるか。"""
    it = iter(long_)
    return all(any(x == y for y in it) for x in short)


def name_closeness(a: Any, b: Any) -> float:
    """2つの件名の近さ（0〜1）。形をそろえて同じなら 1。

    件名の中の数（「5人以下」の 5、「基本要件①」の 1）の並びが、どちらも他方の並びに（順に）含まれない組は 0
    （「従業員数5人以下」と「6～20人」、「基本要件①」と「②」、「②…（5年目計画）」と「⑤…（2年目計画）」を組にしない）。
    片方の数の並びがもう片方に含まれるだけの組（「損益計算書」と「損益計算書（直近2期分）」、「1人当たり…」と
    「1人当たり…（基本要件②）」）は、外さずに近さを NUMBER_GAP 倍に下げる。
    ほかは、2字ずつの組の重なり（Dice と、短いほうに対する割合の平均）。短いほうが長いほうにそのまま入っていれば 0.7 以上。
    """
    fa, fb = name_form(a), name_form(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    # 数は、句読点を除く前の形から拾う（「6～20」を 620 と読まない）
    na = _NAME_NUMBER.findall(urakadori.normalize(str(a)))
    nb = _NAME_NUMBER.findall(urakadori.normalize(str(b)))
    if not (_in_order(na, nb) or _in_order(nb, na)):
        return 0.0
    ga, gb = _grams(fa), _grams(fb)
    common = len(ga & gb)
    score = (2 * common / (len(ga) + len(gb)) + common / min(len(ga), len(gb))) / 2
    short, long_ = sorted((fa, fb), key=len)
    if len(short) >= 2 and short in long_:
        score = max(score, 0.7)
    return score if na == nb else score * NUMBER_GAP


def content_closeness(a: str, b: str) -> Optional[float]:
    """2つの件の中身（根拠の文と値の文字）の近さ（0〜1）。2字ずつの組の Dice と、短いほうに対する割合の平均
    （割合だけだと、中身の短い件が、どの長い件とも近くなる）。どちらかが空なら None（分からない）。"""
    ga, gb = _grams(name_form(a)), _grams(name_form(b))
    if not ga or not gb:
        return None
    common = len(ga & gb)
    return (2 * common / (len(ga) + len(gb)) + common / min(len(ga), len(gb))) / 2


def content_text(item: Any) -> str:
    """件の中の出典つき値の、根拠の文と値をつないだ文字（件の中身の近さを見るため）。"""
    out: List[str] = []

    def visit(node: Any) -> None:
        if _is_sourced(node):
            out.append(str(node.get("根拠の文") or ""))
            if node.get("値") is not None:
                out.append(json.dumps(node.get("値"), ensure_ascii=False))
            return
        if isinstance(node, dict):
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(item)
    return "".join(out)


@dataclass
class Pair:
    old: int          # 前（1回目・前の回）の件の位置
    new: int          # 後（2回目・今の回）の件の位置
    near: bool        # 件名がそろわず、近さで組にした
    score: float      # 近さ（同じ件名なら 1）
    name_score: float = 1.0               # 件名の近さ
    content_score: Optional[float] = None  # 中身の近さ（分からなければ None）

    def label(self) -> str:
        """近さの書き方（報告に出す）：件名 0.70・中身 0.19"""
        content = "－" if self.content_score is None else f"{self.content_score:.2f}"
        return f"件名 {self.name_score:.2f}・中身 {content}"


def pair_items(olds: List[Tuple[Any, str]], news: List[Tuple[Any, str]]) -> List[Pair]:
    """（件名、中身の文字）の一覧どうしを、1対1で組にする。

    1. 件名の形（name_form）が同じ件を、前から順に組にする。
    2. 残った件どうしを、近さ（件名の近さと中身の近さの平均。中身が分からなければ件名の近さ）の高い順に組にする。
       組にするのは、件名の近さが NAME_STRONG 以上の組か、中身が分かって近さが NEAR_MIN 以上の組（件名の近さは
       NEAR_NAME_MIN 以上）だけ。組にならない件は、片方にだけある件。
    """
    pairs: List[Pair] = []
    used_old: set = set()
    used_new: set = set()
    new_forms = [name_form(n) for n, _c in news]
    for i, (name, _c) in enumerate(olds):
        form = name_form(name)
        if not form:
            continue
        j = next((j for j, f in enumerate(new_forms) if j not in used_new and f == form), None)
        if j is not None:
            pairs.append(Pair(i, j, False, 1.0))
            used_old.add(i)
            used_new.add(j)
    candidates = []
    for i, (name_a, text_a) in enumerate(olds):
        if i in used_old:
            continue
        for j, (name_b, text_b) in enumerate(news):
            if j in used_new:
                continue
            n = name_closeness(name_a, name_b)
            if n < NEAR_NAME_MIN:
                continue
            c = content_closeness(text_a, text_b)
            # 中身が分からない件（出典つき値のない件）は、件名がよほど近いときだけ組にする
            score = n if c is None else (n + c) / 2
            if n >= NAME_STRONG or (c is not None and score >= NEAR_MIN):
                candidates.append((score, i, j, n, c))
    for score, i, j, n, c in sorted(candidates, key=lambda x: (-x[0], x[1], x[2])):
        if i in used_old or j in used_new:
            continue
        pairs.append(Pair(i, j, True, round(score, 2), round(n, 2), None if c is None else round(c, 2)))
        used_old.add(i)
        used_new.add(j)
    return sorted(pairs, key=lambda p: p.old)


# ---- 重要な項目の件 ----

FIRST_STAGE = "いちばん前の段階"
IMPORTANT_TOPS = ("決まった期日", "補助額", "手続きの段階", "数値の要件", "書類", "補助の対象にならない経費")


@dataclass
class Entry:
    """重要な項目の1件。leaves は、件の中の場所 →（データの中の道、出典つき値、件があるかだけを見るか）。"""
    top: str
    index: int
    name: str
    item: Any
    leaves: Dict[Tuple[str, ...], Tuple[List[Any], Any, bool]] = field(default_factory=dict)
    subs: List["Entry"] = field(default_factory=list)   # 件の中の名前のある件（補助額の特例）
    kind: Optional[str] = None                          # 書類の区分（必須・条件付き・任意）

    @property
    def content(self) -> str:
        return content_text(self.item)


def important_entries(part: Dict) -> Dict[str, List[Entry]]:
    """重要な項目の件を、項目ごとに並べる（同じ件名の件も、別の件として持つ）。

    書類は、区分によらず全部の件を並べる（組にするため）。値を比べるのは、必須の書類の件だけ。
    """
    out: Dict[str, List[Entry]] = {top: [] for top in IMPORTANT_TOPS}
    for i, d in enumerate(part.get("決まった期日") or []):
        if isinstance(d, dict) and DEADLINE_WORD in str(d.get("名前", "")):
            out["決まった期日"].append(Entry("決まった期日", i, str(d.get("名前")), d,
                                          {("日時",): (["決まった期日", i, "日時"], d.get("日時"), False)}))
    for i, a in enumerate(part.get("補助額") or []):
        if not isinstance(a, dict):
            continue
        e = Entry("補助額", i, str(a.get("区分") or ""), a)
        for leaf in ("上限", "補助率"):
            if leaf in a:
                e.leaves[(leaf,)] = (["補助額", i, leaf], a.get(leaf), False)
        for j, s in enumerate(a.get("特例") or []):
            if isinstance(s, dict) and "値" in s:
                e.subs.append(Entry("特例", j, str(s.get("名前") or ""), s,
                                    {("値",): (["補助額", i, "特例", j, "値"], s.get("値"), False)}))
        out["補助額"].append(e)
    stages = [(i, s) for i, s in enumerate(part.get("手続きの段階") or []) if isinstance(s, dict)]
    if stages:
        i, first = min(stages, key=lambda x: x[1].get("順番") if isinstance(x[1].get("順番"), int) else 10 ** 6)
        if "期限" in first:  # いちばん前の段階どうしを比べる（段階の id や名前の違いでは外さない）
            out["手続きの段階"].append(Entry("手続きの段階", i, FIRST_STAGE, first,
                                          {("期限",): (["手続きの段階", i, "期限"], first.get("期限"), False)}))
    for i, r in enumerate(part.get("数値の要件") or []):
        if isinstance(r, dict) and "基準" in r:
            out["数値の要件"].append(Entry("数値の要件", i, str(r.get("名前") or ""), r,
                                         {("基準",): (["数値の要件", i, "基準"], r.get("基準"), False)}))
    for i, d in enumerate(part.get("書類") or []):
        if isinstance(d, dict):
            leaves = {("内容",): (["書類", i, "内容"], d.get("内容"), True)} if d.get("区分") == "必須" else {}
            out["書類"].append(Entry("書類", i, str(d.get("名前") or ""), d, leaves, kind=str(d.get("区分") or "")))
    for i, c in enumerate(part.get("補助の対象にならない経費") or []):
        if not isinstance(c, dict):
            continue
        e = Entry("補助の対象にならない経費", i, str(c.get("名前") or c.get("区分") or i), c,
                  {("内容",): (["補助の対象にならない経費", i, "内容"], c.get("内容"), False)})
        if "上限" in c:
            e.leaves[("上限",)] = (["補助の対象にならない経費", i, "上限"], c.get("上限"), False)
        out["補助の対象にならない経費"].append(e)
    return out


def _sources_of(item: Any) -> List[Dict]:
    out: List[Dict] = []

    def visit(node: Any) -> None:
        if _is_sourced(node):
            out.extend(s for s in node.get("出典") or [] if isinstance(s, dict))
            return
        if isinstance(node, dict):
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(item)
    return out


def _span(source: Dict) -> Optional[Tuple[int, int]]:
    page = source.get("ページ")
    if not isinstance(page, int):
        return None
    end = source.get("終わりのページ") if isinstance(source.get("終わりのページ"), int) else page
    return page, max(page, end)


def read_covers(sources: List[Dict], read: List[Any]) -> bool:
    """出典のどれかが、読んだページ（資料とページの範囲）に入るか。出典がなければ True（分からないので比べる）。
    ページのない出典・読んだページは、資料が同じなら入るとする。"""
    if not sources:
        return True
    for s in sources:
        for r in read:
            if not isinstance(r, dict) or r.get("資料") != s.get("資料"):
                continue
            a, b = _span(s), _span(r)
            if a is None or b is None or (a[0] <= b[1] and b[0] <= a[1]):
                return True
    return False


def _pages_label(sources: List[Dict]) -> str:
    seen: List[str] = []
    for s in sources:
        span = _span(s)
        label = f"{s.get('資料')}" + (f" p.{span[0]}" + (f"–{span[1]}" if span[1] != span[0] else "") if span else "")
        if label not in seen:
            seen.append(label)
    return "、".join(seen[:4]) + ("ほか" if len(seen) > 4 else "")


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


MISSING_ENTRY = "2回目の読み取りに、この件がありません"
MISSING_VALUE = "2回目の読み取りに、この値がありません"


def _walk(root: Any, path: List[Any]) -> Any:
    node = root
    for part in path:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def _full_places(full: Dict, chapters: List[Dict]) -> Dict[Tuple[int, str, int], int]:
    """（1回目の章、重要な項目、章の中の位置）→ まとめた制度データの中の位置。

    まとめた件は章の件の写し（まったく同じ件は1つ）なので、中身が同じ件を引く。要確認にする前に作る。
    同じ名前の件が2つあっても、別の件として引ける（名前では引かない）。
    """
    out: Dict[Tuple[int, str, int], int] = {}
    for top in IMPORTANT_TOPS:
        index: Dict[str, int] = {}
        for j, item in enumerate(full.get(top) or []):
            index.setdefault(json.dumps(item, ensure_ascii=False, sort_keys=True), j)
        for c in chapters:
            for i, item in enumerate(c["制度データ"].get(top) or []):
                j = index.get(json.dumps(item, ensure_ascii=False, sort_keys=True))
                if j is not None:
                    out[(id(c), top, i)] = j
    return out


def compare_readings(full: Dict, chapters: List[Dict], seconds: List[Dict], result: MergeResult) -> None:
    """2回目の読み取りと1回目を、重要な項目で比べ、食い違った値をまとめた制度データで要確認にする（その場で直す）。

    件は、件名の形が同じ件を組にし、残りを件名と中身の近さで組にする（pair_items）。近さで組にした件は、結果に並べる。
    1回目にあって2回目にない件は要確認にする。ただし、2回目の「読んだページ」が、その件の出典のページを1つも含まないときは、
    2回目がその件を読んでいないので比べず、「2回目が読んでいないページの件」として結果に並べる
    （項目そのものを読んでいないときは比べない、という決まりを、ページの範囲にも当てはめる。11/6 のリハーサル）。
    """
    by_name = {_name_key(c["読み取り"].get("章")): c for c in chapters}
    places = _full_places(full, chapters)
    for second in seconds:
        name = str(second["読み取り"].get("章"))
        result.second_chapters.append(name)
        sec_part = second["制度データ"]
        read = [r for r in second["読み取り"].get("読んだページ") or [] if isinstance(r, dict)]
        first = by_name.get(_name_key(name))
        ref_part = first["制度データ"] if first else full

        def full_path(path: List[Any]) -> Optional[List[Any]]:
            """1回目の章の中の道を、まとめた制度データの中の道にする。"""
            if first is None:
                return list(path)
            j = places.get((id(first), path[0], path[1]))
            return None if j is None else [path[0], j] + list(path[2:])

        def flag(path: List[Any], why: str) -> None:
            fp = full_path(path)
            node = _walk(full, fp) if fp is not None else None
            if node is not None and _is_sourced(node):
                _downgrade(node, why)
                result.double_diffs.append((urakadori.readable(fp, full), why))

        def compare(ref: Entry, sec: Entry) -> None:
            if ref.top == "書類" and ref.kind != sec.kind:
                if ref.leaves or sec.leaves:  # どちらかが必須：区分の食い違い（件があるかだけを見る書類の、ただ1つの比べる所）
                    result.double_compared += 1
                    flag(["書類", ref.index, "内容"], f"1回目は「{ref.kind}」、2回目は「{sec.kind}」")
                return
            for key, (path2, node2, presence) in sec.leaves.items():
                if key not in ref.leaves:
                    result.second_only.append(f"{name}：{urakadori.readable(path2, sec_part)}")
                    continue
                result.double_compared += 1
                path1, node1, _ = ref.leaves[key]
                why = readings_differ(node1, node2, presence)
                if why:
                    flag(path1, why)
            for key, (path1, _node1, _p) in ref.leaves.items():
                if key not in sec.leaves:
                    flag(path1, MISSING_VALUE)
            sub_pairs = pair_items([(s.name, s.content) for s in ref.subs], [(s.name, s.content) for s in sec.subs])
            for p in sub_pairs:
                if p.near:
                    result.near_pairs.append((name, urakadori.readable([ref.top, ref.index], ref_part) + "の特例",
                                              ref.subs[p.old].name, sec.subs[p.new].name, p.label()))
                compare(ref.subs[p.old], sec.subs[p.new])
            for i, s in enumerate(ref.subs):
                if i not in {p.old for p in sub_pairs}:
                    for _k, (path1, _n, _p) in s.leaves.items():
                        flag(path1, MISSING_ENTRY)
            for j, s in enumerate(sec.subs):
                if j not in {p.new for p in sub_pairs}:
                    for _k, (path2, _n, _p) in s.leaves.items():
                        result.second_only.append(f"{name}：{urakadori.readable(path2, sec_part)}")

        ref_all, sec_all = important_entries(ref_part), important_entries(sec_part)
        for top in IMPORTANT_TOPS:
            refs, secs = ref_all[top], sec_all[top]
            pairs = pair_items([(e.name, e.content) for e in refs], [(e.name, e.content) for e in secs])
            for p in pairs:
                ref, sec = refs[p.old], secs[p.new]
                if p.near:
                    result.near_pairs.append((name, top, ref.name, sec.name, p.label()))
                compare(ref, sec)
            matched_new = {p.new for p in pairs}
            for j, sec in enumerate(secs):
                if j not in matched_new:
                    for _k, (path2, _n, _p) in sec.leaves.items():
                        result.second_only.append(f"{name}：{urakadori.readable(path2, sec_part)}")
            if first is None or top not in sec_part:
                continue  # 2回目が、その項目そのものを読んでいない
            matched_old = {p.old for p in pairs}
            for i, ref in enumerate(refs):
                if i in matched_old or not (ref.leaves or ref.subs):
                    continue
                sources = _sources_of(ref.item)
                if not read_covers(sources, read):
                    result.second_unread.append((name, urakadori.readable([top, ref.index], ref_part), _pages_label(sources)))
                    continue
                for _k, (path1, _n, _p) in ref.leaves.items():
                    flag(path1, MISSING_ENTRY)
                for s in ref.subs:
                    for _k, (path1, _n, _p) in s.leaves.items():
                        flag(path1, MISSING_ENTRY)


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


# ---- 読み取れないとした期限の手がかり ----
#
# 章ごとに読ませると、段階の期限が、その段階の章とは別の章に書かれているときに落ちる（11/7 の採択後の通し：
# 交付申請の期限「採択発表日から2か月後の日」は、公募要領の補助事業実施期間の節〈p.25〉の※書きにあり、
# 採択後の手続きの章〈p.37〜38〉だけを読ませた交付申請の段階は「読み取れない」になった）。
# 期限が読み取れない段階について、資料の本文から「<段階>は…<出来事>から<数><単位>…期限」の文を探して示す。
# 制度データは書き換えない（直すのは、読み取り役に読ませ直して裏取りの道具に通す junbi の手順）。

CLUE_MAX = 3  # 段階ごとに示す文の数
CLUE_TEXT_MAX = 80  # 示す文の長さ（字）
CLUE_GAP = 20  # 段階の語の終わりから出来事の始まりまでの字数の上限（表の文字が1行につながったページで、離れた語を拾わない）
_CLUE_PERIOD = re.compile(r"([^、。,，「」『』（）()]{1,12}?日)から([0-9]+)(か月|ヶ月|カ月|ケ月|箇月|日|年)")
_CLUE_TAIL = ("期限", "までに")
_CLUE_BRACKETS = re.compile(r"（[^）]*）|\([^)]*\)|【[^】]*】")


@dataclass
class DeadlineClue:
    """期限が読み取れない段階の、期限らしい文（資料の本文から）。"""

    stage: str  # 段階の名前
    doc: str  # 資料の id
    page: Optional[int]  # 印刷されたページ（ずれが分からない資料は PDF のページ。HTML などは None）
    text: str  # 文（形をそろえたもの。長いときは切る）
    rule: str  # 文から読んだ決め方（「採択発表日から2か月」）

    def where(self) -> str:
        return f"{self.doc} p.{self.page}" if self.page is not None else self.doc

    def line(self) -> str:
        return f"{self.where()}「{self.text}」（決め方の見当：{self.rule}）"


def _deadline_unread(stage: Dict) -> bool:
    """段階の期限が読み取れないか（期限の欄が「値」なし。フォルダのある段階は、期限の欄がないときも）。"""
    node = stage.get("期限")
    if isinstance(node, dict):
        return node.get("値") is None
    return node is None and isinstance(stage.get("フォルダ"), str)


def _stage_keys(stage: Dict) -> List[str]:
    """文の中で段階を指す語（id・名前。かっこの中を除き、「・」で分けた語も。2字以上）。"""
    keys: List[str] = []
    for raw in (stage.get("id"), stage.get("名前")):
        if not isinstance(raw, str):
            continue
        whole = urakadori.normalize(_CLUE_BRACKETS.sub("", raw))
        for key in [whole] + whole.split("・"):
            if len(key) >= 2 and key not in keys:
                keys.append(key)
    return keys


def _key_hits(head: str, keys: List[str]) -> List[int]:
    """head の中の段階の語の位置。出来事の名前として使われた語（「採択発表日」の「採択発表」）と、出来事から
    CLUE_GAP 字より離れた語は除く。"""
    hits = []
    for key in keys:
        start = head.find(key)
        while start >= 0:
            end = start + len(key)
            if head[end:end + 1] != "日" and len(head) - end <= CLUE_GAP:
                hits.append(start)
            start = head.find(key, start + 1)
    return hits


def _rule_events(data: Any) -> List[str]:
    """制度データの手続きの段階の期限の決め方にある出来事の名前（形をそろえたもの。長い順）。"""
    found: List[str] = []

    def walk(rule: Any) -> None:
        if not isinstance(rule, dict):
            return
        if rule.get("種類") == "出来事からの期間" and isinstance(rule.get("出来事"), str):
            name = urakadori.normalize(rule["出来事"])
            if name and name not in found:
                found.append(name)
        for part in rule.get("期限") if isinstance(rule.get("期限"), list) else []:
            walk(part)

    stages = data.get("手続きの段階") if isinstance(data, dict) else None
    for stage in stages if isinstance(stages, list) else []:
        node = stage.get("期限") if isinstance(stage, dict) else None
        walk(node.get("値") if isinstance(node, dict) else None)
    return sorted(found, key=len, reverse=True)


def _clues_in(text: str, keys: List[str], events: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """ページの文字から、段階の語が出来事のすぐ前にあり、後ろに「期限」「までに」がある文（文、決め方）。
    出来事の名前は、制度データの期限の決め方にある出来事（events）で終わっていれば、その名前にそろえる
    （「なるべく採択発表日」→「採択発表日」）。"""
    found = []
    for sentence in urakadori.normalize(text).split("。"):
        for m in _CLUE_PERIOD.finditer(sentence):
            head = sentence[:m.start(1)]
            hits = _key_hits(head, keys)
            if not hits or not any(w in sentence[m.end():] for w in _CLUE_TAIL):
                continue
            event = next((e for e in events or [] if m.group(1).endswith(e)), m.group(1))
            unit = "か月" if m.group(3) in ("ヶ月", "カ月", "ケ月", "箇月") else m.group(3)
            start = max(hits)
            shown = sentence[start:start + CLUE_TEXT_MAX]
            if start > 0:
                shown = "…" + shown
            if start + CLUE_TEXT_MAX < len(sentence):
                shown += "…"
            found.append((shown, f"{event}から{int(m.group(2))}{unit}"))
            break
    return found


def _listed_docs(texts: "urakadori.Texts") -> List[str]:
    """資料の一覧の「資料」の id（一覧の順。前の回の資料は見ない）。一覧がなければ、本文のある資料のフォルダの名前。"""
    listed = texts.root / LIST_FILE
    texts.check_inside(listed)
    try:
        data = json.loads(listed.read_text(encoding="utf-8")) if listed.is_file() else None
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict) and isinstance(data.get("資料"), list):
        return [d["id"] for d in data["資料"] if isinstance(d, dict) and isinstance(d.get("id"), str)]
    names = texts.doc_names() or {}
    return sorted(names)


def deadline_clues(company: Path, case: str, data: Any) -> Dict[str, List[DeadlineClue]]:
    """期限が読み取れない段階ごとの、資料の本文にある期限らしい文（段階の名前 → 手がかり。ない段階は入れない）。

    読めない資料・会社のフォルダの外を指す資料は、黙って飛ばす（手がかりは知らせだけなので、切り替えや確かめを止めない）。
    """
    stages = [s for s in (data.get("手続きの段階") or []) if isinstance(s, dict)] if isinstance(data, dict) else []
    wanted = [(str(s.get("名前") or s.get("id") or ""), _stage_keys(s)) for s in stages if _deadline_unread(s)]
    wanted = [(name, keys) for name, keys in wanted if name and keys]
    if not wanted:
        return {}
    events = _rule_events(data)
    out: Dict[str, List[DeadlineClue]] = {}
    try:
        texts = urakadori.Texts(company, case)
        if not texts.exists():
            return {}
        docs = _listed_docs(texts)
    except Exception:
        return {}
    for doc_id in docs:
        if urakadori._bad_doc_id(doc_id):
            continue
        doc_dir = texts.doc_dir(doc_id)
        try:
            texts.check_inside(doc_dir)
            texts.check_inside(doc_dir / doc_text.INDEX_FILE)
            index = doc_text.load_index(doc_dir)
        except Exception:
            continue
        numbered = index.get("ページのずれ") is not None
        for info in index.get("ページ") or []:
            if not isinstance(info, dict) or not isinstance(info.get("ファイル"), str):
                continue
            try:
                texts.check_inside(doc_dir / info["ファイル"])
                text = doc_text.read_page(doc_dir, info)
            except Exception:
                continue
            page = info.get("印刷されたページ") if numbered else info.get("PDFのページ")
            for name, keys in wanted:
                if len(out.get(name, [])) >= CLUE_MAX:
                    continue
                for shown, rule in _clues_in(text, keys, events):
                    out.setdefault(name, []).append(DeadlineClue(stage=name, doc=doc_id, page=page, text=shown, rule=rule))
                    if len(out[name]) >= CLUE_MAX:
                        break
    return out


def clues_report(clues: Dict[str, List[DeadlineClue]]) -> str:
    """seido_data.py の --check・--merge の結果に添える文（手がかりがなければ空）。"""
    if not clues:
        return ""
    lines = ["", f"読み取れないとした段階の期限に、資料の本文で当たりそうな文：{len(clues)}段階"
             "（制度データの抜けかもしれません。その段階を読んだ章を、下のページを足して読み取り役に読ませ直し、"
             "裏取りの道具に通してから、まとめ直す。読ませ直しても読み取れないなら、そのままでよい）"]
    for name, found in clues.items():
        lines.append(f"- {name}の期限：")
        lines += [f"  - {c.line()}" for c in found]
    return "\n".join(lines) + "\n"


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
    if merged.near_pairs:
        lines += ["", f"件名が1回目と違い、件名と中身の近さで同じ件として比べた件：{len(merged.near_pairs)}"
                  "（値の数が同じなら、要確認にしていません。組が違っていれば、その章の2回目を読み直させる）：", "",
                  "| 章 | 項目 | 1回目の件名 | 2回目の件名 | 近さ |", "|---|---|---|---|---|"]
        for chapter, top, a, b, how in merged.near_pairs:
            lines.append(f"| {chapter} | {top} | {a} | {b} | {how} |")
        lines.append("")
    if merged.second_unread:
        lines.append(f"- 2回目の読み取りが出典のページを読んでいないので、比べていない件：{len(merged.second_unread)}"
                     "（1回目だけの読み取りです。その章の2回目を、1回目と同じページの範囲で読ませ直す）")
        for chapter, where, pages in merged.second_unread[:40]:
            lines.append(f"  - {chapter}：{where}（出典 {pages}）")
        if len(merged.second_unread) > 40:
            lines.append(f"  - ほかに {len(merged.second_unread) - 40} 件")
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
    "IMPORTANT", "CheckResult", "DataMissing", "DeadlineClue", "ImportantItem", "MergeError", "MergeResult", "check",
    "check_report", "clues_report", "data_round", "deadline_clues", "load_data", "make_stage_folders", "merge",
    "merge_and_save", "merge_report", "reference_problems", "seido_path",
]
