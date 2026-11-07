"""読み取り役が返した制度データの下書きを、形と出典で裏取りする（SPEC F3、DESIGN 9.2、TASKS M2b）。

流れ：
1. 形を確かめる（schema/制度データ.schema.json。lib/schema_lite.py）。
   - 章ごとの読み取りの結果（読み取り役が返す形。下の CHAPTER_FORM）は、入っている項目だけを確かめる。
   - 制度データの全体（「スキーマの版」があるもの）は、全体の形を確かめる。
   形が合わなければ、何も書かずに誤りの一覧を返す（読み取り役に返し直してもらう）。
2. 置き場所を決める。置き場所は道具が決め、ほかの場所には書かない（DESIGN 5章「スクリプトは決まった名前でしか書かない」）。
   - 章ごとの読み取り：`記録/制度データ/読み取り/<案件>/<章>_<回目>回目.json`
   - 制度データの全体：`記録/制度データ/<制度の略称>_<公募回>.json`（DESIGN 9章）。
     略称は、案件の `資料の一覧.json` の「制度」が同じ名前のときにその略称を使い、なければ制度の名前を使う（仮）。
     公募回は、制度データの「制度」の公募回。
   - 名前に版の名前の語（「_v2」「最終」「修正版」「コピー」など）があれば、何も書かない（版のファイルを増やさない）。
   - 置き場所が、別名をたどった後も `記録/制度データ/` の中にあり、途中に別名がないことを確かめる。
   - 読む材料（`記録/資料の本文/` の案件の一覧、案件の `資料の一覧.json`、出典のページの本文）も、別名と「..」を
     たどった後に会社のフォルダの中にあるときだけ読む。外なら読まず、何も書かない（DESIGN 5章。確かめは lib/places.py）。
3. 同じ章・同じ回目の結果がすでにあれば、渡された項目（「補助額」など）だけを前の結果に差し替え、
   ほかの項目は前の結果のまま残して、章の全体を照らし直す（外れた項目だけを読み直して通すため）。
4. 前にこの道具が足した「裏取り：」の注記を除き、この道具が下げた状態を、読み取り役が付けた状態に戻す。
   そのうえで照らし直す（直した値は外れなくなり、直していない値は同じ理由でまた要確認になる。何度通しても同じ結果）。
5. 値ごとに裏取りする。値は「値・出典・根拠の文・状態」の組（出典つき値）で持つ（DESIGN 9章）。
   - 根拠の文が、出典のページ（`記録/資料の本文/<案件>/<資料 id>/` の文字。lib/doc_text.py）に本当にあるか。
     比べる前に、文字の形をそろえ（NFKC）、空白と改行を除く（PDF の文字は、行の途中で切れたり空白が入ったりするため）。
     根拠の文は「…」で区切って、いくつかの切れ端にしてよい（長い文を縮めるときや、2か所の文を合わせるとき）。
     切れ端は、どれも出典のページのどれかにあること。「…」のほかに文字のない根拠の文は、根拠の文がないものとする。
   - 値が、その根拠の文の中にあるか。
     - 金額（補助額の上限、上限の特例の値、経費の上限の金額。どれも円）は、根拠の文の「万円」「億円」「円」の付いた数を
       円にしたものと同じであること（「1,500万円」は 15000000 だけ。単位をかける前の 1500 や、人数・割合の数字は金額と読まない）。
     - ほかの数（人数・日数・割合・年など）は、すべて根拠の文の中にあること（「令和8年」は 2026 と 8 の両方と読む）。
     - 補助率（1/2 など）は、「1/2」か「2分の1」の形で根拠の文にあること。
     - 日付と時刻は、月日（と時刻）が根拠の文にあること。年は、根拠の文の同じ日付に書いてあれば合っていること。
     - 期間（期限の「出来事からの期間」の期間、繰り返しの間隔、提出期間の長さ）は、数のすぐ後ろに単位の語があること
       （日：「日」。か月：「か月」「ヶ月」「カ月」「ヵ月」「ケ月」「箇月」「月間」。年：「年」「か年」など）。
       数が 1 なら「毎日」「毎月」「毎年」「年1回」も合っているものとする。「3月14日」の「14日」、「令和9年」の「9年」は期間と読まない。
       「営業日」「週間」は、どの単位とも合わない（要確認にして人が確かめる）。
     - 出来事からの期間の「出来事」は、決まった出来事の言葉（採択・交付決定・交付申請・完了など。EVENT_WORDS）を含むなら、
       その言葉が、根拠の文のその期間の前（1つ前の期間の後から）にあること。前に出来事の言葉が1つもなければ、期間の後ろ
       （次の期間まで）にあればよい。手続きの段階の id なら、その段階の名前で見る。決まった言葉を含まない出来事は照らさない（仮）。
     - 提出期間の「始まりの月」は、「4月」のように、数のすぐ後ろに「月」があること。
     - 経費の上限の「何の上限」が「補助金額」なら、補助金額に当たる言葉（補助金額・補助額・補助上限額・交付申請額など）が
       根拠の文にあること。「補助対象経費」なら、根拠の文が補助金額だけをはっきり言っていない（補助金額・補助金の額・交付申請額が
       あって、補助対象経費・対象経費・対象となる経費がない）こと（仮。資料が「補助上限額」と書いて経費の上限を言うことがあるため）。
     - 文字の値は、そのまま根拠の文にあるか、文字の2字ずつの組の半分以上（仮）が根拠の文にあること
       （値は根拠の文を短く言い換えてよいため。DESIGN 9章）。短い文字（6字まで）は、そのまま根拠の文にあること。
       言葉を比べるときは、句読点・かっこと数字を除く（数は上で別に照らす）。
     - 資料の id を書く欄（様式の入力先の「元のファイル」）は、根拠の文と照らさず、資料の一覧（今の資料と前の回の資料）の id と照らす。
       文字の値の中の資料の呼び名（資料の一覧の id と名前）も、根拠の文の言葉・数とは照らさない
       （根拠の文は資料の中の文で、資料の呼び名は入らない。11/6 のリハーサルで「Wordその1・2」が外れた）。
     - 丸数字は数として読む。①〜⑳は NFKC で数字になるが、黒丸の❶〜❿・⓫〜⓴、二重丸の⓵〜⓾、➀〜➓ はならないので、
       表で数字にそろえる（電子申請マニュアルの流れ「❷ 基本情報」の 2。11/6 のリハーサル）。
   - どれかが外れたら、状態を「要確認」にし、注記に「裏取り：」と理由を書く。外れなければ、状態はそのまま
     （道具は、読み取り役が付けた状態より上げない。読み取り役が「要確認」とした値は、要確認のまま）。
   - 「読み取れない」の値は、出典がないので照らさない（値は null。理由を持つ）。
6. 結果を置く。章ごとの結果を1つの制度データにまとめるのは、M2c。

2回の読み取りで食い違う重要な項目を「要確認」にすることは、B25 で足す。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from lib import case_folder, doc_text, place_text, places
from lib.official_docs import LIST_FILE, RECORDS_DIR, TEXT_DIR  # 資料の本文の置き場所は、取る道具（M2a）と同じ
from lib.schema_lite import Validator, path_label

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = PLUGIN_ROOT / "schema" / "制度データ.schema.json"
SEIDO_DIR = "制度データ"
READING_DIR = "読み取り"

CONFIRMED = "確認済み"
UNREADABLE = "読み取れない"
CONFLICT = "資料で食い違い"
CHECK = "要確認"
NOTE_PREFIX = "裏取り："
NOTE_SEP = "／"
_BEFORE = re.compile(r"（読み取り役は「([^」]+)」としていた）$")

# 照らし方の決まり（仮。作者に確かめる）
MAX_EVIDENCE = 400   # 根拠の文の長さの上限（空白を除いた字数）。これより長いと「値がその文の中にあるか」を確かめにくい
MIN_FRAGMENT = 4     # 「…」で区切った切れ端の、いちばん短い長さ（空白を除いた字数）
SHORT_TEXT = 6       # この字数までの文字の値は、そのまま根拠の文にあることを求める
TEXT_COVERAGE = 0.5  # 文字の値の2字ずつの組のうち、根拠の文にある組の割合の下限

# 版の名前の語（DESIGN 5章「版のファイルを増やさない」）。M0a で版の名前を見張る道具ができたら、そちらの一覧にそろえる（仮）
VERSION_WORDS = re.compile(r"(?i)(?:[_\-\s・](?:v|ver\.?)\d+|最終|修正版|コピー|複製|copy|バックアップ|backup)")

# 文字としては照らさない欄（スキーマの決まった言葉。旬は日付と一緒に照らす。
# 単位・出来事・何の上限は、期間と経費の上限の照らし方で別に照らす）
SKIP_TEXT_KEYS = {"種類", "旬"}
# 金額（円）の欄（値の中の欄の名前）
MONEY_KEYS = {"金額"}
# 資料の id を書く欄（スキーマの「元の様式の資料の id」）。根拠の文の言葉とは照らさず、資料の一覧の id と照らす
# （根拠の文は資料の中の文なので、資料の呼び名は入らない。11/6 のリハーサルで「Wordその1・2」が外れた）
DOC_ID_KEYS = {"元のファイル"}
# 補助額の特例のうち、値が金額のもの（スキーマで「補助率の置き換え」のほかは出典つきの金額）
MONEY_SPECIALS = {"上限の置き換え", "上限の上乗せ"}

ELLIPSIS = re.compile(r"…+|‥+|⋯+|\.{3,}|・{3,}")


def _circled_table() -> Dict[int, str]:
    """NFKC で数字にならない丸数字（黒丸の❶〜❿・⓫〜⓴、二重丸の⓵〜⓾、サンセリフの➀〜➓、⓿）を数字にする表。
    ①〜⑳・㉑〜㊿ は NFKC で数字になる（「1」「21」）ので、同じ形（前後に区切りを入れない）にそろえる。
    電子申請マニュアルの流れ（❶ 宣誓・手引き ❷ 基本情報 …）の順番を、数として読むため（11/6 のリハーサル）。"""
    table: Dict[int, str] = {}
    for start, first in ((0x2776, 1), (0x2780, 1), (0x278A, 1), (0x24F5, 1), (0x24EB, 11)):
        for k in range(10):
            table[start + k] = str(first + k)
    table[0x24FF] = "0"
    table[0x1F10B] = "0"
    table[0x1F10C] = "0"
    return table


_CIRCLED = _circled_table()
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−－﹣"})
_TILDES = str.maketrans({c: "~" for c in "〜～∼"})
_SPACES = re.compile(r"[\s​‌‍﻿]+")
_DIGIT_GAP = re.compile(r"(?<=\d)[\s​‌‍﻿]+(?=\d)")
_PUNCT = re.compile(r"[、。,.・･「」『』()\[\]【】〔〕{}<>〈〉《》:;!?\"'“”‘’※*/\-~|]")
_NUM_COMMA = re.compile(r"(?<=\d),(?=\d)")
_NUMERIC_CHARS = re.compile(r"[0-9%+=]")

# 読み取り役が返す形（章ごと）。「制度データ」には、制度データのスキーマの項目のうち、その章で読んだものだけを入れる
CHAPTER_FORM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["読み取り", "制度データ"],
    "properties": {
        "読み取り": {
            "type": "object",
            "additionalProperties": False,
            "required": ["章", "読んだページ"],
            "properties": {
                "章": {"type": "string", "minLength": 1},
                "読んだページ": {"$ref": "#/$defs/出典の一覧"},
                "回目": {"enum": [1, 2]},
                "案件": {"type": "string"},
            },
        },
        "制度データ": {"type": "object"},
        "メモ": {"type": "array", "items": {"type": "string"}},
        # 前にこの道具が置いた結果を、もう一度通すとき（中身は作り直す）
        "裏取り": {"type": "object"},
    },
}

# 「税」の欄の言葉と、根拠の文にあるべき言葉
TAX_WORDS = {"税抜き": ("税抜", "税別"), "税込み": ("税込",)}

# 期間の単位ごとの、根拠の文の書き方（数のすぐ後ろに付く語）と、数の前に来てはいけない字
# （日：「3月14日」の 14 は日付。年：「令和9年」の 9 は元号の年。どれも、数の途中から読まない）
UNIT_FORMS = {
    "日": ("日",),
    "か月": ("か月", "カ月", "ヵ月", "ヶ月", "ケ月", "箇月", "月間"),
    "年": ("年", "か年", "カ年", "ヵ年", "ヶ年", "ケ年", "箇年"),
}
_UNIT_LEFT = {"日": r"(?<![\d.月])", "か月": r"(?<![\d.])", "年": r"(?<![\d.和成])"}
_UNIT_DIGITS = {"日": r"\d+", "か月": r"\d+", "年": r"\d{1,3}"}  # 4桁の年（2027年）は期間と読まない
# 数が 1 の期間の、数を書かない言い方（間隔の「毎年」など）
_EVERY = {"日": r"毎日", "か月": r"毎月", "年": r"毎年|(?<![\dかカヵヶケ箇])年に?1回"}


def _unit_alt(unit: str) -> str:
    return "(?:" + "|".join(re.escape(w) for w in UNIT_FORMS[unit]) + ")"


# 根拠の文の中の、どの単位の期間にも当たる所（出来事を、どの期間の前の文で探すかを決めるのに使う）
_ANY_PERIOD = re.compile("|".join(_UNIT_LEFT[u] + _UNIT_DIGITS[u] + _unit_alt(u) for u in UNIT_FORMS))

# 決まった出来事の言葉（仮）。出来事の値がこの言葉を含めば、根拠の文の期間の前（か後ろ）に、同じ出来事の言葉があることを求める
EVENT_WORDS = (
    ("採択", ("採択",)),
    ("交付決定", ("交付決定", "交付の決定")),
    ("交付申請", ("交付申請", "交付の申請")),
    ("完了", ("完了",)),
    ("実績報告", ("実績報告", "実績の報告")),
    ("確定", ("確定",)),
    ("支払", ("支払", "入金")),
    ("契約", ("契約",)),
    ("発注", ("発注",)),
    ("締切", ("締切", "締め切")),
)
_ALL_EVENT_WORDS = tuple(w for _name, words in EVENT_WORDS for w in words)

# 経費の上限の「何の上限」（仮）。補助金額の上限は、補助金額に当たる言葉がはっきりあるときだけ通す。
# 補助対象経費の上限は、根拠の文が補助金額だけをはっきり言うときだけ外す（資料が「補助上限額」と書いて経費の上限を言うことがあるため）
SUBSIDY_WORDS = ("補助金額", "補助金の額", "補助額", "補助上限額", "補助金の上限", "交付申請額")
SUBSIDY_CLEAR = ("補助金額", "補助金の額", "交付申請額")
COST_CLEAR = ("補助対象経費", "対象経費", "対象となる経費")


class InputError(ValueError):
    """読み取りの結果の形が合わない（誤りの一覧を持つ）。"""

    def __init__(self, errors: List[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


class PlaceError(ValueError):
    """置き場所を決められない（版の名前の語がある、記録/制度データ/ の外になる、前の結果が読めない）。何も書かない。"""


class OutsideError(PlaceError):
    """読む材料（資料の本文・資料の一覧）が、別名などで会社のフォルダの外を指している（lib/places.py）。

    外のファイルは読まず、何も書かない（DESIGN 5章）。文は、そのまま社長への説明に使える形（lib/place_text.py）。
    """


# ---- 形 ----


def load_schema() -> Dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _validator() -> Tuple[Validator, Dict]:
    schema = load_schema()
    combined = dict(CHAPTER_FORM)
    combined["$defs"] = schema["$defs"]
    return Validator(combined), schema


def is_full(data: Any) -> bool:
    """制度データの全体か（「スキーマの版」がある）。そうでなければ章ごとの読み取りの結果。"""
    return isinstance(data, dict) and "スキーマの版" in data


def _part_errors(part: Dict, validator: Validator, schema: Dict) -> List[str]:
    errors = []
    props = schema["properties"]
    for key, value in part.items():
        if key not in props:
            errors.append(f"制度データ.{key}：制度データにない項目です（項目は {'・'.join(props)}）")
            continue
        errors += validator.errors(value, props[key], ["制度データ", key])
    return errors


def shape_errors(data: Any) -> List[str]:
    """形の誤りの一覧。空なら形が合っている。"""
    if not isinstance(data, dict):
        return ["（全体）：いちばん外側を { } の形にしてください"]
    schema = load_schema()
    if is_full(data):
        return Validator(schema).errors(data)
    validator, schema = _validator()
    errors = validator.errors(data)
    part = data.get("制度データ")
    if isinstance(part, dict):
        if not part:
            errors.append("制度データ：読み取った項目が1つもありません")
        errors += _part_errors(part, validator, schema)
    return errors


def form_for(keys: List[str]) -> Dict:
    """読み取り役に渡す形（指定した項目のスキーマと、そこから使う $defs だけ）。"""
    schema = load_schema()
    props = schema["properties"]
    unknown = [k for k in keys if k not in props]
    if unknown:
        raise InputError([f"制度データにない項目です：{'・'.join(unknown)}（項目は {'・'.join(props)}）"])
    used: Set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref[len("#/$defs/"):]
                if name not in used:
                    used.add(name)
                    collect(schema["$defs"][name])
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    picked = {k: props[k] for k in keys}
    collect(picked)
    collect(CHAPTER_FORM)
    return {
        "読み取りの結果の形": CHAPTER_FORM,
        "制度データの項目": picked,
        "$defs": {k: schema["$defs"][k] for k in schema["$defs"] if k in used},
    }


# ---- 文字の形をそろえる ----


def normalize(text: str) -> str:
    """NFKC にそろえ（NFKC で数字にならない丸数字も数字にする）、ダッシュと波線を1つの形にし、空白と改行を除く。"""
    text = unicodedata.normalize("NFKC", text.translate(_CIRCLED)).translate(_DASHES).translate(_TILDES)
    return _SPACES.sub("", text)


def numeric_form(text: str) -> str:
    """数を読むための形。normalize と同じだが、数字と数字の間の空白は「|」にして残す
    （「※２ 2/3」を「22/3」と読まないように）。"""
    text = unicodedata.normalize("NFKC", text.translate(_CIRCLED)).translate(_DASHES).translate(_TILDES)
    text = _DIGIT_GAP.sub("|", text)
    return _SPACES.sub("", text)


def _for_text(text: str) -> str:
    """言葉を比べるための形。数は別に（厳しく）照らすので、数字と、数に付く記号も除く（「令和8年」と「2026年」を言葉で比べない）。"""
    return _NUMERIC_CHARS.sub("", _PUNCT.sub("", normalize(text)))


def fragments(sentence: str) -> List[str]:
    """根拠の文を「…」で区切った切れ端（形をそろえたもの）。「…」だけなら空。"""
    return [f for f in (normalize(x) for x in ELLIPSIS.split(sentence)) if f]


def numeric_fragments(sentence: str) -> List[str]:
    """根拠の文の切れ端を、数を読むための形にしたもの。"""
    return [f for f in (numeric_form(x) for x in ELLIPSIS.split(sentence)) if f]


# ---- 数 ----

_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"\d+(?:\.\d+)?"
_KNUM = r"[0-9〇一二三四五六七八九十百]+"
_TOKEN = re.compile(
    r"(?P<era>令和|平成)(?P<era_n>\d+|元)年"
    r"|(?P<y>\d{4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})"
    r"|(?P<rn>\d+)/(?P<rd>\d+)"
    rf"|(?P<fd>{_KNUM})分の(?P<fn>{_KNUM})"
    rf"|(?P<oku>{_NUM})億(?:(?P<oku_man>{_NUM})万)?"
    rf"|(?P<man>{_NUM})万"
    rf"|(?P<sen>{_NUM})千"
    rf"|(?P<num>{_NUM})"
)
_ERA_BASE = {"令和": 2018, "平成": 1988}
_YEN = "円"


def _kanji_number(text: str) -> Optional[int]:
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch in _KANJI_DIGITS:
            current = current * 10 + _KANJI_DIGITS[ch] if current else _KANJI_DIGITS[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    return total + current


def _dec(text: str) -> Decimal:
    return Decimal(text)


@dataclass
class Numbers:
    """文字の中の数。

    numbers：数（単位をかけた数。根拠の文の側では、元の数字も入れる）
    ratios：割合（分子, 分母）
    money：金額（円）。「万円」「億円」「千円」「円」の付いた数を円にしたものだけ
    """

    numbers: Set[Decimal] = field(default_factory=set)
    ratios: Set[Tuple[int, int]] = field(default_factory=set)
    money: Set[Decimal] = field(default_factory=set)
    labels: List[str] = field(default_factory=list)


def scan_numbers(text: str, evidence: bool) -> Numbers:
    """text（形をそろえたもの）の中の数を拾う。

    evidence が True なら、根拠の文の側：単位をかけた数のほかに、元の数字も「数」に入れる
    （「1,500万円」から 15000000 と 1500 の両方。「令和8年」から 2026 と 8 の両方）。
    ただし「金額」には、円の付いた数を円にしたもの（15000000）だけを入れる。
    False なら、値の側：単位をかけた数だけを、根拠の文にあることを求める。
    """
    text = _NUM_COMMA.sub("", text)
    out = Numbers()
    for m in _TOKEN.finditer(text):
        g = m.groupdict()
        yen = text[m.end():m.end() + 1] == _YEN
        if g["era"]:
            n = 1 if g["era_n"] == "元" else int(g["era_n"])
            out.numbers.add(Decimal(_ERA_BASE[g["era"]] + n))
            out.labels.append(m.group(0))
            if evidence:
                out.numbers.add(Decimal(n))
        elif g["y"]:
            for part in ("y", "m", "d"):
                out.numbers.add(_dec(g[part]))
            out.labels.append(m.group(0))
        elif g["rn"]:
            out.ratios.add((int(g["rn"]), int(g["rd"])))
            out.labels.append(m.group(0))
            if evidence:
                out.numbers.update({_dec(g["rn"]), _dec(g["rd"])})
        elif g["fd"]:
            den, num = _kanji_number(g["fd"]), _kanji_number(g["fn"])
            if den is not None and num is not None:
                out.ratios.add((num, den))
                out.labels.append(m.group(0))
                if evidence:
                    out.numbers.update({Decimal(num), Decimal(den)})
        elif g["oku"]:
            value = _dec(g["oku"]) * 100000000 + (_dec(g["oku_man"]) * 10000 if g["oku_man"] else 0)
            out.numbers.add(value)
            out.labels.append(m.group(0))
            if yen:
                out.money.add(value)
            if evidence:
                out.numbers.add(_dec(g["oku"]))
                if g["oku_man"]:
                    out.numbers.add(_dec(g["oku_man"]))
        elif g["man"] or g["sen"]:
            value = _dec(g["man"]) * 10000 if g["man"] else _dec(g["sen"]) * 1000
            out.numbers.add(value)
            out.labels.append(m.group(0))
            if yen:
                out.money.add(value)
            if evidence:
                out.numbers.add(_dec(g["man"] or g["sen"]))
        elif g["num"]:
            try:
                value = _dec(g["num"])
            except InvalidOperation:
                continue
            out.numbers.add(value)
            out.labels.append(m.group(0))
            if yen:
                out.money.add(value)
    return out


def _show(d: Decimal) -> str:
    return format(d.normalize(), "f")


# ---- 日付 ----

_ISO = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?(?:T(\d{2}):(\d{2})(?::\d{2})?(?:\+09:00)?)?$")
_YEAR = r"(?:(?P<year>\d{4})年|(?P<era>令和|平成)(?P<era_n>\d+|元)年)?"
_JP_DATE = re.compile(_YEAR + r"(?P<month>\d{1,2})月(?:(?P<day>\d{1,2})日)?")
_SLASH_DATE = re.compile(r"(?:(?P<year>\d{4})/)?(?P<month>\d{1,2})/(?P<day>\d{1,2})")
_TIME = re.compile(r"(?P<h>\d{1,2})(?::(?P<mi>\d{2})|時(?:(?P<mi2>\d{1,2})分)?)")


def _year_of(m: re.Match) -> Optional[int]:
    g = m.groupdict()
    if g.get("year"):
        return int(g["year"])
    if g.get("era"):
        return _ERA_BASE[g["era"]] + (1 if g["era_n"] == "元" else int(g["era_n"]))
    return None


def date_problems(year: int, month: int, day: Optional[int], hour: Optional[int], minute: Optional[int],
                  evidence: str, term: Optional[str] = None) -> List[str]:
    text = _NUM_COMMA.sub("", evidence)
    ok = False
    for pattern in (_JP_DATE, _SLASH_DATE):
        for m in pattern.finditer(text):
            if int(m.group("month")) != month:
                continue
            found_day = m.group("day")
            if day is not None and (found_day is None or int(found_day) != day):
                continue
            if day is None and found_day is not None:
                continue
            y = _year_of(m)
            if y is None or y == year:
                ok = True
    problems = []
    shown = f"{year}年{month}月" + (f"{day}日" if day is not None else "")
    if not ok:
        problems.append(f"日付（{shown}）が根拠の文にありません")
    if hour is not None:
        hit = False
        for m in _TIME.finditer(text):
            mi = m.group("mi") or m.group("mi2")
            if int(m.group("h")) == hour and ((mi is not None and int(mi) == minute) or (mi is None and minute == 0)):
                hit = True
        if not hit:
            problems.append(f"時刻（{hour}:{minute:02d}）が根拠の文にありません")
    if term and term not in text:
        problems.append(f"「{term}」が根拠の文にありません")
    return problems


def _iso_problems(value: str, evidence: str, term: Optional[str] = None) -> Optional[List[str]]:
    m = _ISO.match(value)
    if not m:
        return None
    y, mo, d, hh, mi = m.groups()
    return date_problems(int(y), int(mo), int(d) if d else None, int(hh) if hh else None,
                         int(mi) if mi else None, evidence, term)


# ---- 期間・出来事・始まりの月・何の上限 ----


def _is_period(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"数", "単位"} and value["単位"] in UNIT_FORMS
            and isinstance(value["数"], int) and not isinstance(value["数"], bool))


def _period_label(period: Dict) -> str:
    return f"{period['数']}{period['単位']}"


def period_spans(period: Dict, evidence: str) -> List[Tuple[int, int]]:
    """根拠の文（数を読む形）の中で、期間（数のすぐ後ろに単位の語）に当たる所の（始め、終わり）の一覧。"""
    text = _NUM_COMMA.sub("", evidence)
    unit, n = period["単位"], period["数"]
    if unit == "年" and n >= 1000:
        return []  # 4桁の年は、暦の年と区別できない
    pattern = _UNIT_LEFT[unit] + re.escape(str(n)) + _unit_alt(unit)
    if n == 1:
        pattern += "|" + _EVERY[unit]
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def period_problems(period: Dict, evidence: str, found: Numbers) -> List[str]:
    """期間（数と単位）が、根拠の文に「数のすぐ後ろに単位の語」の形であるか。"""
    if period_spans(period, evidence):
        return []
    n, unit = period["数"], period["単位"]
    if n != 1 and Decimal(n) not in found.numbers:
        return [f"数「{n}」が根拠の文にありません"]
    words = "」「".join(UNIT_FORMS[unit][:3])
    every = f"。数が 1 なら「{_EVERY[unit].split('|')[0]}」も見ます" if n == 1 else ""
    return [f"期間「{_period_label(period)}」が根拠の文にありません"
            f"（根拠の文の「{n}」のすぐ後ろに、単位の語「{words}」などがありません{every}）"]


def _event_concepts(event: str) -> List[Tuple[str, Tuple[str, ...]]]:
    text = normalize(event)
    return [(name, words) for name, words in EVENT_WORDS if any(w in text for w in words)]


def event_problems(event: Any, period: Dict, evidence: str, steps: Optional[Dict[str, str]]) -> List[str]:
    """出来事からの期間の「出来事」が、根拠の文のその期間の前（前に出来事の言葉がなければ後ろ）にあるか。

    前の文は、1つ前の期間（どの単位でも）の後から、その期間の前まで。後ろの文は、その期間の後から次の期間の前まで。
    決まった出来事の言葉（EVENT_WORDS）を含まない出来事は照らさない（手続きの段階の id は、その段階の名前で見る）。
    """
    if not isinstance(event, str) or not event:
        return []
    name = steps.get(event) if steps and event in steps else event
    concepts = _event_concepts(name or "")
    if not concepts:
        return []
    text = _NUM_COMMA.sub("", evidence)
    spans = period_spans(period, text)
    if not spans:
        return []  # 期間がないことは、期間の照らしで書く
    bounds = [(m.start(), m.end()) for m in _ANY_PERIOD.finditer(text)]
    for start, end in spans:
        before_from = max([e for s, e in bounds if e <= start] + [0])
        after_to = min([s for s, e in bounds if s >= end] + [len(text)])
        before, after = text[before_from:start], text[end:after_to]
        place = before if any(w in before for w in _ALL_EVENT_WORDS) else before + after
        if all(any(w in place for w in words) for _n, words in concepts):
            return []
    shown = "・".join(words[0] for _n, words in concepts)
    via = f"（手続きの段階「{name}」）" if name != event else ""
    return [f"出来事「{event}」{via}に当たる言葉（{shown}）が、根拠の文の期間「{_period_label(period)}」の前にありません"]


def month_problems(month: int, evidence: str) -> List[str]:
    """提出期間の「始まりの月」が、根拠の文に「4月」の形であるか（「4か月」の 4 は月と読まない）。"""
    text = _NUM_COMMA.sub("", evidence)
    if re.search(rf"(?<![\d.]){month}月", text):
        return []
    return [f"始まりの月「{month}月」が根拠の文にありません"]


def limit_kind_problems(kind: Any, evidence: str) -> List[str]:
    """経費の上限の「何の上限」が、根拠の文と食い違わないか（SUBSIDY_WORDS・SUBSIDY_CLEAR・COST_CLEAR の注を見る）。"""
    if kind == "補助金額":
        if any(w in evidence for w in SUBSIDY_WORDS):
            return []
        return [f"「補助金額」の上限に当たる言葉（{'・'.join(SUBSIDY_WORDS)}）が根拠の文にありません"]
    if kind == "補助対象経費":
        clear = [w for w in SUBSIDY_CLEAR if w in evidence]
        if clear and not any(w in evidence for w in COST_CLEAR):
            return [f"根拠の文は「{clear[0]}」の上限で、「補助対象経費」の上限に当たる言葉（{'・'.join(COST_CLEAR)}）がありません"]
    return []


# ---- 値が根拠の文の中にあるか ----


def number_problems(text: str, found: Numbers) -> List[str]:
    """text（値の側の文字）の数が、すべて根拠の文の側にあるか。"""
    want = scan_numbers(numeric_form(text), evidence=False)
    problems = []
    for n in sorted(want.numbers):
        if n not in found.numbers:
            problems.append(f"数「{_show(n)}」が根拠の文にありません")
    for r in sorted(want.ratios):
        if r not in found.ratios:
            problems.append(f"割合「{r[0]}/{r[1]}」が根拠の文にありません")
    return problems


def text_found(text: str, evidence: str) -> bool:
    t = _for_text(text)
    e = _for_text(evidence)
    if not t or t in e:
        return True
    if len(t) <= SHORT_TEXT:
        return False
    grams = {t[i:i + 2] for i in range(len(t) - 1)}
    hit = sum(1 for g in grams if g in e)
    return hit / len(grams) >= TEXT_COVERAGE


def _short(text: str, limit: int = 30) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def doc_id_problems(doc_id: str, docs: Optional[Dict[str, str]]) -> List[str]:
    """資料の id を書く欄（元のファイル）が、資料の一覧の id か。docs（id → 資料の名前）が分からなければ照らさない。"""
    if docs is None or doc_id in docs:
        return []
    named = [i for i, name in docs.items() if name and normalize(name) == normalize(doc_id)]
    if named:
        return [f"「{_short(doc_id)}」は資料の名前です。資料の一覧の id（「{named[0]}」）を書いてください"]
    return [f"「{_short(doc_id)}」が、資料の一覧の id にありません（資料の id：{'・'.join(sorted(docs)) or 'なし'}）"]


def _without_doc_names(text: str, docs: Optional[Dict[str, str]]) -> str:
    """文字の値から、資料の呼び名（資料の一覧の id と名前）を除く。根拠の文は資料の中の文なので、
    「Wordその1・2 の様式」のように値が資料を名指ししていても、その呼び名は根拠の文にない（11/6 のリハーサル）。"""
    if not docs:
        return text
    names = sorted({numeric_form(n) for i, name in docs.items() for n in (i, name) if isinstance(n, str)},
                   key=len, reverse=True)
    text = numeric_form(text)  # 数字の間の空白は「|」で残す（数の読み方を変えない）
    for n in names:
        if len(n) >= 2:
            text = text.replace(n, "|")
    return text


def value_problems(value: Any, evidence: str, key: Optional[str] = None, money: bool = False,
                   steps: Optional[Dict[str, str]] = None, docs: Optional[Dict[str, str]] = None) -> List[str]:
    """値（出典つき値の「値」）が、根拠の文（数を読む形にそろえ、切れ端を「|」でつないだもの）の中にあるか。

    money が True なら、値は金額（円）：根拠の文の円の付いた数を円にしたものと同じであることを求める。
    steps は、手続きの段階の id と名前（出来事が段階の id のとき、名前で照らすため）。
    docs は、資料の一覧の id と名前（元のファイルは id と照らし、文字の値の資料の呼び名は言葉として照らさない）。
    """
    found = scan_numbers(evidence, evidence=True)
    if value is None:
        return ["値がありません（読み取れないなら、状態を「読み取れない」にして理由を書く）"]
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        n = Decimal(str(value))
        if money or key in MONEY_KEYS:
            if n in found.money:
                return []
            return [f"金額「{_show(n)}円」が根拠の文にありません（根拠の文の「万円」「億円」「円」の付いた数を、円にして照らします）"]
        return [] if n in found.numbers else [f"数「{_show(n)}」が根拠の文にありません"]
    if isinstance(value, str):
        iso = _iso_problems(value, evidence)
        if iso is not None:
            return iso
        if re.fullmatch(r"\d+/\d+", value.strip()):
            return number_problems(value, found)
        text = _without_doc_names(value, docs)  # 資料の呼び名は、根拠の文の言葉・数と照らさない
        problems = number_problems(text, found)
        if key not in SKIP_TEXT_KEYS and not text_found(text, evidence):
            problems.append(f"「{_short(value)}」に当たる言葉が根拠の文にありません")
        return problems
    if isinstance(value, list):
        problems = []
        for i, item in enumerate(value):
            problems += [f"{i + 1}つ目：{p}" for p in value_problems(item, evidence, key, money, steps, docs)]
        return problems
    if isinstance(value, dict):
        if set(value) == {"日時"} and isinstance(value["日時"], str):
            return _iso_problems(value["日時"], evidence) or []
        if "年月" in value and isinstance(value["年月"], str):
            m = re.match(r"^(\d{4})-(\d{2})$", value["年月"])
            if m:
                return date_problems(int(m.group(1)), int(m.group(2)), None, None, None, evidence, value.get("旬"))
        if _is_period(value):
            # 期間（間隔・提出期間の長さも）：数と単位を組で照らす（数だけが別の所にあっても通さない）
            return period_problems(value, evidence, found)
        problems = []
        handled: Set[str] = set()
        if value.get("種類") == "出来事からの期間" and _is_period(value.get("期間")):
            problems += period_problems(value["期間"], evidence, found)
            problems += event_problems(value.get("出来事"), value["期間"], evidence, steps)
            handled |= {"出来事", "期間"}
        if "何の上限" in value:
            problems += limit_kind_problems(value["何の上限"], evidence)
            handled.add("何の上限")
        for k, item in value.items():
            if k in handled:
                continue
            if k == "税" and item in TAX_WORDS:
                if not any(w in evidence for w in TAX_WORDS[item]):
                    problems.append(f"「{item}」（{'・'.join(TAX_WORDS[item])}）が根拠の文にありません")
                continue
            if k in SKIP_TEXT_KEYS and isinstance(item, str):
                continue
            if k in DOC_ID_KEYS and isinstance(item, str):
                problems += doc_id_problems(item, docs)
                continue
            if k == "日時" and isinstance(item, str):
                problems += _iso_problems(item, evidence) or []
                continue
            if k == "始まりの月" and isinstance(item, int) and not isinstance(item, bool):
                problems += month_problems(item, evidence)
                continue
            problems += value_problems(item, evidence, k, steps=steps, docs=docs)
        return problems
    return []


# ---- 出典のページの文字 ----


def _bad_doc_id(doc_id: Any) -> bool:
    """資料の id が、資料の本文のフォルダの名前として使えないか（外の場所を指させない）。"""
    return (not isinstance(doc_id, str) or not doc_id or doc_id.startswith(".")
            or any(c in doc_id for c in "/\\:\x00"))


class Texts:
    """案件の資料の本文（`記録/資料の本文/<案件>/`）。

    読む前に、別名と「..」をたどった後も会社のフォルダの中かを確かめる（lib/places.py）。外なら読まずに OutsideError。
    """

    def __init__(self, company: Path, case: str) -> None:
        self.company = company
        self.root = company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case)
        self._cache: Dict[Tuple[str, Optional[int]], Optional[str]] = {}
        self._inside: Set[Path] = set()  # 中にあると確かめた場所（値ごとに確かめ直さない）

    def exists(self) -> bool:
        return self.root.is_dir()

    def doc_names(self) -> Optional[Dict[str, str]]:
        """資料の一覧（今の資料と前の回の資料）の id → 名前。一覧がなければ、本文のある資料のフォルダの名前。
        どちらもなければ None（元のファイルの id を照らさない）。一覧が会社のフォルダの外なら、読まずに OutsideError。"""
        if hasattr(self, "_docs"):
            return self._docs
        docs: Optional[Dict[str, str]] = None
        listed = self.root / LIST_FILE
        self.check_inside(listed)
        try:
            data = json.loads(listed.read_text(encoding="utf-8")) if listed.is_file() else None
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            docs = {}
            for d in list(data.get("資料") or []) + list(data.get("前の回の資料") or []):
                if isinstance(d, dict) and isinstance(d.get("id"), str):
                    docs[d["id"]] = str(d.get("名前") or "")
        elif self.root.is_dir():
            docs = {d.name: "" for d in self.root.iterdir() if (d / doc_text.INDEX_FILE).is_file()} or None
        self._docs = docs
        return docs

    def doc_dir(self, doc_id: str) -> Path:
        return self.root / doc_id

    def check_inside(self, path: Path) -> None:
        """path が、別名と「..」をたどった後も会社のフォルダの中か。外なら、読まずに OutsideError。"""
        if path in self._inside:
            return
        try:
            shown = path.relative_to(self.company).as_posix()
        except ValueError:  # ページの対応の「ファイル」が絶対の場所のとき（外なので、下で断る）
            shown = path.name
        problem = place_text.read_problem(self.company, path, f"資料の本文（{shown}）")
        if problem:
            raise OutsideError(problem)
        self._inside.add(path)

    def pages(self, source: Dict) -> Tuple[List[Tuple[str, str]], List[str]]:
        """出典（資料・ページ・終わりのページ）の、（ページの名前、形をそろえた文字）の一覧と、問題の一覧。"""
        doc_id = source.get("資料", "")
        label = f"{doc_id}"
        if _bad_doc_id(doc_id):
            return [], [f"出典の資料の id「{doc_id}」の形が違います（資料の一覧の id を書いてください）"]
        doc_dir = self.doc_dir(doc_id)
        self.check_inside(doc_dir)
        self.check_inside(doc_dir / doc_text.INDEX_FILE)
        if not (doc_dir / doc_text.INDEX_FILE).is_file():
            return [], [f"出典の資料「{doc_id}」の本文がありません（資料の id が違うか、文字にしていない資料です）"]
        index = doc_text.load_index(doc_dir)
        page = source.get("ページ")
        if page is None:
            if index.get("種類") == "PDF":
                return [], [f"出典（{label}）にページがありません。PDF の資料は、印刷されたページ番号を書いてください"]
            out = []
            for info in index.get("ページ", []):
                self.check_inside(doc_dir / info["ファイル"])
                out.append((label, normalize(doc_text.read_page(doc_dir, info))))
            return out, []
        if index.get("種類") != "PDF":
            return [], [f"出典（{label} p.{page}）：{index.get('種類')} の資料にはページの番号がありません。ページを書かずに資料だけを示してください"]
        end = source.get("終わりのページ") or page
        if end < page:
            return [], [f"出典（{label} p.{page}）：終わりのページ（{end}）が始めのページより前です"]
        out, problems = [], []
        for n in range(page, end + 1):
            key = (doc_id, n)
            if key not in self._cache:
                # ページの対応から当たるページのファイルを引き、読む前に会社のフォルダの中かを確かめる
                # （ページなしの経路と同じ。ページのファイル1つが外への別名のときも、外を読まない）
                info = doc_text.find_page(index, printed_page=n)
                if info is None:
                    self._cache[key] = None
                else:
                    self.check_inside(doc_dir / info["ファイル"])
                    self._cache[key] = normalize(doc_text.read_page(doc_dir, info))
            if self._cache[key] is None:
                problems.append(f"出典の資料「{doc_id}」に p.{n} がありません")
            else:
                out.append((f"{label} p.{n}", self._cache[key]))
        if len(out) > 1:
            # ページをまたぐ文のために、続けた文字も入れる
            out.append((f"{label} p.{page}–{end}", "".join(t for _l, t in out)))
        return out, problems


def _sources_label(sources: List[Dict]) -> str:
    parts = []
    for s in sources:
        if s.get("ページ") is None:
            parts.append(str(s.get("資料")))
        elif s.get("終わりのページ") and s["終わりのページ"] != s["ページ"]:
            parts.append(f"{s.get('資料')} p.{s['ページ']}–{s['終わりのページ']}")
        else:
            parts.append(f"{s.get('資料')} p.{s['ページ']}")
    return "、".join(parts)


def evidence_problems(item: Dict, texts: Texts) -> Tuple[List[str], str]:
    """根拠の文が出典のページにあるか。返すのは（問題の一覧、値を照らすための根拠の文）。"""
    sentence = item.get("根拠の文") or ""
    sources = item.get("出典") or []
    problems: List[str] = []
    if not sources:
        problems.append("出典がありません")
    parts = fragments(sentence)
    if not parts:
        # 空の文や、「…」「...」「・・・」だけの文は、照らす文字がない
        problems.append("根拠の文がありません（ページの文字のとおりに写してください。「…」だけにしない）")
    pages: List[Tuple[str, str]] = []
    missing: List[str] = []
    for s in sources:
        got, lost = texts.pages(s)
        pages += got
        missing += lost
    problems += missing
    if sources and not pages and not missing:
        problems.append(f"出典（{_sources_label(sources)}）に文字がありません")
    total = sum(len(p) for p in parts)
    if total > MAX_EVIDENCE:
        problems.append(f"根拠の文が長すぎます（{total}字。{MAX_EVIDENCE}字まで。値に関わる所だけを抜き出す）")
    if pages:
        for part in parts:
            if len(part) < MIN_FRAGMENT:
                problems.append(f"根拠の文の切れ端「{part}」が短すぎます（{MIN_FRAGMENT}字以上にする）")
            elif not any(part in text for _label, text in pages):
                problems.append(f"根拠の文「{_short(part)}」が、出典のページ（{_sources_label(sources)}）にありません")
    return problems, "|".join(numeric_fragments(sentence))


# ---- 裏取り ----


@dataclass
class Finding:
    where: str
    problems: List[str]


@dataclass
class Result:
    values: int = 0        # 出典つき値の数（読み取れないを含む）
    checked: int = 0       # 照らした値の数（読み取れないを除く出典つき値と、資料どうしの食い違いの値）
    states: Dict[str, int] = field(default_factory=dict)
    downgraded: List[Finding] = field(default_factory=list)
    conflicts_flagged: List[Finding] = field(default_factory=list)
    conflict_values: int = 0
    out_file: str = ""
    replaced: List[Tuple[str, int, int]] = field(default_factory=list)  # 前の結果に差し替えた項目（名前、前の件数、今の件数）
    kept: List[str] = field(default_factory=list)                       # 前の結果のまま残した項目

    @property
    def clean(self) -> bool:
        return not self.downgraded and not self.conflicts_flagged


def _add_note(node: Dict, note: str) -> None:
    existing = node.get("注記")
    if not existing:
        node["注記"] = note
    elif note not in existing:
        node["注記"] = existing + NOTE_SEP + note


def _own_note(problems: List[str], before: Optional[str] = None) -> str:
    """この道具が足す注記。区切りの「／」は、注記を分けるのに使うので、理由の中では「/」にする。"""
    note = NOTE_PREFIX + "。".join(p.replace(NOTE_SEP, "/") for p in problems)
    if before:
        note += f"（読み取り役は「{before}」としていた）"
    return note


def strip_own_notes(node: Dict) -> Optional[str]:
    """前にこの道具が足した「裏取り：」の注記を除く。この道具が状態を下げていたなら、下げる前の状態を返す。"""
    note = node.get("注記")
    if not isinstance(note, str) or NOTE_PREFIX not in note:
        return None
    kept, before = [], None
    for segment in note.split(NOTE_SEP):
        if segment.startswith(NOTE_PREFIX):
            m = _BEFORE.search(segment)
            if m and m.group(1) in (CONFIRMED, CONFLICT):
                before = m.group(1)
        else:
            kept.append(segment)
    if kept:
        node["注記"] = NOTE_SEP.join(kept)
    else:
        del node["注記"]
    return before


def _item_name(item: Any) -> Optional[str]:
    if isinstance(item, dict):
        for key in ("名前", "区分", "項目", "id"):
            if isinstance(item.get(key), str) and item[key]:
                return item[key]
    return None


def readable(path: List[Any], root: Dict) -> str:
    """場所を、社長にも分かる書き方にする。例：補助額「従業員5人以下」の上限"""
    out = ""
    node: Any = root
    for part in path:
        child = node[part] if isinstance(node, (dict, list)) else None
        if isinstance(part, int):
            name = _item_name(child)
            out += f"「{name}」" if name else f"の{part + 1}件目"
        else:
            out += f"の{part}" if out else str(part)
        node = child
    return out


def _is_sourced_value(node: Any) -> bool:
    return isinstance(node, dict) and "値" in node and "状態" in node


def _money_place(path: List[Any], parent: Any) -> bool:
    """出典つき値の場所が、金額（円）の値か（補助額の上限と、上限の特例の値）。"""
    if len(path) >= 3 and path[-1] == "上限" and path[-3] == "補助額":
        return True
    if len(path) >= 5 and path[-1] == "値" and path[-3] == "特例" and path[-5] == "補助額":
        return isinstance(parent, dict) and parent.get("種類") in MONEY_SPECIALS
    return False


def restore(data: Dict) -> None:
    """前にこの道具が足した注記を除き、この道具が下げた状態を、読み取り役が付けた状態に戻す（照らし直す前に）。"""

    def visit(node: Any, top: bool) -> None:
        if _is_sourced_value(node):
            before = strip_own_notes(node)
            if before and node["状態"] == CHECK:
                node["状態"] = before
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if top and key in ("資料", "資料どうしの食い違い"):
                    continue
                visit(value, False)
        elif isinstance(node, list):
            for value in node:
                visit(value, False)

    visit(data, True)
    for entry in data.get("資料どうしの食い違い") or []:
        if isinstance(entry, dict):
            strip_own_notes(entry)


def verify(data: Dict, texts: Texts) -> Result:
    """data（形を確かめた後の、章ごとの結果の「制度データ」か、制度データの全体）を、その場で直す。"""
    result = Result()
    # 手続きの段階の id と名前（出来事が段階の id のとき、名前で照らす）
    steps = {s["id"]: s["名前"] for s in data.get("手続きの段階") or []
             if isinstance(s, dict) and isinstance(s.get("id"), str) and isinstance(s.get("名前"), str)}
    # 資料の id と名前（元のファイルを id と照らし、文字の値の資料の呼び名は言葉として照らさない）
    docs = texts.doc_names()

    def visit(node: Any, path: List[Any], parent: Any) -> None:
        if _is_sourced_value(node):
            result.values += 1
            if node["状態"] != UNREADABLE:
                result.checked += 1
                problems, evidence = evidence_problems(node, texts)
                if evidence:
                    problems += value_problems(node.get("値"), evidence, money=_money_place(path, parent), steps=steps,
                                               docs=docs)
                if problems:
                    before = node["状態"]
                    node["状態"] = CHECK
                    _add_note(node, _own_note(problems, before if before != CHECK else None))
                    result.downgraded.append(Finding(readable(path, data), problems))
            result.states[node["状態"]] = result.states.get(node["状態"], 0) + 1
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if path == [] and key in ("資料", "資料どうしの食い違い"):
                    continue
                visit(value, path + [key], node)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                visit(value, path + [i], node)

    visit(data, [], None)
    # 資料どうしの食い違い：それぞれの値に出典と根拠の文がある（状態はない）。外れたら、その食い違いの注記に書く
    for i, entry in enumerate(data.get("資料どうしの食い違い") or []):
        for j, item in enumerate(entry.get("値") or []):
            result.checked += 1
            result.conflict_values += 1
            problems, evidence = evidence_problems(item, texts)
            if evidence:
                problems += value_problems(item.get("値"), evidence, docs=docs)
            if problems:
                where = f"資料どうしの食い違い「{entry.get('項目')}」の{j + 1}つ目の値（{_sources_label(item.get('出典') or [])}）"
                _add_note(entry, _own_note([f"{j + 1}つ目の値：" + "。".join(problems)]))
                result.conflicts_flagged.append(Finding(where, problems))
    return result


# ---- 置き場所と、まとめての動かし方 ----


def find_case(company: Path, case: Optional[str]) -> str:
    """裏取りに使う案件。渡されなければ、`記録/資料の本文/` の中の案件が1つのときだけ、それを使う。

    `記録/資料の本文/` が、別名と「..」をたどった後に会社のフォルダの外なら、外の中の一覧を見ずに CaseError（lib/places.py）。
    """
    root = company / RECORDS_DIR / TEXT_DIR
    problem = place_text.read_problem(company, root, f"資料の本文（{RECORDS_DIR}/{TEXT_DIR}/）")
    if problem:
        raise case_folder.CaseError(problem)
    if case:
        name = case_folder.safe_name(case)
        if not (root / name).is_dir():
            raise case_folder.CaseError(f"案件「{name}」の資料の本文（{RECORDS_DIR}/{TEXT_DIR}/{name}/）がありません。先に公式資料を取ってください")
        return name
    found = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not found:
        raise case_folder.CaseError(f"資料の本文（{RECORDS_DIR}/{TEXT_DIR}/）がありません。先に公式資料を取ってください")
    if len(found) > 1:
        raise case_folder.CaseError("案件が2つ以上あります（" + "、".join(found) + "）。--case で案件を渡してください")
    return found[0]


def _no_version_words(name: str, what: str) -> None:
    m = VERSION_WORDS.search(name)
    if m:
        raise PlaceError(f"{what}（{name}）に、版の名前の語「{m.group(0).strip()}」があります。"
                         "版のファイルは増やさないので、何も書いていません（前の版は版の履歴に残ります）。"
                         f"{what}を、資料の書き方のまま（「_v2」「最終」などを付けずに）渡してください")


def seido_dir(company: Path) -> Path:
    return company / RECORDS_DIR / SEIDO_DIR


def chapter_out_path(company: Path, case: str, data: Dict) -> Path:
    """章ごとの結果の置き場所：`記録/制度データ/読み取り/<案件>/<章>_<回目>回目.json`。"""
    info = data["読み取り"]
    _no_version_words(info["章"], "章の名前")
    name = case_folder.safe_name(f"{info['章']}_{info.get('回目', 1)}回目")
    return seido_dir(company) / READING_DIR / case_folder.safe_name(case) / f"{name}.json"


def _abbreviation(company: Path, case: str, seido: Dict) -> str:
    """制度の略称。案件の資料の一覧の「制度」が同じ名前なら、その略称。なければ制度の名前（仮）。

    資料の一覧が、別名と「..」をたどった後に会社のフォルダの外なら、読まずに OutsideError（lib/places.py）。
    """
    path = company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case) / LIST_FILE
    problem = place_text.read_problem(company, path, f"案件の資料の一覧（{path.relative_to(company).as_posix()}）")
    if problem:
        raise OutsideError(problem)
    try:
        listed = json.loads(path.read_text(encoding="utf-8")).get("制度") or {}
    except (OSError, ValueError, AttributeError):
        listed = {}
    if isinstance(listed, dict) and listed.get("名前") == seido.get("名前") and listed.get("略称"):
        return str(listed["略称"])
    return str(seido.get("名前"))


def full_out_path(company: Path, case: str, data: Dict) -> Path:
    """制度データの全体の置き場所：`記録/制度データ/<制度の略称>_<公募回>.json`（DESIGN 9章）。"""
    seido = data["制度"]
    name = case_folder.safe_name(f"{_abbreviation(company, case, seido)}_{seido['公募回']}")
    _no_version_words(name, "制度データの名前")
    return seido_dir(company) / f"{name}.json"


def _check_place(company: Path, out: Path) -> None:
    """置き場所が、別名をたどった後も `記録/制度データ/` の中にあるか（.claude/ や 原本/ などに書かせない。lib/places.py）。"""
    try:
        rel = Path(places.relative_inside(company, out))
    except places.PlaceError:
        raise PlaceError(f"置き場所（{out}）が、会社のフォルダの外になります。何も書いていません")
    if rel.parts[:2] != (RECORDS_DIR, SEIDO_DIR) or out.suffix != ".json":
        raise PlaceError(f"置き場所（{rel}）が、{RECORDS_DIR}/{SEIDO_DIR}/ の中の JSON になりません"
                         "（別名のフォルダかもしれません）。何も書いていません")
    # 別名の先が 記録/制度データ/ の中でも、行き先が別の置き場に変わるので書かない（lib/places.py）
    problem = place_text.write_problem(company, out.relative_to(company).as_posix(), "何も書いていません")
    if problem:
        raise PlaceError(problem)


def _size(value: Any) -> int:
    return len(value) if isinstance(value, list) else 1


def _merge_previous(company: Path, out: Path, data: Dict, result: Result) -> Dict:
    """同じ章・同じ回目の前の結果があれば、渡された項目だけを差し替えた章の全体を返す。なければ渡されたもの。"""
    if not out.exists():
        return data
    rel = out.relative_to(company)
    try:
        previous = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PlaceError(f"この章の前の結果（{rel}）が読めません（{type(e).__name__}）。何も書いていません。"
                         "前の結果を直すか、章の名前を確かめてください")
    old = previous.get("制度データ") if isinstance(previous, dict) else None
    old_info = previous.get("読み取り") if isinstance(previous, dict) else None
    if not isinstance(old, dict) or not isinstance(old_info, dict):
        raise PlaceError(f"この章の前の結果（{rel}）の形が違います（「読み取り」と「制度データ」がありません）。何も書いていません")
    validator, schema = _validator()
    kept = {k: v for k, v in old.items() if k not in data["制度データ"]}
    errors = _part_errors(kept, validator, schema)
    if errors:
        raise PlaceError(f"この章の前の結果（{rel}）のうち、残す項目の形が合いません。何も書いていません：" + "／".join(errors[:5]))
    merged_part = dict(old)
    for key, value in data["制度データ"].items():
        result.replaced.append((key, _size(old[key]) if key in old else 0, _size(value)))
        merged_part[key] = value
    result.kept = list(kept)
    pages: List[Dict] = []
    for p in list(old_info.get("読んだページ") or []) + list(data["読み取り"]["読んだページ"]):
        if isinstance(p, dict) and p not in pages:
            pages.append(p)
    memo: List[str] = []
    for m in list(previous.get("メモ") or []) + list(data.get("メモ") or []):
        if isinstance(m, str) and m not in memo:
            memo.append(m)
    merged = {"読み取り": dict(data["読み取り"], 読んだページ=pages), "制度データ": merged_part}
    if memo:
        merged["メモ"] = memo
    return merged


def run(company: Path, case: str, data: Any) -> Tuple[Result, Dict]:
    """形を確かめ、置き場所を決め、裏取りし、結果を置く。

    形が合わなければ InputError、置き場所を決められなければ PlaceError か case_folder.CaseError（どれも何も書かない）。
    """
    errors = shape_errors(data)
    if errors:
        raise InputError(errors)
    full = is_full(data)
    out = full_out_path(company, case, data) if full else chapter_out_path(company, case, data)
    _check_place(company, out)
    # 出典のページを読む資料の本文も、会社のフォルダの中にあるときだけ読む（資料ごとのフォルダは、読むときに確かめる）
    texts = Texts(company, case)
    texts.check_inside(texts.root)
    merged = Result()  # 前の結果に差し替えた項目と、残した項目だけを持つ
    if not full:
        data = _merge_previous(company, out, data, merged)
    target = data if full else data["制度データ"]
    restore(target)
    result = verify(target, texts)
    result.replaced, result.kept = merged.replaced, merged.kept
    saved = dict(data)
    if not full:
        saved = {
            "読み取り": dict(data["読み取り"], 案件=case, 回目=data["読み取り"].get("回目", 1)),
            "裏取り": summary(result),
            "制度データ": target,
        }
        if data.get("メモ"):
            saved["メモ"] = data["メモ"]
    out.parent.mkdir(parents=True, exist_ok=True)
    _check_place(company, out)  # 作ったフォルダが別名になっていないかを、書く直前にもう一度
    out.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.out_file = str(out.relative_to(company))
    return result, saved


def summary(result: Result) -> Dict:
    out = {
        "照らした値": result.checked,
        "出典つき値": result.values,
        "状態ごとの数": dict(sorted(result.states.items())),
        "要確認にした値": [{"場所": f.where, "理由": f.problems} for f in result.downgraded],
        "食い違いで外れた値": [{"場所": f.where, "理由": f.problems} for f in result.conflicts_flagged],
    }
    if result.replaced:
        out["前の結果に差し替えた項目"] = [{"項目": k, "前の件数": a, "今の件数": b} for k, a, b in result.replaced]
        out["前の結果のまま残した項目"] = list(result.kept)
    return out


def report(result: Result, case: str, label: str) -> str:
    states = result.states
    counts = "、".join(f"{s} {states.get(s, 0)}" for s in (CONFIRMED, CHECK, CONFLICT, UNREADABLE))
    lines = [f"読み取りの結果を裏取りしました（案件：{case}、{label}）。", ""]
    lines.append(f"- 出典つき値：{result.values}（{counts}）")
    extra = f"。資料どうしの食い違いの値 {result.conflict_values} を含む" if result.conflict_values else ""
    lines.append(f"- 照らした値：{result.checked}（読み取れない値は照らしていません{extra}）")
    if result.conflicts_flagged:
        lines.append(f"- 資料どうしの食い違いのうち、裏取りで外れた値：{len(result.conflicts_flagged)}")
    if result.replaced:
        parts = "、".join(f"{k}（{a}件 → {b}件）" for k, a, b in result.replaced)
        lines.append(f"- この章の前の結果に、渡された項目を差し替えました：{parts}")
        if result.kept:
            lines.append(f"- 前の結果のまま残した項目（照らし直しました）：{'、'.join(result.kept)}")
    lines.append(f"- 置き場所：{result.out_file}")
    if result.clean:
        if result.checked == 0:
            lines.append("- 照らせる値がありませんでした（どの値も「読み取れない」です）。"
                         "読み取れない項目は、空けたまま社長に伝え、問い合わせ文の案を作ってください。")
        else:
            lines.append("- 根拠の文はどれも出典のページにあり、値はどれも根拠の文の中にありました。")
        return "\n".join(lines) + "\n"
    lines += ["", "裏取りで外れた値（状態を「要確認」にし、注記に理由を書きました）：", "", "| 場所 | 理由 |", "|---|---|"]
    for f in result.downgraded + result.conflicts_flagged:
        lines.append(f"| {f.where} | {'。'.join(f.problems)} |")
    lines += ["", "外れた値のある項目（「補助額」など）を、読み取り役にもう一度、項目ごと全部読ませてください。"
                  "根拠の文はページの文字のとおりに写させ、値を直させます。返った JSON を同じ章・同じ回目のまま通すと、"
                  "この章の前の結果のその項目だけが差し替わります。直せないものは、要確認のまま社長に示します。"]
    return "\n".join(lines) + "\n"


def error_report(errors: List[str]) -> str:
    lines = ["読み取りの結果の形が、制度データの決まりと合いません。何も書いていません。", "",
             "読み取り役に、次の所を直して返し直してもらってください：", ""]
    lines += [f"- {e}" for e in errors[:40]]
    if len(errors) > 40:
        lines.append(f"- ほかに {len(errors) - 40} か所")
    return "\n".join(lines) + "\n"


__all__ = [
    "CHAPTER_FORM", "InputError", "OutsideError", "PlaceError", "Result", "Texts", "error_report", "event_problems", "find_case",
    "form_for", "fragments", "is_full", "limit_kind_problems", "month_problems", "normalize", "path_label",
    "period_problems", "period_spans", "report", "restore", "run", "scan_numbers", "shape_errors", "strip_own_notes",
    "text_found", "value_problems", "verify",
]
