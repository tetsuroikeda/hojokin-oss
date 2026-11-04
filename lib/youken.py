"""数値の要件を制度データから読み、財務モデルの数字で判定するための部品（SPEC F8「数値の要件」T8-4、
DESIGN 6章・8.3・9章。TASKS M5）。

標準のライブラリだけを使う（テストの Python の中でも読み込めるように。同梱の openpyxl は読み込まない）。

要件の定義は、制度データの「数値の要件」から読む。プログラムに 4.0 や 3.5 のような基準の数を書かない。
- 指標：要件の「名前」（なければ「計算式」の値）に、財務モデルが計算する指標の名前が入っているもの。
  見る順は「1人当たり給与支給総額」「労働生産性」「付加価値額」（INDICATORS）。どれも入っていなければ判定しない。
- 基準の数：「基準」の値の「◯%以上」（全角の ％ や数字も読む）。数が2つ以上あるときは「合計で」の後の数。
  それでも1つに決まらなければ判定しない（推測しない）。
- いつの値で比べるか：「基準」の値に「毎年」があれば計画期間の毎年、「終了時点」「終了時」があれば最後の年。
  どちらもなければ判定しない。
- 名前に「特例」がある要件は、特例を選んだときだけの要件として、基本の要件のまとめに入れない。

計算は、様式（省力化の事業計画書その3の別紙4）の数式と同じ順で、同じ丸めをする（実験 E2b。DESIGN 8.3）。
- 労働生産性 ＝ 付加価値額 ÷ 労働者数 を小数第2位で切り捨て（付加価値額が負なら切り上げ）。別紙4 の F27。
- 1人当たり給与支給総額 ＝ 給与支給総額 ÷ 給与を受けた従業員数 を小数第2位で切り捨て。別紙4 の C35。
- 年平均成長率（％）＝ ((n年目 ÷ 基準年度)^(1/n) − 1) × 100 を小数第2位で切り捨て。別紙4 の G24・G29。
  1人当たり給与支給総額だけは、下がったときに切り上げ、計算できないときは0にする。別紙4 の G40。
- 切り捨て・切り上げは、表計算ソフトと同じく、有効数字15桁にそろえてから行う
  （0.29 × 100 が 28.999… になるような、浮動小数の誤差で1つ下に落ちないため）。

境目：判定は様式の値（切り捨てた値）で行う。そのうえで、切り捨てる前の伸びと基準との差が0.01ポイント未満なら
知らせる（DESIGN 8.3。11/3 の作者の決定）。ちょうど3.5%の計画が、別紙4 では3.49%（満たさない）になる例を拾うため。
差は小数第9位で丸めてから比べる（Excel の式でも同じ形にし、Python と表計算ソフトで境目の判断が割れないように）。
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

# 財務モデルが計算する指標。要件の名前に入っているかを、この順に見る（長い名前を先に）
PAY = "1人当たり給与支給総額"
PRODUCTIVITY = "労働生産性"
VALUE_ADDED = "付加価値額"
INDICATORS = (PAY, PRODUCTIVITY, VALUE_ADDED)

EVERY_YEAR = "毎年"
LAST_YEAR = "終了時点"

MEETS = "満たす"
FAILS = "満たさない"
UNJUDGEABLE = "判定できない"
CANNOT_CALC = "計算できない"
NEAR = "境目"

# 境目：基準との差がこれ未満なら知らせる（ポイント）
NEAR_LIMIT = Decimal("0.01")
NEAR_DIGITS = 9

_PERCENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%\s*以上")


class YoukenError(ValueError):
    """制度データの「数値の要件」が読めない。文は社長への説明にも使える。"""


def nfkc(text: Any) -> str:
    return unicodedata.normalize("NFKC", text) if isinstance(text, str) else ""


# ---------------------------------------------------------------- 表計算ソフトと同じ丸め


def _dec15(x: float) -> Decimal:
    """有効数字15桁にそろえた Decimal（表計算ソフトの数の扱いに近づける）。"""
    if not math.isfinite(x):
        raise ArithmeticError("数ではありません")
    return Decimal(format(x, ".15g"))


def _quantum(digits: int) -> Decimal:
    return Decimal(1).scaleb(-int(digits))


def rounddown(x: float, digits: int) -> float:
    """Excel の ROUNDDOWN（0に近いほうへ切り捨て）。"""
    return float(_dec15(x).quantize(_quantum(digits), rounding=ROUND_DOWN))


def roundup(x: float, digits: int) -> float:
    """Excel の ROUNDUP（0から遠いほうへ切り上げ）。"""
    return float(_dec15(x).quantize(_quantum(digits), rounding=ROUND_UP))


def round_half_up(x: float, digits: int) -> float:
    """Excel の ROUND（0.5 は0から遠いほうへ）。"""
    return float(_dec15(x).quantize(_quantum(digits), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- 様式（別紙4）と同じ計算


def productivity(value_added: float, workers: float) -> float:
    """労働生産性（別紙4 の F27）。"""
    x = value_added / workers
    return roundup(x, 2) if value_added < 0 else rounddown(x, 2)


def pay_per_person(pay: float, employees: float) -> float:
    """1人当たり給与支給総額（別紙4 の C35・G35）。"""
    return rounddown(pay / employees, 2)


def raw_growth(value: float, base: float, years: int) -> Optional[float]:
    """切り捨てる前の年平均成長率（％）。計算できない（基準が0、負の数の分数乗など）ときは None。"""
    try:
        ratio = value / base
    except ZeroDivisionError:
        return None
    if ratio < 0 or (ratio == 0 and years <= 0) or years <= 0:
        return None
    try:
        return (ratio ** (1 / years) - 1) * 100
    except (OverflowError, ValueError, ZeroDivisionError):
        return None


def growth_plain(value: float, base: float, years: int) -> Optional[float]:
    """付加価値額・労働生産性の年平均成長率（別紙4 の G24・G29）。計算できなければ None。"""
    raw = raw_growth(value, base, years)
    return None if raw is None else rounddown(raw, 2)


def growth_pay(value: float, base: float, years: int) -> float:
    """1人当たり給与支給総額の年平均成長率（別紙4 の G40。下がったら切り上げ、計算できなければ0）。"""
    raw = raw_growth(value, base, years)
    if raw is None:
        return 0.0
    return rounddown(raw, 2) if value >= base else roundup(raw, 2)


def judge(growth: Any, threshold: Decimal) -> str:
    """様式の値（切り捨てた伸び）で判定する。数でなければ「判定できない」。"""
    if not isinstance(growth, (int, float)) or isinstance(growth, bool):
        return UNJUDGEABLE
    try:
        return MEETS if _dec15(float(growth)) >= threshold else FAILS
    except ArithmeticError:
        return UNJUDGEABLE


def is_near(raw: Optional[float], threshold: Decimal) -> bool:
    """切り捨てる前の伸びと基準との差が0.01ポイント未満か（差は小数第9位で丸めてから比べる）。"""
    if raw is None:
        return False
    try:
        diff = _dec15(abs(raw - float(threshold))).quantize(_quantum(NEAR_DIGITS), rounding=ROUND_HALF_UP)
    except ArithmeticError:
        return False
    return diff < NEAR_LIMIT


# ---------------------------------------------------------------- 制度データから要件を読む


@dataclass
class Requirement:
    """制度データの「数値の要件」の1件と、そこから読んだ判定の決まり。"""

    name: str
    indicator: Optional[str] = None
    threshold: Optional[Decimal] = None
    when: Optional[str] = None
    optional: bool = False
    basis_text: str = ""
    basis_state: str = ""
    sources: List[dict] = field(default_factory=list)
    skip_reason: Optional[str] = None

    @property
    def judged(self) -> bool:
        return self.skip_reason is None

    def threshold_text(self) -> str:
        return f"{self.threshold}%以上" if self.threshold is not None else ""

    def source_text(self) -> str:
        return sources_text(self.sources)

    def years(self, plan_years: int) -> List[int]:
        """判定する年（1 から数える）。"""
        if self.when == EVERY_YEAR:
            return list(range(1, plan_years + 1))
        return [plan_years]


def sources_text(sources: Sequence[Any]) -> str:
    """出典の一覧を「要領8 p.10」の形にする。"""
    parts = []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        doc = str(s.get("資料") or "").strip()
        page = s.get("ページ")
        end = s.get("終わりのページ")
        if not doc:
            continue
        if page is None:
            parts.append(doc)
        elif end is not None and end != page:
            parts.append(f"{doc} p.{page}–{end}")
        else:
            parts.append(f"{doc} p.{page}")
    return "、".join(parts)


def _value_text(item: Any) -> str:
    if isinstance(item, dict):
        value = item.get("値")
        return value if isinstance(value, str) else ""
    return ""


def _indicator(name: str, formula: str) -> Optional[str]:
    for text in (nfkc(name), nfkc(formula)):
        for indicator in INDICATORS:
            if indicator in text:
                return indicator
    return None


def _threshold(text: str) -> "tuple[Optional[Decimal], Optional[str]]":
    """基準の文から「◯%以上」の数を読む。（数, 読めないときの理由）。"""
    norm = nfkc(text)
    found = list(_PERCENT.finditer(norm))
    if not found:
        return None, "基準に「◯%以上」の数が書かれていません"
    total_at = norm.find("合計で")
    if total_at >= 0:
        after = [m for m in found if m.start() > total_at]
        if after:
            return Decimal(after[0].group(1)), None
    numbers = {Decimal(m.group(1)) for m in found}
    if len(numbers) == 1:
        return numbers.pop(), None
    listed = "・".join(m.group(1) + "%" for m in found)
    return None, f"基準に数が2つ以上あり（{listed}）、どれと比べるかを決められません"


def _when(text: str) -> Optional[str]:
    norm = nfkc(text)
    if "毎年" in norm:
        return EVERY_YEAR
    if "終了時点" in norm or "終了時" in norm:
        return LAST_YEAR
    return None


def read_requirements(seido: Any) -> List[Requirement]:
    """制度データの「数値の要件」を読み、1件ごとに判定の決まりを作る。判定しないものも理由つきで返す。"""
    if not isinstance(seido, dict):
        raise YoukenError("制度データの形が違います（JSON の { } ではありません）")
    items = seido.get("数値の要件")
    if not isinstance(items, list):
        raise YoukenError("制度データに「数値の要件」がありません")
    out = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("名前"), str):
            raise YoukenError("制度データの「数値の要件」に、名前のない件があります")
        name = item["名前"]
        basis = item.get("基準") if isinstance(item.get("基準"), dict) else {}
        req = Requirement(
            name=name,
            optional="特例" in nfkc(name),
            basis_text=_value_text(basis),
            basis_state=str(basis.get("状態") or ""),
            sources=list(basis.get("出典") or []),
        )
        req.indicator = _indicator(name, _value_text(item.get("計算式")))
        if req.basis_state == "読み取れない" or not req.basis_text:
            req.skip_reason = "制度データで、基準が読み取れていません"
        elif req.indicator is None:
            req.skip_reason = "財務モデルで計算する指標（" + "・".join(INDICATORS) + "）の要件ではありません"
        else:
            req.threshold, reason = _threshold(req.basis_text)
            req.when = _when(req.basis_text)
            if reason:
                req.skip_reason = reason
            elif req.when is None:
                req.skip_reason = "いつの値で比べるか（毎年か、計画期間の終わりか）が、基準に書かれていません"
        out.append(req)
    return out


def threshold_literal(threshold: Decimal) -> str:
    """Excel の式に書く基準の数（Decimal の文字のまま。指数の形にしない）。"""
    try:
        text = format(threshold, "f")
    except (InvalidOperation, ValueError):
        raise YoukenError(f"基準の数 {threshold} を式に書けません")
    return text


def requirement_rows(reqs: Sequence[Requirement]) -> Dict[str, List[Requirement]]:
    """指標ごとに、判定する要件を並べる。"""
    out: Dict[str, List[Requirement]] = {}
    for req in reqs:
        if req.judged and req.indicator is not None:
            out.setdefault(req.indicator, []).append(req)
    return out
