"""事業期間中と事業後の義務を、期限の台帳の作業と知らせにする（SPEC F6「事業期間中の義務」「事業後の義務」・F12・T6-7、
DESIGN 4.5・4.6・9章の「義務」の行。TASKS K3）。

lib/deadlines.py の case_status から呼ぶ。読むのは、制度データの「義務」（任意の欄）と手続きの段階・数値の要件、
期限の台帳の出来事（交付決定・事業の完了）、書類の台帳の原本、経費明細（`記録/経費明細.json`）、会社の記録の決算の月。
何も書かない（台帳を書くのは道具だけ。開いたときの hook からも呼ぶため）。

時期の分け方
- 事業期間中：交付決定の日（台帳の出来事か予定）から、事業の完了の日まで（完了の日が分からなければ、それまでずっと）。
- 事業後：事業の完了の日の後。

示すもの（それぞれの時期に）
- 経費ごとの証拠の揃い具合（事業期間中と、事業後に実績報告を出すまで）：経費明細の行ごとに、義務の「証拠の書類」
  （種類が「証拠をそろえる」の義務）が、書類の台帳にあるか。相手先は、経費明細の行の見積書の原本の相手先で見る。
  見積書のほかの証拠は、交付決定の日より後の日付の原本だけを数える（前の日付は事前着手のおそれがあるので、数えずに知らせる）。
  作業（種類「証拠」）は1つにまとめ、締切は補助事業の実施の段階の期限（なければ実績報告の期限）。
- 事前に申請する義務（計画変更・処分の承認など）の注意：その時期の間ずっと、内容と守れないときを出典つきで。
  義務の欄がない制度データでは、条件付きの手続きの段階のうち名前に「変更」のあるものの始まる条件から作る。
- 報告する・守り続ける義務：その時期の間、内容を知らせる。始まり・終わりの決め方があれば日付を添える。
- 残す義務（書類を残す期間など）：事業後に、終わりの日（決め方から出せれば）を添えて知らせる。
- 効果報告の数字の用意（事業後）：繰り返しの報告の段階の、まだ出していない回のうち、その回の年度が終わった（決算日を過ぎた）
  ものについて、作業（種類「義務」）を作る。締切はその回の提出期間。使う数字は、制度データの数値の要件の名前から挙げる。
- 事業場内最低賃金の確かめ（事業期間中と事業後。効果報告の最後の回まで）：数値の要件か義務の名前に「最低賃金」があれば、
  毎年、地域別最低賃金の改定の後（MIN_WAGE_MONTH 月。仮）に確かめる作業を作る。改定の日は都道府県ごとに違うので見込みとし、
  所在地の都道府県の公表を確かめるよう添える。次の1回だけを作業にする。

義務の始まり・終わりの決め方の出来事の名前のうち、事業の完了（終了）に「翌月の初め」「年度の終わり」を付けたものは、
完了の日から出す（年度は国の年度。4月から翌年3月。仮）。ほかの出せない決め方は、日付を出さずに決め方を示す。

hook から呼ぶので、標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EVIDENCE_KIND = "証拠"  # lib/task_ledger.py の KINDS
DUTY_KIND = "義務"
COLLECT = "証拠をそろえる"
DURING = "事業期間中"
AFTER = "事業後"
DECISION_WORD = "交付決定"
MIN_WAGE_WORD = "最低賃金"
MIN_WAGE_MONTH = 10  # 地域別最低賃金の改定の後に確かめる月（多くの都道府県で10月に変わる。仮。都道府県ごとに違う）
QUOTE_WORD = "見積"
EXPENSES_FILE = "記録/経費明細.json"  # lib/keihi.py の RECORD_PATH と同じ
CHANGE_WORD = "変更"
NUMBERS_HINT = "決算書、給与支給総額、従業員数など"


@dataclass
class EvidenceRow:
    """経費明細の1行の、証拠の揃い具合。"""

    expense: str  # 品名
    partner: str  # 相手先（見積書の原本の相手先）
    amount: int
    have: List[str] = field(default_factory=list)  # そろった証拠の種類
    missing: List[str] = field(default_factory=list)  # まだの証拠の種類
    early: List[str] = field(default_factory=list)  # 交付決定の日より前の日付の原本（事前着手のおそれ）


@dataclass
class Result:
    tasks: list = field(default_factory=list)  # deadlines.Task
    notes: List[str] = field(default_factory=list)  # 義務の知らせ（時期・内容・出典）
    evidence: List[EvidenceRow] = field(default_factory=list)
    evidence_note: str = ""  # 揃い具合を出せないわけ、など
    period: str = ""  # 事業期間中・事業後・（空：交付決定の前）


def nfc(text: Any) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def squash(text: Any) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = re.sub(r"\s+", "", t)
    for word in ("株式会社", "有限会社", "合同会社", "(株)", "（株）", "御中"):
        t = t.replace(unicodedata.normalize("NFKC", word), "")
    return t


def _valued(node: Any, sources) -> str:
    """出典つき値の「値（出典）」。値がなければ空。"""
    if not isinstance(node, dict) or not isinstance(node.get("値"), str):
        return ""
    where = "、".join(sources(node))
    return f"{node['値']}（{where}）" if where else node["値"]


def duties(data: Dict) -> List[Dict]:
    items = data.get("義務") if isinstance(data, dict) else None
    return [d for d in items if isinstance(d, dict) and isinstance(d.get("名前"), str)] if isinstance(items, list) else []


# ---- 日付 ----


def fiscal_year_end(day: date) -> date:
    """国の年度（4月〜翌年3月）の終わりの日。"""
    return date(day.year if day.month <= 3 else day.year + 1, 3, 31)


def first_of_next_month(day: date) -> date:
    return date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)


def resolve(plan, rule: Any, completion: Optional[date]):
    """義務の始まり・終わりの決め方の日付（deadlines.Due）。事業の完了に「翌月の初め」「年度の終わり」を付けた出来事も解く。"""
    from lib import deadlines

    due = plan.compute(rule)
    if due.dated or not isinstance(rule, dict) or rule.get("種類") != "出来事からの期間":
        return due
    name = unicodedata.normalize("NFKC", str(rule.get("出来事") or ""))
    if completion is None or not any(w in name for w in deadlines.COMPLETION_WORDS):
        return due
    if "翌月" in name:
        base = first_of_next_month(completion)
    elif "年度" in name:
        base = fiscal_year_end(completion)
    else:
        base = completion
    day = deadlines.add_period(base, rule.get("期間"))
    if day is None:
        return due
    return deadlines.Due(first=day, last=day, estimate=False, basis=[f"事業の完了 {deadlines.dates.format_date(completion)}"])


# ---- 証拠の揃い具合 ----


def _alternatives(kind: str) -> List[str]:
    """「発注書・申込書・契約書」→ [発注書, 申込書, 契約書]。括弧の中は除く。"""
    from lib import deadlines

    core = deadlines._BRACKETS.sub("", unicodedata.normalize("NFKC", kind))
    return [p.strip() for p in re.split(r"[・/、]", core) if len(p.strip()) >= 2]


def _kind_match(kind: str, original_kind: str) -> bool:
    from lib import deadlines

    return any(deadlines.names_match(a, original_kind) or a in unicodedata.normalize("NFKC", original_kind)
               for a in _alternatives(kind))


def load_expenses(folder: Path, case: str) -> Tuple[Optional[List[Dict]], str]:
    """経費明細の、この案件の行。なければ (None, わけ)。"""
    from lib import places

    if places.first_link(folder, EXPENSES_FILE) is not None:
        return None, f"{EXPENSES_FILE} の途中が別名のため、読んでいません"
    path = places.actual(folder, EXPENSES_FILE)
    if path is None or not path.is_file():
        return None, f"経費明細（{EXPENSES_FILE}）がまだないため、経費ごとの揃い具合は出せません（kaku で経費明細を作ると出ます）"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"経費明細（{EXPENSES_FILE}）が読めません（{type(error).__name__}）"
    for entry in data.get("案件") or [] if isinstance(data, dict) else []:
        if isinstance(entry, dict) and nfc(entry.get("案件")) == nfc(case):
            rows = [r for r in entry.get("行") or [] if isinstance(r, dict)]
            return rows, ""
    return None, f"経費明細（{EXPENSES_FILE}）に、この案件の行がないため、経費ごとの揃い具合は出せません"


def evidence_rows(kinds: List[str], expenses: List[Dict], originals, decision: Optional[date]) -> List[EvidenceRow]:
    """経費明細の行ごとに、証拠の種類（kinds）がそろっているか。"""
    by_place = {nfc(o.place): o for o in originals or []}
    rows = []
    for row in expenses:
        quote = by_place.get(nfc(row.get("原本")))
        partner = nfc(quote.partner) if quote is not None else ""
        amount = row.get("金額") if isinstance(row.get("金額"), int) else 0
        item = EvidenceRow(expense=nfc(row.get("品名")), partner=partner, amount=amount)
        for kind in kinds:
            is_quote = QUOTE_WORD in kind
            if is_quote and quote is not None:
                item.have.append(kind)
                continue
            found = [o for o in originals or [] if _kind_match(kind, o.kind)
                     and partner and squash(partner) and squash(o.partner) == squash(partner)]
            if not is_quote and decision is not None:
                early = [o for o in found if o.day is not None and o.day < decision]
                item.early += [o.place for o in early if o.place not in item.early]
                found = [o for o in found if o.day is None or o.day >= decision]
            (item.have if found else item.missing).append(kind)
        rows.append(item)
    return rows


# ---- まとめ ----


def build(folder: Path, status, data: Dict, plan, today: date, originals) -> Result:
    """1つの案件の、事業期間中と事業後の義務の作業と知らせ。"""
    from lib import dates, deadlines

    out = Result()
    decision_due = plan.event_due(DECISION_WORD)
    completion_name = plan.completion_event()
    completion_due = plan.event_due(completion_name) if completion_name else None
    decision = decision_due.first if decision_due is not None and decision_due.dated else None
    completion = completion_due.last if completion_due is not None and completion_due.dated else None
    if decision is None or decision > today:
        return out  # 交付決定の前（事前着手の注意は、段階の切り替えと書類の確かめが出す）
    after = completion is not None and completion < today
    out.period = AFTER if after else DURING
    period_text = (f"事業後（事業の完了 {dates.format_date(completion)} の後）" if after
                   else f"事業期間中（交付決定 {dates.format_date(decision)} から）")
    sources = deadlines.source_text
    items = duties(data)
    stages = deadlines._stages(data)
    report_row = next((r for s, r in zip(stages, status.stages) if "実績" in nfc(s.get("id")) + r.name), None)
    report_sent = report_row is not None and report_row.state == "済み"

    # 経費ごとの証拠の揃い具合
    collect = [d for d in items if d.get("種類") == COLLECT and d.get("時期", DURING) == DURING]
    kinds = []
    for d in collect:
        kinds += [k for k in d.get("証拠の書類") or [] if isinstance(k, str) and k not in kinds]
    if not report_sent:
        if not items:
            out.evidence_note = "制度データに「義務」の欄がないため、経費ごとにそろえる証拠の種類が分かりません（制度データを作り直すと出ます）"
        elif not kinds:
            out.evidence_note = "制度データの義務に、経費ごとにそろえる証拠の種類（証拠の書類）がありません"
        else:
            expenses, problem = load_expenses(folder, status.name)
            if expenses is None:
                out.evidence_note = problem
            else:
                out.evidence = evidence_rows(kinds, expenses, originals, decision)
        if out.evidence or out.evidence_note:
            due_row = next((r for s, r in zip(stages, status.stages) if "実施" in nfc(s.get("id")) + r.name
                            and r.due is not None and r.due.dated), report_row)
            due = due_row.due if due_row is not None and due_row.due is not None else deadlines.Due(how="締切が分かりません")
            done = sum(1 for e in out.evidence if not e.missing)
            what = (f"経費の証拠をそろえる（そろった経費 {done}/{len(out.evidence)}件）" if out.evidence
                    else "経費の証拠をそろえる")
            task = deadlines.Task(case=status.name, order=due_row.order if due_row else 0,
                                  stage=due_row.name if due_row else "", what=what, due=due, kind=EVIDENCE_KIND,
                                  who="社長", state="済み" if out.evidence and done == len(out.evidence) else "")
            short: Dict[str, int] = {}
            for e in out.evidence:
                for k in e.missing:
                    short[k] = short.get(k, 0) + 1
            if short:
                task.notes.append("足りない証拠：" + "、".join(f"{k} {n}件" for k, n in short.items()))
            early = sorted({p for e in out.evidence for p in e.early})
            if early:
                task.notes.append("交付決定より前の日付の原本があります（事前着手のおそれ。数えていません）：" + "、".join(early))
            if out.evidence_note:
                task.notes.append(out.evidence_note)
            for d in collect:
                text = _valued(d.get("守れないとき"), sources)
                if text:
                    task.notes.append(f"守れないとき：{text}")
            task.notes.append("一覧は 今の状態.html の「経費ごとの証拠の揃い具合」にあります")
            out.tasks.append(task)

    # 義務の知らせ（その時期のもの）
    want = AFTER if after else DURING
    for d in items:
        if d.get("種類") == COLLECT or d.get("時期", DURING) != want:
            continue
        text = f"{d['名前']}（{d.get('種類')}）：{_valued(d.get('内容'), sources)}"
        for key, label in (("始まり", "始まり"), ("終わり", "終わり")):
            node = d.get(key)
            if isinstance(node, dict):
                if node.get("値") is not None:
                    due = resolve(plan, node["値"], completion)
                    if due.dated:
                        text += f"。{label}：{dates.format_date(due.first)}"
                elif node.get("理由"):
                    text += f"。{label}：資料から読み取れません（{node['理由']}）"
        fail = _valued(d.get("守れないとき"), sources)
        if fail:
            text += f"。守れないとき：{fail}"
        out.notes.append(text)
    if not items:
        if not after:
            for s, r in zip(stages, status.stages):
                if s.get("条件付き") is True and CHANGE_WORD in r.name:
                    start = _valued(s.get("始まる条件"), sources)
                    out.notes.append(f"{r.name}（事前に申請する）：{start}" if start else f"{r.name}（事前に申請する）")
        out.notes.append("制度データに「義務」の欄がないため、処分の制限・書類を残す期間・経費ごとの証拠は出していません"
                         "（制度データを作り直すと出ます）")

    # 効果報告の数字の用意（事業後）
    if after:
        for s, r in zip(stages, status.stages):
            pending = [y for y in r.years if not y.submitted]
            if not pending or plan.closing is None:
                continue
            year = pending[0]
            closed = deadlines._closing_day(year.due.first.year, plan.closing)
            if closed >= year.due.first:
                closed = deadlines._closing_day(year.due.first.year - 1, plan.closing)
            if today <= closed or today > year.due.last:
                continue
            names = [n.get("名前") for n in data.get("数値の要件") or [] if isinstance(n, dict) and n.get("名前")]
            task = deadlines.Task(case=status.name, order=r.order, stage=r.name,
                                  what=f"{r.name}（{year.number}{deadlines.YEAR_WORD}）の数字を用意する",
                                  due=year.due, kind=DUTY_KIND, who="社長")
            task.notes.append(f"決算日（{dates.format_date(closed)}）を過ぎました。この期の決算の数字（{NUMBERS_HINT}）を、"
                              "提出期間までに用意します")
            if names:
                task.notes.append("確かめる数値の要件：" + "、".join(names))
            out.tasks.append(task)

    # 事業場内最低賃金の確かめ（毎年の改定の後）
    words = [d["名前"] for d in items] + [n.get("名前") for n in data.get("数値の要件") or []
                                          if isinstance(n, dict) and isinstance(n.get("名前"), str)]
    wage = next((w for w in words if MIN_WAGE_WORD in nfc(w)), None)
    if wage is not None:
        last_year = max((y.due.last.year for r in status.stages for y in r.years), default=None)
        year = today.year
        first = date(year, MIN_WAGE_MONTH, 1)
        end = first_of_next_month(first) - timedelta(days=1)
        if end < today:
            year += 1
            first, end = date(year, MIN_WAGE_MONTH, 1), first_of_next_month(date(year, MIN_WAGE_MONTH, 1)) - timedelta(days=1)
        if last_year is None or year <= last_year:
            task = deadlines.Task(case=status.name, order=0, stage="",
                                  what=f"事業場内最低賃金を確かめる（{year}年の地域別最低賃金の改定の後）",
                                  due=deadlines.Due(first=first, last=end, term=True, term_word="確かめる時期",
                                                    estimate=True), kind=DUTY_KIND, who="社長")
            task.notes.append(f"もとにした要件：{wage}。改定の日は都道府県ごとに違うので、所在地の都道府県の公表を確かめ、"
                              "いちばん低い時給と比べます")
            out.tasks.append(task)
    if out.notes:
        out.notes.insert(0, f"今は{period_text}です")
    return out


__all__ = ["EvidenceRow", "Result", "build", "evidence_rows", "load_expenses", "resolve"]
