"""期限と、外部への依頼と待ちの道具の中身（SPEC F6・T6-6、DESIGN 4.5〜4.7・6章。TASKS K2）。

skills/junbi/scripts/kigen.py から呼ぶ。日付と日数はすべてここ（と lib/deadlines.py）で出し、Claude には結果の値を
そのまま使わせる（DESIGN 6章）。

- 一覧（show_text）：すべての案件の期限と作業（期限切れ・今日やること・近い締切・遅れている作業、それより先、日付がまだ
  出せないもの、外部への依頼と待ち、済んだもの）。開いたときの文と同じ組み立て（lib/deadlines.build）。
- 人に頼む書類の候補（requests_text）：案件の今の段階と、次のフォルダのある段階までで使う、必須・条件付きの書類のうち、
  外部機関が出すものと、制度データに依頼先があるもの（様式で作る書類を除く）。今の依頼の状態・目安の日数・締切・始める日。
  目安の日数は、制度データ、会社の記録（前の案件で社長に聞いた「依頼の目安の日数：<書類>」）の順に引き、どこにもなければ
  「聞くこと」に並べる（SPEC F6「ないものは初めて出てきたときに社長に聞いて会社の記録に残す」）。
- 依頼を残す（apply）：足す・目安の日数・頼む人・依頼先・状態・届いた書類を、期限の台帳の「作業」に残す（lib/task_ledger.py）。
  社長に聞いた目安の日数は、会社の記録にも「依頼の目安の日数：<書類>」として残す（次の案件で聞き直さないため。T6-6）。
  前と違う日数を聞いたときは、会社の記録の値を新しい答えに直す（社長がいま答えた値のため）。
  台帳に足すとき、目安の日数が会社の記録にあれば、それを台帳にも写す（出どころを「会社の記録」とする）。
  書類の名前は、制度データの書類の名前に当たるものだけを受け付け、台帳には制度データの名前で残す（締切を出すため）。
- 日付で示された期限を残す（apply_dues）：差し戻しの出し直しの期限のように、通知に日付で書かれた期限を、期限の台帳の
  「作業」（種類「提出」）に、出典（通知の原本の場所か社長の答え）と一緒に残す。出したら「済み」にする（11/7 の採択後の通し）。
- 近い締切の日数（set_near）：`.hojokin/設定.json` に残す（会社のフォルダの設定が `.hojokin/` の Edit を拒むため）。

書いた後は、今の状態.html を作り直す（lib/status_view）。書く前に、書くものの場所を lib/places.py で確かめる。
/usr/bin/python3（3.9）で動く。会社の記録を書くときだけ lib/company_record.py（スキーマの検査）を読み込む。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import dates, deadlines, places, seido_data, status_view, task_ledger

LEAD_FACT = deadlines.LEAD_FACT
EXTERNAL = "外部機関"
_CHANGE = re.compile(r"^\s*(.+?)\s*[=＝]\s*(.*?)\s*$")
_STATE_DAY = re.compile(r"^(.+?)\s*[@＠]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})$")


class ToolError(ValueError):
    """道具を動かせない（書類の名前が当たらない、値の形が違う など）。何も書いていない。"""


@dataclass
class Change:
    """1つの書類への変更（kigen.py の引数をまとめたもの）。"""

    doc: str
    add: bool = False
    days: Optional[int] = None
    asker: Optional[str] = None
    to: Optional[str] = None
    state: Optional[str] = None
    day: Optional[date] = None  # 状態を変えた日（依頼した日・届いた日）
    received: Optional[str] = None


@dataclass
class Applied:
    case: str
    lines: List[str] = field(default_factory=list)  # 残したことの文
    notes: List[str] = field(default_factory=list)  # 知らせること


def split_change(text: str, what: str) -> Tuple[str, str]:
    m = _CHANGE.match(text or "")
    if not m or not m.group(1) or not m.group(2):
        raise ToolError(f"{what}は「<書類>=<値>」の形で渡してください（{text}）")
    return unicodedata.normalize("NFC", m.group(1)), unicodedata.normalize("NFC", m.group(2))


def parse_days(text: str) -> int:
    """「14」「14日」「2週間」を日数に。か月は日数で聞き直す（依頼の目安は日で持つ）。"""
    period = deadlines.parse_period(text)
    if period is None and re.fullmatch(r"\s*[0-9]+\s*", unicodedata.normalize("NFKC", text)):
        period = {"数": int(unicodedata.normalize("NFKC", text)), "単位": "日"}
    if period is None or period["単位"] != "日" or period["数"] < 1:
        raise ToolError(f"目安の日数（{text}）は、「14日」「2週間」のように、1日以上の日数で渡してください")
    return period["数"]


def parse_state(text: str, today: date) -> Tuple[str, date]:
    m = _STATE_DAY.match(text.strip())
    state, day = (m.group(1).strip(), date.fromisoformat(m.group(2))) if m else (text.strip(), today)
    if state not in task_ledger.STATES:
        raise ToolError(f"状態（{state}）は、{'・'.join(task_ledger.STATES)} のどれかにしてください")
    if day > today:
        raise ToolError(f"状態を変えた日（{dates.format_date(day)}）が、今日（{dates.format_date(today)}）より後です")
    return state, day


def _case_data(folder: Path, case: str) -> Dict:
    try:
        _path, data = seido_data.load_data(folder, case)
    except (seido_data.DataMissing, seido_data.MergeError) as error:
        raise ToolError(str(error)) from error
    if not isinstance(data, dict):
        raise ToolError("制度データの形が違います。junbi の道具（seido_data.py --check）で確かめてください")
    return data


def _status(ov: deadlines.Overview, case: str) -> deadlines.CaseStatus:
    found = next((c for c in ov.cases if c.name == case), None)
    if found is None:
        raise ToolError(f"案件のフォルダ（{deadlines.CASES_DIR}/{case}/）がありません。先に公式資料を取り、案件のフォルダを作ってください")
    if found.problem:
        raise ToolError(found.problem)
    return found


# ---- 人に頼む書類の候補 ----


@dataclass
class Candidate:
    doc: Dict
    stage_name: str
    group: str  # 必須・条件付き
    request: Optional[deadlines.Task]  # 台帳にある依頼（なければ None）
    due: deadlines.Due
    lead: Optional[Dict[str, Any]]
    lead_source: str
    start: Optional[date]
    to: str = ""  # 依頼先（台帳の値、なければ制度データの依頼先か出す人）


def _requestable(doc: Dict) -> bool:
    return doc.get("発行元") == EXTERNAL or isinstance(doc.get("依頼先"), dict)


def candidates(folder: Path, case: str, ov: deadlines.Overview) -> Tuple[List[Candidate], int]:
    """今の段階と、次のフォルダのある段階までで使う、人に頼む書類。(候補, この後の段階の候補の数)。"""
    status = _status(ov, case)
    data = _case_data(folder, case)
    events = {}
    try:
        from lib import event_ledger
        found, _problem = event_ledger.events_by_case(folder)
        events = found
    except Exception:
        events = {}
    plan = deadlines.Plan(data, deadlines._case_round(folder, case), events.get(case))
    stages = deadlines._stages(data)
    rows = {r.order: r for r in status.stages}
    open_stages = [(s, rows[deadlines._int(s.get("順番"))]) for s in stages
                   if deadlines._int(s.get("順番")) in rows and rows[deadlines._int(s.get("順番"))].state != "済み"]
    # 今の段階から、次のフォルダのある段階まで
    window: List[Tuple[Dict, deadlines.StageRow]] = []
    foldered = 0
    for stage, row in open_stages:
        window.append((stage, row))
        if row.folder:
            foldered += 1
        if foldered >= 2:
            break
    window_ids = {s.get("id") for s, _r in window}
    requests = {t.doc: t for t in status.tasks if t.kind == deadlines.REQUEST}
    ledger, _problem = task_ledger.requests_by_case(folder)
    recorded = ledger.get(case, [])
    facts = deadlines._company_facts(folder)
    found_list: List[Candidate] = []
    later = 0
    docs = data.get("書類") if isinstance(data.get("書類"), list) else []
    for doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("名前"), str):
            continue
        if doc.get("区分") not in ("必須", "条件付き") or not _requestable(doc):
            continue
        uses = doc.get("手続き") if isinstance(doc.get("手続き"), list) else []
        stage_pair = next(((s, r) for s, r in open_stages if s.get("id") in uses), None)
        if stage_pair is None or deadlines._is_form(doc, stage_pair[0], data):
            continue
        if stage_pair[0].get("id") not in window_ids:
            later += 1
            continue
        req = next((t for name, t in requests.items() if task_ledger.same_doc(name, doc["名前"])), None)
        due, _what = deadlines.request_due(data, plan, open_stages, doc)
        probe = task_ledger.Request(case=case, doc=doc["名前"])
        lead, lead_source = deadlines.request_lead(probe, doc, facts)
        if req is not None and req.lead:
            lead_source = req.lead
        start = deadlines.sub_period(due.first, lead) if lead is not None and due.dated else None
        entry = task_ledger.find_request(recorded, doc["名前"])
        to = (entry.to if entry is not None and entry.to else "") or _to_of(doc)
        found_list.append(Candidate(doc=doc, stage_name=stage_pair[1].name, group=str(doc.get("区分")), request=req,
                                    due=due, lead=lead, lead_source=lead_source, start=start, to=to))
    return found_list, later


def _condition(doc: Dict) -> str:
    node = doc.get("条件")
    return str(node.get("値")) if isinstance(node, dict) and node.get("値") else ""


def _to_of(doc: Dict) -> str:
    """制度データの依頼先（「出す人」は申請する人の区分なので使わない）。"""
    node = doc.get("依頼先")
    return str(node["値"]) if isinstance(node, dict) and node.get("値") else ""


def requests_text(folder: Path, case: str) -> Tuple[str, bool]:
    """人に頼む書類の候補の文と、目安の日数を聞くものがあるか。"""
    ov = deadlines.build(folder)
    found, later = candidates(folder, case, ov)
    status = _status(ov, case)
    today = ov.today
    lines = [f"## 人に頼む書類（{case}。今日 {dates.format_date(today)}"
             + ("。日付を差し替えています" if ov.substituted else "") + "）",
             f"今の段階：{status.current}。今の段階と次の段階で使う、外部（金融機関・業者・商工会議所など）が出す書類です。"
             "条件付きの書類は、条件に当たるかを会社の記録で確かめ、分からなければ社長に聞いてください。"
             "日付と日数は、この一覧の値を使ってください（頭で計算し直さない）。", ""]
    asking = []
    if not found:
        lines.append("- ありません")
    for c in found:
        name = c.doc["名前"]
        cond = _condition(c.doc)
        head = f"- {name}（{c.group}" + (f"：{cond}" if cond else "") + f"。{c.stage_name}で使う）"
        parts = [head]
        if c.to:
            parts.append(f"依頼先：{c.to}")
        days = c.due.days_text(today)
        parts.append(f"締切：{c.due.label()}" + (f"（{days}）" if days else ""))
        if c.lead is not None:
            parts.append(f"目安：{deadlines.period_text(c.lead)}（{c.lead_source}）" if c.lead_source
                         else f"目安：{deadlines.period_text(c.lead)}")
            if c.start is not None:
                parts.append(f"始める日（頼む日）：{dates.format_date(c.start)}" + ("（見込み）" if c.due.estimate else ""))
        else:
            parts.append("目安：まだ分かりません")
            if c.request is not None and not c.request.done:
                asking.append(name)
        if c.request is not None:
            parts.append(f"台帳：{c.request.state}｜{c.request.who}")
        else:
            parts.append("台帳：まだ足していません")
        lines.append("｜".join(parts))
    if later:
        lines.append(f"（この後の段階で使う、人に頼む書類が{later}件あります。その段階に近づいたら出します）")
    lines.append("")
    if asking:
        lines += ["### 目安の日数を社長に聞くもの（台帳に足した依頼のうち、目安がまだ分からないもの）",
                  f"- {'、'.join(asking)}：頼んでから届くまでの日数（理由：始める日〈頼む日〉を締切から逆算するため）。"
                  "聞いた日数は --days で残すと、会社の記録にも残り、次の案件では聞き直さずに使います"]
    else:
        lines.append("頼む書類を決めたら --add で台帳に足し、目安が「まだ分かりません」のものだけ、頼んでから届くまでの日数を"
                     "社長に聞いてください（条件に当たらない書類は聞かない。目安が出ている書類は聞き直さない）。")
    return "\n".join(lines) + "\n", bool(asking)


# ---- 依頼を残す ----


def _resolve_doc(data: Dict, name: str) -> str:
    doc = deadlines.find_doc(data, name)
    if doc is None:
        names = [d["名前"] for d in data.get("書類") or [] if isinstance(d, dict) and isinstance(d.get("名前"), str)
                 and _requestable(d)] if isinstance(data.get("書類"), list) else []
        hint = "、".join(names[:12]) if names else "（人に頼む書類が制度データにありません）"
        raise ToolError(f"制度データの書類に「{name}」が見当たりません。制度データの書類の名前で渡してください"
                        f"（人に頼む書類：{hint}）")
    return doc["名前"]


def _received_place(folder: Path, raw: str) -> str:
    text = unicodedata.normalize("NFC", raw.strip())
    try:
        rel = places.relative_inside(folder, text)
    except places.PlaceError as error:
        raise ToolError(f"届いた書類（{raw}）が会社のフォルダの外を指しています。会社のフォルダの中の場所を渡してください") from error
    if rel == "." or not (places.real(folder) / rel).is_file():
        raise ToolError(f"届いた書類（{raw}）が会社のフォルダにありません。整理した後の場所（原本/…）を渡してください")
    return rel


def _record_lead(folder: Path, doc: str, days: int, applied: Applied) -> str:
    """社長に聞いた目安の日数を、会社の記録に残す。出どころの文を返す。"""
    from lib import company_record
    name = f"{LEAD_FACT}：{doc}"
    value = f"{days}日"
    source = company_record.make_source(folder, "質問", question=f"{doc}を頼んでから届くまでの日数")
    result, item, others = company_record.add_fact(folder, name, value, True, source)
    if result == "conflict" and others:
        before, item = company_record.update_fact(folder, others[0]["id"], value, source, changeable=True)
        applied.notes.append(f"会社の記録の「{name}」を {before['値']} から {value} に直しました（社長の新しい答え）")
    elif result == "added":
        applied.lines.append(f"会社の記録に「{name}」＝{value} を残しました（{item['id']}。次の案件でも使います）")
    return f"社長の答え（{dates.today(folder).isoformat()}。会社の記録 {item['id']}）"


def place_problem(folder: Path) -> Optional[str]:
    """期限の台帳の置き場に別名があれば、断る文（lib/places.py）。"""
    from lib import event_ledger, place_text
    return place_text.write_problem(folder, event_ledger.LEDGER_FILE, task_ledger.LEDGER_ACTION)


def apply(folder: Path, case: str, changes: List[Change]) -> Applied:
    """依頼を期限の台帳に残す。書類の名前と値をすべて確かめてから書く（1つでも合わなければ何も書かない）。"""
    folder = Path(folder)
    data = _case_data(folder, case)
    today = dates.today(folder)
    resolved = [(c, _resolve_doc(data, c.doc)) for c in changes]
    for c, _name in resolved:
        if c.received is not None:
            c.received = _received_place(folder, c.received)
    current, problem = task_ledger.requests_by_case(folder)
    if problem:
        raise ToolError(problem)
    if any(c.days is not None for c in changes):  # 会社の記録に書く前に、読めるか（形が合うか）を確かめる
        from lib import company_record
        try:
            company_record.load(folder)
        except company_record.RecordError as error:
            raise ToolError(f"{error}。目安の日数を会社の記録に残せないので、期限の台帳にも書いていません") from error
    if place_problem(folder):
        raise ToolError(place_problem(folder))
    mine = list(current.get(case, []))
    facts = deadlines._company_facts(folder)
    applied = Applied(case=case)
    for c, name in resolved:
        req = task_ledger.find_request(mine, name) or task_ledger.Request(case=case, doc=name)
        is_new = task_ledger.find_request(mine, name) is None
        if c.days is not None:
            req.days = c.days
            req.days_source = _record_lead(folder, name, c.days, applied)
        elif req.days is None:
            found = deadlines.recorded_lead(facts, name)
            if found is not None and found[0]["単位"] == "日":
                req.days, req.days_source = found[0]["数"], found[1]
                applied.notes.append(f"{name}の目安の日数は、{found[1]}の {found[0]['数']}日 を使いました（聞き直していません）")
        if c.asker is not None:
            if c.asker not in task_ledger.ASKERS:
                raise ToolError(f"頼む人（{c.asker}）は、{'・'.join(task_ledger.ASKERS)} のどちらかにしてください")
            req.asker = c.asker
        if c.to is not None:
            req.to = c.to
        if c.received is not None:
            req.state, req.arrived, req.arrived_doc = task_ledger.ARRIVED, c.day or today, c.received
        if c.state is not None:
            req.state = c.state
            day = c.day or today
            if c.state in (task_ledger.REQUESTED, task_ledger.WAITING) and req.requested is None:
                req.requested = day
            if c.state == task_ledger.REQUESTED:
                req.requested = day
            if c.state == task_ledger.ARRIVED and req.arrived is None:
                req.arrived = day
            if c.state == task_ledger.NOT_YET:
                req.requested, req.arrived = None, None
        req.recorded = today.isoformat()
        try:
            task_ledger.save_request(folder, req)
        except task_ledger.TaskLedgerError as error:
            raise ToolError(str(error)) from error
        if is_new:
            mine.append(req)
        applied.lines.append(f"期限の台帳に残しました：{name}（状態：{req.state}"
                             + (f"。頼む人：{req.asker}" if req.asker else "")
                             + (f"。目安：{req.days}日" if req.days is not None else "") + "）")
    return applied


DEFAULT_SOURCE = "社長の答え"
_ISO_DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _due_source(folder: Path, raw: Optional[str]) -> str:
    """日付で示された期限の出典。会社のフォルダの中のファイル（通知の原本・入れ口の文）か「社長の答え」。"""
    text = unicodedata.normalize("NFC", (raw or "").strip()) or DEFAULT_SOURCE
    if text == DEFAULT_SOURCE:
        return text
    try:
        rel = places.relative_inside(folder, text)
    except places.PlaceError as error:
        raise ToolError(f"出典（{raw}）が会社のフォルダの外を指しています。通知の原本の場所（原本/…）を渡してください") from error
    if rel == "." or not (places.real(folder) / rel).is_file():
        raise ToolError(f"出典（{raw}）が会社のフォルダにありません。通知の原本の場所（原本/…）か「{DEFAULT_SOURCE}」を渡してください")
    return rel


def apply_dues(folder: Path, case: str, items: List[Tuple[str, str]], source: Optional[str] = None) -> Applied:
    """事務局などが日付で示した期限（差し戻しの出し直しの期限など）を、期限の台帳の作業（種類「提出」）に残す。

    items は（期限の名前、値）。値は日付（YYYY-MM-DD）か「済み」（出した）か「まだ」（済みを取り消す）。
    名前と値をすべて確かめてから書く（1つでも合わなければ何も書かない）。今日より前の日付も受け付ける（期限切れとして示す）。
    """
    folder = Path(folder)
    today = dates.today(folder)
    current, problem = task_ledger.dues_by_case(folder)
    if problem:
        raise ToolError(problem)
    mine = list(current.get(case, []))
    planned: List[task_ledger.FixedDue] = []
    for name, value in items:
        name = unicodedata.normalize("NFC", name.strip())
        if not name:
            raise ToolError("--due には「<期限の名前>=<日付>」の形で、期限の名前を渡してください")
        old = task_ledger.find_due(planned, name) or task_ledger.find_due(mine, name)
        if _ISO_DAY.match(value):
            try:
                day = date.fromisoformat(value)
            except ValueError as error:
                raise ToolError(f"{name}の日付（{value}）が、日付として正しくありません") from error
            due = task_ledger.FixedDue(case=case, name=old.name if old else name, day=day,
                                       source=_due_source(folder, source),
                                       state=old.state if old else task_ledger.NOT_YET, extra=dict(old.extra) if old else {})
        elif value in task_ledger.DUE_STATES:
            if old is None:
                raise ToolError(f"「{name}」の期限は、まだ台帳にありません。先に --due \"{name}=<日付>\" で日付を残してください")
            due = task_ledger.FixedDue(case=case, name=old.name, day=old.day, source=old.source, state=value,
                                       extra=dict(old.extra))
            if source:
                due.source = _due_source(folder, source)
        else:
            raise ToolError(f"--due の値（{value}）は、日付（2027-06-11 の形）か「{'・'.join(task_ledger.DUE_STATES)}」にしてください")
        due.recorded = today.isoformat()
        planned = [p for p in planned if not task_ledger.same_doc(p.name, due.name)] + [due]
    if place_problem(folder):
        raise ToolError(place_problem(folder))
    applied = Applied(case=case)
    for due in planned:
        try:
            previous = task_ledger.save_due(folder, due)
        except task_ledger.TaskLedgerError as error:
            raise ToolError(str(error)) from error
        fix = ""
        if previous is not None and previous.day != due.day:
            fix = f"。前に残っていた {dates.format_date(previous.day)} から直しました"
        applied.lines.append(f"期限の台帳に残しました：{due.name}の期限 {dates.format_date(due.day)}"
                             f"（状態：{due.state}。出典：{due.source}）{fix}")
    return applied


def due_rows(folder: Path, case: str) -> List[str]:
    """残した後の、その案件の日付で示された期限の一覧（開いたときの文と同じ行。済んだものを含む）。"""
    ov = deadlines.build(folder)
    tasks = [t for c in ov.cases if c.name == case for t in c.tasks if t.fixed]
    rows = [f"- {t.due.label()}｜{t.case}｜{t.what}（済み）" if t.done else status_view.task_line(t, ov.today)
            for t in sorted(tasks, key=deadlines.Task.sort_key)]
    return rows or ["- ありません"]


def requests_rows(folder: Path, case: str) -> List[str]:
    """残した後の、その案件の依頼の一覧（開いたときの文と同じ行）。"""
    ov = deadlines.build(folder)
    rows = [status_view.request_line(t, ov.today) for t in ov.requests() if t.case == case]
    return rows or ["- ありません"]


def refresh_page(folder: Path) -> str:
    """今の状態.html を作り直す。書けなかったときは、そのわけ（書けたら空）。"""
    try:
        ov = deadlines.build(folder)
        if status_view.page_wanted(folder, ov):
            return status_view.write_all(folder, ov) or ""
    except Exception as error:
        return f"{status_view.PAGE_NAME} を作れませんでした（{type(error).__name__}: {error}）"
    return ""


# ---- 一覧 ----


def show_text(folder: Path) -> Tuple[str, bool]:
    """すべての案件の期限と作業の一覧と、目安の日数を聞く依頼があるか。"""
    ov = deadlines.build(folder)
    today = ov.today
    text = status_view.deadline_text(ov)
    lines = [text, ""]
    if ov.later:
        lines.append(f"### {ov.near_days}日より先の期限")
        lines += [status_view.task_line(t, today) for t in ov.later]
    if ov.undated:
        lines += ["", "### 日付がまだ出せない期限"]
        lines += [f"- {t.case}｜{t.what}：{t.due.label()}" for t in ov.undated]
    if ov.done:
        lines += ["", "### 済んだもの"]
        lines += [status_view.task_line(t, today) for t in ov.done]
    asking = any(not t.lead and not t.done for t in ov.requests())
    return "\n".join(lines).rstrip() + "\n", asking
