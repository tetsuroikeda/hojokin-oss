"""制度データを、正解（testdata/正解/）と突き合わせる（SPEC T3-7 の突き合わせ。DESIGN 11章・14章「制度データの確かめ方」。TASKS B25）。

開発のテストだけが使う（製品の lib/ は正解を読まない）。照らす範囲は DESIGN 14章のとおり：
必須書類、締切、要件（数値の要件と数値でない要件）、審査項目、加点、様式の項目と文字数、補助額、審査の段階、
手続きの段階（期限の決め方）、採択後の書類、補助の対象にならない経費（上限と品目）。あわせて、
- すべての値に出典ページ（HTML のページなど、ページのない資料は資料名だけでよい）
- 読み取れない項目は、値を推測で埋めずに空けたまま：正解で「読み取れない」の場所ごとに、作った方の同じ場所（配列の件は名前で対にする）が
  「読み取れない」で値が空かを、一致率の点（読み取れない項目）に数える。正解の「読み取れなかった項目」の項目が、作った方の一覧にあるかも点に数える。
  作った方の「読み取れない」に値が入っていないかも見る（filled_unreadable）
- 正解に含めた資料どうしの食い違いが、すべて示されている

照らし方：
- 件は、名前で対にする（NFKC、空白・括弧の中を除いた形が同じか、一方が他方で始まるか、2字ずつの組の6割以上が重なる）。
- 値は、中の数（万・億は円に直す。日付・時刻・割合の数字も数）が同じか（lib/seido_data.numbers_in）。言い回しの違いは見ない。
  補助の対象にならない経費は、1件が資料の箇条書きのいちばん細かい1項目（品目）なので（DESIGN 9章）、件が対になるかで品目を照らす。
- 一致率は、正解の照らす点のうち、合った点の割合。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lib import seido_data

_BRACKETS = re.compile(r"[（(【［\[][^）)】］\]]*[）)】］\]]")
_SPACES = re.compile(r"\s+")


def core(text: Any) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = _BRACKETS.sub("", t)
    return _SPACES.sub("", t)


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else ({s} if s else set())


def same_name(a: Any, b: Any) -> bool:
    x, y = core(a), core(b)
    if not x or not y:
        return unicodedata.normalize("NFKC", str(a)) == unicodedata.normalize("NFKC", str(b))
    if x == y or x.startswith(y) or y.startswith(x):
        return True
    bx, by = _bigrams(x), _bigrams(y)
    return bool(bx and by) and len(bx & by) / min(len(bx), len(by)) >= 0.6


def _value(node: Any) -> Any:
    return node.get("値") if isinstance(node, dict) and "状態" in node else node


def same_value(a: Any, b: Any) -> bool:
    return seido_data.numbers_in(_value(a)) == seido_data.numbers_in(_value(b))


def words_found(answer_text: str, text: str) -> bool:
    x, y = _bigrams(core(answer_text)), _bigrams(core(text))
    return bool(x) and len(x & y) / len(x) >= 0.5


@dataclass
class Point:
    category: str
    where: str
    ok: bool
    why: str = ""


@dataclass
class Report:
    points: List[Point] = field(default_factory=list)
    unsourced: List[str] = field(default_factory=list)
    filled_unreadable: List[str] = field(default_factory=list)
    missing_conflicts: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return sum(p.ok for p in self.points) / len(self.points) if self.points else 0.0

    def misses(self) -> List[Point]:
        return [p for p in self.points if not p.ok]

    def by_category(self) -> Dict[str, Tuple[int, int]]:
        out: Dict[str, Tuple[int, int]] = {}
        for p in self.points:
            ok, n = out.get(p.category, (0, 0))
            out[p.category] = (ok + int(p.ok), n + 1)
        return out


def _plain(text: Any) -> str:
    return _SPACES.sub("", unicodedata.normalize("NFKC", str(text or "")))


def _find(items: Iterable[Dict], name: Any, key: str = "名前") -> Optional[Dict]:
    """いちばん近い名前の件。同じ（空白を除く）＞括弧の中を除いて同じ＞一方が他方で始まる・よく似ている、の順に探す。"""
    items = [it for it in items if isinstance(it, dict)]
    for test in (lambda a, b: _plain(a) == _plain(b),
                 lambda a, b: bool(core(a)) and core(a) == core(b),
                 same_name):
        for it in items:
            if test(it.get(key), name):
                return it
    return None


def _list(data: Dict, key: str) -> List[Dict]:
    v = data.get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


ABSENT_ITEM = object()    # 対になる件がない
MISSING_FIELD = object()  # 件はあるが、その欄がない
_NAME_KEYS = ("名前", "区分", "項目", "id")


def unreadable_places(answer: Dict) -> List[Tuple[List[Any], Dict]]:
    """正解で「読み取れない」の出典つき値の、データの中の道と値（資料・資料どうしの食い違い・読み取れなかった項目は除く）。"""
    out: List[Tuple[List[Any], Dict]] = []

    def visit(node: Any, path: List[Any]) -> None:
        if isinstance(node, dict) and "値" in node and "状態" in node:
            if node["状態"] == "読み取れない":
                out.append((path, node))
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い", "読み取れなかった項目"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(answer, [])
    return out


def resolve(got: Dict, answer: Dict, path: List[Any]) -> Any:
    """正解の道を、作った方のデータでたどる。配列の件は名前（名前・区分・項目・id）で対にする（名前がなければ同じ順番）。"""
    node_a: Any = answer
    node_g: Any = got
    for part in path:
        if isinstance(part, int):
            item_a = node_a[part]
            if not isinstance(node_g, list):
                return MISSING_FIELD
            key = next((k for k in _NAME_KEYS if isinstance(item_a, dict) and item_a.get(k)), None)
            if key:
                cand = _find(node_g, item_a[key], key)
            else:
                cand = node_g[part] if part < len(node_g) else None
            if cand is None:
                return ABSENT_ITEM
            node_a, node_g = item_a, cand
        else:
            node_a = node_a[part]
            if not isinstance(node_g, dict) or part not in node_g:
                return MISSING_FIELD
            node_g = node_g[part]
    return node_g


def urakadori_label(path: List[Any], data: Dict) -> str:
    from lib import urakadori

    return urakadori.readable(path, data)


def _first_stage_id(data: Dict) -> Optional[str]:
    stages = _list(data, "手続きの段階")
    if not stages:
        return None
    return min(stages, key=lambda s: s.get("順番") if isinstance(s.get("順番"), int) else 10 ** 6).get("id")


def compare(got: Dict, answer: Dict) -> Report:
    rep = Report()

    def point(cat: str, where: str, ok: bool, why: str = "") -> None:
        rep.points.append(Point(cat, where, ok, why))

    def named(cat: str, key: str, fields: Tuple[str, ...] = (), name_key: str = "名前",
              pick=lambda x: True) -> None:
        mine = [x for x in _list(got, key) if pick(x)]
        for item in [x for x in _list(answer, key) if pick(x)]:
            name = item.get(name_key)
            other = _find(mine, name, name_key)
            point(cat, f"{key}「{name}」", other is not None, "" if other else "件がない")
            for f in fields:
                if f in item and _value(item[f]) is not None:
                    ok = other is not None and f in other and same_value(item[f], other[f])
                    point(cat, f"{key}「{name}」の{f}", ok, "" if ok else f"正解 {_value(item[f])!r}、作った {_value((other or {}).get(f))!r}")

    first_id = _first_stage_id(answer)
    named("必須書類", "書類", pick=lambda d: d.get("区分") == "必須")
    named("締切", "決まった期日", ("日時",), pick=lambda d: "締切" in str(d.get("名前", "")))
    named("要件", "数値の要件", ("基準",))
    named("要件", "数値でない要件")
    named("審査項目", "審査項目")
    named("審査の段階", "審査の段階")
    named("採択後の書類", "書類", pick=lambda d: first_id not in (d.get("手続き") or []))

    # 加点：項目の名前と、種類の数
    bonus_a = answer.get("加点") if isinstance(answer.get("加点"), dict) else {}
    bonus_g = got.get("加点") if isinstance(got.get("加点"), dict) else {}
    for item in _list(bonus_a, "項目"):
        point("加点", f"加点「{item.get('名前')}」", _find(_list(bonus_g, "項目"), item.get("名前")) is not None)
    if _value(bonus_a.get("種類の数")) is not None:
        point("加点", "加点の種類の数", same_value(bonus_a.get("種類の数"), bonus_g.get("種類の数")))

    # 様式：様式の名前、項目の名前と分量の上限
    for form in _list(answer, "様式"):
        other = _find(_list(got, "様式"), form.get("名前"))
        point("様式", f"様式「{form.get('名前')}」", other is not None)
        for it in _list(form, "項目"):
            o = _find(_list(other or {}, "項目"), it.get("名前"))
            point("様式", f"様式「{form.get('名前')}」の項目「{it.get('名前')}」", o is not None)
            if "分量の上限" in it and _value(it["分量の上限"]) is not None:
                point("様式", f"様式「{form.get('名前')}」の項目「{it.get('名前')}」の分量の上限",
                      o is not None and same_value(it["分量の上限"], o.get("分量の上限")))

    # 補助額：区分ごとの上限・補助率、特例の名前と値
    for row in _list(answer, "補助額"):
        other = _find(_list(got, "補助額"), row.get("区分"), "区分")
        point("補助額", f"補助額「{row.get('区分')}」", other is not None)
        for f in ("上限", "補助率"):
            point("補助額", f"補助額「{row.get('区分')}」の{f}", other is not None and same_value(row.get(f), other.get(f)))
        for sp in _list(row, "特例"):
            o = _find(_list(other or {}, "特例"), sp.get("名前"))
            point("補助額", f"補助額「{row.get('区分')}」の特例「{sp.get('名前')}」",
                  o is not None and same_value(sp.get("値"), o.get("値")))

    # 手続きの段階：段階と、期限の決め方
    for st in _list(answer, "手続きの段階"):
        other = _find(_list(got, "手続きの段階"), st.get("名前"))
        point("手続きの段階", f"手続きの段階「{st.get('名前')}」", other is not None)
        if isinstance(st.get("期限"), dict) and _value(st["期限"]) is not None:
            point("手続きの段階", f"手続きの段階「{st.get('名前')}」の期限",
                  other is not None and same_value(st["期限"], other.get("期限")))

    # 補助の対象にならない経費：件、上限、品目
    mine_costs = _list(got, "補助の対象にならない経費")
    for c in _list(answer, "補助の対象にならない経費"):
        other = _find(mine_costs, c.get("名前"))
        point("補助の対象にならない経費", f"補助の対象にならない経費「{c.get('名前')}」", other is not None)
        if isinstance(c.get("上限"), dict) and _value(c["上限"]) is not None:
            point("補助の対象にならない経費", f"補助の対象にならない経費「{c.get('名前')}」の上限",
                  other is not None and same_value(c["上限"], other.get("上限")))

    # 読み取れない項目：正解で「読み取れない」の場所は、作った方でも「読み取れない」で値が空のまま（推測で埋めない）。
    # 件そのものがないときは、件の点（上）で外れに数えるので、ここでは数えない。欄がないときは外れ
    for path, _node in unreadable_places(answer):
        found = resolve(got, answer, path)
        if found is ABSENT_ITEM:
            continue
        where = urakadori_label(path, answer)
        if found is MISSING_FIELD:
            point("読み取れない項目", f"{where}（読み取れないのまま）", False, "欄がない")
            continue
        ok = (isinstance(found, dict) and found.get("状態") == "読み取れない"
              and found.get("値") in (None, "", [], {}))
        point("読み取れない項目", f"{where}（読み取れないのまま）", ok,
              "" if ok else f"作った方は {found.get('状態') if isinstance(found, dict) else '形が違う'}、値 {_value(found)!r}")
    # 読み取れなかった項目の一覧：正解の項目が、作った方の一覧にもある（理由と問い合わせ文の案を社長に示すため）
    for entry in _list(answer, "読み取れなかった項目"):
        name = entry.get("項目")
        other = _find(_list(got, "読み取れなかった項目"), name, "項目")
        point("読み取れない項目", f"読み取れなかった項目「{name}」", other is not None, "" if other else "一覧にない")

    # 資料どうしの食い違い：正解の項目がすべて示されている
    for conflict in _list(answer, "資料どうしの食い違い"):
        if _find(_list(got, "資料どうしの食い違い"), conflict.get("項目"), "項目") is None:
            rep.missing_conflicts.append(str(conflict.get("項目")))

    # 出典ページと、読み取れない値
    def visit(node: Any, path: List[Any]) -> None:
        if isinstance(node, dict) and "値" in node and "状態" in node:
            where = "／".join(str(p) for p in path)
            if node["状態"] == "読み取れない":
                if node.get("値") not in (None, "", [], {}):
                    rep.filled_unreadable.append(where)
            elif not node.get("出典"):
                rep.unsourced.append(where)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if path == [] and k in ("資料", "資料どうしの食い違い"):
                    continue
                visit(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, path + [i])

    visit(got, [])
    return rep


def summary(rep: Report) -> str:
    lines = [f"一致率 {rep.rate:.1%}（{sum(p.ok for p in rep.points)}/{len(rep.points)}）"]
    for cat, (ok, n) in rep.by_category().items():
        lines.append(f"- {cat}：{ok}/{n}")
    for p in rep.misses()[:40]:
        lines.append(f"  - 外れ：{p.where}（{p.why}）")
    if rep.missing_conflicts:
        lines.append("- 示されていない資料どうしの食い違い：" + "、".join(rep.missing_conflicts))
    if rep.unsourced:
        lines.append(f"- 出典のない値：{len(rep.unsourced)}")
    if rep.filled_unreadable:
        lines.append(f"- 読み取れないのに値が入っている：{len(rep.filled_unreadable)}")
    return "\n".join(lines)
