"""申請の締切から逆算した日程と、加点が締切までに間に合うかの判定（SPEC F3・T3-2・T3-3、DESIGN 6章。TASKS B24）。

日付の計算は、ここ（コード）で行う。Claude は、会社に当てはまるか（条件付きの書類・加点の条件）と、説明の文を受け持つ。

逆算した日程（build_schedule）：申請の段階（手続きの段階のいちばん前）について、次の作業と期日を出す。
- 申請の締切：段階の期限（lib/deadlines.Plan.stage_due。決まった期日の締切も見る）。
- 電子申請の入力：決まった期日の「受付開始」から。入力を終える目安は締切の INPUT_BUFFER_DAYS 日前（目安。出典はない）。
- 外部に頼む書類（発行元が外部機関の、必須と条件付きの書類）：期日は制度データの「依頼の締切」、なければ申請の締切。
  始める日（頼む日）は、期日から目安の日数を戻した日。目安の日数は、制度データの「依頼の目安の日数」、会社の記録の
  「依頼の目安の日数：<書類>」（前に社長に聞いた日数）の順に取る。どちらにもなければ、始める日を出さず「まだ分かりません」とする
  （推測で日数を入れない。Claude が社長に聞く）。
- 取る期間のある書類（「発行から3か月以内」など。lib/deadlines.acquisition_period）：取る期間（締切から期間を戻した日〜締切）。
- 計画書（案）を固める：外部に頼む書類のうち、制度データに「依頼の締切」があるものは、計画書を見せて頼むので、
  その始める日（分からなければ依頼の締切）までに固める（例：持続化は様式4の受付の締切の前）。依頼の締切のある書類がなければ、
  外部に頼む書類の始める日のうち早いもの、それもなければ締切の PLAN_BUFFER_DAYS 日前（目安）。
- 加点の準備：締切までに間に合う加点（下の判定で「取れる見込み」）のうち、始める日か期日が出たもの。

加点の判定（judge_bonuses）：その加点を「これから取り始める」として、締切までに間に合うか。
- 締切を過ぎた → 今回は取れない。
- 基準日（決まった期日のうち、名前にその加点の名前と「基準日」を含むもの）までに満たす決まり（加点の中身の文で、
  基準日の後ろに「までに」があるもの）で、基準日を過ぎた → 今回は取れない（基準日の時点ですでに満たしていれば取れる、と添える）。
- 加点に要る書類に、制度データの依頼の締切（日付）があり、それを過ぎた → 今回は取れない。
- かかる日数（制度データに出典つきである日数か、会社の記録の「加点の日数：<加点>」）から逆算した始める日を過ぎた → 今回は取れない。
- 上の期日か始める日が出て、まだ間に合う → 取れる見込み（いつまでに何をするか）。
- どれも出ない（かかる日数が資料に書かれていない）→ 確かめが要る（日数を推測しない。DESIGN 14章「加点にかかる日数の出典」）。
すでに満たしている加点（認定を受けているなど）か、そもそも条件に当たるかは、Claude が会社の記録で判断する。

標準のライブラリと lib/ だけで動く（/usr/bin/python3 3.9）。何も書かない。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lib import dates, deadlines

INPUT_BUFFER_DAYS = 3  # 電子申請の入力を終える目安（締切の何日前か）。出典はない（締切の直前の混み合いに備える目安）
PLAN_BUFFER_DAYS = 7  # 外部に頼む書類がないときの、計画書（案）を固める目安（締切の何日前か）
BONUS_DAYS_FACT = "加点の日数"  # 会社の記録の事実の名前の頭（「加点の日数：経営力向上計画加点」）

OK = "取れる見込み"
NO = "今回は取れない"
CHECK = "確かめが要る"

KIND_DEADLINE = "締切"
KIND_INPUT = "電子申請"
KIND_REQUEST = "外部に頼む"
KIND_ACQUIRE = "取る"
KIND_PLAN = "計画書"
KIND_BONUS = "加点"


@dataclass
class Item:
    kind: str
    name: str
    due: Optional[date] = None  # 期日（終える日）
    start: Optional[date] = None  # 始める日（頼む日・取り始める日）
    time: str = ""
    note: str = ""
    sources: List[str] = field(default_factory=list)
    conditional: bool = False  # 当てはまるときだけ（条件付きの書類）
    estimate: bool = False  # 目安（出典のない、ツールの決め方）

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"種類": self.kind, "作業": self.name,
                               "期日": self.due.isoformat() if self.due else None,
                               "始める日": self.start.isoformat() if self.start else None}
        if self.time:
            out["時刻"] = self.time
        if self.conditional:
            out["当てはまるときだけ"] = True
        if self.estimate:
            out["目安"] = True
        if self.note:
            out["注記"] = self.note
        out["出典"] = list(self.sources)
        return out


@dataclass
class Bonus:
    name: str
    judge: str
    reason: str
    due: Optional[date] = None
    start: Optional[date] = None
    sources: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"加点": self.name, "判定": self.judge, "わけ": self.reason,
                "期日": self.due.isoformat() if self.due else None,
                "始める日": self.start.isoformat() if self.start else None, "出典": list(self.sources)}


@dataclass
class Schedule:
    today: date
    deadline: Optional[date] = None
    deadline_time: str = ""
    deadline_label: str = ""
    items: List[Item] = field(default_factory=list)
    bonuses: List[Bonus] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"今日": self.today.isoformat(), "締切": self.deadline.isoformat() if self.deadline else None,
                "締切の時刻": self.deadline_time, "作業": [i.as_dict() for i in self.items],
                "加点": [b.as_dict() for b in self.bonuses], "知らせること": list(self.notes)}


def _nfkc(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _sv_value(node: Any) -> Any:
    if isinstance(node, dict) and node.get("状態") != "読み取れない":
        return node.get("値")
    return None


def first_stage(data: Dict) -> Optional[Dict]:
    stages = deadlines._stages(data)
    return stages[0] if stages else None


def _uses(doc: Dict, stage: Dict) -> bool:
    steps = doc.get("手続き") if isinstance(doc.get("手続き"), list) else []
    return stage.get("id") in steps or stage.get("名前") in steps


def _fixed_named(plan: deadlines.Plan, *words: str) -> List[Tuple[Dict, deadlines.Due]]:
    out = []
    for entry in plan.fixed:
        name = _nfkc(entry["名前"])
        if all(w in name for w in words) and plan.round_ok(entry["名前"]):
            due = plan.fixed_due(entry)
            if due is not None and due.dated:
                out.append((entry, due))
    return out


def lead_of(doc: Dict, facts: Sequence[Dict]) -> Tuple[Optional[Dict[str, Any]], str]:
    """依頼の目安の日数と、その出どころ。制度データ → 会社の記録の順。"""
    node = doc.get("依頼の目安の日数")
    period = deadlines.parse_period(_sv_value(node))
    if period is not None:
        return period, "制度データ（" + "、".join(deadlines.source_text(node)) + "）"
    found = deadlines.recorded_lead(list(facts), str(doc.get("名前") or ""))
    if found is not None:
        return found
    return None, ""


def request_due(plan: deadlines.Plan, doc: Dict) -> Tuple[Optional[deadlines.Due], List[str]]:
    node = doc.get("依頼の締切")
    rule = _sv_value(node)
    if isinstance(rule, dict):
        due = plan.compute(rule)
        if due.dated:
            return due, deadlines.source_text(node)
    return None, []


def build_schedule(data: Dict, today: date, facts: Sequence[Dict] = (), case_round: Optional[int] = None) -> Schedule:
    plan = deadlines.Plan(data, case_round)
    sched = Schedule(today=today)
    stage = first_stage(data)
    if stage is None:
        sched.notes.append("制度データに手続きの段階がないので、日程を作れません")
        return sched
    due = plan.stage_due(stage, application=True)
    if due is None or not due.dated:
        sched.notes.append("申請の締切が、制度データから出せません（" + ((due.how if due else "") or "期限がない") + "）。"
                           "公式サイトで締切を確かめてください")
        sched.bonuses = judge_bonuses(data, today, None, facts, case_round)
        return sched
    deadline = due.last
    sched.deadline, sched.deadline_time = deadline, due.time
    sched.deadline_label = due.label()
    sched.items.append(Item(KIND_DEADLINE, f"{stage.get('名前')}の締切", due=deadline, time=due.time,
                            sources=list(due.sources), estimate=due.estimate))
    if deadline < today:
        sched.notes.append(f"申請の締切（{due.label()}）を過ぎています。次の公募回の日程を、公式サイトで確かめてください")

    opened = _fixed_named(plan, "受付開始")
    open_day = opened[0][1].first if opened else None
    sched.items.append(Item(KIND_INPUT, "電子申請の入力と提出（締切の直前は混み合うので、早めに出す）",
                            due=deadline - timedelta(days=INPUT_BUFFER_DAYS), start=open_day,
                            sources=list(opened[0][1].sources) if opened else [], estimate=True,
                            note=f"終える日は締切の{INPUT_BUFFER_DAYS}日前の目安（出典はない）。始める日は申請の受付開始"))

    requests: List[Item] = []
    fixed_requests: List[Item] = []
    for doc in data.get("書類") or []:
        if not isinstance(doc, dict) or not _uses(doc, stage):
            continue
        kind_class = doc.get("区分")
        if kind_class not in ("必須", "条件付き"):
            continue
        name = str(doc.get("名前") or "")
        conditional = kind_class == "条件付き"
        if doc.get("発行元") == "外部機関" or "依頼先" in doc:
            rdue, rsrc = request_due(plan, doc)
            end = rdue.last if rdue else deadline
            lead, lead_from = lead_of(doc, facts)
            start = deadlines.sub_period(end, lead) if lead else None
            note = (f"頼んでから届くまで {deadlines.period_text(lead)}（{lead_from}）" if lead
                    else "頼んでから届くまでの日数は、まだ分かりません（社長に聞く）")
            if not rdue:
                note += "。依頼の締切は資料にないので、申請の締切を期日にした"
            item = Item(KIND_REQUEST, f"{name}を頼む", due=end, start=start, note=note,
                        sources=rsrc or [], conditional=conditional)
            requests.append(item)
            if rdue:
                fixed_requests.append(item)
            continue
        period, psrc = deadlines.acquisition_period(doc)
        if period is not None:
            first = deadlines.sub_period(deadline, period)
            sched.items.append(Item(KIND_ACQUIRE, f"{name}を取る（発行から{deadlines.period_text(period)}以内のもの）",
                                    due=deadline, start=first, sources=psrc, conditional=conditional,
                                    note="早く出すときは、取る期間のはじめも早まる"))
    sched.items.extend(requests)

    base = fixed_requests or requests
    if base:
        points = [(i.start or i.due, i) for i in base if (i.start or i.due)]
        day, item = min(points, key=lambda p: p[0])
        sched.items.append(Item(KIND_PLAN, "計画書（案）を固める", due=day,
                                note=f"「{item.name}」に計画書を見せて頼むため、その{'始める日' if item.start else '期日'}までに固める",
                                sources=list(item.sources)))
    else:
        sched.items.append(Item(KIND_PLAN, "計画書（案）を固める", due=deadline - timedelta(days=PLAN_BUFFER_DAYS),
                                estimate=True, note=f"外部に頼む書類がないので、締切の{PLAN_BUFFER_DAYS}日前の目安（出典はない）"))

    sched.bonuses = judge_bonuses(data, today, deadline, facts, case_round)
    for b in sched.bonuses:
        if b.judge == OK and (b.start or b.due):
            sched.items.append(Item(KIND_BONUS, f"加点の準備：{b.name}", due=b.due or deadline, start=b.start,
                                    note=b.reason, sources=list(b.sources)))
    sched.items.sort(key=lambda i: (i.start or i.due or date.max, i.due or date.max))
    return sched


def _bonus_core(name: str) -> str:
    return _nfkc(name).replace("に対する加点", "").replace("加点", "").strip()


def bonus_days(bonus: Dict, facts: Sequence[Dict]) -> Tuple[Optional[Dict[str, Any]], str]:
    node = bonus.get("かかる日数")
    period = deadlines.parse_period(_sv_value(node))
    if period is not None:
        return period, "制度データ（" + "、".join(deadlines.source_text(node)) + "）"
    target = _bonus_core(str(bonus.get("名前") or ""))
    for fact in facts:
        name = _nfkc(fact.get("名前")).strip()
        if not name.startswith(BONUS_DAYS_FACT):
            continue
        rest = _bonus_core(name[len(BONUS_DAYS_FACT):].lstrip("：:（(").rstrip("）)"))
        if rest and target and (rest in target or target in rest):
            period = deadlines.parse_period(fact.get("値"))
            if period is not None:
                return period, f"会社の記録 {fact.get('id') or ''}（前に社長に聞いた日数）".replace(" （", "（")
    return None, ""


def _by_reference_date(text: str) -> bool:
    """加点の中身の文が「基準日（…）までに」の形か（基準日までに満たす決まり）。"""
    return bool(re.search(r"基準日[^。]{0,30}?までに", _nfkc(text)))


def judge_bonuses(data: Dict, today: date, deadline: Optional[date], facts: Sequence[Dict] = (),
                  case_round: Optional[int] = None) -> List[Bonus]:
    plan = deadlines.Plan(data, case_round)
    bonus_part = data.get("加点") if isinstance(data.get("加点"), dict) else {}
    items = bonus_part.get("項目") if isinstance(bonus_part.get("項目"), list) else []
    docs = {str(d.get("名前")): d for d in data.get("書類") or [] if isinstance(d, dict)}
    out: List[Bonus] = []
    for bonus in items:
        if not isinstance(bonus, dict):
            continue
        name = str(bonus.get("名前") or "")
        if deadline is None:
            out.append(Bonus(name, CHECK, "申請の締切が出せないので、間に合うかを判定できません"))
            continue
        if deadline < today:
            out.append(Bonus(name, NO, f"申請の締切（{dates.format_date(deadline)}）を過ぎています"))
            continue
        limits: List[Tuple[date, str, List[str]]] = []  # （期日, わけ, 出典）
        content = _sv_value(bonus.get("内容"))
        core = _bonus_core(name)
        if isinstance(content, str) and _by_reference_date(content):
            for entry, due in _fixed_named(plan, "基準日"):
                if core and core in _nfkc(entry["名前"]):
                    limits.append((due.last, f"基準日（{dates.format_date(due.last)}）までに満たす決まり",
                                   list(due.sources)))
        for need in bonus.get("必要な書類") or []:
            doc = next((d for n, d in docs.items() if deadlines.names_match(n, str(need))), None)
            if doc is None:
                continue
            rdue, rsrc = request_due(plan, doc)
            if rdue:
                limits.append((rdue.last, f"要る書類「{doc.get('名前')}」の依頼の締切（{dates.format_date(rdue.last)}）",
                               rsrc))
        period, period_from = bonus_days(bonus, facts)
        start = deadlines.sub_period(deadline, period) if period else None
        passed = [lim for lim in limits if lim[0] < today]
        if passed:
            day, why, src = min(passed, key=lambda x: x[0])
            reason = f"{why}を過ぎています。これから取り始めても間に合いません"
            if "基準日" in why:
                reason += "（基準日の時点ですでに満たしていれば取れます）"
            out.append(Bonus(name, NO, reason, due=day, sources=src))
            continue
        if start is not None and start < today:
            out.append(Bonus(name, NO, f"かかる日数（{deadlines.period_text(period)}。{period_from}）から逆算した始める日"
                                       f"（{dates.format_date(start)}）を過ぎています", start=start))
            continue
        if limits or start is not None:
            due_day = min([lim[0] for lim in limits] + [deadline])
            parts = [lim[1] for lim in limits]
            if start is not None:
                parts.append(f"かかる日数 {deadlines.period_text(period)}（{period_from}）から、{dates.format_date(start)}までに始める")
            srcs: List[str] = []
            for lim in limits:
                srcs += [s for s in lim[2] if s not in srcs]
            out.append(Bonus(name, OK, "。".join(parts) + "。まだ間に合います", due=due_day, start=start, sources=srcs))
            continue
        out.append(Bonus(name, CHECK, "かかる日数が資料に書かれていません（推測しない）。すでに満たしているか、"
                                      "取るのに何日かかるかを社長に確かめてください"))
    return out


DOC_CLASSES = ("必須", "条件付き", "任意")


def doc_list(data: Dict) -> Dict[str, List[Dict[str, Any]]]:
    """申請の段階で使う書類を、必須・条件付き・任意に分ける（SPEC F3「必須書類と、あると有利な任意書類の一覧」・T3-4）。

    任意書類には、制度データの「効く審査項目」（審査項目・加点の名前）を添える。ないものは空にして、Claude が審査項目から添える。
    """
    stage = first_stage(data)
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DOC_CLASSES}
    if stage is None:
        return out
    for doc in data.get("書類") or []:
        if not isinstance(doc, dict) or not _uses(doc, stage) or doc.get("区分") not in DOC_CLASSES:
            continue
        row: Dict[str, Any] = {"書類": str(doc.get("名前") or ""), "発行元": doc.get("発行元") or "",
                               "出典": deadlines.source_text(doc.get("内容"))}
        who = str(doc.get("出す人") or "")
        if who and who != "全事業者":
            row["出す人"] = who
        cond = _sv_value(doc.get("条件"))
        if cond:
            row["条件"] = str(cond)
        valid = _sv_value(doc.get("有効期限"))
        if valid:
            row["有効期限"] = str(valid)
        effects = doc.get("効く審査項目")
        row["効く審査項目・加点"] = [str(e) for e in effects] if isinstance(effects, list) else []
        if deadlines._is_form(doc, stage, data):
            row["様式で作る"] = True
        out[doc["区分"]].append(row)
    return out


def doc_report(data: Dict) -> str:
    groups = doc_list(data)
    reviews = [str(r.get("名前")) for r in data.get("審査項目") or [] if isinstance(r, dict) and r.get("名前")]
    bonus_part = data.get("加点") if isinstance(data.get("加点"), dict) else {}
    bonuses = [str(b.get("名前")) for b in bonus_part.get("項目") or [] if isinstance(b, dict) and b.get("名前")]
    lines = ["# 申請の書類の一覧（制度データから）", ""]
    for cls in DOC_CLASSES:
        rows = groups[cls]
        lines += [f"## {cls}（{len(rows)}件）", "", "| 書類 | 発行元 | 条件・有効期限 | 効く審査項目・加点 | 出典 |", "|---|---|---|---|---|"]
        for r in rows:
            who = f"出す人：{r['出す人']}" if r.get("出す人") else ""
            extra = "。".join(x for x in (who, r.get("条件", ""), r.get("有効期限", "")) if x) or "—"
            name = r["書類"] + ("（様式で作る）" if r.get("様式で作る") else "")
            effects = "、".join(r["効く審査項目・加点"]) or ("（制度データにない。審査項目から添える）" if cls == "任意" else "—")
            lines.append(f"| {name} | {r['発行元'] or '—'} | {extra} | {effects} | {'、'.join(r['出典']) or '—'} |")
        lines.append("")
    lines.append("審査項目：" + ("、".join(reviews) if reviews else "（制度データにない）"))
    lines.append("加点：" + ("、".join(bonuses) if bonuses else "（制度データにない）"))
    lines.append("")
    lines.append("制度データにない任意の書類（会社概要、事業別の収支、商品・サービスの説明、作業工程の写真など）を勧めるときは、"
                 "上の審査項目・加点のどれに効くかを、1つずつ添える。")
    return "\n".join(lines)


def report(sched: Schedule, title: str = "") -> str:
    lines = [f"# 申請までの日程（逆算）{('：' + title) if title else ''}", "",
             f"今日：{dates.format_date(sched.today)}"]
    if sched.deadline:
        lines.append(f"申請の締切：{sched.deadline_label}")
    for n in sched.notes:
        lines.append(f"- 知らせること：{n}")
    if sched.items:
        lines += ["", "## 作業と期日（始める日の早い順）", "", "| 作業 | 始める日 | 期日 | 注記 | 出典 |", "|---|---|---|---|---|"]
        for i in sched.items:
            start = dates.format_date(i.start) if i.start else "—"
            due = (dates.format_date(i.due) + i.time) if i.due else "—"
            if i.estimate:
                due += "（目安）"
            name = i.name + ("（当てはまるときだけ）" if i.conditional else "")
            if i.due and i.due < sched.today and i.kind != KIND_ACQUIRE:
                name = "【期日を過ぎた】" + name
            elif i.start and i.start < sched.today and i.kind in (KIND_REQUEST, KIND_PLAN, KIND_BONUS):
                name = "【遅れ】" + name
            lines.append(f"| {name} | {start} | {due} | {i.note} | {'、'.join(i.sources) or '—'} |")
    if sched.bonuses:
        lines += ["", "## 加点が締切までに間に合うか（これから取り始めるとき）", "", "| 加点 | 判定 | わけ |", "|---|---|---|"]
        for b in sched.bonuses:
            lines.append(f"| {b.name} | {b.judge} | {b.reason} |")
        lines.append("")
        lines.append("すでに満たしている加点と、会社が条件に当たるかは、会社の記録で確かめてから伝える（判定は日付だけで見ている）。")
    return "\n".join(lines)
