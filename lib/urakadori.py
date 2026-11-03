"""読み取り役が返した制度データの下書きを、形と出典で裏取りする（SPEC F3、DESIGN 9.2、TASKS M2b）。

流れ：
1. 形を確かめる（schema/制度データ.schema.json。lib/schema_lite.py）。
   - 章ごとの読み取りの結果（読み取り役が返す形。下の CHAPTER_FORM）は、入っている項目だけを確かめる。
   - 制度データの全体（「スキーマの版」があるもの）は、全体の形を確かめる。
   形が合わなければ、何も書かずに誤りの一覧を返す（読み取り役に返し直してもらう）。
2. 値ごとに裏取りする。値は「値・出典・根拠の文・状態」の組（出典つき値）で持つ（DESIGN 9章）。
   - 根拠の文が、出典のページ（`記録/資料の本文/<案件>/<資料 id>/` の文字。lib/doc_text.py）に本当にあるか。
     比べる前に、文字の形をそろえ（NFKC）、空白と改行を除く（PDF の文字は、行の途中で切れたり空白が入ったりするため）。
     根拠の文は「…」で区切って、いくつかの切れ端にしてよい（長い文を縮めるときや、2か所の文を合わせるとき）。
     切れ端は、どれも出典のページのどれかにあること。
   - 値が、その根拠の文の中にあるか。
     - 数（金額・人数・日数・割合・年など）は、すべて根拠の文の中にあること（「1,500万円」は 15000000、「令和8年」は 2026 と読む）。
     - 補助率（1/2 など）は、「1/2」か「2分の1」の形で根拠の文にあること。
     - 日付と時刻は、月日（と時刻）が根拠の文にあること。年は、根拠の文の同じ日付に書いてあれば合っていること。
     - 文字の値は、そのまま根拠の文にあるか、文字の2字ずつの組の半分以上（仮）が根拠の文にあること
       （値は根拠の文を短く言い換えてよいため。DESIGN 9章）。短い文字（6字まで）は、そのまま根拠の文にあること。
       言葉を比べるときは、句読点・かっこと数字を除く（数は上で別に照らす）。
   - どれかが外れたら、状態を「要確認」にし、注記に「裏取り：」と理由を書く。外れなければ、状態はそのまま
     （道具は状態を上げない。読み取り役が「要確認」とした値は、要確認のまま）。
   - 「読み取れない」の値は、出典がないので照らさない（値は null。理由を持つ）。
3. 結果を `記録/制度データ/読み取り/<案件>/<章>_<回目>回目.json` に置く（章ごとの読み取り）。
   章ごとの結果を1つの制度データにまとめるのは、M2c。

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

from lib import case_folder, doc_text
from lib.official_docs import RECORDS_DIR, TEXT_DIR  # 資料の本文の置き場所は、取る道具（M2a）と同じ
from lib.schema_lite import Validator, path_label

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = PLUGIN_ROOT / "schema" / "制度データ.schema.json"
OUT_DIR = ("制度データ", "読み取り")

CONFIRMED = "確認済み"
UNREADABLE = "読み取れない"
CONFLICT = "資料で食い違い"
CHECK = "要確認"
NOTE_PREFIX = "裏取り："

# 照らし方の決まり（仮。作者に確かめる）
MAX_EVIDENCE = 400   # 根拠の文の長さの上限（空白を除いた字数）。これより長いと「値がその文の中にあるか」を確かめにくい
MIN_FRAGMENT = 4     # 「…」で区切った切れ端の、いちばん短い長さ（空白を除いた字数）
SHORT_TEXT = 6       # この字数までの文字の値は、そのまま根拠の文にあることを求める
TEXT_COVERAGE = 0.5  # 文字の値の2字ずつの組のうち、根拠の文にある組の割合の下限

# 文字としては照らさない欄（スキーマの決まった言葉や、手続きの段階の id）
SKIP_TEXT_KEYS = {"種類", "単位", "何の上限", "税", "旬", "出来事"}

ELLIPSIS = re.compile(r"…+|‥+|⋯+|\.{3,}|・{3,}")
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


class InputError(ValueError):
    """読み取りの結果の形が合わない（誤りの一覧を持つ）。"""

    def __init__(self, errors: List[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


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
        props = schema["properties"]
        for key, value in part.items():
            if key not in props:
                errors.append(f"制度データ.{key}：制度データにない項目です（項目は {'・'.join(props)}）")
                continue
            errors += validator.errors(value, props[key], ["制度データ", key])
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
    """NFKC にそろえ、ダッシュと波線を1つの形にし、空白と改行を除く。"""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_TILDES)
    return _SPACES.sub("", text)


def numeric_form(text: str) -> str:
    """数を読むための形。normalize と同じだが、数字と数字の間の空白は「|」にして残す
    （「※２ 2/3」を「22/3」と読まないように）。"""
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_TILDES)
    text = _DIGIT_GAP.sub("|", text)
    return _SPACES.sub("", text)


def _for_text(text: str) -> str:
    """言葉を比べるための形。数は別に（厳しく）照らすので、数字と、数に付く記号も除く（「令和8年」と「2026年」を言葉で比べない）。"""
    return _NUMERIC_CHARS.sub("", _PUNCT.sub("", normalize(text)))


def fragments(sentence: str) -> List[str]:
    """根拠の文を「…」で区切った切れ端（形をそろえたもの）。"""
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
    rf"|(?P<num>{_NUM})"
)
_ERA_BASE = {"令和": 2018, "平成": 1988}


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
    """文字の中の数（required は値の側で求めるもの、found は根拠の文の側で見つかるもの）。"""

    numbers: Set[Decimal] = field(default_factory=set)
    ratios: Set[Tuple[int, int]] = field(default_factory=set)
    labels: List[str] = field(default_factory=list)


def scan_numbers(text: str, evidence: bool) -> Numbers:
    """text（形をそろえたもの）の中の数を拾う。

    evidence が True なら、根拠の文の側：単位をかけた数のほかに、元の数字も見つかったものに入れる
    （「1,500万円」から 15000000 と 1500 の両方。「令和8年」から 2026 と 8 の両方）。
    False なら、値の側：単位をかけた数だけを、根拠の文にあることを求める。
    """
    text = _NUM_COMMA.sub("", text)
    out = Numbers()
    for m in _TOKEN.finditer(text):
        g = m.groupdict()
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
            if evidence:
                out.numbers.add(_dec(g["oku"]))
                if g["oku_man"]:
                    out.numbers.add(_dec(g["oku_man"]))
        elif g["man"]:
            out.numbers.add(_dec(g["man"]) * 10000)
            out.labels.append(m.group(0))
            if evidence:
                out.numbers.add(_dec(g["man"]))
        elif g["num"]:
            try:
                out.numbers.add(_dec(g["num"]))
                out.labels.append(m.group(0))
            except InvalidOperation:
                pass
    return out


def _show(d: Decimal) -> str:
    text = format(d.normalize(), "f")
    return text


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


def value_problems(value: Any, evidence: str, key: Optional[str] = None) -> List[str]:
    """値（出典つき値の「値」）が、根拠の文（形をそろえ、切れ端を「|」でつないだもの）の中にあるか。"""
    found = scan_numbers(evidence, evidence=True)
    if value is None:
        return ["値がありません（読み取れないなら、状態を「読み取れない」にして理由を書く）"]
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        n = Decimal(str(value))
        return [] if n in found.numbers else [f"数「{_show(n)}」が根拠の文にありません"]
    if isinstance(value, str):
        iso = _iso_problems(value, evidence)
        if iso is not None:
            return iso
        if re.fullmatch(r"\d+/\d+", value.strip()):
            return number_problems(value, found)
        problems = number_problems(value, found)
        if key not in SKIP_TEXT_KEYS and not text_found(value, evidence):
            problems.append(f"「{_short(value)}」に当たる言葉が根拠の文にありません")
        return problems
    if isinstance(value, list):
        problems = []
        for i, item in enumerate(value):
            problems += [f"{i + 1}つ目：{p}" for p in value_problems(item, evidence, key)]
        return problems
    if isinstance(value, dict):
        if set(value) == {"日時"} and isinstance(value["日時"], str):
            return _iso_problems(value["日時"], evidence) or []
        if "年月" in value and isinstance(value["年月"], str):
            m = re.match(r"^(\d{4})-(\d{2})$", value["年月"])
            if m:
                return date_problems(int(m.group(1)), int(m.group(2)), None, None, None, evidence, value.get("旬"))
        problems = []
        for k, item in value.items():
            if k == "税" and item in TAX_WORDS:
                if not any(w in evidence for w in TAX_WORDS[item]):
                    problems.append(f"「{item}」（{'・'.join(TAX_WORDS[item])}）が根拠の文にありません")
                continue
            if k in SKIP_TEXT_KEYS and isinstance(item, str):
                continue
            if k == "日時" and isinstance(item, str):
                problems += _iso_problems(item, evidence) or []
                continue
            problems += value_problems(item, evidence, k)
        return problems
    return []


# ---- 出典のページの文字 ----


class Texts:
    """案件の資料の本文（`記録/資料の本文/<案件>/`）。"""

    def __init__(self, company: Path, case: str) -> None:
        self.root = company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case)
        self._cache: Dict[Tuple[str, Optional[int]], Optional[str]] = {}

    def exists(self) -> bool:
        return self.root.is_dir()

    def doc_dir(self, doc_id: str) -> Path:
        return self.root / doc_id

    def pages(self, source: Dict) -> Tuple[List[Tuple[str, str]], List[str]]:
        """出典（資料・ページ・終わりのページ）の、（ページの名前、形をそろえた文字）の一覧と、問題の一覧。"""
        doc_id = source.get("資料", "")
        label = f"{doc_id}"
        doc_dir = self.doc_dir(doc_id)
        if not (doc_dir / doc_text.INDEX_FILE).is_file():
            return [], [f"出典の資料「{doc_id}」の本文がありません（資料の id が違うか、文字にしていない資料です）"]
        index = doc_text.load_index(doc_dir)
        page = source.get("ページ")
        if page is None:
            if index.get("種類") == "PDF":
                return [], [f"出典（{label}）にページがありません。PDF の資料は、印刷されたページ番号を書いてください"]
            out = []
            for info in index.get("ページ", []):
                raw = (doc_dir / info["ファイル"]).read_text(encoding="utf-8")
                out.append((label, normalize(doc_text._strip_header(raw))))
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
                text = doc_text.page_text(doc_dir, printed_page=n)
                self._cache[key] = normalize(text) if text is not None else None
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
    if not sentence.strip():
        problems.append("根拠の文がありません")
    pages: List[Tuple[str, str]] = []
    for s in sources:
        got, missing = texts.pages(s)
        pages += got
        problems += missing
    parts = fragments(sentence)
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
    checked: int = 0
    states: Dict[str, int] = field(default_factory=dict)
    downgraded: List[Finding] = field(default_factory=list)
    conflicts_flagged: List[Finding] = field(default_factory=list)
    out_file: str = ""

    @property
    def clean(self) -> bool:
        return not self.downgraded and not self.conflicts_flagged


def _add_note(node: Dict, note: str) -> None:
    existing = node.get("注記")
    if not existing:
        node["注記"] = note
    elif note not in existing:
        node["注記"] = existing + "／" + note


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


def verify(data: Dict, texts: Texts) -> Result:
    """data（形を確かめた後の、章ごとの結果の「制度データ」か、制度データの全体）を、その場で直す。"""
    result = Result()

    def visit(node: Any, path: List[Any]) -> None:
        if _is_sourced_value(node):
            result.checked += 1
            if node["状態"] != UNREADABLE:
                problems, evidence = evidence_problems(node, texts)
                problems += value_problems(node.get("値"), evidence) if evidence else []
                if problems:
                    before = node["状態"]
                    node["状態"] = CHECK
                    note = NOTE_PREFIX + "。".join(problems)
                    if before != CHECK:
                        note += f"（読み取り役は「{before}」としていた）"
                    _add_note(node, note)
                    result.downgraded.append(Finding(readable(path, data), problems))
            result.states[node["状態"]] = result.states.get(node["状態"], 0) + 1
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if path == [] and key in ("資料", "資料どうしの食い違い"):
                    continue
                visit(value, path + [key])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                visit(value, path + [i])

    visit(data, [])
    # 資料どうしの食い違い：それぞれの値に出典と根拠の文がある（状態はない）。外れたら、その食い違いの注記に書く
    for i, entry in enumerate(data.get("資料どうしの食い違い") or []):
        for j, item in enumerate(entry.get("値") or []):
            result.checked += 1
            problems, evidence = evidence_problems(item, texts)
            problems += value_problems(item.get("値"), evidence) if evidence else []
            if problems:
                where = f"資料どうしの食い違い「{entry.get('項目')}」の{j + 1}つ目の値（{_sources_label(item.get('出典') or [])}）"
                _add_note(entry, NOTE_PREFIX + f"{j + 1}つ目の値：" + "。".join(problems))
                result.conflicts_flagged.append(Finding(where, problems))
    return result


# ---- 置き場所と、まとめての動かし方 ----


def find_case(company: Path, case: Optional[str]) -> str:
    """裏取りに使う案件。渡されなければ、`記録/資料の本文/` の中の案件が1つのときだけ、それを使う。"""
    root = company / RECORDS_DIR / TEXT_DIR
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


def chapter_out_path(company: Path, case: str, data: Dict) -> Path:
    info = data["読み取り"]
    name = case_folder.safe_name(f"{info['章']}_{info.get('回目', 1)}回目")
    return company / RECORDS_DIR / Path(*OUT_DIR) / case_folder.safe_name(case) / f"{name}.json"


def run(company: Path, case: str, data: Any, out: Optional[Path] = None) -> Tuple[Result, Dict]:
    """形を確かめ、裏取りし、結果を置く。形が合わなければ InputError（何も書かない）。"""
    errors = shape_errors(data)
    if errors:
        raise InputError(errors)
    full = is_full(data)
    if out is None:
        if full:
            raise InputError(["制度データの全体を裏取りするときは、置き場所（--out）を渡してください"])
        out = chapter_out_path(company, case, data)
    texts = Texts(company, case)
    target = data if full else data["制度データ"]
    result = verify(target, texts)
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
    out.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.out_file = str(out.relative_to(company)) if _inside(out, company) else str(out)
    return result, saved


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def summary(result: Result) -> Dict:
    return {
        "照らした値": result.checked,
        "状態ごとの数": dict(sorted(result.states.items())),
        "要確認にした値": [{"場所": f.where, "理由": f.problems} for f in result.downgraded],
        "食い違いで外れた値": [{"場所": f.where, "理由": f.problems} for f in result.conflicts_flagged],
    }


def report(result: Result, case: str, label: str) -> str:
    states = result.states
    counts = "、".join(f"{s} {states.get(s, 0)}" for s in (CONFIRMED, CHECK, CONFLICT, UNREADABLE))
    lines = [f"読み取りの結果を裏取りしました（案件：{case}、{label}）。", ""]
    lines.append(f"- 照らした値：{result.checked}（{counts}）")
    if result.conflicts_flagged:
        lines.append(f"- 資料どうしの食い違いのうち、裏取りで外れた値：{len(result.conflicts_flagged)}")
    lines.append(f"- 置き場所：{result.out_file}")
    if result.clean:
        lines.append("- 根拠の文はどれも出典のページにあり、値はどれも根拠の文の中にありました。")
        return "\n".join(lines) + "\n"
    lines += ["", "裏取りで外れた値（状態を「要確認」にし、注記に理由を書きました）：", "", "| 場所 | 理由 |", "|---|---|"]
    for f in result.downgraded + result.conflicts_flagged:
        lines.append(f"| {f.where} | {'。'.join(f.problems)} |")
    lines += ["", "外れた値は、読み取り役にそのページをもう一度読ませて、根拠の文をページの文字のとおりに写させるか、"
                  "値を直させてから、もう一度この道具に通してください。直せないものは、要確認のまま社長に示します。"]
    return "\n".join(lines) + "\n"


def error_report(errors: List[str]) -> str:
    lines = ["読み取りの結果の形が、制度データの決まりと合いません。何も書いていません。", "",
             "読み取り役に、次の所を直して返し直してもらってください：", ""]
    lines += [f"- {e}" for e in errors[:40]]
    if len(errors) > 40:
        lines.append(f"- ほかに {len(errors) - 40} か所")
    return "\n".join(lines) + "\n"


__all__ = [
    "CHAPTER_FORM", "InputError", "Result", "Texts", "error_report", "find_case", "form_for", "fragments",
    "is_full", "normalize", "path_label", "report", "run", "scan_numbers", "shape_errors", "text_found",
    "value_problems", "verify",
]
