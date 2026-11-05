"""実績を財務モデルに入れて、計画と比べる（SPEC F12「実績報告と効果報告では、実績を財務モデルに入れて計画と比べる。
要件を満たせない見込みなら、返還の条件とあわせて知らせる」・T12-4、DESIGN 4.6・8.3。TASKS B31c）。

- 計画は、財務モデルの指定（`記録/財務モデルの指定.json`）から lib/zaimu.py で組み立て直したもの（財務モデル.xlsx と同じ計算）。
- 実績は、その年の決算などの数字（基準年度と同じ9つ：売上・原材料費・給与支給総額・その他の人件費・減価償却費・
  その他の経費・役員数・常勤従業員数・給与を受けた従業員数）。数か {"値", "根拠", "出典"}。
  人件費・営業利益・付加価値額・労働生産性・1人当たり給与支給総額と、それぞれの年平均成長率は、財務モデルと同じ式と丸め
  （様式の別紙4。lib/youken.py）で計算する。
- 行ごとに、計画・実績・差・差の割合（％。小数第1位で四捨五入）を出す。
- 数値の要件（制度データ。特例を除く）ごとに判定する。
  - 「毎年」の要件：その年の実績の伸びで、満たす・満たさない。
  - 「終了時点」の要件：途中の年は、その年までの伸びが基準（目標値を渡されたら目標値）に届いているか。届いていなければ、
    残りの年に毎年どれだけ伸ばせば届くかを示す。最後の年なら、満たす・満たさない。
  - 満たさない・届かない見込みの要件には、制度データの「満たせないとき」（返還の条件）を出典つきで添える。なければ、
    資料から読み取れないことを添える。
  - 満たせないときの文に「達成率」があり、補助金の交付額を渡されたら、今の伸びが最後まで続いたときの達成率
    （伸び ÷ 目標値。0〜1）と、返還額の目安（交付額 ×（1 − 達成率）。補助上限の引き上げがない場合。伸びが0以下なら全額）を出す（仮）。

標準のライブラリだけを使う（lib/zaimu.py・lib/youken.py も標準のライブラリだけ）。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal
from typing import Any, Dict, List, Optional

from lib import youken, zaimu

DERIVED = ("人件費", "営業利益")
ROWS = zaimu.ROW_KEYS + DERIVED
INDICATOR_KEYS = {youken.VALUE_ADDED: "付加価値額", youken.PRODUCTIVITY: "労働生産性", youken.PAY: "1人当たり給与"}
INDICATOR_NAMES = {"付加価値額": "付加価値額", "労働生産性": "労働生産性", "1人当たり給与": "1人当たり給与支給総額"}
SHORT = "届かない見込み"
ON_TRACK = "届く見込み"
NO_RULE = "満たせないときの定め（返還の条件）は、資料から読み取れません（制度データの数値の要件に「満たせないとき」がありません）"


class JissekiError(ValueError):
    """比べられない（実績の形が違う など）。"""


def _value(raw: Any, where: str) -> float:
    value = raw.get("値") if isinstance(raw, dict) else raw
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JissekiError(f"実績の「{where}」は数にしてください（{raw}）")
    return float(value)


def _pct(diff: float, plan: float) -> Optional[float]:
    if not plan:
        return None
    return youken.round_half_up(diff / plan * 100, 1)


def _rule_of(seido: dict, name: str) -> Optional[dict]:
    for item in seido.get("数値の要件") or [] if isinstance(seido, dict) else []:
        if isinstance(item, dict) and item.get("名前") == name:
            node = item.get("満たせないとき")
            return node if isinstance(node, dict) and node.get("値") else None
    return None


def _source_text(node: dict) -> str:
    return youken.sources_text(node.get("出典") or [])


def compare(spec: "zaimu.Spec", seido: dict, actual: dict, target: Optional[float] = None,
            grant: Optional[int] = None) -> Dict[str, Any]:
    """計画と実績の差と、数値の要件の判定（返還の条件つき）。"""
    if not isinstance(actual, dict) or not isinstance(actual.get("実績"), dict):
        raise JissekiError("実績は {\"年\": 1, \"実績\": {\"売上\": …, …}} の形にしてください")
    year = actual.get("年")
    requirements = youken.read_requirements(seido)
    book = zaimu.build(spec, requirements, scenario=False)
    s = book.summary
    n = s["計画の年数"]
    if not isinstance(year, int) or isinstance(year, bool) or not 1 <= year <= n:
        raise JissekiError(f"実績の「年」は、計画の年（1〜{n}）にしてください（{year}）")
    got = actual["実績"]
    missing = [k for k in zaimu.BASE_KEYS if k not in got]
    if missing:
        raise JissekiError(f"実績に、次の値がありません：{'、'.join(missing)}（基準年度と同じ9つが要ります）")
    act = {k: _value(got[k], k) for k in zaimu.BASE_KEYS}
    act["人件費"] = act["給与支給総額"] + act["その他の人件費"]
    act["営業利益"] = act["売上"] - act["原材料費"] - act["人件費"] - act["減価償却費"] - act["その他の経費"]

    rows = {}
    for key in ROWS:
        plan = float(s["合算"][key][year])
        diff = act[key] - plan
        rows[key] = {"計画": round(plan), "実績": round(act[key]), "差": round(diff), "差の割合（%）": _pct(diff, plan)}

    va = act["営業利益"] + act["人件費"] + act["減価償却費"]
    levels = {"付加価値額": va,
              "労働生産性": youken.productivity(va, act["役員数"] + act["常勤従業員数"]),
              "1人当たり給与": youken.pay_per_person(act["給与支給総額"], act["給与を受けた従業員数"])}
    ind = s["指標"]
    indicators = {}
    for key, level in levels.items():
        base = float(ind[key][0])
        grow = youken.growth_pay(level, base, year) if key == "1人当たり給与" else youken.growth_plain(level, base, year)
        indicators[INDICATOR_NAMES[key]] = {"基準年度": base, "計画": float(ind[key][year]), "実績": level,
                                            "計画の伸び（%）": ind[f"{key}の伸び"][year], "実績の伸び（%）": grow}

    judged = []
    for req in requirements:
        if not req.judged or req.optional:
            continue
        key = INDICATOR_KEYS[req.indicator]
        entry = indicators[INDICATOR_NAMES[key]]
        grow = entry["実績の伸び（%）"]
        goal = Decimal(str(target)) if target is not None and req.indicator == youken.PAY else req.threshold
        item = {"名前": req.name, "基準": f"{req.threshold_text()}（{req.when}）", "出典": req.source_text(),
                "実績の伸び（%）": grow, "計画の伸び（%）": entry["計画の伸び（%）"]}
        if goal != req.threshold:
            item["目標値（%）"] = float(goal)
        if req.when == youken.EVERY_YEAR or year == n:
            verdict = youken.judge(grow, goal)
            item["判定"] = f"{verdict}（{year}年目）"
            short = verdict == youken.FAILS
        else:
            ok = isinstance(grow, (int, float)) and Decimal(str(grow)) >= goal
            item["判定"] = f"{ON_TRACK if ok else SHORT}（判定は{req.when}の{n}年目。{year}年目までの伸びで見た）"
            short = not ok
            if not ok:
                ratio = entry["実績"] / entry["基準年度"] if entry["基準年度"] else None
                if ratio and ratio > 0:
                    need = ((1 + float(goal) / 100) ** n / ratio) ** (1 / (n - year)) - 1
                    item["届くのに要る伸び（残りの年、毎年。%）"] = youken.round_half_up(need * 100, 2)
        if short:
            rule = _rule_of(seido, req.name)
            if rule is None:
                item["返還の条件"] = NO_RULE
            else:
                item["返還の条件"] = rule["値"]
                item["返還の条件の出典"] = _source_text(rule)
                if "達成率" in unicodedata.normalize("NFKC", rule["値"]) and grant is not None and goal > 0:
                    rate = 0.0 if not isinstance(grow, (int, float)) or grow <= 0 else min(1.0, float(grow) / float(goal))
                    item["返還額の目安"] = {"達成率": youken.round_half_up(rate, 2), "補助金の交付額": grant,
                                       "返還額": round(grant * (1 - youken.round_half_up(rate, 2))),
                                       "注": "今の伸びが最後の年まで続いたときの見込み。補助上限の引き上げがない場合（仮）"}
        judged.append(item)
    return {"年": year, "計画の年数": n, "行ごとの差（円）": rows, "指標": indicators, "要件": judged,
            "満たさない・届かない要件": [j["名前"] for j in judged if "返還の条件" in j]}


def report(result: Dict[str, Any]) -> str:
    year = result["年"]
    lines = [f"財務モデルの計画（{year}年目）と、実績を比べました。数字は道具が計算した値です（頭で計算し直さない）。", "",
             f"## {year}年目の計画と実績（円）", "", "| 行 | 計画 | 実績 | 差 | 差の割合 |", "|---|---|---|---|---|"]
    for key, r in result["行ごとの差（円）"].items():
        pct = "—" if r["差の割合（%）"] is None else f"{r['差の割合（%）']:+.1f}%"
        lines.append(f"| {key} | {r['計画']:,} | {r['実績']:,} | {r['差']:+,} | {pct} |")
    lines += ["", "## 指標", "", "| 指標 | 基準年度 | 計画 | 実績 | 計画の伸び | 実績の伸び |", "|---|---|---|---|---|---|"]
    for key, r in result["指標"].items():
        lines.append(f"| {key} | {r['基準年度']:,.2f} | {r['計画']:,.2f} | {r['実績']:,.2f} | {r['計画の伸び（%）']}% | "
                     f"{r['実績の伸び（%）']}% |")
    lines += ["", "## 数値の要件", ""]
    for j in result["要件"]:
        text = f"- {j['名前']}（{j['基準']}。{j['出典']}）：実績の伸び {j['実績の伸び（%）']}% → **{j['判定']}**"
        if "目標値（%）" in j:
            text += f"。目標値 {j['目標値（%）']}%"
        if "届くのに要る伸び（残りの年、毎年。%）" in j:
            text += f"。届くには、残りの年に毎年 {j['届くのに要る伸び（残りの年、毎年。%）']}% 伸ばす必要があります"
        lines.append(text)
        if "返還の条件" in j:
            where = f"（{j['返還の条件の出典']}）" if j.get("返還の条件の出典") else ""
            lines.append(f"  - 返還の条件：{j['返還の条件']}{where}")
        if "返還額の目安" in j:
            g = j["返還額の目安"]
            lines.append(f"  - 返還額の目安：達成率 {g['達成率']}、交付額 {g['補助金の交付額']:,}円 × (1 − {g['達成率']}) ＝ "
                         f"{g['返還額']:,}円（{g['注']}）")
    if result["満たさない・届かない要件"]:
        lines += ["", "満たさない・届かない見込みの要件があります。返還の条件とあわせて社長に伝え、残りの年の計画（賃上げなど）を相談してください。"]
    return "\n".join(lines) + "\n"


__all__ = ["JissekiError", "compare", "report"]
