"""財務モデル（計画の数字の土台）の中身を組み立てる（SPEC F8「財務モデル」「数値の要件」、DESIGN 6章・8.3。TASKS M5）。

標準のライブラリだけを使う。Excel のファイルに書くのは lib/zaimu_xlsx.py（同梱の openpyxl）、
LibreOffice で計算し直すのは lib/libreoffice.py。ここでは、どのセルに何を書くか（数式と、同じ計算を Python で
した値）を決める。Excel の数式と Python の値を、同じ所で一緒に作るので、2つが食い違えば計算し直しで見つかる。

指定（Claude が聞き取りと書類から作り、`記録/財務モデルの指定.json` などに置く JSON）
    {
      "計画の年数": 5,                       # 1〜5。省けば5
      "前提": [                              # 数字の元になる前提。1〜20個（DESIGN 8.3。多くても20個（仮））
        {"名前": "単価_冷凍惣菜", "値": 680, "単位": "円/個", "説明": "冷凍惣菜1個の値段",
         "根拠": "聞き取り", "出典": "社長の答え（2026-11-04）", "仮": false},
        {"名前": "賃上げ率", "値": 0.04, "単位": "%", ...}      # 率は小数で書き、単位を "%" にする
      ],
      "基準年度": {                          # 基準年度の実績（決算書など）。9つとも要る。数か {"値", "根拠", "出典", "仮"}
        "売上": ..., "原材料費": ..., "給与支給総額": ..., "その他の人件費": ..., "減価償却費": ...,
        "その他の経費": ..., "役員数": ..., "常勤従業員数": ..., "給与を受けた従業員数": ...
      },
      "既存事業": {"給与支給総額": "基準_給与支給総額*(1+賃上げ率)^年"},   # 1年目から。書かない行は基準年度のまま
      "新事業": [{"名前": "冷凍惣菜", "始まる年": 1, "売上": "単価_冷凍惣菜*数量_冷凍惣菜"}],  # 書かない行は0
      "人数": {"常勤従業員数": "基準_常勤従業員数+1"},                    # 1年目から。書かない人数は基準年度のまま
      "月次の波": [1, 1, 1.2, ...],          # 任意。12個の重み。1年目の売上と原材料費を月に分ける（季節の波）
      "省力化": {                            # 任意。様式その3 の別紙1・別紙3 と同じ計算をする（TASKS B13）
        "導入前": [{"工程": "計量", "分": 480}],                         # 1日あたりの作業時間（分）。No は並びの順
        "導入後": [{"工程": "計量と盛り付けの見守り", "分": 120, "種別": "新たに追加される作業"},
                   {"工程": "検品", "分": 60, "種別": "内容は変化しない作業", "対応する導入前": 4}],
        "投資総額": {"値": 22500000, "根拠": "見積書", "出典": "…"}, "年間稼働日数": …, "人件費単価": …
      },
      # 以下は任意。様式（省力化その3 の別紙4）に写す数字を道具が出すためのもの（11/6 のリハーサルの穴1・穴2）
      "年度": {"直近期": "2026-03", "補助事業の完了予定": "2028-01", "応募の締切": "2026-12"},
                                             # 年-月。直近期は決算書の期の終わり（決算月もここから取る）。応募の締切を
                                             # 省くと、道具（zaimu_model.py）が制度データの「決まった期日」の公募締切日を入れる
      "直近期の実績": {"給与支給総額": {"値": 41600000, "根拠": "決算書", "出典": "…"}, ...},  # kijun --as 直近期 が書く
      "基準年度": {"給与支給総額": {"式": "直近_給与支給総額*(1+賃上げ率)^経過年数", "根拠": "…", "出典": "…"}, ...},
                                             # 基準年度の値は、数のほか、直近期の実績からの式でもよい
      "売上原価の割合": {"給与支給総額": {"値": 0.8029, "根拠": "決算書", "出典": "…"}, ...},  # kijun が書く
      "本補助金の設備の減価償却費": {"式": "新設備の取得額/新設備の耐用年数", "根拠": "…", "出典": "…"}
    }

- 式に使えるもの：前提の名前、基準年度の名前（「基準_売上」など）、年（基準年度が0、1年目が1）、同じ事業の行の名前
  （「売上」など。人数の式では人数の名前）、数、+ - * / ^（累乗）、かっこ、ROUND・ROUNDDOWN・ROUNDUP・MIN・MAX。
- 売上・経費の区分は DESIGN 8.3 の4区分（原材料費・人件費・減価償却費・その他の経費）。人件費は「給与支給総額」と
  「その他の人件費」（法定福利費・役員の報酬など）に分けて持つ。給与支給総額は、全月分の給与を受けた従業員の分
  （数値の要件に使う。別紙4 の⑦）。営業利益と人件費は道具が計算する。
- 指標（付加価値額・労働生産性・1人当たり給与支給総額と、それぞれの年平均成長率）は、様式（別紙4）の数式と同じ
  計算にする（lib/youken.py）。数値の要件の基準とその出典は、制度データから読む。

シート（DESIGN 8.3。シートは3つ）
- 前提：前提の表と、基準年度の実績の表。値のセルに名前を付け、色を付ける（社長が書き換えてよいのはここだけ）。
  決まっていない前提は「状態」の欄に「仮」と書き、その欄に色を付ける（DESIGN 6章）。
- 計画（N年）：上に「まとめ」。その下に、既存事業・新事業・合算・人数・補助金の指標・数値の要件の判定。
- 月次（1年目）：1年目の合算を12か月に分けたもの。「月次の波」があれば、売上と原材料費をその重みで分ける。
  合計は計画の1年目とつながる。

数量が2割少ない場合（DESIGN 8.3「簡単にしすぎないための工夫」）：名前が「数量_」で始まる前提を0.8倍にした指定で
同じ計算をし直し、数値の要件（特例を除く）をすべて満たすかを「まとめ」に1行で示す（式ではなく、道具が計算した値）。

  ただし、既存事業の式が年=0 で基準年度の実績になる（今の数量で今の売上を作っている）のに、数量の前提を0.8倍にすると
  年=0 の値まで変わるなら、今の数量（実績）まで2割減らした判定なので「判定できない」とし、理由と参考の値を示す
  （DESIGN 8.3 の「計画より2割少ない」は、計画で増やす分のこと。今の数量には「数量_」を付けない）。あわせて、数量を
  減らすと変わる行と、売上が減っても動かない原材料費を示す。

省力化の指標（様式その3。応募手引8 p.30・p.59）：別紙1 の数式と同じ形で、削減される業務に要していた時間・導入後に
発生する時間・省力化指数を、別紙3 の数式と同じ形で投資回収期間を計算する。増加した付加価値額は、応募手引8 p.59 の
例の形（（最後の年の付加価値額−基準年度の付加価値額）÷計画の年数）で、計画の合算から出す。

様式（別紙4）に写す数字（指定に「年度」「直近期の実績」「売上原価の割合」「本補助金の設備の減価償却費」のどれかが
あるとき）：計画のシートの下に、別紙4 の行の並びで、円に丸めた値を数式で置く。
- 売上原価 ＝ 区分ごとの合算 × 売上原価の割合、販売費及び一般管理費 ＝ 区分ごとの合算 ×（1 − 割合）。割合は決算書の
  科目（製造原価報告書か販管費の内訳か）から kijun が出す。丸める前の和が「売上 − 営業利益」と合うかも行に置く。
- 減価償却費は、本補助金で導入する設備の分（指定の式。1年目から）と、既存設備の分（合算 − 本補助金の分）に分ける。
- 円に丸めた値から、様式と同じ計算で付加価値額・労働生産性・1人当たり給与支給総額と伸びを出し、財務モデルの値と
  違えば知らせる（様式には円で写すので、切り捨ての境目では伸びが変わりうる）。
- 決算期：基準年度は補助事業の完了日を含む事業年度（要領9 p.6（3））、1年目はその翌年度（p.7（8））。締切期は応募の
  締切を含む期、直近期は締切期の前の期（様式の「応募申請の直近の決算期」。決算が出ていなければ前々期の値を使う注5）。
  経過年数は直近期から基準年度までの年数（別紙4 の「応募申請の直近から基準年度までの経過年数」）。
- 足下の賃上げ：直近期（決算書）・締切期・基準年度の給与支給総額と人数から、1人当たり給与支給総額の年平均成長率を
  別紙4 と同じ計算で出す。締切期の値は、基準年度の式の経過年数を1にしたもの。要件ではなく審査で見る値なので、
  満たす・満たさないは付けない。
"""

from __future__ import annotations

import ast
import dataclasses
import keyword
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from lib import youken

MODEL_FILE = "財務モデル.xlsx"
SHEET_ASSUMPTIONS = "前提"
SHEET_MONTHLY = "月次（1年目）"

MAX_ASSUMPTIONS = 20
MAX_YEARS = 5
DEFAULT_YEARS = 5

YEAR = "年"
BASE_PREFIX = "基準_"
# 事業ごとに、指定の式で決める行
ROW_KEYS = ("売上", "原材料費", "給与支給総額", "その他の人件費", "減価償却費", "その他の経費")
# 人数（会社全体）
PEOPLE_KEYS = ("役員数", "常勤従業員数", "給与を受けた従業員数")
BASE_KEYS = ROW_KEYS + PEOPLE_KEYS
BASE_INFO = {
    "売上": ("円", "基準年度の売上高"),
    "原材料費": ("円", "基準年度の原材料費"),
    "給与支給総額": ("円", "基準年度の給与支給総額（全月分の給与を受けた従業員の分。役員を除く）"),
    "その他の人件費": ("円", "基準年度の、給与支給総額のほかの人件費（法定福利費・役員の報酬など）"),
    "減価償却費": ("円", "基準年度の減価償却費"),
    "その他の経費": ("円", "基準年度の、上のどれにも当たらない経費"),
    "役員数": ("人", "基準年度の役員の数"),
    "常勤従業員数": ("人", "基準年度の常勤の従業員の数"),
    "給与を受けた従業員数": ("人", "基準年度に全月分の給与を受けた従業員の数"),
}
FUNCS = ("ROUND", "ROUNDDOWN", "ROUNDUP", "MIN", "MAX")

# 数量が2割少ない場合（DESIGN 8.3）。名前がこの頭で始まる前提を数量とみなす
QUANTITY_PREFIX = "数量_"
LOW_FACTOR = 0.8
LOW_LABEL = "数量が計画より2割少ない場合に、数値の要件（特例を除く）をすべて満たすか"
NO_QUANTITY = "数量の前提（名前が「数量_」で始まるもの）がないので、判定していません"

MONTHS = 12

# 様式（別紙4）の決算期（要領9 p.6（3）基準年度・p.7（8）事業計画期間、様式その3 別紙4 の決算期の列）
TIMELINE_KEY = "年度"
RECENT_KEY = "直近期の実績"
RECENT_PREFIX = "直近_"
ELAPSED = "経過年数"  # 直近期から基準年度までの年数。基準年度の式で使う
FORMULA_KEY = "式"
# 様式（別紙4）の売上原価と販売費及び一般管理費（区分ごとの、売上原価に入る割合。残りは販管費）
COST_SHARE_KEY = "売上原価の割合"
COST_SHARE_PREFIX = "原価割合_"
COST_KEYS = ROW_KEYS[1:]
NEW_DEP_KEY = "本補助金の設備の減価償却費"
BEPPYO_KEYS = (TIMELINE_KEY, RECENT_KEY, COST_SHARE_KEY, NEW_DEP_KEY)
# 数量が2割少ない場合：既存事業の式が年=0 で基準年度の実績（との差がこの割合以内）になり、数量を0.8倍にすると
# 年=0 の値が基準年度のこの割合以上動くなら、今の数量（実績）まで「数量_」にしているとみる
CURRENT_LEVEL_TOL = 0.01

# 省力化の指標（様式その3 の別紙1・別紙3）
SHORYOKU_KEY = "省力化"
MAX_STEPS = 30  # 別紙1 の行の数
KIND_NEW = "新たに追加される作業"
KIND_SAME = "内容は変化しない作業"
STEP_KINDS = (KIND_NEW, KIND_SAME)
SHORYOKU_ITEMS = {
    "投資総額": ("円", "補助の対象でない分も含めた投資の総額（別紙3）"),
    "年間稼働日数": ("日", "この事業が1年に動く日数（別紙3）"),
    "人件費単価": ("円/時", "この事業で働く人の時給の平均（別紙3）"),
}

FILL_INPUT = "FFF2CC"  # 社長が書き換えてよい値
FILL_PROVISIONAL = "FCE4D6"  # 仮の印
FMT_YEN = "#,##0"
FMT_PEOPLE = "General"
FMT_PER = "#,##0.00"
FMT_GROWTH = "0.00"
FMT_RATE = "0.0%"
FMT_NUMBER = "General"

# Excel のセルの場所や R1C1 と見分けがつかない名前は、名前を付けたセルにできない
_CELL_LIKE = re.compile(r"[A-Za-z]{1,3}[0-9]{1,7}|[RrCc][0-9]*|[Rr][0-9]+[Cc][0-9]+")


class SpecError(ValueError):
    """指定が正しくない、または計算できない。文は社長への説明にも使える。"""


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def col_name(index: int) -> str:
    """1 → A、2 → B …"""
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


# ---------------------------------------------------------------- 指定


@dataclass
class Item:
    """前提か、基準年度の実績の1つ。"""

    name: str
    value: float
    unit: str = ""
    desc: str = ""
    basis: str = ""
    source: str = ""
    provisional: bool = False
    formula: Optional["Expr"] = None  # 基準年度を直近期の実績からの式で置いたとき・本補助金の設備の減価償却費

    @property
    def unsupported(self) -> bool:
        """根拠か出典がなく、仮の印もない。"""
        return not self.provisional and not (self.basis.strip() and self.source.strip())


@dataclass
class Business:
    name: str
    start: int
    exprs: Dict[str, "Expr"]
    existing: bool = False


@dataclass
class Step:
    """別紙1 の1行（1日あたりの作業）。"""

    no: int
    name: str
    minutes: float
    kind: str = ""  # 導入後だけ
    before_no: Optional[int] = None  # 導入後の「内容は変化しない作業」が対応する導入前の No


@dataclass
class Shoryoku:
    before: List[Step]
    after: List[Step]
    items: Dict[str, Item]  # 投資総額・年間稼働日数・人件費単価


@dataclass
class Timeline:
    """様式（別紙4）の決算期。年は、その期の終わりの年（決算月は、直近期の終わりの月）。"""

    month: int
    recent: int  # 様式の「応募申請の直近の決算期」の終わりの年
    recent_actual: int  # 指定の直近期（決算書の期）の終わりの年。注5 のときは recent の前の年
    deadline: Optional[Tuple[int, int]]
    deadline_source: str
    closing: int  # 締切期（応募の締切を含む期）の終わりの年
    completion: Tuple[int, int]
    base: int  # 基準年度（補助事業の完了日を含む期）の終わりの年
    elapsed: int  # 経過年数（直近期から基準年度まで）
    basis: str = ""
    source: str = ""
    notes: List[str] = field(default_factory=list)

    def label(self, year: int) -> str:
        return f"{year}年{self.month}月期"


@dataclass
class Spec:
    years: int
    assumptions: List[Item]
    base: Dict[str, Item]
    businesses: List[Business]
    people: Dict[str, "Expr"]
    waves: Optional[List[float]] = None
    shoryoku: Optional[Shoryoku] = None
    timeline: Optional[Timeline] = None
    recent: Dict[str, Item] = field(default_factory=dict)  # 直近期の実績（名前は「直近_売上」など）
    cost_share: Dict[str, Item] = field(default_factory=dict)  # 区分 → 売上原価に入る割合（名前は「原価割合_…」）
    new_dep: Optional[Item] = None  # 本補助金で導入する設備の減価償却費（式）
    beppyo: bool = False  # 様式（別紙4）に写す数字を出すか

    def values(self) -> Dict[str, float]:
        out = {a.name: a.value for a in self.assumptions}
        out.update({BASE_PREFIX + k: item.value for k, item in self.base.items()})
        if self.shoryoku is not None:
            out.update({k: item.value for k, item in self.shoryoku.items.items()})
        return out

    def quantity_names(self) -> List[str]:
        return [a.name for a in self.assumptions if a.name.startswith(QUANTITY_PREFIX)]

    def scaled_quantities(self, factor: float) -> "Spec":
        """数量の前提を factor 倍にした指定（数量が少ない場合の判定に使う）。"""
        names = set(self.quantity_names())
        assumptions = [dataclasses.replace(a, value=a.value * factor) if a.name in names else a for a in self.assumptions]
        return dataclasses.replace(self, assumptions=assumptions)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SpecError(f"{where} の値が数ではありません（{value!r}）")
    return float(value)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _check_name(name: str, where: str) -> str:
    norm = nfkc(name).strip()
    if not norm:
        raise SpecError(f"{where} に名前がありません")
    if not norm.isidentifier() or keyword.iskeyword(norm):
        raise SpecError(f"{where} の名前「{name}」は使えません（文字・数字・「_」だけにし、数字で始めない）")
    if _CELL_LIKE.fullmatch(norm) or norm.upper() in ("TRUE", "FALSE") or norm.upper() in FUNCS:
        raise SpecError(f"{where} の名前「{name}」は、Excel のセルの場所や関数と紛れるので使えません")
    if (norm in (YEAR, ELAPSED) or norm in BASE_KEYS or norm.startswith(BASE_PREFIX) or norm.startswith(RECENT_PREFIX)
            or norm.startswith(COST_SHARE_PREFIX)):
        raise SpecError(f"{where} の名前「{name}」は、道具が使う名前と重なるので使えません")
    if len(norm) > 200:
        raise SpecError(f"{where} の名前が長すぎます")
    return norm


def _item(name: str, raw: Any, where: str, unit: str = "", desc: str = "") -> Item:
    if isinstance(raw, dict):
        return Item(
            name=name,
            value=_number(raw.get("値"), where),
            unit=_text(raw.get("単位")) or unit,
            desc=_text(raw.get("説明")) or desc,
            basis=_text(raw.get("根拠")),
            source=_text(raw.get("出典")),
            provisional=raw.get("仮") is True,
        )
    return Item(name=name, value=_number(raw, where), unit=unit, desc=desc)


def parse_spec(data: Any) -> Spec:
    """指定の JSON を確かめて読む。正しくなければ SpecError。"""
    if not isinstance(data, dict):
        raise SpecError("指定の形が違います（JSON の { } ではありません）")
    known = {"計画の年数", "前提", "基準年度", "既存事業", "新事業", "人数", "月次の波", SHORYOKU_KEY} | set(BEPPYO_KEYS)
    extra = sorted(set(data) - known)
    if extra:
        raise SpecError("指定に、知らない項目があります：" + "、".join(extra))
    years = data.get("計画の年数", DEFAULT_YEARS)
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= MAX_YEARS:
        raise SpecError(f"計画の年数は 1〜{MAX_YEARS} の整数にしてください（{years!r}）")

    raw_assumptions = data.get("前提")
    if not isinstance(raw_assumptions, list) or not raw_assumptions:
        raise SpecError("前提が1つもありません")
    if len(raw_assumptions) > MAX_ASSUMPTIONS:
        raise SpecError(
            f"前提が {len(raw_assumptions)} 個あります。財務に詳しくない人でも説明できるよう、"
            f"{MAX_ASSUMPTIONS} 個までにしてください（DESIGN 8.3）"
        )
    assumptions: List[Item] = []
    seen: Dict[str, str] = {}
    for i, raw in enumerate(raw_assumptions, start=1):
        where = f"前提の{i}つ目"
        if not isinstance(raw, dict):
            raise SpecError(f"{where} の形が違います")
        name = _check_name(str(raw.get("名前") or ""), where)
        if name.casefold() in seen:
            raise SpecError(f"前提の名前「{name}」が2つあります（大文字と小文字の違いは同じに数えます）")
        seen[name.casefold()] = name
        assumptions.append(_item(name, raw, f"前提「{name}」"))

    raw_base = data.get("基準年度")
    if not isinstance(raw_base, dict):
        raise SpecError("基準年度の実績がありません（決算書などの数字が要ります）")
    missing = [k for k in BASE_KEYS if k not in raw_base]
    if missing:
        raise SpecError("基準年度の実績に、ない項目があります：" + "、".join(missing))
    extra = sorted(set(raw_base) - set(BASE_KEYS))
    if extra:
        raise SpecError("基準年度の実績に、知らない項目があります：" + "、".join(extra))
    timeline = _timeline(data.get(TIMELINE_KEY))
    recent = _recent(data.get(RECENT_KEY))
    base = _base_items(raw_base, assumptions, recent, timeline)

    names = set(seen.values()) | {BASE_PREFIX + k for k in BASE_KEYS}
    businesses = [Business("既存事業", 0, _exprs(data.get("既存事業", {}), "既存事業", ROW_KEYS, names), True)]
    raw_new = data.get("新事業", [])
    if not isinstance(raw_new, list):
        raise SpecError("新事業は [ ] の並びにしてください")
    labels = {"既存事業"}
    for i, raw in enumerate(raw_new, start=1):
        if not isinstance(raw, dict):
            raise SpecError(f"新事業の{i}つ目の形が違います")
        label = _text(raw.get("名前")) or f"新事業{i}"
        if label in labels:
            raise SpecError(f"事業の名前「{label}」が2つあります")
        labels.add(label)
        start = raw.get("始まる年", 1)
        if isinstance(start, bool) or not isinstance(start, int) or not 1 <= start <= years:
            raise SpecError(f"新事業「{label}」の始まる年は 1〜{years} の整数にしてください（{start!r}）")
        body = {k: v for k, v in raw.items() if k not in ("名前", "始まる年")}
        businesses.append(Business(label, start, _exprs(body, f"新事業「{label}」", ROW_KEYS, names)))
    people = _exprs(data.get("人数", {}), "人数", PEOPLE_KEYS, names)
    waves = _waves(data.get("月次の波"))
    shoryoku = _shoryoku(data.get(SHORYOKU_KEY), {n.casefold() for n in seen.values()})
    return Spec(years, assumptions, base, businesses, people, waves, shoryoku, timeline, recent,
                _cost_share(data.get(COST_SHARE_KEY)), _new_dep(data.get(NEW_DEP_KEY), names),
                any(data.get(k) is not None for k in BEPPYO_KEYS))


# ---------------------------------------------------------------- 様式（別紙4）の年度・直近期・売上原価の割合


_YEAR_MONTH = re.compile(r"([0-9]{4})-([0-9]{1,2})(?:-[0-9]{1,2}.*)?")


def _year_month(raw: Any, where: str) -> Tuple[Tuple[int, int], str]:
    """「2026-03」（日付・日時でもよい）か {"値": "2026-03", "出典": …} を、(年, 月) と出典にする。"""
    source = ""
    if isinstance(raw, dict):
        source = _text(raw.get("出典"))
        raw = raw.get("値")
    m = _YEAR_MONTH.fullmatch(nfkc(raw).strip()) if isinstance(raw, str) else None
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise SpecError(f"{where}は「2026-03」のような年-月で書いてください（{raw!r}）")
    return (int(m.group(1)), int(m.group(2))), source


def fiscal_year_end(year_month: Tuple[int, int], month: int) -> int:
    """その年月を含む事業年度（決算月が month）の、終わりの年。"""
    y, m = year_month
    return y if m <= month else y + 1


def _timeline(raw: Any) -> Optional[Timeline]:
    if raw is None:
        return None
    where = TIMELINE_KEY
    if not isinstance(raw, dict):
        raise SpecError(f"{where}は {{ }} の形にしてください")
    extra = sorted(set(raw) - {"直近期", "補助事業の完了予定", "応募の締切", "根拠", "出典"})
    if extra:
        raise SpecError(f"{where}に、知らない項目があります：" + "、".join(extra))
    for key in ("直近期", "補助事業の完了予定"):
        if raw.get(key) is None:
            raise SpecError(f"{where}に「{key}」がありません（年-月。例：2026-03）")
    (recent_actual, month), _src = _year_month(raw["直近期"], f"{where}の直近期")
    completion, _src = _year_month(raw["補助事業の完了予定"], f"{where}の補助事業の完了予定")
    base = fiscal_year_end(completion, month)

    def label(year: int) -> str:
        return f"{year}年{month}月期"

    notes: List[str] = []
    deadline, deadline_source = None, ""
    if raw.get("応募の締切") is not None:
        deadline, deadline_source = _year_month(raw["応募の締切"], f"{where}の応募の締切")
        if completion < deadline:
            raise SpecError(f"{where}の補助事業の完了予定（{completion[0]}年{completion[1]}月）が、応募の締切より前です")
        closing = fiscal_year_end(deadline, month)
        recent = closing - 1
        if recent_actual == recent - 1:
            notes.append(f"直近期を {label(recent_actual)} としています。様式の「応募申請の直近の決算期」は {label(recent)} です"
                         "（決算が確定していないときは、前々期の値を前期に読み替えて使う。別紙4 の注5）")
        elif recent_actual != recent:
            raise SpecError(f"{where}の直近期（{label(recent_actual)}）が、応募の締切（{deadline[0]}年{deadline[1]}月）を含む期"
                            f"（{label(closing)}）の前の期（{label(recent)}）ではありません。決算書の期と締切を確かめてください")
    else:
        recent = recent_actual
        closing = recent + 1
        notes.append("応募の締切が分からないので、直近期の次の期を締切期としました")
    if base < closing:
        raise SpecError(f"{where}の補助事業の完了予定を含む期（{label(base)}）が、締切期（{label(closing)}）より前です")
    return Timeline(month, recent, recent_actual, deadline, deadline_source, closing, completion, base, base - recent,
                    _text(raw.get("根拠")), _text(raw.get("出典")), notes)


def _recent(raw: Any) -> Dict[str, Item]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise SpecError(f"{RECENT_KEY}は、{{ }} に決算書の値を入れてください（区分は基準年度と同じ）")
    extra = sorted(set(raw) - set(BASE_KEYS))
    if extra:
        raise SpecError(f"{RECENT_KEY}に、知らない項目があります：" + "、".join(extra))
    out = {}
    for key in BASE_KEYS:
        if key in raw:
            unit, desc = BASE_INFO[key]
            out[key] = _item(RECENT_PREFIX + key, raw[key], f"{RECENT_KEY}の{key}", unit, desc.replace("基準年度", "直近期"))
    return out


def _is_formula(raw: Any) -> bool:
    return isinstance(raw, dict) and FORMULA_KEY in raw


def _names_in(node: ast.AST) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _formula_item(name: str, raw: dict, where: str, unit: str, desc: str, names: set) -> Item:
    extra = sorted(set(raw) - {FORMULA_KEY, "根拠", "出典", "仮", "単位", "説明"})
    if extra:
        raise SpecError(f"{where}に、知らない項目があります：" + "、".join(extra))
    text = raw.get(FORMULA_KEY)
    if isinstance(text, bool) or not isinstance(text, (str, int, float)):
        raise SpecError(f"{where}の式が、文字でも数でもありません")
    expr = Expr.parse(str(text), where, names, ())
    return Item(name=name, value=0.0, unit=_text(raw.get("単位")) or unit, desc=_text(raw.get("説明")) or desc,
                basis=_text(raw.get("根拠")), source=_text(raw.get("出典")), provisional=raw.get("仮") is True,
                formula=expr)


def _bridge_lookup(assumptions: Sequence[Item], recent: Dict[str, Item], elapsed: float) -> Callable[[str], float]:
    """基準年度の式の名前の値（前提・直近期の実績・経過年数）。"""
    values = {a.name: a.value for a in assumptions}
    values.update({item.name: item.value for item in recent.values()})
    values[ELAPSED] = float(elapsed)
    return lambda n: values[n]


def _base_items(raw_base: dict, assumptions: List[Item], recent: Dict[str, Item],
                timeline: Optional[Timeline]) -> Dict[str, Item]:
    """基準年度の9つ。数か、直近期の実績からの式（{"式": "直近_給与支給総額*(1+賃上げ率)^経過年数", …}）。"""
    formulas = [k for k in BASE_KEYS if _is_formula(raw_base[k])]
    if (formulas or recent) and timeline is None:
        raise SpecError(f"{RECENT_KEY}や基準年度の式を使うときは、「{TIMELINE_KEY}」（直近期・補助事業の完了予定）を書いてください"
                        "（経過年数を、決算期から道具が決めるため）")
    names = {a.name for a in assumptions} | {item.name for item in recent.values()} | {ELAPSED}
    base = {}
    for key in BASE_KEYS:
        unit, desc = BASE_INFO[key]
        where = f"基準年度の{key}"
        if key not in formulas:
            base[key] = _item(BASE_PREFIX + key, raw_base[key], where, unit, desc)
            continue
        item = _formula_item(BASE_PREFIX + key, raw_base[key], where, unit, desc, names)
        if YEAR in _names_in(item.formula.node):
            raise SpecError(f"{where}の式には「{YEAR}」を使えません（直近期からの年数は「{ELAPSED}」）")
        item.value = item.formula.value(_bridge_lookup(assumptions, recent, timeline.elapsed))
        base[key] = item
    return base


def _cost_share(raw: Any) -> Dict[str, Item]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise SpecError(f"{COST_SHARE_KEY}は、{{ }} に区分ごとの割合（0〜1）を入れてください")
    allowed = COST_KEYS + (NEW_DEP_KEY,)  # 本補助金の設備の減価償却費は、既存の減価償却費と別の割合にできる（製造の設備なら1）
    extra = sorted(set(raw) - set(allowed))
    if extra:
        raise SpecError(f"{COST_SHARE_KEY}に、知らない区分があります：" + "、".join(extra) + "（使える区分：" + "、".join(allowed) + "）")
    out = {}
    for key in allowed:
        if key in raw:
            item = _item(COST_SHARE_PREFIX + key, raw[key], f"{COST_SHARE_KEY}の{key}", "%",
                         f"{key}のうち、売上原価に入る割合（残りは販売費及び一般管理費）")
            if not 0 <= item.value <= 1:
                raise SpecError(f"{COST_SHARE_KEY}の{key}は0〜1にしてください（{item.value!r}）")
            out[key] = item
    return out


def _new_dep(raw: Any, names: set) -> Optional[Item]:
    if raw is None:
        return None
    if isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
        raw = {FORMULA_KEY: raw}
    if not _is_formula(raw):
        raise SpecError(f"{NEW_DEP_KEY}は {{\"式\": …, \"根拠\": …, \"出典\": …}} の形にしてください")
    return _formula_item(NEW_DEP_KEY, raw, NEW_DEP_KEY, "円", "本補助金で導入する設備の減価償却費（1年目から）", names)


def deadline_from_seido(seido: Any) -> Optional[Dict[str, str]]:
    """制度データの「決まった期日」から、応募の締切（年-月）と出典。決められなければ None。"""
    items = seido.get("決まった期日") if isinstance(seido, dict) else None
    found = []
    for item in items if isinstance(items, list) else []:
        name = nfkc(item.get("名前")) if isinstance(item, dict) and isinstance(item.get("名前"), str) else ""
        if "締切" not in name and "締め切り" not in name:
            continue
        when = item.get("日時") if isinstance(item.get("日時"), dict) else {}
        value = when.get("値") if isinstance(when.get("値"), dict) else {}
        text = next((value[k] for k in ("日時", "日付", "年月") if isinstance(value.get(k), str)), "")
        if not _YEAR_MONTH.fullmatch(nfkc(text).strip()):
            continue
        state = str(when.get("状態") or "")
        docs = youken.sources_text(when.get("出典") or [])
        found.append((("公募" in name or "応募" in name), name, nfkc(text).strip()[:7], state, docs))
    preferred = [f for f in found if f[0]] or found
    if len(preferred) != 1:
        return None
    _p, name, ym, state, docs = preferred[0]
    detail = "。".join(x for x in (docs, f"状態 {state}" if state else "") if x)
    return {"値": ym, "出典": f"制度データ「決まった期日」の{name}" + (f"（{detail}）" if detail else "")}


def with_seido_deadline(raw_spec: Any, seido: Any) -> Any:
    """指定の「年度」に応募の締切がなければ、制度データから入れた写しを返す（指定のファイルは書き換えない）。"""
    if not isinstance(raw_spec, dict) or not isinstance(raw_spec.get(TIMELINE_KEY), dict):
        return raw_spec
    if raw_spec[TIMELINE_KEY].get("応募の締切") is not None:
        return raw_spec
    found = deadline_from_seido(seido)
    if found is None:
        return raw_spec
    out = dict(raw_spec)
    timeline = dict(raw_spec[TIMELINE_KEY])
    timeline["応募の締切"] = found
    out[TIMELINE_KEY] = timeline
    return out


def _waves(raw: Any) -> Optional[List[float]]:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != MONTHS:
        raise SpecError(f"月次の波は、{MONTHS}か月分の重みの並び（[ ] に{MONTHS}個の数）にしてください")
    out = [_number(v, f"月次の波の{i}か月目") for i, v in enumerate(raw, start=1)]
    if any(v < 0 for v in out) or sum(out) <= 0:
        raise SpecError("月次の波の重みは0以上にし、少なくとも1つは0より大きくしてください")
    return out


def _shoryoku(raw: Any, taken: set) -> Optional[Shoryoku]:
    if raw is None:
        return None
    where = "省力化"
    if not isinstance(raw, dict):
        raise SpecError(f"{where}は {{ }} の形にしてください")
    known = {"導入前", "導入後"} | set(SHORYOKU_ITEMS)
    extra = sorted(set(raw) - known)
    if extra:
        raise SpecError(f"{where}に、知らない項目があります：" + "、".join(extra))
    items = {}
    for key, (unit, desc) in SHORYOKU_ITEMS.items():
        if key not in raw:
            raise SpecError(f"{where}の「{key}」がありません（様式その3 の別紙3 に入れる数）")
        if key.casefold() in taken:
            raise SpecError(f"前提の名前「{key}」は、省力化の数の名前と重なるので使えません")
        items[key] = _item(key, raw[key], f"{where}の{key}", unit, desc)
    for key in ("年間稼働日数", "人件費単価"):
        if items[key].value <= 0:
            raise SpecError(f"{where}の{key}は0より大きくしてください")
    before = _steps(raw.get("導入前"), f"{where}の導入前", False, 0)
    after = _steps(raw.get("導入後"), f"{where}の導入後", True, len(before))
    return Shoryoku(before, after, items)


def _steps(raw: Any, where: str, is_after: bool, n_before: int) -> List[Step]:
    if not isinstance(raw, list) or not raw:
        raise SpecError(f"{where}の作業が1つもありません（[ ] に、工程と1日あたりの分を並べる）")
    if len(raw) > MAX_STEPS:
        raise SpecError(f"{where}の作業が {len(raw)} 個あります。様式（別紙1）の行は {MAX_STEPS} までです")
    steps = []
    for no, row in enumerate(raw, start=1):
        at = f"{where}の{no}つ目"
        if not isinstance(row, dict):
            raise SpecError(f"{at}の形が違います")
        allowed = {"工程", "分"} | ({"種別", "対応する導入前"} if is_after else set())
        extra = sorted(set(row) - allowed)
        if extra:
            raise SpecError(f"{at}に、知らない項目があります：" + "、".join(extra))
        name = _text(row.get("工程"))
        if not name:
            raise SpecError(f"{at}に工程の名前がありません")
        minutes = _number(row.get("分"), f"{at}の分")
        if minutes < 0:
            raise SpecError(f"{at}の分が負の数です")
        kind, before_no = "", None
        if is_after:
            kind = _text(row.get("種別"))
            if kind not in STEP_KINDS:
                raise SpecError(f"{at}の種別は「{KIND_NEW}」か「{KIND_SAME}」にしてください（{kind!r}）")
            if kind == KIND_SAME:
                before_no = row.get("対応する導入前")
                if isinstance(before_no, bool) or not isinstance(before_no, int) or not 1 <= before_no <= n_before:
                    raise SpecError(f"{at}は「{KIND_SAME}」なので、対応する導入前の作業の番号（1〜{n_before}）を書いてください")
            elif row.get("対応する導入前") is not None:
                raise SpecError(f"{at}は「{KIND_NEW}」なので、対応する導入前の作業は書かないでください")
        steps.append(Step(no, name, minutes, kind, before_no))
    return steps


def _exprs(raw: Any, where: str, keys: Sequence[str], names: set) -> Dict[str, "Expr"]:
    if not isinstance(raw, dict):
        raise SpecError(f"{where} は {{ }} の形にしてください")
    unknown = sorted(set(raw) - set(keys))
    if unknown:
        raise SpecError(f"{where} に、知らない行があります：" + "、".join(unknown) + "（使える行：" + "、".join(keys) + "）")
    out = {}
    for key, text in raw.items():
        if isinstance(text, bool) or not isinstance(text, (str, int, float)):
            raise SpecError(f"{where} の{key}の式が、文字でも数でもありません")
        out[key] = Expr.parse(str(text), f"{where} の{key}", names, keys)
    _check_cycles(out, where)
    return out


def _check_cycles(exprs: Dict[str, "Expr"], where: str) -> None:
    state: Dict[str, int] = {}

    def visit(key: str, path: List[str]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            raise SpecError(f"{where} の式が、ぐるぐる回っています（" + " → ".join(path + [key]) + "）")
        state[key] = 1
        expr = exprs.get(key)
        if expr is not None:
            for ref in expr.rows:
                visit(ref, path + [key])
        state[key] = 2

    for key in exprs:
        visit(key, [])


def shoryoku_pairs(sh: Shoryoku) -> List[Tuple[Step, Step]]:
    """別紙1 で「内容は変化しない作業」として対応づく（導入前, 導入後）の組。

    別紙1 は、導入前の行ごとに、導入後の行のうち「対応する導入前の No」が同じ最初の行を MATCH で探し、
    それが「内容は変化しない作業」のときだけ組にする（E 列。N 列も同じ組になる）。
    """
    first: Dict[int, Step] = {}
    for a in sh.after:
        if a.before_no is not None and a.before_no not in first:
            first[a.before_no] = a
    pairs = []
    for b in sh.before:
        a = first.get(b.no)
        if a is not None and a.kind == KIND_SAME:
            pairs.append((b, a))
    return pairs


def shoryoku_hours(sh: Shoryoku) -> Tuple[float, float]:
    """別紙1 の D3（削減される業務に要していた時間）と J3（導入後に発生する業務に要する時間）。1日あたりの時間。

    D3 =（導入前の合計 −組になった導入前の分 −組の差のうち負のもの）÷60
    J3 =（導入後の合計 −組になった導入後の分 ＋組の差のうち正のもの）÷60
    差は（導入後の分 −導入前の分）。別紙1 の F 列・N 列は、分が0の行では差を出さないが、その行の分は0なので同じになる。
    """
    pairs = shoryoku_pairs(sh)
    before_total = sum(s.minutes for s in sh.before)
    after_total = sum(s.minutes for s in sh.after)
    paired_before = sum(b.minutes for b, _a in pairs)
    paired_after = sum(a.minutes for _b, a in pairs)
    negative = sum(min(0.0, a.minutes - b.minutes) for b, a in pairs)
    positive = sum(max(0.0, a.minutes - b.minutes) for b, a in pairs)
    return (before_total - paired_before - negative) / 60, (after_total - paired_after + positive) / 60


def shoryoku_index(cut: float, after: float) -> float:
    """別紙1 の M3：IF(D3=0,0,IF((D3-J3)/D3<0,0,(D3-J3)/D3))。"""
    if cut == 0:
        return 0.0
    ratio = (cut - after) / cut
    return 0.0 if ratio < 0 else ratio


def payback_years(total: float, saved_hours: float, days: float, wage: float, added_value: float) -> Optional[float]:
    """別紙3 の C3：投資総額 ÷（削減工数 × 年間稼働日数 × 人件費単価 ＋ 増加した付加価値額）。0以下と0割りは None（空）。"""
    denom = saved_hours * days * wage + added_value
    if denom == 0:
        return None
    years = total / denom
    return None if years <= 0 else years


# ---------------------------------------------------------------- 式


class CalcError(ArithmeticError):
    pass


@dataclass
class Expr:
    """指定の式1つ。Python の式として読み、使える形だけを通す。"""

    text: str
    where: str
    node: ast.AST
    rows: List[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str, where: str, names: set, row_keys: Sequence[str]) -> "Expr":
        source = nfkc(text).strip().replace("^", "**")
        if not source:
            raise SpecError(f"{where} の式が空です")
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError:
            raise SpecError(f"{where} の式「{text}」を読めません")
        expr = cls(text, where, tree.body)
        expr._check(tree.body, names, set(row_keys))
        return expr

    def _check(self, node: ast.AST, names: set, row_keys: set) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            self._check(node.left, names, row_keys)
            self._check(node.right, names, row_keys)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._check(node.operand, names, row_keys)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(
                node.value, bool):
            if not math.isfinite(float(node.value)):
                raise SpecError(f"{self.where} の式に、数でない数があります")
        elif isinstance(node, ast.Name):
            if node.id == YEAR or node.id in names:
                return
            if node.id in row_keys:
                if node.id not in self.rows:
                    self.rows.append(node.id)
                return
            raise SpecError(f"{self.where} の式の「{node.id}」が、前提にも基準年度にもありません")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS:
            if node.keywords or not node.args:
                raise SpecError(f"{self.where} の式の {node.func.id} の書き方が違います")
            if node.func.id in ("ROUND", "ROUNDDOWN", "ROUNDUP") and len(node.args) != 2:
                raise SpecError(f"{self.where} の式の {node.func.id} は、2つの値を取ります")
            for arg in node.args:
                self._check(arg, names, row_keys)
        else:
            raise SpecError(f"{self.where} の式「{self.text}」に、使えない書き方があります")

    def excel(self, resolve: Callable[[str], str]) -> str:
        return "=" + _excel(self.node, resolve)

    def value(self, lookup: Callable[[str], float]) -> float:
        try:
            return _eval(self.node, lookup)
        except CalcError as e:
            raise SpecError(f"{self.where} の式「{self.text}」を計算できません（{e}）")


_OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "^"}


def _number_text(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value)).replace("e", "E")


def _excel(node: ast.AST, resolve: Callable[[str], str]) -> str:
    """Excel の式にする。どの演算にもかっこを付け、Excel と Python の優先順位の違い（-2^2 など）を消す。"""
    if isinstance(node, ast.BinOp):
        return f"({_excel(node.left, resolve)}{_OPS[type(node.op)]}{_excel(node.right, resolve)})"
    if isinstance(node, ast.UnaryOp):
        inner = _excel(node.operand, resolve)
        return f"(-{inner})" if isinstance(node.op, ast.USub) else inner
    if isinstance(node, ast.Constant):
        return _number_text(node.value)
    if isinstance(node, ast.Name):
        return resolve(node.id)
    if isinstance(node, ast.Call):
        return node.func.id + "(" + ",".join(_excel(a, resolve) for a in node.args) + ")"
    raise SpecError("式を Excel の形にできません")


def _eval(node: ast.AST, lookup: Callable[[str], float]) -> float:
    if isinstance(node, ast.BinOp):
        a = _eval(node.left, lookup)
        b = _eval(node.right, lookup)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise CalcError("0 で割っています")
            return a / b
        if a < 0 and not float(b).is_integer():
            raise CalcError("負の数を、整数でない数で累乗しています")
        if a == 0 and b <= 0:
            raise CalcError("0 を0以下の数で累乗しています")
        try:
            return float(a) ** float(b)
        except OverflowError:
            raise CalcError("数が大きすぎます")
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, lookup)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(lookup(node.id))
    if isinstance(node, ast.Call):
        args = [_eval(a, lookup) for a in node.args]
        name = node.func.id
        if name == "MIN":
            return min(args)
        if name == "MAX":
            return max(args)
        digits = args[1]
        if not float(digits).is_integer():
            raise CalcError(f"{name} の桁が整数ではありません")
        fn = {"ROUND": youken.round_half_up, "ROUNDDOWN": youken.rounddown, "ROUNDUP": youken.roundup}[name]
        return fn(args[0], int(digits))
    raise CalcError("使えない書き方です")


# ---------------------------------------------------------------- ブック（どのセルに何を書くか）


@dataclass
class Cell:
    value: Any = None  # 数式でないもの（文字・数）
    formula: Optional[str] = None  # "=..."
    py: Any = None  # 数式を Python で計算した値
    fmt: Optional[str] = None
    fill: Optional[str] = None
    bold: bool = False


@dataclass
class Sheet:
    title: str
    cells: Dict[str, Cell] = field(default_factory=dict)
    widths: Dict[str, float] = field(default_factory=dict)

    def put(self, ref: str, value: Any = None, **kw: Any) -> Cell:
        cell = Cell(value=value, **kw)
        self.cells[ref] = cell
        return cell

    def formula(self, ref: str, formula: str, py: Any, fmt: Optional[str] = None, bold: bool = False) -> Cell:
        return self.put(ref, formula=formula, py=py, fmt=fmt, bold=bold)


@dataclass
class Book:
    sheets: List[Sheet]
    names: Dict[str, Tuple[str, str]]  # 名前 → (シート, "$C$5")
    summary: Dict[str, Any]

    def formulas(self) -> Dict[Tuple[str, str], Any]:
        """数式のセルと、その Python の値。"""
        return {(s.title, ref): c.py for s in self.sheets for ref, c in s.cells.items() if c.formula is not None}


def plan_sheet_title(years: int) -> str:
    return f"計画（{years}年）"


def _quoted(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _fmt_for(item: Item) -> str:
    if item.unit == "%":
        return FMT_RATE
    if item.unit == "円":
        return FMT_YEN
    return FMT_NUMBER


def _assumption_sheet(spec: Spec) -> Tuple[Sheet, Dict[str, Tuple[str, str]], Dict[Tuple[str, int], str]]:
    sh = Sheet(SHEET_ASSUMPTIONS)
    names: Dict[str, Tuple[str, str]] = {}
    steps_at: Dict[Tuple[str, int], str] = {}
    sh.put("A1", "前提（数字の元になるもの）", bold=True)
    sh.put("A2", "色を付けた「値」のセルだけを書き換えてください。決まっていない前提は「状態」の欄に「仮」と書いてあります。"
                 "率は小数で書いてあり、% で表示しています。")
    headers = ("番号", "名前", "値", "単位", "この数字は何か", "根拠", "出典", "状態")
    groups = (("前提（これからの見込み）", "P", spec.assumptions), ("基準年度の実績（決算書など）", "J", list(spec.base.values())))
    row = 4
    for title, prefix, items in groups:
        sh.put(f"A{row}", title, bold=True)
        row += 1
        for i, h in enumerate(headers, start=1):
            sh.put(f"{col_name(i)}{row}", h, bold=True)
        row += 1
        for n, item in enumerate(items, start=1):
            sh.put(f"A{row}", f"{prefix}-{n:02d}")
            sh.put(f"B{row}", item.name)
            if item.formula is not None:  # 直近期の実績からの式（書き換えるのは直近期の値）
                sh.formula(f"C{row}", item.formula.excel(lambda name: name), item.value, _fmt_for(item))
            else:
                sh.put(f"C{row}", item.value, fmt=_fmt_for(item), fill=FILL_INPUT)
            sh.put(f"D{row}", item.unit)
            sh.put(f"E{row}", item.desc)
            sh.put(f"F{row}", item.basis)
            sh.put(f"G{row}", item.source)
            if item.provisional:
                sh.put(f"H{row}", "仮", fill=FILL_PROVISIONAL)
            names[item.name] = (SHEET_ASSUMPTIONS, f"$C${row}")
            row += 1
        row += 1
    row = _beppyo_assumption_tables(sh, spec, row, names, headers)
    if spec.shoryoku is not None:
        sh.put(f"A{row}", "省力化の元（様式その3 の別紙1・別紙3 に入れる数）", bold=True)
        row += 1
        for i, h in enumerate(headers, start=1):
            sh.put(f"{col_name(i)}{row}", h, bold=True)
        row += 1
        for n, item in enumerate(spec.shoryoku.items.values(), start=1):
            sh.put(f"A{row}", f"S-{n:02d}")
            sh.put(f"B{row}", item.name)
            sh.put(f"C{row}", item.value, fmt=FMT_YEN if item.unit.startswith("円") else FMT_NUMBER, fill=FILL_INPUT)
            sh.put(f"D{row}", item.unit)
            sh.put(f"E{row}", item.desc)
            sh.put(f"F{row}", item.basis)
            sh.put(f"G{row}", item.source)
            if item.provisional:
                sh.put(f"H{row}", "仮", fill=FILL_PROVISIONAL)
            names[item.name] = (SHEET_ASSUMPTIONS, f"$C${row}")
            row += 1
        row += 1
        for title, side, steps in (("設備導入前の作業（1日あたり。別紙1 の左）", "前", spec.shoryoku.before),
                                   ("設備導入後の作業（1日あたり。別紙1 の右）", "後", spec.shoryoku.after)):
            sh.put(f"A{row}", title, bold=True)
            row += 1
            heads = ["No.", "工程名・作業名", "作業時間（分）"] + (["作業種別", "対応する導入前の No."] if side == "後" else [])
            for i, h in enumerate(heads, start=1):
                sh.put(f"{col_name(i)}{row}", h, bold=True)
            row += 1
            for step in steps:
                sh.put(f"A{row}", step.no)
                sh.put(f"B{row}", step.name)
                sh.put(f"C{row}", step.minutes, fmt=FMT_NUMBER, fill=FILL_INPUT)
                if side == "後":
                    sh.put(f"D{row}", step.kind)
                    if step.before_no is not None:
                        sh.put(f"E{row}", step.before_no)
                steps_at[(side, step.no)] = f"{_quoted(SHEET_ASSUMPTIONS)}!$C${row}"
                row += 1
            row += 1
    sh.widths.update({"A": 8, "B": 26, "C": 16, "D": 10, "E": 44, "F": 14, "G": 30, "H": 8})
    return sh, names, steps_at


def _beppyo_assumption_tables(sh: Sheet, spec: Spec, row: int, names: Dict[str, Tuple[str, str]],
                              headers: Sequence[str]) -> int:
    """前提のシートに、年度・直近期の実績・売上原価の割合の表を置く（様式の別紙4 に写す数字の元）。次の行を返す。"""
    tl = spec.timeline
    if tl is not None:
        sh.put(f"A{row}", "年度（様式の別紙4 の決算期。道具が年月から決めたもので、書き換えない）", bold=True)
        row += 1
        for i, h in enumerate(headers[:7], start=1):
            sh.put(f"{col_name(i)}{row}", h, bold=True)
        row += 1
        deadline = f"{tl.deadline[0]}年{tl.deadline[1]}月" if tl.deadline else "（分からない）"
        lines = (
            ("直近期", tl.label(tl.recent_actual), "", "直近の決算期（決算書の期）", tl.basis, tl.source),
            ("応募の締切", deadline, "", "応募申請の締切", "", tl.deadline_source),
            ("締切期", tl.label(tl.closing), "", "応募の締切を含む決算期", "", ""),
            ("補助事業の完了予定", f"{tl.completion[0]}年{tl.completion[1]}月", "", "補助事業を完了する予定の年月", tl.basis,
             tl.source),
            ("基準年度", tl.label(tl.base), "", "補助事業の完了日を含む決算期", "", ""),
            (ELAPSED, tl.elapsed, "年", "直近期から基準年度までの年数（基準年度の式で使う）", "", ""),
            ("計画の期間", f"{tl.label(tl.base + 1)}〜{tl.label(tl.base + spec.years)}", "", "基準年度の翌年度を1年目とする",
             "", ""),
        )
        for n, (name, value, unit, desc, basis, source) in enumerate(lines, start=1):
            for col, v in zip("ABCDEFG", (f"Y-{n:02d}", name, value, unit, desc, basis, source)):
                sh.put(f"{col}{row}", v)
            if name == ELAPSED:
                names[ELAPSED] = (SHEET_ASSUMPTIONS, f"$C${row}")
            row += 1
        row += 1
    for title, prefix, items in (("直近期の実績（決算書）", "R", list(spec.recent.values())),
                                 ("売上原価の割合（区分ごと。残りは販売費及び一般管理費）", "G", list(spec.cost_share.values()))):
        if not items:
            continue
        sh.put(f"A{row}", title, bold=True)
        row += 1
        for i, h in enumerate(headers, start=1):
            sh.put(f"{col_name(i)}{row}", h, bold=True)
        row += 1
        for n, item in enumerate(items, start=1):
            for col, v in zip("ABDEFG", (f"{prefix}-{n:02d}", item.name, item.unit, item.desc, item.basis, item.source)):
                sh.put(f"{col}{row}", v)
            sh.put(f"C{row}", item.value, fmt=_fmt_for(item), fill=FILL_INPUT)
            if item.provisional:
                sh.put(f"H{row}", "仮", fill=FILL_PROVISIONAL)
            names[item.name] = (SHEET_ASSUMPTIONS, f"$C${row}")
            row += 1
        row += 1
    return row


def _lookup_values(values: Dict[str, float], extra: Dict[str, float]) -> Callable[[str], float]:
    def lookup(name: str) -> float:
        if name in extra:
            return extra[name]
        return values[name]

    return lookup


def build(spec: Spec, requirements: Sequence[youken.Requirement], scenario: bool = True) -> Book:
    """指定と、制度データから読んだ要件から、ブックの中身（数式と Python の値）を作る。

    scenario が真なら、数量の前提を2割減らした指定でも計算し直し、要件の判定を「まとめ」に置く。
    """
    n = spec.years
    values = spec.values()
    year_cols = [col_name(2 + y) for y in range(n + 1)]  # 基準年度=B、1年目=C …
    judge_col = col_name(3 + n)
    basis_col = col_name(4 + n)
    note_col = col_name(5 + n)
    first, last = year_cols[1], year_cols[-1]
    title = plan_sheet_title(n)
    pa, names, steps_at = _assumption_sheet(spec)
    pl = Sheet(title)

    # ---- 見出しと年
    pl.put("A1", f"{title}：既存事業・新事業・合算", bold=True)
    head_row, year_row = 9, 10
    pl.put(f"A{head_row}", "項目", bold=True)
    for y, col in enumerate(year_cols):
        pl.put(f"{col}{head_row}", "基準年度" if y == 0 else f"{y}年目", bold=True)
        pl.put(f"{col}{year_row}", y)
    pl.put(f"{judge_col}{head_row}", "判定（全体）", bold=True)
    pl.put(f"{basis_col}{head_row}", "基準", bold=True)
    pl.put(f"{note_col}{head_row}", "出典・説明", bold=True)
    pl.put(f"A{year_row}", "年（基準年度=0）")

    def ycell(col: str) -> str:
        return f"{col}${year_row}"

    row = 12
    # 値：(区分, 行の名前) → 年ごとの Python の値
    py: Dict[Tuple[str, str], List[float]] = {}
    at: Dict[Tuple[str, str], int] = {}
    labels = {
        "売上": "売上", "原材料費": "原材料費", "人件費": "人件費（給与支給総額＋その他の人件費）",
        "給与支給総額": "　うち給与支給総額（全月分の給与を受けた従業員）", "その他の人件費": "　うちその他の人件費（法定福利費・役員の報酬など）",
        "減価償却費": "減価償却費", "その他の経費": "その他の経費", "営業利益": "営業利益",
    }
    order = ("売上", "原材料費", "人件費", "給与支給総額", "その他の人件費", "減価償却費", "その他の経費", "営業利益")

    def place_rows(group: str, heading: str) -> None:
        nonlocal row
        pl.put(f"A{row}", heading, bold=True)
        row += 1
        for key in order:
            at[(group, key)] = row
            pl.put(f"A{row}", labels[key])
            row += 1
        row += 1

    for b in spec.businesses:
        place_rows(b.name, "【既存事業】" if b.existing else f"【新事業：{b.name}】")
    place_rows("合算", "【合算】")

    # 事業ごとの行の値と式
    for b in spec.businesses:
        for y, col in enumerate(year_cols):
            done: Dict[str, float] = {}

            def row_value(key: str, b=b, y=y, col=col, done=done) -> float:
                if key in done:
                    return done[key]
                expr = b.exprs.get(key)
                ref = f"{col}{at[(b.name, key)]}"
                if y < b.start:
                    v = 0.0
                    pl.put(ref, 0, fmt=FMT_YEN)
                elif b.existing and (y == 0 or expr is None):
                    v = values[BASE_PREFIX + key]
                    pl.formula(ref, f"={BASE_PREFIX}{key}", v, FMT_YEN)
                elif expr is None:
                    v = 0.0
                    pl.put(ref, 0, fmt=FMT_YEN)
                else:
                    extra = {YEAR: float(y)}
                    for r in expr.rows:
                        extra[r] = row_value(r)
                    v = expr.value(_lookup_values(values, extra))

                    def resolve(name: str, col=col, b=b) -> str:
                        if name == YEAR:
                            return ycell(col)
                        if name in ROW_KEYS:
                            return f"{col}{at[(b.name, name)]}"
                        return name

                    pl.formula(ref, expr.excel(resolve), v, FMT_YEN)
                done[key] = v
                return v

            for key in ROW_KEYS:
                py.setdefault((b.name, key), [0.0] * (n + 1))[y] = row_value(key)
            _derived_rows(pl, py, at, b.name, y, col)

    # 合算
    for y, col in enumerate(year_cols):
        for key in ROW_KEYS:
            total = 0.0
            refs = []
            for b in spec.businesses:
                total += py[(b.name, key)][y]
                refs.append(f"{col}{at[(b.name, key)]}")
            py.setdefault(("合算", key), [0.0] * (n + 1))[y] = total
            pl.formula(f"{col}{at[('合算', key)]}", "=" + "+".join(refs), total, FMT_YEN)
        _derived_rows(pl, py, at, "合算", y, col)

    # ---- 人数
    pl.put(f"A{row}", "【人数】", bold=True)
    row += 1
    people_at = {}
    for key in ("役員数", "常勤従業員数", "労働者数", "給与を受けた従業員数"):
        people_at[key] = row
        pl.put(f"A{row}", {"労働者数": "労働者数（役員＋常勤従業員）"}.get(key, key))
        row += 1
    row += 1
    people: Dict[str, List[float]] = {k: [0.0] * (n + 1) for k in people_at}
    for y, col in enumerate(year_cols):
        done: Dict[str, float] = {}

        def person(key: str, y=y, col=col, done=done) -> float:
            if key in done:
                return done[key]
            expr = spec.people.get(key)
            ref = f"{col}{people_at[key]}"
            if y == 0 or expr is None:
                v = values[BASE_PREFIX + key]
                pl.formula(ref, f"={BASE_PREFIX}{key}", v, FMT_PEOPLE)
            else:
                extra = {YEAR: float(y)}
                for r in expr.rows:
                    extra[r] = person(r)
                v = expr.value(_lookup_values(values, extra))

                def resolve(name: str, col=col) -> str:
                    if name == YEAR:
                        return ycell(col)
                    if name in PEOPLE_KEYS:
                        return f"{col}{people_at[name]}"
                    return name

                pl.formula(ref, expr.excel(resolve), v, FMT_PEOPLE)
            done[key] = v
            return v

        for key in PEOPLE_KEYS:
            people[key][y] = person(key)
        w = people["役員数"][y] + people["常勤従業員数"][y]
        people["労働者数"][y] = w
        pl.formula(f"{col}{people_at['労働者数']}", f"={col}{people_at['役員数']}+{col}{people_at['常勤従業員数']}",
                   w, FMT_PEOPLE)
        label = "基準年度" if y == 0 else f"{y}年目"
        if w <= 0:
            raise SpecError(f"{label}の労働者数（役員＋常勤従業員）が0以下です。労働生産性を計算できません")
        if people["給与を受けた従業員数"][y] <= 0:
            raise SpecError(f"{label}の給与を受けた従業員数が0以下です。1人当たり給与支給総額を計算できません")

    # ---- 補助金の指標（様式の別紙4 と同じ計算）
    pl.put(f"A{row}", "【補助金の指標（様式の別紙4 と同じ計算）】", bold=True)
    row += 1
    ind_at = {}
    ind_labels = (
        ("付加価値額", "付加価値額（営業利益＋人件費＋減価償却費）", "会社が新しく生み出した価値。営業利益＋人件費＋減価償却費"),
        ("付加価値額の伸び", "付加価値額の年平均成長率（％）", "基準年度から毎年平均で何％伸びたか。小数第2位で切り捨て（別紙4 と同じ）"),
        ("労働生産性", "労働生産性（付加価値額÷労働者数）", "働く人1人当たりの付加価値額。小数第2位で切り捨て（別紙4 と同じ）"),
        ("労働生産性の伸び", "労働生産性の年平均成長率（％）", "小数第2位で切り捨て（別紙4 と同じ）"),
        ("1人当たり給与", "1人当たり給与支給総額（給与支給総額÷給与を受けた従業員数）", "小数第2位で切り捨て（別紙4 と同じ）"),
        ("1人当たり給与の伸び", "1人当たり給与支給総額の年平均成長率（％）", "下がったときは切り上げ、計算できないときは0（別紙4 と同じ）"),
    )
    for key, label, note in ind_labels:
        ind_at[key] = row
        pl.put(f"A{row}", label)
        pl.put(f"{note_col}{row}", note)
        row += 1
    row += 1
    ind: Dict[str, List[Any]] = {k: [None] * (n + 1) for k in ind_at}
    va_r, pr_r, pp_r = ind_at["付加価値額"], ind_at["労働生産性"], ind_at["1人当たり給与"]
    for y, col in enumerate(year_cols):
        va = py[("合算", "営業利益")][y] + py[("合算", "人件費")][y] + py[("合算", "減価償却費")][y]
        ind["付加価値額"][y] = va
        pl.formula(f"{col}{va_r}", f"={col}{at[('合算', '営業利益')]}+{col}{at[('合算', '人件費')]}"
                                   f"+{col}{at[('合算', '減価償却費')]}", va, FMT_YEN)
        w_ref = f"{col}{people_at['労働者数']}"
        p = youken.productivity(va, people["労働者数"][y])
        ind["労働生産性"][y] = p
        pl.formula(f"{col}{pr_r}", f"=IF({col}{va_r}<0,ROUNDUP(({col}{va_r}/{w_ref}),2),ROUNDDOWN(({col}{va_r}/{w_ref}),2))",
                   p, FMT_PER)
        pp = youken.pay_per_person(py[("合算", "給与支給総額")][y], people["給与を受けた従業員数"][y])
        ind["1人当たり給与"][y] = pp
        pl.formula(f"{col}{pp_r}",
                   f"=ROUNDDOWN({col}{at[('合算', '給与支給総額')]}/{col}{people_at['給与を受けた従業員数']},2)", pp, FMT_PER)
    for y, col in enumerate(year_cols):
        if y == 0:
            continue
        for key, level_r in (("付加価値額の伸び", va_r), ("労働生産性の伸び", pr_r)):
            g = youken.growth_plain(ind[key.replace("の伸び", "")][y], ind[key.replace("の伸び", "")][0], y)
            value = youken.CANNOT_CALC if g is None else g
            ind[key][y] = value
            pl.formula(f"{col}{ind_at[key]}",
                       f'=IFERROR(ROUNDDOWN((({col}{level_r}/$B${level_r})^(1/{ycell(col)})-1)*100,2),"{youken.CANNOT_CALC}")',
                       value, FMT_GROWTH)
        g = youken.growth_pay(ind["1人当たり給与"][y], ind["1人当たり給与"][0], y)
        ind["1人当たり給与の伸び"][y] = g
        inner = f"(({col}{pp_r}/$B${pp_r})^(1/{ycell(col)})-1)*100"
        pl.formula(f"{col}{ind_at['1人当たり給与の伸び']}",
                   f"=IFERROR(IF({col}{pp_r}>=$B${pp_r},ROUNDDOWN({inner},2),ROUNDUP({inner},2)),0)", g, FMT_GROWTH)

    # ---- 数値の要件の判定（制度データから読んだ基準）
    pl.put(f"A{row}", "【数値の要件の判定（基準は制度データから）】", bold=True)
    row += 1
    growth_row = {youken.VALUE_ADDED: "付加価値額の伸び", youken.PRODUCTIVITY: "労働生産性の伸び", youken.PAY: "1人当たり給与の伸び"}
    level_row = {youken.VALUE_ADDED: "付加価値額", youken.PRODUCTIVITY: "労働生産性", youken.PAY: "1人当たり給与"}
    results = []
    judge_cells_basic: List[str] = []
    near_cells_basic: List[str] = []
    for req in requirements:
        if not req.judged:
            continue
        t = req.threshold
        t_text = youken.threshold_literal(t)
        g_key, l_key = growth_row[req.indicator], level_row[req.indicator]
        g_r, l_r = ind_at[g_key], ind_at[l_key]
        jr, nr = row, row + 1
        row += 2
        suffix = "（特例を選ぶときだけ）" if req.optional else ""
        pl.put(f"A{jr}", f"要件：{req.name}{suffix}")
        pl.put(f"A{nr}", "　基準との差が0.01ポイント未満（境目）")
        pl.put(f"{basis_col}{jr}", f"{req.threshold_text()}（{req.when}）")
        pl.put(f"{note_col}{jr}", req.source_text())
        pl.put(f"{note_col}{nr}", "様式の計算は小数第3位以下を切り捨てるので、ちょうど基準の計画が基準を下回ることがあります")
        per_year = []
        judged_years = req.years(n)
        for y in judged_years:
            col = year_cols[y]
            g = ind[g_key][y]
            verdict = youken.judge(g, t)
            pl.formula(f"{col}{jr}", f'=IF(ISNUMBER({col}{g_r}),IF({col}{g_r}>={t_text},"{youken.MEETS}","{youken.FAILS}"),'
                                     f'"{youken.UNJUDGEABLE}")', verdict)
            raw = youken.raw_growth(ind[l_key][y], ind[l_key][0], y)
            near = youken.is_near(raw, t)
            raw_f = f"(({col}{l_r}/$B${l_r})^(1/{ycell(col)})-1)*100"
            pl.formula(f"{col}{nr}", f'=IFERROR(IF(ROUND(ABS({raw_f}-{t_text}),{youken.NEAR_DIGITS})<0.01,"{youken.NEAR}",""),"")',
                       youken.NEAR if near else "")
            per_year.append({"年": y, "伸び": g, "切り捨てる前": raw, "判定": verdict, "境目": near})
        verdicts = [p["判定"] for p in per_year]
        if youken.FAILS in verdicts:
            overall = youken.FAILS
        elif youken.UNJUDGEABLE in verdicts:
            overall = youken.UNJUDGEABLE
        else:
            overall = youken.MEETS
        rng = f"{first}{jr}:{last}{jr}"
        pl.formula(f"{judge_col}{jr}",
                   f'=IF(COUNTIF({rng},"{youken.FAILS}")>0,"{youken.FAILS}",IF(COUNTIF({rng},"{youken.UNJUDGEABLE}")>0,'
                   f'"{youken.UNJUDGEABLE}","{youken.MEETS}"))', overall, bold=True)
        any_near = any(p["境目"] for p in per_year)
        pl.formula(f"{judge_col}{nr}", f'=IF(COUNTIF({first}{nr}:{last}{nr},"{youken.NEAR}")>0,"境目あり","")',
                   "境目あり" if any_near else "")
        if not req.optional:
            judge_cells_basic.append(f"{judge_col}{jr}")
            near_cells_basic.append(f"{judge_col}{nr}")
        results.append({
            "名前": req.name, "指標": req.indicator, "基準": req.threshold_text(), "いつ": req.when,
            "特例": req.optional, "出典": req.source_text(), "制度データの状態": req.basis_state,
            "年ごと": per_year, "判定": overall, "境目": any_near,
        })
    skipped = [{"名前": r.name, "理由": r.skip_reason} for r in requirements if not r.judged]

    # ---- 省力化の指標（様式その3 の別紙1・別紙3 と同じ計算）
    shoryoku_summary = None
    if spec.shoryoku is not None:
        row += 1
        shoryoku_summary = _shoryoku_rows(pl, spec.shoryoku, steps_at, row, n, ind["付加価値額"], va_r, first, last,
                                          ycell(last), note_col)
        row = shoryoku_summary.pop("_次の行")

    # ---- 様式（別紙4）に写す数字（指定に年度・直近期の実績・売上原価の割合などがあるとき）
    beppyo = None
    if spec.beppyo:
        beppyo = _beppyo4_rows(pl, spec, requirements, py, at, people, people_at, ind, year_cols, ycell, row + 1)
        row = beppyo.pop("_次の行")

    # ---- まとめ（上）
    pl.put("A2", "まとめ", bold=True)
    summary_rows = [
        (f"{n}年目の売上（合算）", f"={last}{at[('合算', '売上')]}", py[("合算", "売上")][n], "円", FMT_YEN),
        (f"{n}年目の付加価値額", f"={last}{va_r}", ind["付加価値額"][n], "円", FMT_YEN),
        (f"労働生産性の年平均成長率（{n}年目）", f"={last}{ind_at['労働生産性の伸び']}", ind["労働生産性の伸び"][n], "％",
         FMT_GROWTH),
        (f"1人当たり給与支給総額の年平均成長率（{n}年目）", f"={last}{ind_at['1人当たり給与の伸び']}",
         ind["1人当たり給与の伸び"][n], "％", FMT_GROWTH),
    ]
    basic = [r for r in results if not r["特例"]]
    for i, (label, formula, value, unit, fmt) in enumerate(summary_rows, start=3):
        pl.put(f"A{i}", label)
        pl.formula(f"B{i}", formula, value, fmt)
        pl.put(f"C{i}", unit)
    pl.put("A7", "数値の要件（特例を除く）をすべて満たすか")
    if basic:
        fails = ",".join(f'{c}="{youken.FAILS}"' for c in judge_cells_basic)
        unj = ",".join(f'{c}="{youken.UNJUDGEABLE}"' for c in judge_cells_basic)
        verdicts = [r["判定"] for r in basic]
        overall = youken.FAILS if youken.FAILS in verdicts else (
            youken.UNJUDGEABLE if youken.UNJUDGEABLE in verdicts else youken.MEETS)
        pl.formula("B7", f'=IF(OR({fails}),"{youken.FAILS}",IF(OR({unj}),"{youken.UNJUDGEABLE}","{youken.MEETS}"))',
                   overall, bold=True)
        nears = ",".join(f'{c}="境目あり"' for c in near_cells_basic)
        near_any = any(r["境目"] for r in basic)
        near_text = "あり（計画の数字を少し上げることを勧めます）"
        pl.put("C7", "基準との差が0.01ポイント未満の要件")
        pl.formula("D7", f'=IF(OR({nears}),"{near_text}","なし")', near_text if near_any else "なし")
    else:
        overall = None
        pl.put("B7", "判定できる要件がありません（制度データを確かめてください）")

    # 数量が2割少ない場合（式ではなく、道具が数量の前提を0.8倍にして計算し直した値）
    low = _low_case(spec, requirements, scenario, py)
    pl.put("A8", LOW_LABEL)
    if low is None:
        pl.put("B8", NO_QUANTITY)
    else:
        shown = low["判定"] if low["判定"] is not None else "判定できる要件がありません"
        pl.put("B8", shown, bold=True)
        pl.put("C8", "数量の前提（" + "・".join(low["数量の前提"]) + "）を0.8倍にして、道具が計算し直した結果（式ではありません）"
               + ("。" + CURRENT_LEVEL_NOTE if low.get("今の数量まで減らしている行") else ""))
    pl.widths.update({"A": 48})
    for col in year_cols:
        pl.widths[col] = 15
    pl.widths.update({judge_col: 13, basis_col: 22, note_col: 60})

    # ---- 月次（1年目）
    mo = Sheet(SHEET_MONTHLY)
    mo.put("A1", "月次（1年目）：1年目の合算を12か月に分けたもの", bold=True)
    month_cols = [col_name(2 + m) for m in range(MONTHS)]
    total_col, plan_col = col_name(14), col_name(15)
    wave_row = 11
    if spec.waves is None:
        mo.put("A2", "季節の波は入れていません（12か月で同じにしています）。合計は計画の1年目と同じになります。")
    else:
        mo.put("A2", f"売上と原材料費は、{wave_row}行目の重み（季節の波）で月に分けています。ほかの経費は12か月で同じです。"
                     "営業利益は月ごとの売上から経費を引いたもので、合計は計画の1年目と同じになります。")
        mo.put(f"A{wave_row}", "売上と原材料費の月ごとの重み（季節の波）", bold=True)
        for col, w in zip(month_cols, spec.waves):
            mo.put(f"{col}{wave_row}", w, fmt=FMT_NUMBER, fill=FILL_INPUT)
        mo.formula(f"{total_col}{wave_row}", f"=SUM({month_cols[0]}{wave_row}:{month_cols[-1]}{wave_row})",
                   sum(spec.waves), FMT_NUMBER)
    wave_total = sum(spec.waves) if spec.waves is not None else None
    mo.put("A3", "項目", bold=True)
    for m, col in enumerate(month_cols, start=1):
        mo.put(f"{col}3", f"{m}か月目", bold=True)
    mo.put(f"{total_col}3", "合計", bold=True)
    mo.put(f"{plan_col}3", "1年目（計画）", bold=True)
    monthly = {}
    monthly_values: Dict[str, List[float]] = {}
    q_title = _quoted(title)
    month_keys = ("売上", "原材料費", "人件費", "減価償却費", "その他の経費", "営業利益")
    for i, key in enumerate(month_keys, start=4):
        mo.put(f"A{i}", key)
        year1 = py[("合算", key)][1]
        src = f"{q_title}!{first}{at[('合算', key)]}"
        parts = []
        for m, col in enumerate(month_cols):
            if spec.waves is not None and key in ("売上", "原材料費"):
                v = year1 * spec.waves[m] / wave_total
                formula = f"={src}*{col}${wave_row}/${total_col}${wave_row}"
            elif spec.waves is not None and key == "営業利益":
                vals = [monthly_values[k][m] for k in month_keys[:5]]
                v = vals[0] - vals[1] - vals[2] - vals[3] - vals[4]
                formula = f"={col}4-{col}5-{col}6-{col}7-{col}8"
            else:
                v = year1 / 12
                formula = f"={src}/12"
            parts.append(v)
            mo.formula(f"{col}{i}", formula, v, FMT_YEN)
        monthly_values[key] = parts
        total = 0.0
        for v in parts:
            total += v
        mo.formula(f"{total_col}{i}", f"=SUM({month_cols[0]}{i}:{month_cols[-1]}{i})", total, FMT_YEN)
        mo.formula(f"{plan_col}{i}", f"={src}", year1, FMT_YEN)
        monthly[key] = {"合計": total, "1年目": year1}
    mo.widths.update({"A": 16, total_col: 16, plan_col: 16})
    for col in month_cols:
        mo.widths[col] = 13

    summary = {
        "計画の年数": n,
        "シート": [SHEET_ASSUMPTIONS, title, SHEET_MONTHLY],
        "前提の数": len(spec.assumptions),
        "根拠か出典のない前提": [a.name for a in spec.assumptions if a.unsupported],
        "根拠か出典のない基準年度の値": [k for k, item in spec.base.items() if item.unsupported],
        "仮の前提": [a.name for a in spec.assumptions if a.provisional],
        "仮の基準年度の値": [k for k, item in spec.base.items() if item.provisional],
        "まとめ": {label: value for label, _f, value, _u, _fmt in summary_rows},
        "数値の要件（特例を除く）をすべて満たすか": overall,
        "判定した要件": results,
        "判定しなかった要件": skipped,
        "数量が2割少ない場合": low,
        "省力化": shoryoku_summary,
        "年度": _timeline_summary(spec),
        "別紙4": beppyo,
        "根拠か出典のない、そのほかの値": [item.name for item in _other_items(spec) if item.unsupported],
        "仮の、そのほかの値": [item.name for item in _other_items(spec) if item.provisional],
        "月次の波": spec.waves,
        "月次": monthly_values,
        "月次の合計と1年目": monthly,
        "合算": {key: py[("合算", key)] for key in ROW_KEYS + ("人件費", "営業利益")},
        "事業ごと": {b.name: {key: py[(b.name, key)] for key in ROW_KEYS + ("人件費", "営業利益")}
                    for b in spec.businesses},
        "人数": people,
        "指標": ind,
    }
    return Book([pa, pl, mo], names, summary)


def _low_case(spec: Spec, requirements: Sequence[youken.Requirement], scenario: bool,
              plan_py: Optional[Dict[Tuple[str, str], List[float]]] = None) -> Optional[Dict[str, Any]]:
    """数量の前提を0.8倍にして計算し直した、数値の要件（特例を除く）の判定。数量の前提がなければ None。"""
    names = spec.quantity_names()
    if not scenario or not names:
        return None
    out: Dict[str, Any] = {"数量の前提": names, "割合": LOW_FACTOR}
    try:
        low = build(spec.scaled_quantities(LOW_FACTOR), requirements, scenario=False).summary
    except SpecError as e:
        out.update({"判定": youken.UNJUDGEABLE, "理由": str(e), "要件ごと": []})
        return out
    out["判定"] = low["数値の要件（特例を除く）をすべて満たすか"]
    out["要件ごと"] = [{"名前": r["名前"], "特例": r["特例"], "判定": r["判定"],
                     "年ごと": [{"年": p["年"], "伸び": p["伸び"], "判定": p["判定"]} for p in r["年ごと"]]}
                    for r in low["判定した要件"]]
    out["まとめ"] = low["まとめ"]
    out.update(_low_case_reading(spec, plan_py, low))
    if out["今の数量まで減らしている行"]:
        out["参考の判定（今の数量まで減らした場合）"] = out["判定"]
        out["判定"] = youken.UNJUDGEABLE
    return out


CURRENT_LEVEL_NOTE = ("今の数量（実績）まで「数量_」にしているので、判定しません。今の数量は「数量_」を付けない前提に分け、"
                      "計画で増やす分だけを「数量_」にしてください")


def _row_values_at(b: Business, y: int, values: Dict[str, float]) -> Dict[str, float]:
    """既存事業の行を、式どおりに年 y で計算した値（年=0 でも式を使う。式のない行は基準年度の値）。"""
    done: Dict[str, float] = {}

    def value(key: str) -> float:
        if key not in done:
            expr = b.exprs.get(key)
            if expr is None:
                done[key] = values[BASE_PREFIX + key]
            else:
                extra = {YEAR: float(y)}
                for r in expr.rows:
                    extra[r] = value(r)
                done[key] = expr.value(_lookup_values(values, extra))
        return done[key]

    return {key: value(key) for key in ROW_KEYS}


def _current_level_rows(spec: Spec) -> List[Dict[str, Any]]:
    """既存事業の式のうち、年=0 で基準年度の実績になる（今の数量で今の売上を作っている）のに、数量の前提を0.8倍にすると
    年=0 の値まで動く行（今の数量まで「数量_」にしている）。"""
    b = next(x for x in spec.businesses if x.existing)
    values, low_values = spec.values(), spec.scaled_quantities(LOW_FACTOR).values()
    try:
        plain, scaled = _row_values_at(b, 0, values), _row_values_at(b, 0, low_values)
    except SpecError:
        return []
    out = []
    for key in ROW_KEYS:
        if key not in b.exprs:
            continue
        base = values[BASE_PREFIX + key]
        scale = max(abs(base), 1.0)
        if abs(plain[key] - base) <= CURRENT_LEVEL_TOL * scale and abs(scaled[key] - plain[key]) >= CURRENT_LEVEL_TOL * scale:
            out.append({"事業": b.name, "行": key, "基準年度の値": base, "数量を0.8倍にした年0の値": scaled[key]})
    return out


def _low_case_reading(spec: Spec, plan_py: Optional[Dict[Tuple[str, str], List[float]]],
                      low: Dict[str, Any]) -> Dict[str, Any]:
    """数量が2割少ない場合の読み方：今の数量まで減らしていないか、数量を減らすと変わる行、動かない原材料費。"""
    current = _current_level_rows(spec)
    out: Dict[str, Any] = {"今の数量まで減らしている行": current, "数量を減らすと変わる行": [], "最後の年": None, "知らせ": []}
    notes = out["知らせ"]
    for c in current:
        notes.append(f"{c['事業']}の{c['行']}の式は、基準年度（年=0）で実績の {c['基準年度の値']:,.0f}円 になります。数量の前提を"
                     f"0.8倍にすると年=0 でも {c['数量を0.8倍にした年0の値']:,.0f}円 になり、今の数量（実績）まで2割減らした"
                     "判定になります（1年目にいきなり実績から2割下がるので、伸びが大きく負になる）。" + CURRENT_LEVEL_NOTE)
    if plan_py is None:
        return out
    n = spec.years
    for b in spec.businesses:
        moved = []
        for key in ROW_KEYS:
            plan, lowered = plan_py[(b.name, key)], low["事業ごと"][b.name][key]
            if any(abs(p - q) > 1e-9 * max(1.0, abs(p)) for p, q in zip(plan, lowered)):
                moved.append(key)
                out["数量を減らすと変わる行"].append({"事業": b.name, "行": key, "計画": plan[n], "2割少ない場合": lowered[n]})
        material = plan_py[(b.name, "原材料費")]
        if "売上" in moved and "原材料費" not in moved and any(abs(v) > 0 for v in material[1:]):
            notes.append(f"{b.name}の売上は数量で減りますが、原材料費は減りません（原材料費の式が数量や売上につながっていない）。"
                         "原材料費が数量に比例するなら、式を数量か売上につなげてください（つながないと、2割少ない場合を厳しく見積もる）")
    out["最後の年"] = {
        "年": n,
        "売上": [plan_py[("合算", "売上")][n], low["合算"]["売上"][n]],
        "付加価値額": [sum(plan_py[("合算", k)][n] for k in ("営業利益", "人件費", "減価償却費")), low["指標"]["付加価値額"][n]],
    }
    return out


# ---------------------------------------------------------------- 様式（別紙4）に写す数字（11/6 のリハーサルの穴1・穴2）

BEPPYO_ROWS = (
    ("売上高", "売上高"),
    ("売上原価", "　売上原価（区分ごとの合算 × 売上原価の割合）"),
    ("売上総利益", "売上総利益"),
    ("販売費及び一般管理費", "　販売費及び一般管理費（区分ごとの合算 ×（1 − 売上原価の割合））"),
    ("営業利益", "① 営業利益"),
    ("人件費", "② 人件費"),
    ("減価償却費", "③ 減価償却費"),
    ("既存設備の減価償却費", "　（内訳）既存設備の減価償却費"),
    ("本補助金で導入する設備の減価償却費", "　本補助金で導入する設備の減価償却費（1年目から）"),
    ("付加価値額", "④ 付加価値額（①＋②＋③）"),
    ("付加価値額の伸び", "付加価値額の年平均成長率（％）"),
    ("役員数", "⑤ 労働者数のうち役員数（人）"),
    ("常勤従業員数", "⑥ 労働者数のうち常勤従業員数（人）"),
    ("労働生産性", "労働生産性（④÷（⑤＋⑥））"),
    ("労働生産性の伸び", "労働生産性の年平均成長率（％）"),
    ("給与支給総額", "⑦ 全月分の給与等の支給を受けた従業員の給与支給総額"),
    ("給与を受けた従業員数", "⑧ 全月分の給与等の支給を受けた従業員数（人）"),
    ("1人当たり給与支給総額", "1人当たり給与支給総額（⑦÷⑧）"),
    ("1人当たり給与支給総額の伸び", "1人当たり給与支給総額の年平均成長率（％）"),
)
CHECK_COST = "照らし：売上原価＋販売費及び一般管理費（丸める前）"
CHECK_PROFIT = "照らし：売上−営業利益（丸める前。上と同じなら合う）"
_GROWTH_PAIRS = ((youken.VALUE_ADDED, "付加価値額の伸び", "付加価値額の伸び"),
                 (youken.PRODUCTIVITY, "労働生産性の伸び", "労働生産性の伸び"),
                 (youken.PAY, "1人当たり給与支給総額の伸び", "1人当たり給与の伸び"))


def _yen(x: float) -> float:
    return youken.round_half_up(x, 0)


def _beppyo4_rows(pl: Sheet, spec: Spec, requirements: Sequence[youken.Requirement],
                  py: Dict[Tuple[str, str], List[float]], at: Dict[Tuple[str, str], int], people: Dict[str, List[float]],
                  people_at: Dict[str, int], ind: Dict[str, List[Any]], year_cols: List[str],
                  ycell: Callable[[str], str], row: int) -> Dict[str, Any]:
    """計画のシートに、様式（別紙4）の行の並びで、円に丸めた値を数式で置く。Python の値と知らせも返す。"""
    n = spec.years
    tl, share, new_dep = spec.timeline, spec.cost_share, spec.new_dep
    notes: List[str] = []
    if share:
        missing = [k for k in COST_KEYS if k not in share and any(abs(v) > 0 for v in py[("合算", k)])]
        if missing:
            raise SpecError(f"{COST_SHARE_KEY}に、ない区分があります：" + "、".join(missing) + "（計画に金額がある区分は、すべて割合が要ります）")
    else:
        notes.append(f"「{COST_SHARE_KEY}」がないので、売上原価と販売費及び一般管理費は出していません（決算の内訳の行に「損益の区分」を"
                     "付けて kijun を動かすと、決算書の割合を指定に書きます）")
    if new_dep is None:
        notes.append(f"「{NEW_DEP_KEY}」がないので、減価償却費はすべて既存設備の分にしています（指定に式を書くと分けます）")
    elif share and NEW_DEP_KEY not in share:
        notes.append(f"{COST_SHARE_KEY}に「{NEW_DEP_KEY}」がないので、新しい設備の減価償却費も、決算書の減価償却費の割合"
                     f"（{share['減価償却費'].value * 100:.2f}%）で売上原価と販管費に分けています。製造の設備なら、割合に"
                     f"「{NEW_DEP_KEY}」: 1（根拠と出典つき）を書いてください" if "減価償却費" in share else
                     f"{COST_SHARE_KEY}に「{NEW_DEP_KEY}」がありません")
    skip = set() if share else {"売上原価", "売上総利益", "販売費及び一般管理費"}
    if new_dep is None:
        skip.add("本補助金で導入する設備の減価償却費")
    rows = [(k, label) for k, label in BEPPYO_ROWS if k not in skip]
    if share:
        rows += [(CHECK_COST, CHECK_COST), (CHECK_PROFIT, CHECK_PROFIT)]

    pl.put(f"A{row}", "【様式（別紙4）に写す数字（円に丸めた値。伸びは、この値から様式と同じ計算で出したもの）】", bold=True)
    row += 1
    if tl is not None:
        pl.put(f"A{row}", "決算期")
        for y, col in enumerate(year_cols):
            pl.put(f"{col}{row}", tl.label(tl.base + y))
        row += 1
    r: Dict[str, int] = {}
    for key, label in rows:
        r[key] = row
        pl.put(f"A{row}", label)
        row += 1
    vals: Dict[str, List[Any]] = {key: [None] * (n + 1) for key, _label in rows}
    values = spec.values()

    def total(key: str, col: str) -> str:
        return f"{col}{at[('合算', key)]}"

    def here(key: str, col: str) -> str:
        return f"{col}{r[key]}"

    def put(key: str, col: str, y: int, formula: str, value: Any, fmt: str) -> Any:
        vals[key][y] = value
        pl.formula(here(key, col), formula, value, fmt)
        return value

    for y, col in enumerate(year_cols):
        t = {k: py[("合算", k)][y] for k in ROW_KEYS + ("人件費", "営業利益")}
        sales = put("売上高", col, y, f"=ROUND({total('売上', col)},0)", _yen(t["売上"]), FMT_YEN)
        dep = t["減価償却費"]
        new_raw, new_f = None, ""
        if new_dep is not None and y >= 1:
            new_raw = new_dep.formula.value(_lookup_values(values, {YEAR: float(y)}))
            if new_raw < 0 or new_raw > dep + 1e-6 * max(1.0, abs(dep)):
                raise SpecError(f"{NEW_DEP_KEY}（{y}年目 {new_raw:,.0f}円）が、0より小さいか、合算の減価償却費（{dep:,.0f}円）"
                                "より大きいです")
            new_f = new_dep.formula.excel(lambda name, col=col: ycell(col) if name == YEAR else name)[1:]
        if share:
            # 区分ごとの（Excel の項, Python の値）。本補助金の設備の分に別の割合があれば、減価償却費を既存と本補助金に分けて掛ける
            terms = []
            for k in COST_KEYS:
                if k not in share:
                    continue
                if k == "減価償却費" and new_raw is not None and NEW_DEP_KEY in share:
                    terms.append((f"({total(k, col)}-{new_f})", t[k] - new_raw, COST_SHARE_PREFIX + k, share[k].value))
                    terms.append((new_f, new_raw, COST_SHARE_PREFIX + NEW_DEP_KEY, share[NEW_DEP_KEY].value))
                else:
                    terms.append((total(k, col), t[k], COST_SHARE_PREFIX + k, share[k].value))
            cost_raw, sga_raw = 0.0, 0.0
            for _f, amount, _name, s in terms:
                cost_raw += amount * s
            for _f, amount, _name, s in terms:
                sga_raw += amount * (1 - s)
            cost_f = "+".join(f"{f}*{name}" for f, _a, name, _s in terms)
            sga_f = "+".join(f"{f}*(1-{name})" for f, _a, name, _s in terms)
            cost = put("売上原価", col, y, f"=ROUND({cost_f},0)", _yen(cost_raw), FMT_YEN)
            gross = put("売上総利益", col, y, f"={here('売上高', col)}-{here('売上原価', col)}", sales - cost, FMT_YEN)
            sga = put("販売費及び一般管理費", col, y, f"=ROUND({sga_f},0)", _yen(sga_raw), FMT_YEN)
            put("営業利益", col, y, f"={here('売上総利益', col)}-{here('販売費及び一般管理費', col)}", gross - sga, FMT_YEN)
            put(CHECK_COST, col, y, f"=({cost_f})+({sga_f})", cost_raw + sga_raw, FMT_YEN)
            put(CHECK_PROFIT, col, y, f"={total('売上', col)}-{total('営業利益', col)}", t["売上"] - t["営業利益"], FMT_YEN)
        else:
            put("営業利益", col, y, f"=ROUND({total('営業利益', col)},0)", _yen(t["営業利益"]), FMT_YEN)
        put("人件費", col, y, f"=ROUND({total('人件費', col)},0)", _yen(t["人件費"]), FMT_YEN)
        if new_raw is not None:
            new = put("本補助金で導入する設備の減価償却費", col, y, f"=ROUND({new_f},0)", _yen(new_raw), FMT_YEN)
            old = put("既存設備の減価償却費", col, y, f"=ROUND({total('減価償却費', col)}-{new_f},0)", _yen(dep - new_raw), FMT_YEN)
            put("減価償却費", col, y, f"={here('既存設備の減価償却費', col)}+{here('本補助金で導入する設備の減価償却費', col)}",
                old + new, FMT_YEN)
        else:
            old = put("既存設備の減価償却費", col, y, f"=ROUND({total('減価償却費', col)},0)", _yen(dep), FMT_YEN)
            put("減価償却費", col, y, f"={here('既存設備の減価償却費', col)}", old, FMT_YEN)
        va = vals["営業利益"][y] + vals["人件費"][y] + vals["減価償却費"][y]
        put("付加価値額", col, y, f"={here('営業利益', col)}+{here('人件費', col)}+{here('減価償却費', col)}", va, FMT_YEN)
        officers = put("役員数", col, y, f"={col}{people_at['役員数']}", people["役員数"][y], FMT_PEOPLE)
        regular = put("常勤従業員数", col, y, f"={col}{people_at['常勤従業員数']}", people["常勤従業員数"][y], FMT_PEOPLE)
        v, o, e = here("付加価値額", col), here("役員数", col), here("常勤従業員数", col)
        put("労働生産性", col, y, f"=IF({v}<0,ROUNDUP(({v}/({o}+{e})),2),ROUNDDOWN(({v}/({o}+{e})),2))",
            youken.productivity(va, officers + regular), FMT_PER)
        pay = put("給与支給総額", col, y, f"=ROUND({total('給与支給総額', col)},0)", _yen(t["給与支給総額"]), FMT_YEN)
        emp = put("給与を受けた従業員数", col, y, f"={col}{people_at['給与を受けた従業員数']}", people["給与を受けた従業員数"][y],
                  FMT_PEOPLE)
        put("1人当たり給与支給総額", col, y, f"=ROUNDDOWN({here('給与支給総額', col)}/{here('給与を受けた従業員数', col)},2)",
            youken.pay_per_person(pay, emp), FMT_PER)
    for y, col in enumerate(year_cols):
        if y == 0:
            continue
        for key, level in (("付加価値額の伸び", "付加価値額"), ("労働生産性の伸び", "労働生産性")):
            g = youken.growth_plain(vals[level][y], vals[level][0], y)
            lr = r[level]
            put(key, col, y, f'=IFERROR(ROUNDDOWN((({col}{lr}/$B${lr})^(1/{ycell(col)})-1)*100,2),"{youken.CANNOT_CALC}")',
                youken.CANNOT_CALC if g is None else g, FMT_GROWTH)
        pr = r["1人当たり給与支給総額"]
        inner = f"(({col}{pr}/$B${pr})^(1/{ycell(col)})-1)*100"
        put("1人当たり給与支給総額の伸び", col, y, f"=IFERROR(IF({col}{pr}>=$B${pr},ROUNDDOWN({inner},2),ROUNDUP({inner},2)),0)",
            youken.growth_pay(vals["1人当たり給与支給総額"][y], vals["1人当たり給与支給総額"][0], y), FMT_GROWTH)

    # 様式に円で写した値の伸びと、財務モデルの伸び（判定に使った値）を比べる
    diffs = [{"指標": key, "年": y, "財務モデル": ind[model_key][y], "様式に写した値": vals[key][y]}
             for _i, key, model_key in _GROWTH_PAIRS for y in range(1, n + 1) if vals[key][y] != ind[model_key][y]]
    changed = []
    for req in requirements:
        if not req.judged:
            continue
        key, model_key = next((k, m) for i, k, m in _GROWTH_PAIRS if i == req.indicator)
        for y in req.years(n):
            form_v, model_v = youken.judge(vals[key][y], req.threshold), youken.judge(ind[model_key][y], req.threshold)
            if form_v != model_v:
                changed.append(f"「{req.name}」の{y}年目")
                notes.append(f"様式（別紙4）に円で写した数字で計算すると、「{req.name}」の{y}年目は {vals[key][y]}（財務モデルは "
                             f"{ind[model_key][y]}）で、判定が「{model_v}」から「{form_v}」に変わります。様式の値で審査されるので、"
                             "計画の数字を見直してください")
    if diffs and not changed:
        notes.append("様式（別紙4）に円で写した数字で計算すると、伸びが財務モデルと少し違う年があります（判定は変わりません）：" + "、".join(
            f"{d['指標']} {d['年']}年目 {d['財務モデル']} → {d['様式に写した値']}" for d in diffs))

    check = None
    if share:
        gaps = [abs(a - b) for a, b in zip(vals[CHECK_COST], vals[CHECK_PROFIT])]
        check = {"売上原価＋販管費": vals.pop(CHECK_COST), "売上−営業利益": vals.pop(CHECK_PROFIT), "差の最大": max(gaps),
                 "合う": max(gaps) < 1}
    ashimoto = None
    if tl is not None:
        ashimoto, row = _ashimoto_rows(pl, spec, vals, r, year_cols[0], row + 1, notes)
    return {
        "列": [tl.label(tl.base + y) if tl else ("基準年度" if y == 0 else f"{y}年目") for y in range(n + 1)],
        "年ごと": vals,
        "照らし": check,
        "足下の賃上げ": ashimoto,
        "様式の値と財務モデルの伸びの違い": diffs,
        "知らせ": notes,
        "_次の行": row + 1,
    }


def _ashimoto_rows(pl: Sheet, spec: Spec, vals: Dict[str, List[Any]], r: Dict[str, int], base_col: str, row: int,
                   notes: List[str]) -> Tuple[Optional[Dict[str, Any]], int]:
    """足下の賃上げ（別紙4 の、直近期・締切期・基準年度の⑦⑧と、1人当たり給与支給総額の年平均成長率）。"""
    tl = spec.timeline
    pay_item, emp_item = spec.recent.get("給与支給総額"), spec.recent.get("給与を受けた従業員数")
    if pay_item is None or emp_item is None:
        notes.append(f"{RECENT_KEY}に給与支給総額と給与を受けた従業員数がないので、足下の賃上げは出していません")
        return None, row
    pl.put(f"A{row}", "【足下の賃上げ（別紙4 の、直近期から基準年度まで。直近期は決算書の実績。要件ではなく審査で見る値）】",
           bold=True)
    row += 1
    pl.put(f"A{row}", "決算期")
    labels = [tl.label(tl.recent), tl.label(tl.closing), tl.label(tl.base)]
    for col, label in zip("BCD", labels):
        pl.put(f"{col}{row}", label)
    pr, er, ppr, gr = row + 1, row + 2, row + 3, row + 4
    for at_row, label in ((pr, "⑦ 全月分の給与等の支給を受けた従業員の給与支給総額"), (er, "⑧ 全月分の給与等の支給を受けた従業員数（人）"),
                          (ppr, "1人当たり給与支給総額（⑦÷⑧）"), (gr, f"1人当たり給与支給総額の年平均成長率（％。直近期から基準年度まで、{ELAPSED}で）")):
        pl.put(f"A{at_row}", label)
    out: Dict[str, Any] = {"列": labels, "給与支給総額": [None] * 3, "給与を受けた従業員数": [None] * 3,
                           "1人当たり給与支給総額": [None] * 3, "経過年数": tl.elapsed, "伸び": None}

    def put(key: str, at_row: int, i: int, formula: str, value: Any, fmt: str) -> None:
        out[key][i] = value
        pl.formula(f"{'BCD'[i]}{at_row}", formula, value, fmt)

    put("給与支給総額", pr, 0, f"=ROUND({pay_item.name},0)", _yen(pay_item.value), FMT_YEN)
    put("給与を受けた従業員数", er, 0, f"={emp_item.name}", emp_item.value, FMT_PEOPLE)
    put("給与支給総額", pr, 2, f"={base_col}{r['給与支給総額']}", vals["給与支給総額"][0], FMT_YEN)
    put("給与を受けた従業員数", er, 2, f"={base_col}{r['給与を受けた従業員数']}", vals["給与を受けた従業員数"][0], FMT_PEOPLE)
    lookup = _bridge_lookup(spec.assumptions, spec.recent, 1)
    for key, at_row, fmt, rounding in (("給与支給総額", pr, FMT_YEN, True), ("給与を受けた従業員数", er, FMT_PEOPLE, False)):
        item = spec.base[key]
        if tl.elapsed == 1:  # 締切期と基準年度が同じ期
            put(key, at_row, 1, f"=D{at_row}", out[key][2], fmt)
        elif item.formula is not None:  # 基準年度の式の経過年数を1にしたもの
            excel = item.formula.excel(lambda name: "1" if name == ELAPSED else name)[1:]
            value = item.formula.value(lookup)
            put(key, at_row, 1, f"=ROUND({excel},0)" if rounding else f"={excel}", _yen(value) if rounding else value, fmt)
    if out["給与支給総額"][1] is None or out["給与を受けた従業員数"][1] is None:
        notes.append("締切期の⑦⑧は、基準年度の給与支給総額と給与を受けた従業員数を、直近期の実績からの式（{\"式\": …}）にすると"
                     "道具が出します（今は空けています）")
    for i in range(3):
        if out["給与支給総額"][i] is not None and out["給与を受けた従業員数"][i] is not None:
            col = "BCD"[i]
            put("1人当たり給与支給総額", ppr, i, f"=ROUNDDOWN({col}{pr}/{col}{er},2)",
                youken.pay_per_person(out["給与支給総額"][i], out["給与を受けた従業員数"][i]), FMT_PER)
    recent_pp, base_pp = out["1人当たり給与支給総額"][0], out["1人当たり給与支給総額"][2]
    growth = youken.growth_pay(base_pp, recent_pp, tl.elapsed)
    inner = f"((D{ppr}/B{ppr})^(1/{ELAPSED})-1)*100"
    pl.formula(f"D{gr}", f"=IFERROR(IF(D{ppr}>=B{ppr},ROUNDDOWN({inner},2),ROUNDUP({inner},2)),0)", growth, FMT_GROWTH)
    out["伸び"] = growth
    return out, gr + 1


def _timeline_summary(spec: Spec) -> Optional[Dict[str, Any]]:
    tl = spec.timeline
    if tl is None:
        return None
    return {
        "決算月": tl.month, "直近期": tl.label(tl.recent_actual), "様式の直近期": tl.label(tl.recent),
        "応募の締切": f"{tl.deadline[0]}-{tl.deadline[1]:02d}" if tl.deadline else None, "応募の締切の出典": tl.deadline_source,
        "締切期": tl.label(tl.closing), "補助事業の完了予定": f"{tl.completion[0]}-{tl.completion[1]:02d}",
        "基準年度": tl.label(tl.base), "経過年数": tl.elapsed,
        "計画の年": [tl.label(tl.base + y) for y in range(1, spec.years + 1)],
        "根拠": tl.basis, "出典": tl.source, "知らせ": tl.notes,
    }


def _other_items(spec: Spec) -> List[Item]:
    """直近期の実績・売上原価の割合・本補助金の設備の減価償却費（根拠と出典を確かめる値）。"""
    return list(spec.recent.values()) + list(spec.cost_share.values()) + ([spec.new_dep] if spec.new_dep else [])


def _shoryoku_rows(pl: Sheet, sh: Shoryoku, steps_at: Dict[Tuple[str, int], str], row: int, years: int,
                   va: List[Any], va_r: int, first: str, last: str, year_ref: str, note_col: str) -> Dict[str, Any]:
    """計画のシートに、省力化の指標（別紙1・別紙3 と同じ計算）を数式で書く。Python の値も返す。"""
    pairs = shoryoku_pairs(sh)
    cut, after = shoryoku_hours(sh)
    index = shoryoku_index(cut, after)
    saved = cut - after
    added = (va[years] - va[0]) / years
    items = {k: v.value for k, v in sh.items.items()}
    payback = payback_years(items["投資総額"], saved, items["年間稼働日数"], items["人件費単価"], added)

    def ref(side: str, no: int) -> str:
        return steps_at[(side, no)]

    before_sum = "+".join(ref("前", s.no) for s in sh.before)
    after_sum = "+".join(ref("後", s.no) for s in sh.after)
    paired_b = "+".join(ref("前", b.no) for b, _a in pairs) or "0"
    paired_a = "+".join(ref("後", a.no) for _b, a in pairs) or "0"
    neg = "+".join(f"MIN(0,{ref('後', a.no)}-{ref('前', b.no)})" for b, a in pairs) or "0"
    pos = "+".join(f"MAX(0,{ref('後', a.no)}-{ref('前', b.no)})" for b, a in pairs) or "0"

    col = "B"
    pl.put(f"A{row}", "【省力化の指標（様式その3 の別紙1・別紙3 と同じ計算）】", bold=True)
    row += 1
    at = {}
    lines = (
        ("削減", "設備導入により削減される業務に要していた時間（時間/日）",
         f"=(({before_sum})-({paired_b})-({neg}))/60", cut, FMT_PER, "別紙1 の D3。内容が変わらない作業は、減った分だけを数える"),
        ("導入後", "設備導入後に発生する業務に要する時間（時間/日）",
         f"=(({after_sum})-({paired_a})+({pos}))/60", after, FMT_PER, "別紙1 の J3。内容が変わらない作業は、増えた分だけを数える"),
        ("省力化指数", "省力化指数", None, index, FMT_PER, "別紙1 の M3。（削減される時間−導入後に発生する時間）÷削減される時間"),
        ("削減工数", "削減工数（時間/日）", None, saved, FMT_PER, "別紙3 の削減工数。削減される時間−導入後に発生する時間"),
        ("増加した付加価値額", "増加した付加価値額（円/年）", None, added, FMT_YEN,
         f"応募手引8 p.59 の例の形：（{years}年目の付加価値額−基準年度の付加価値額）÷{years}"),
        ("投資回収期間", "投資回収期間（年）", None, payback, FMT_PER,
         "別紙3 の C3。投資総額÷（削減工数×年間稼働日数×人件費単価＋増加した付加価値額）"),
    )
    for key, _label, _f, _v, _fmt, _note in lines:
        at[key] = row
        row += 1
    for key, label, formula, value, fmt, note in lines:
        r = at[key]
        pl.put(f"A{r}", label)
        pl.put(f"{note_col}{r}", note)
        if key == "省力化指数":
            d, j = f"{col}{at['削減']}", f"{col}{at['導入後']}"
            formula = f"=IF({d}=0,0,IF(({d}-{j})/{d}<0,0,({d}-{j})/{d}))"
        elif key == "削減工数":
            formula = f"={col}{at['削減']}-{col}{at['導入後']}"
        elif key == "増加した付加価値額":
            formula = f"=({last}{va_r}-$B${va_r})/{year_ref}"
        elif key == "投資回収期間":
            denom = f"({col}{at['削減工数']}*年間稼働日数*人件費単価+{col}{at['増加した付加価値額']})"
            formula = f'=IFERROR(IF(投資総額/{denom}<=0,"",投資総額/{denom}),"")'
        pl.formula(f"{col}{r}", formula, "" if value is None else value, fmt)
    return {
        "削減される業務に要していた時間": cut,
        "導入後に発生する業務に要する時間": after,
        "省力化指数": index,
        "削減工数": saved,
        "年間稼働日数": items["年間稼働日数"],
        "人件費単価": items["人件費単価"],
        "投資総額": items["投資総額"],
        "増加した付加価値額": added,
        "投資回収期間": payback,
        "表示": {
            "省力化指数": youken.round_half_up(index, 2),
            "削減工数": youken.round_half_up(saved, 2),
            "投資回収期間": None if payback is None else youken.round_half_up(payback, 2),
        },
        "組になった作業": [{"導入前": b.no, "導入後": a.no} for b, a in pairs],
        "根拠か出典のない数": [k for k, v in sh.items.items() if v.unsupported],
        "仮の数": [k for k, v in sh.items.items() if v.provisional],
        "_次の行": row + 1,
    }


def _derived_rows(pl: Sheet, py: Dict[Tuple[str, str], List[float]], at: Dict[Tuple[str, str], int], group: str,
                  y: int, col: str) -> None:
    """人件費と営業利益（道具が計算する行）。"""
    n1 = len(py[(group, "売上")])
    pay, other = py[(group, "給与支給総額")][y], py[(group, "その他の人件費")][y]
    labor = pay + other
    py.setdefault((group, "人件費"), [0.0] * n1)[y] = labor
    r = {k: f"{col}{at[(group, k)]}" for k in ("売上", "原材料費", "人件費", "給与支給総額", "その他の人件費", "減価償却費",
                                                "その他の経費", "営業利益")}
    pl.formula(r["人件費"], f"={r['給与支給総額']}+{r['その他の人件費']}", labor, FMT_YEN)
    op = (py[(group, "売上")][y] - py[(group, "原材料費")][y] - labor - py[(group, "減価償却費")][y]
          - py[(group, "その他の経費")][y])
    py.setdefault((group, "営業利益"), [0.0] * n1)[y] = op
    pl.formula(r["営業利益"], f"={r['売上']}-{r['原材料費']}-{r['人件費']}-{r['減価償却費']}-{r['その他の経費']}", op, FMT_YEN)


# ---------------------------------------------------------------- 数字の控え（計画書との照合に使う。TASKS B13・B16）

NUMBERS_FILE = "記録/財務モデルの数字.json"


def numbers_record(spec: Spec, book: Book, seido_rel: Optional[str], when: str) -> Dict[str, Any]:
    """計画書・様式・入力シートと照らすための、財務モデルの数字の控え（前提の番号・値と、計画の数字）。"""
    assumptions = []
    groups = [("P", spec.assumptions), ("J", list(spec.base.values()))]
    if spec.shoryoku is not None:
        groups.append(("S", list(spec.shoryoku.items.values())))
    groups += [(prefix, items) for prefix, items in (("R", list(spec.recent.values())), ("G", list(spec.cost_share.values())))
               if items]
    for prefix, items in groups:
        for n, item in enumerate(items, start=1):
            assumptions.append({"番号": f"{prefix}-{n:02d}", "名前": item.name, "値": item.value, "単位": item.unit,
                                "根拠": item.basis, "出典": item.source, "仮": item.provisional})
            if item.formula is not None:
                assumptions[-1]["式"] = item.formula.text
    steps = []
    if spec.shoryoku is not None:
        for side, items in (("導入前", spec.shoryoku.before), ("導入後", spec.shoryoku.after)):
            steps += [{"側": side, "No": s.no, "工程": s.name, "分": s.minutes, "種別": s.kind,
                       "対応する導入前": s.before_no} for s in items]
    return {"説明": "財務モデル.xlsx を作ったときの数字の控え（zaimu_model.py が書く。書き換えない）",
            "作った日時": when, "制度データ": seido_rel, "前提": assumptions, "中身": book.summary,
            "省力化の作業": steps}


# ---------------------------------------------------------------- 計算し直した値と比べる


def same(py_value: Any, other: Any) -> bool:
    """Python の値と、表計算ソフトで計算し直した値が同じか。数は 1e-9 の相対の差（小さい数は 1e-6）まで同じとみる。"""
    if isinstance(py_value, str) or isinstance(other, str):
        a = "" if py_value is None else py_value
        b = "" if other is None else other
        return a == b
    if py_value is None or other is None or isinstance(other, bool):
        return False
    try:
        a, b = float(py_value), float(other)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= max(1e-6, 1e-9 * abs(a))


def compare(expected: Dict[Tuple[str, str], Any], got: Dict[Tuple[str, str], Any]) -> List[str]:
    """数式のセルごとに比べ、食い違ったものを返す。"""
    wrong = []
    for (sheet, ref), value in sorted(expected.items()):
        other = got.get((sheet, ref))
        if not same(value, other):
            wrong.append(f"{sheet}!{ref}：Python {value!r} ／ 計算し直し {other!r}")
    return wrong


def decimal_text(value: Optional[Decimal]) -> str:
    return "" if value is None else format(value, "f")
