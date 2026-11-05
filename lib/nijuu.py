"""二重受給の照合：同じ経費を、2つの案件（補助金）に計上していないか（SPEC F2・T2-2、DESIGN 6章）。

照らすもの：
- `記録/経費明細.json`（lib/keihi.py が書く。案件ごとの経費の行）
- まだ経費明細のない案件の、計上する予定の経費（Claude が社長の話や見積書から書いた行。`記録/一時/二重受給.json` などで渡す）

案件どうしで、行を2つずつ比べる（同じ案件の中は比べない）。
- 重大（同じ経費とみなす）：
  - 同じ見積書の原本の、同じ明細の番号を、2つの案件が使っている
  - 型番が同じ（空白・記号・全角半角の違いは除く）
  - 品名が同じで、金額も同じ
- 確かめが要る（同じ経費かもしれない）：
  - 品名が同じで、金額が違う
  - 品名の一方が他方を含む、または品名がよく似ている（2字ずつの組の6割以上が重なる）
重大は、同じ経費を2つの補助金に計上しているので、どちらか1つにしないと不採択・交付決定の取消・返還になりうる（制度データの
「してはいけないこと」に出典がある）。確かめが要るものは、社長に同じものかを聞く。

何も書かない（照らした結果を返すだけ）。会社のフォルダの中だけを読む（lib/places.py）。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import keihi, place_text, places

SERIOUS = "重大"
CHECK = "確かめが要る"
SIMILAR_RATIO = 0.6

_DROP = re.compile(r"[\s\-‐－―ー・/／.,，、。（）()「」\[\]【】]+")


class NijuuError(ValueError):
    """照らせなかった（形が違う、会社のフォルダの外を指す など）。"""


def norm(text: Any) -> str:
    """比べるための形：NFKC、小文字、空白と記号を除く。"""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _DROP.sub("", s)


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else ({s} if s else set())


def similar(a: str, b: str) -> bool:
    """品名がよく似ているか（片方がもう片方を含む、または2字ずつの組の6割以上が重なる）。"""
    if not a or not b:
        return False
    if len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
        return True
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return False
    return len(x & y) / min(len(x), len(y)) >= SIMILAR_RATIO


@dataclass
class Row:
    case: str
    name: str
    amount: Optional[int]
    model: str = ""
    original: str = ""
    numbers: Tuple[int, ...] = ()
    where: str = ""  # 「経費明細」か「予定」

    def label(self) -> str:
        parts = [self.name]
        if self.model:
            parts.append(f"型番 {self.model}")
        if isinstance(self.amount, int):
            parts.append(f"{self.amount:,}円")
        if self.original:
            nums = "・".join(str(n) for n in self.numbers)
            parts.append(f"見積書 {self.original}" + (f" の明細 {nums}" if nums else ""))
        return "、".join(parts)


@dataclass
class Finding:
    level: str
    reason: str
    a: Row
    b: Row


@dataclass
class Result:
    findings: List[Finding] = field(default_factory=list)
    cases: List[str] = field(default_factory=list)
    rows: int = 0

    @property
    def serious(self) -> List[Finding]:
        return [f for f in self.findings if f.level == SERIOUS]

    @property
    def to_check(self) -> List[Finding]:
        return [f for f in self.findings if f.level == CHECK]


def _amount(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    return None


def _numbers(value: Any) -> Tuple[int, ...]:
    items = value if isinstance(value, list) else [value]
    return tuple(n for n in items if isinstance(n, int) and not isinstance(n, bool))


def _row(case: str, item: Dict, where: str) -> Row:
    name = unicodedata.normalize("NFC", str(item.get("品名") or "")).strip()
    if not name:
        raise NijuuError(f"案件「{case}」の行に、品名のないものがあります")
    return Row(case=case, name=name, amount=_amount(item.get("金額")),
               model=unicodedata.normalize("NFC", str(item.get("型番") or "")).strip(),
               original=unicodedata.normalize("NFC", str(item.get("原本") or "")).strip(),
               numbers=_numbers(item.get("明細の番号")), where=where)


def ledger_rows(folder: Path) -> List[Row]:
    """経費明細（`記録/経費明細.json`）の行。ないときは空。"""
    try:
        data = keihi.load(folder)
    except keihi.KeihiError as e:
        raise NijuuError(str(e)) from e
    rows: List[Row] = []
    for entry in data.get("案件") or []:
        if not isinstance(entry, dict):
            continue
        case = unicodedata.normalize("NFC", str(entry.get("案件") or "")).strip()
        for item in entry.get("行") or []:
            if isinstance(item, dict):
                rows.append(_row(case, item, "経費明細"))
    return rows


def planned_rows(data: Any) -> List[Row]:
    """計上する予定の経費。形：{"案件": [{"案件": "<案件>", "行": [{"品名", "型番", "金額", "原本", "明細の番号"}]}]}
    （案件が1つなら {"案件": "<案件>", "行": [...]} でもよい）。"""
    if isinstance(data, dict) and isinstance(data.get("案件"), str):
        data = {"案件": [data]}
    if not isinstance(data, dict) or not isinstance(data.get("案件"), list):
        raise NijuuError("予定の経費は {\"案件\": [{\"案件\": \"<案件>\", \"行\": [...]}]} の形で渡してください")
    rows: List[Row] = []
    for entry in data["案件"]:
        if not isinstance(entry, dict) or not str(entry.get("案件") or "").strip():
            raise NijuuError("予定の経費の各案件に、「案件」（案件の名前）を入れてください")
        case = unicodedata.normalize("NFC", str(entry["案件"])).strip()
        items = entry.get("行")
        if not isinstance(items, list) or not items:
            raise NijuuError(f"案件「{case}」に、「行」（経費の行）を1つ以上入れてください")
        for item in items:
            if not isinstance(item, dict):
                raise NijuuError(f"案件「{case}」の行は {{ }} の形にしてください")
            rows.append(_row(case, item, "予定"))
    return rows


def compare(a: Row, b: Row) -> Optional[Finding]:
    """2つの行（別の案件）を比べる。同じ経費・同じかもしれない経費なら Finding。"""
    if a.original and a.original == b.original and set(a.numbers) & set(b.numbers):
        nums = "・".join(str(n) for n in sorted(set(a.numbers) & set(b.numbers)))
        return Finding(SERIOUS, f"同じ見積書の同じ明細（{nums}）を、2つの案件に計上しています", a, b)
    ma, mb = norm(a.model), norm(b.model)
    if ma and ma == mb:
        return Finding(SERIOUS, f"型番が同じ（{a.model}）経費を、2つの案件に計上しています", a, b)
    na, nb = norm(a.name), norm(b.name)
    if na and na == nb:
        if a.amount is not None and a.amount == b.amount:
            return Finding(SERIOUS, "品名も金額も同じ経費を、2つの案件に計上しています", a, b)
        return Finding(CHECK, "品名が同じで、金額が違います（同じものか、別のものかを確かめる）", a, b)
    if ma and mb and ma != mb:
        return None  # 型番がどちらにもあって違うなら、別のもの
    if similar(na, nb):
        return Finding(CHECK, "品名がよく似ています（同じものか、別のものかを確かめる）", a, b)
    return None


def check_rows(rows: List[Row]) -> Result:
    result = Result(rows=len(rows))
    seen_cases: List[str] = []
    for r in rows:
        if r.case not in seen_cases:
            seen_cases.append(r.case)
    result.cases = seen_cases
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a.case == b.case:
                continue
            f = compare(a, b)
            if f:
                result.findings.append(f)
    order = {SERIOUS: 0, CHECK: 1}
    result.findings.sort(key=lambda f: order[f.level])
    return result


def check(folder: Path, planned: Any = None) -> Result:
    """会社のフォルダの経費明細と、予定の経費（あれば）を照らす。予定の案件と同じ名前の経費明細の行は、予定で置き換える。"""
    folder = Path(folder)
    problem = place_text.read_problem(folder, keihi.RECORD_PATH, "経費明細")
    if problem:
        raise NijuuError(problem)
    rows = ledger_rows(folder)
    if planned is not None:
        plan = planned_rows(planned)
        replaced = {r.case for r in plan}
        rows = [r for r in rows if r.case not in replaced] + plan
    return check_rows(rows)


def report(result: Result, sources: Optional[List[str]] = None) -> str:
    lines = ["# 二重受給の照合（同じ経費を2つの補助金に計上していないか）", ""]
    lines.append(f"- 照らした案件：{'、'.join(result.cases) if result.cases else '（なし）'}（経費の行 {result.rows}）")
    if len(result.cases) < 2:
        lines.append("- 案件が1つしかないので、比べる相手がありません。もう1つの案件の予定の経費を渡すと照らせます。")
        return "\n".join(lines)
    if not result.findings:
        lines.append("- 同じ経費・同じかもしれない経費は、見つかりませんでした。")
        return "\n".join(lines)
    if result.serious:
        lines += ["", f"## 【重大】同じ経費を2つの補助金に計上しています（{len(result.serious)}件）",
                  "どちらか1つの補助金にだけ計上しないと、二重受給として不採択・交付決定の取消・補助金の返還になりえます。"
                  "どちらに計上するかを社長に決めてもらい、もう一方の計画と経費から外してください。"]
        if sources:
            lines.append("出典：" + "、".join(sources))
        for f in result.serious:
            lines.append(f"- {f.reason}：「{f.a.case}」の {f.a.label()} ／「{f.b.case}」の {f.b.label()}")
    if result.to_check:
        lines += ["", f"## 確かめが要るもの（{len(result.to_check)}件）",
                  "同じものなら重大（上と同じ扱い）になります。社長に、同じものか別のものかを確かめてください。"]
        for f in result.to_check:
            lines.append(f"- {f.reason}：「{f.a.case}」の {f.a.label()} ／「{f.b.case}」の {f.b.label()}")
    return "\n".join(lines)


def rule_sources(folder: Path) -> List[str]:
    """制度データの「してはいけないこと」のうち、重複・二重の受給に当たるものの出典（資料 p.N）。"""
    out: List[str] = []
    base = Path(folder) / "記録" / "制度データ"
    if not base.is_dir():
        return out
    for path in sorted(base.glob("*.json")):
        if places.first_link(folder, path.relative_to(folder).as_posix()) is not None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or "スキーマの版" not in data:
            continue
        for item in data.get("してはいけないこと") or []:
            name = str(item.get("名前") or "") if isinstance(item, dict) else ""
            if not re.search(r"重複|二重|複数の補助金|他の補助金", name):
                continue
            node = item.get("内容") if isinstance(item.get("内容"), dict) else {}
            for src in node.get("出典") or []:
                if isinstance(src, dict) and src.get("資料"):
                    page = f" p.{src['ページ']}" if isinstance(src.get("ページ"), int) else ""
                    label = f"{path.stem}：{name}（{src['資料']}{page}）"
                    if label not in out:
                        out.append(label)
    return out
