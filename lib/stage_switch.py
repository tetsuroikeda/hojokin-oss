"""採択後に、次の手続きの段階へ切り替える（SPEC F12・F3・F6、DESIGN 4.5・4.7・6章・9章。TASKS M10）。

流れ（switch）：
1. 案件の制度データ（lib/seido_data.load_data）と、今の状態の組み立て（lib/deadlines.build。M3）から、今の段階を読む。
   今の段階は、段階のフォルダのうち、いちばん進んだもの（M3 と同じ決め方）。
2. 切り替える先：渡された段階のフォルダの名前（2_交付申請 など）。なければ、今の段階の次の、フォルダのある段階。
   今の段階より前の段階は断る。今の段階を渡したときは、段階は変えずに、出来事の記録と一覧だけを行う（交付決定日を残すときなど）。
   今の段階が繰り返しの報告（効果報告）で、まだ出していない回があれば、段階は進めずに次の回にする。繰り返しの報告の段階では、
   次に出す回の年のフォルダ（「4_効果報告/2年目」。中は「申請書」と「添付する書類」）も作る（B31a）。
3. 出来事の日付（採択発表日など。社長の答えか通知の原本で確かめたもの）を渡されたら、期限の台帳の「出来事」に「確定」として残す
   （lib/event_ledger.py）。名前は、制度データの手続きの段階の期限の決め方にある出来事の名前だけを受け付ける。
   今日（差し替えを含む。lib/dates.py）より後の日付は断る（通知の日付の打ち間違いと見る。仮）。
   出典が「原本/」で始まるときは、そのファイルが会社のフォルダの中にあることを確かめる。
4. 段階のフォルダを作る（lib/seido_data.make_stage_folders。中は「申請書」と「添付する書類」）。
5. 今の状態の組み立てで、切り替えた後の段階と期限を出し直し、今の状態.html を作り直す（lib/status_view）。
6. 結果：切り替えた段階の期限（日付・あと何日・決め方・もとにした日・出典）、書類の一覧（制度データの書類のうち、
   手続きにその段階の id があるもの。必須・条件付き・任意に分け、集める書類は、書類の台帳と、その段階の「添付する書類」に
   あるかを示す）、段階の注意、事前着手の注意（その段階が交付決定より前のとき）、この後の段階の期限。

書く前に、書くもの（期限の台帳と段階のフォルダ）の場所をすべて確かめ、1つでも別名があれば何も書かない（lib/places.py。DESIGN 5章）。
日付と日数は、すべてここ（とその下の lib/dates.py・lib/deadlines.py）で出す。Claude には結果の値をそのまま使わせる
（DESIGN 6章。実験 E9 の「うまくいかないときの手」と同じ形）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import case_folder, dates, deadlines, event_ledger, place_text, places, seido_data, status_view

DEFAULT_SOURCE = "社長の答え"
ORIGINALS_DIR = "原本"
DOC_GROUPS = ("必須", "条件付き", "任意")
PRE_START_WORD = "事前着手"  # してはいけないことのうち、交付決定の前に強く注意するもの（SPEC F12）
DECISION_WORD = "交付決定"   # この語を名前か id に持つ段階より前なら、事前着手の注意を添える
STAGE_ACTION = "段階のフォルダを作りません"
LEDGER_ACTION = "出来事の日付を期限の台帳に残していません"
_EVENT_ARG = re.compile(r"^\s*([^=＝]+?)\s*[=＝]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$")


class SwitchError(ValueError):
    """切り替えられない。何も書いていない。"""


@dataclass
class DocRow:
    name: str
    group: str        # 必須・条件付き・任意
    issuer: str
    kind: str         # 集める書類・様式で作る書類
    state: str        # 台帳にあり・添付する書類にあり・見当たらない・分からない・様式で作る（申請書）
    condition: str = ""
    content: str = ""
    extra: List[str] = field(default_factory=list)  # 出す人・形式・有効期限・期数


@dataclass
class Outcome:
    case: str
    data_rel: str
    title: str
    today: date
    substituted: bool
    before: str = ""
    before_folder: str = ""
    target: Dict = field(default_factory=dict)
    target_folder: str = ""
    switched: bool = False
    made: List[str] = field(default_factory=list)
    recorded: List[Tuple[event_ledger.Event, Optional[event_ledger.Event]]] = field(default_factory=list)
    status: Optional[deadlines.CaseStatus] = None
    docs: List[DocRow] = field(default_factory=list)
    unlisted: List[str] = field(default_factory=list)
    forms: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    prohibitions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    page_problem: str = ""
    show_only: bool = False
    kept_for_event: bool = False  # 今の段階の出来事の日付だけを渡されたので、段階を進めなかった
    year: int = 0  # 繰り返しの報告の段階で、次に出す回（「2」なら 4_効果報告/2年目。B31a）
    year_made: List[str] = field(default_factory=list)  # 作った年のフォルダ

    def where(self) -> str:
        """書類を置く段階のフォルダ（繰り返しの報告は年のフォルダ）。"""
        return deadlines.year_folder(self.target_folder, self.year) if self.year else self.target_folder

    def target_row(self) -> Optional[deadlines.StageRow]:
        if self.status is None:
            return None
        return next((r for r in self.status.stages if r.folder and r.folder == self.target_folder), None)

    def dated(self) -> bool:
        row = self.target_row()
        return row is not None and row.due is not None and row.due.dated


# ---- 材料を読む ----


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def parse_event(text: str) -> Tuple[str, date]:
    """「採択発表日=2027-03-10」→（「採択発表日」, 2027-03-10）。形が違えば SwitchError。"""
    m = _EVENT_ARG.match(text or "")
    if not m:
        raise SwitchError(f"出来事は「採択発表日=2027-03-10」の形で渡してください（{text}）")
    try:
        return m.group(1), date.fromisoformat(m.group(2))
    except ValueError as error:
        raise SwitchError(f"出来事の日付（{m.group(2)}）が、日付として正しくありません") from error


def _walk_rule(rule: Any, out: List[str]) -> None:
    if not isinstance(rule, dict):
        return
    kind = rule.get("種類")
    if kind == "出来事からの期間":
        name = rule.get("出来事")
        if isinstance(name, str) and event_ledger.key_of(name) and \
                all(event_ledger.key_of(n) != event_ledger.key_of(name) for n in out):
            out.append(name)
    elif kind == "早いほう":
        parts = rule.get("期限")
        for part in parts if isinstance(parts, list) else []:
            _walk_rule(part, out)


def stage_events(stage: Dict) -> List[str]:
    """1つの段階の期限の決め方にある、出来事の名前。"""
    out: List[str] = []
    node = stage.get("期限")
    _walk_rule(node.get("値") if isinstance(node, dict) else None, out)
    return out


def only_own_events(stage: Dict, events: List[str]) -> bool:
    """渡された出来事が1つ以上あり、どれもこの段階の期限の決め方にあるか（期限が出なかった後の流し直しや、日付の直し）。"""
    own = {event_ledger.key_of(n) for n in stage_events(stage)}
    names = [parse_event(text)[0] for text in events]
    return bool(names) and all(event_ledger.key_of(n) in own for n in names)


def rule_events(data: Dict) -> List[str]:
    """制度データの手続きの段階の期限の決め方にある、出来事の名前（段階の順）。"""
    out: List[str] = []
    for stage in deadlines._stages(data):
        node = stage.get("期限")
        _walk_rule(node.get("値") if isinstance(node, dict) else None, out)
    return out


def next_year(folder: Path, case: str, stage: Dict, stage_folder: str) -> int:
    """繰り返しの報告の段階で、次に出す回（提出版のない、いちばん前の回）。繰り返しでないか、すべて出したら 0。"""
    rule = deadlines.repeat_rule(stage)
    count = rule.get("回数") if rule is not None else None
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return 0
    entries, _problem = deadlines._submissions(folder)
    sent = {nfc(str(e.get("段階") or "")).strip().strip("/") for e in entries if nfc(str(e.get("案件") or "")) == nfc(case)}
    return next((n for n in range(1, count + 1) if deadlines.year_folder(stage_folder, n) not in sent), 0)


def _case_of(ov: deadlines.Overview, case: str) -> Optional[deadlines.CaseStatus]:
    return next((c for c in ov.cases if c.name == nfc(case)), None)


def _valued(node: Any) -> str:
    """出典つき値を「値（出典）」の文にする。読み取れないときは、そう書く。"""
    if not isinstance(node, dict):
        return ""
    value = node.get("値")
    if value is None:
        reason = str(node.get("理由") or "").strip()
        text = f"資料から読み取れませんでした（{reason}）" if reason else "資料から読み取れませんでした"
    elif isinstance(value, dict) and "数" in value and "単位" in value:  # 有効期限（「発行」から3か月）など
        head = f"{value.get('出来事')}から" if value.get("出来事") else ""
        text = f"{head}{value.get('数')}{value.get('単位')}"
    else:
        text = value if isinstance(value, str) else str(value)
    sources = "、".join(deadlines.source_text(node))
    if sources:
        text += f"（{sources}）"
    if node.get("状態") in deadlines.CHECK_STATES:
        text = "【要確認】" + text
    return text


def _check_source(folder: Path, source: str) -> str:
    text = (source or "").strip() or DEFAULT_SOURCE
    if nfc(text).startswith(ORIGINALS_DIR + "/"):
        try:
            path = places.actual(folder, text)
        except places.PlaceError as error:
            raise SwitchError(f"出典の場所（{text}）が、会社のフォルダからの場所として正しくありません（{error}）") from error
        if path is None or not path.is_file() or not places.is_inside(folder, path):
            raise SwitchError(f"出典の原本（{text}）が見つかりません。通知の原本の場所（原本/役所からの通知/…）を確かめてください")
    return text


# ---- 書類の一覧 ----


def doc_rows(folder: Path, case: str, data: Dict, stage: Dict, target_folder: str) -> Tuple[List[DocRow], List[str]]:
    """段階の書類の一覧と、段階の「書類」に名前があるのに制度データの書類にないもの。"""
    stage_id = stage.get("id")
    kinds, _problem = deadlines._ledger_kinds(folder)
    attached = deadlines._list_files(folder, f"{deadlines.CASES_DIR}/{nfc(case)}/{target_folder}/{deadlines.ATTACH_DIR}") \
        if target_folder else []
    rows: List[DocRow] = []
    docs = data.get("書類")
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict) or not isinstance(doc.get("名前"), str):
            continue
        uses = doc.get("手続き")
        if not isinstance(uses, list) or stage_id not in uses:
            continue
        name = doc["名前"]
        group = doc.get("区分") if doc.get("区分") in DOC_GROUPS else "条件付き"
        if deadlines._is_form(doc, stage, data):
            kind, state = "様式で作る書類", "様式で作る（申請書）"
        else:
            kind = "集める書類"
            if kinds is not None and any(deadlines.names_match(name, k) for k in kinds):
                state = "台帳にあり"
            elif any(deadlines.names_match(name, f) for f in attached):
                state = "添付する書類にあり"
            elif kinds is None:
                state = "分からない"
            else:
                state = "見当たらない"
        extra = []
        if doc.get("出す人"):
            extra.append(f"出す人：{doc['出す人']}")
        if doc.get("形式"):
            extra.append(f"形式：{doc['形式']}")
        for key in ("有効期限", "期数"):
            if isinstance(doc.get(key), dict):
                extra.append(f"{key}：{_valued(doc[key])}")
        rows.append(DocRow(name=name, group=group, issuer=str(doc.get("発行元") or ""), kind=kind, state=state,
                           condition=_valued(doc.get("条件")), content=_valued(doc.get("内容")), extra=extra))
    rows.sort(key=lambda r: DOC_GROUPS.index(r.group))
    listed = stage.get("書類")
    unlisted = [n for n in listed if isinstance(n, str) and not any(deadlines.names_match(n, r.name) for r in rows)] \
        if isinstance(listed, list) else []
    return rows, unlisted


def _cautions(stage: Dict) -> List[str]:
    notes = stage.get("注意")
    return [_valued(n) for n in notes if isinstance(n, dict) and n.get("値") is not None] \
        if isinstance(notes, list) else []


def _before_decision(data: Dict, stage: Dict) -> bool:
    """この段階の後に、交付決定の段階があるか（まだ交付決定の前か）。"""
    order = deadlines._int(stage.get("順番"))
    for s in deadlines._stages(data):
        words = f"{s.get('id') or ''}{s.get('名前') or ''}"
        if DECISION_WORD in words and deadlines._int(s.get("順番")) > order:
            return True
    return False


def _prohibitions(data: Dict) -> List[str]:
    found = []
    items = data.get("してはいけないこと")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("内容")
        words = f"{item.get('名前') or ''}{content.get('値') if isinstance(content, dict) else ''}"
        if PRE_START_WORD in words:
            found.append(f"{item.get('名前')}：{_valued(content)}")
    return found


# ---- 切り替える ----


def switch(folder: Path, case: str, stage: Optional[str] = None, events: Optional[List[str]] = None,
           source: Optional[str] = None, show_only: bool = False) -> Outcome:
    """次の段階へ切り替える（show_only なら書かずに、今の段階か渡された段階の一覧と期限だけを出す）。

    切り替えられないときは SwitchError（何も書いていない）。今日の日付の差し替えが読めないときは ValueError。
    """
    folder = Path(folder)
    case = nfc(case)
    events = list(events or [])
    if show_only and events:
        raise SwitchError("一覧を見るだけのときは、出来事の日付を渡せません（日付を残すときは、--show を付けずに流してください）")
    try:
        path, data = seido_data.load_data(folder, case)
    except (seido_data.DataMissing, seido_data.MergeError) as error:
        raise SwitchError(str(error)) from error
    if not isinstance(data, dict):
        raise SwitchError("制度データの形が違います。junbi の道具（seido_data.py --check）で確かめてください")
    today = dates.today(folder)
    substituted = dates.substituted_today(folder) is not None
    before = _case_of(deadlines.build(folder, today=today), case)
    if before is None:
        raise SwitchError(f"案件のフォルダ（{deadlines.CASES_DIR}/{case}/）がありません。先に公式資料を取り、案件のフォルダを作ってください")
    if before.problem:
        raise SwitchError(before.problem)

    stages = [s for s in deadlines._stages(data) if deadlines._folder_of(s)]
    folders = [deadlines._folder_of(s) for s in stages]
    if not folders:
        raise SwitchError("制度データの手続きの段階に、フォルダの名前（1_申請 など）のある段階がありません")
    numbering = seido_data.numbering_problems(folders)
    if numbering:
        raise SwitchError("段階のフォルダの名前が、書類を出す段階を順に数えた「1_申請」「2_交付申請」…の形になっていません"
                          f"（{'。'.join(numbering)}）。手続きの段階を読み取り役に読ませ直してください")
    current = folders.index(before.current_folder) if before.current_folder in folders else 0
    kept_for_event = False
    if stage:
        wanted = nfc(stage.strip())
        if wanted not in folders:
            raise SwitchError(f"手続きの段階にないフォルダの名前です：{wanted}（段階のフォルダは {'・'.join(folders)}）")
        index = folders.index(wanted)
        if index < current:
            raise SwitchError(f"今の段階（{folders[current]}）より前の段階（{wanted}）には切り替えません")
    elif show_only:
        index = current
    elif before.current_folder in folders and only_own_events(stages[current], events):
        # 今の段階の期限を出すための日付を渡し直しただけなので、段階は進めない（進めると前の段階へは戻れない）
        index = current
        kept_for_event = True
    elif before.current_folder in folders and next_year(folder, case, stages[current], folders[current]):
        # 繰り返しの報告の段階で、まだ出していない回がある（1年目を出したら、次は2年目。B31a）
        index = current
    else:
        index = current + 1
        if index >= len(folders):
            raise SwitchError(f"今の段階（{folders[current]}）が、フォルダのある最後の段階です。次に切り替える段階はありません")
    target, target_folder = stages[index], folders[index]

    out = Outcome(case=case, data_rel=path.relative_to(folder).as_posix(), title=before.title, today=today,
                  substituted=substituted, before=before.current, before_folder=before.current_folder,
                  target=target, target_folder=target_folder, show_only=show_only, kept_for_event=kept_for_event,
                  year=next_year(folder, case, target, target_folder))

    # 出来事：名前と日付と出典を、書く前にすべて確かめる
    planned: List[event_ledger.Event] = []
    known = rule_events(data)
    for text in events:
        name, day = parse_event(text)
        match = next((k for k in known if event_ledger.key_of(k) == event_ledger.key_of(name)), None)
        if match is None:
            raise SwitchError(f"制度データの期限の決め方にない出来事です：{name}"
                              f"（使える出来事：{'・'.join(known) if known else 'ありません'}）")
        if day > today:
            raise SwitchError(f"{match}（{dates.format_date(day)}）が、今日（{dates.format_date(today)}）より後です。"
                              "通知の日付と、今日の日付の差し替え（.hojokin/設定.json の「今日の日付」）を確かめてください")
        planned.append(event_ledger.Event(case=case, name=match, day=day, state=event_ledger.CONFIRMED,
                                          source=_check_source(folder, source or ""), recorded=today.isoformat()))

    if not show_only:
        # 書く先の場所を、書く前にすべて確かめる（1つでも別名があれば、何も書かない）
        if planned:
            problem = place_text.write_problem(folder, event_ledger.LEDGER_FILE, LEDGER_ACTION)
            if problem:
                raise SwitchError(problem)
            try:
                event_ledger.load(folder)
            except event_ledger.LedgerError as error:
                raise SwitchError(f"{error}。{LEDGER_ACTION}") from error
        rel_case = f"{case_folder.CASES_DIR}/{case_folder.safe_name(case)}"
        for sub in case_folder.STAGE_SUBDIRS:
            problem = place_text.write_problem(folder, f"{rel_case}/{target_folder}/{sub}", STAGE_ACTION)
            if not problem and out.year:
                problem = place_text.write_problem(folder, f"{rel_case}/{out.where()}/{sub}", STAGE_ACTION)
            if problem:
                raise SwitchError(problem)
        # 書く
        for event in planned:
            try:
                out.recorded.append((event, event_ledger.record(folder, event)))
            except event_ledger.LedgerError as error:
                raise SwitchError(str(error)) from error
        try:
            out.made, _wanted = seido_data.make_stage_folders(folder, case, data, only=[target_folder])
        except case_folder.CaseError as error:
            raise SwitchError(str(error)) from error
        if out.year:
            base = case_folder.case_dir(folder, case) / out.where()
            for path in [base] + [base / sub for sub in case_folder.STAGE_SUBDIRS]:
                if not path.is_dir():
                    path.mkdir(parents=True)
                    out.year_made.append(path.relative_to(folder).as_posix())
        out.switched = index != current or not before.current_folder

    ov = deadlines.build(folder, today=today)
    out.status = _case_of(ov, case)
    if not show_only and status_view.page_wanted(folder, ov):
        try:
            out.page_problem = status_view.write_page(folder, status_view.render_page(ov, nfc(folder.name))) or ""
        except Exception as error:  # 画面が作れなくても、切り替えは済んでいる
            out.page_problem = f"{status_view.PAGE_NAME} を作れませんでした（{type(error).__name__}: {error}）"

    out.docs, out.unlisted = doc_rows(folder, case, data, target, out.where())
    out.forms = [f for f in target.get("様式") or [] if isinstance(f, str)] if isinstance(target.get("様式"), list) else []
    out.cautions = _cautions(target)
    if _before_decision(data, target):
        out.prohibitions = _prohibitions(data)
    out.notes = _notes(before, out, data)
    return out


def _notes(before: deadlines.CaseStatus, out: Outcome, data: Dict) -> List[str]:
    notes = []
    if out.switched and before.current_folder:
        row = next((r for r in before.stages if r.folder == before.current_folder), None)
        if row is not None and row.due is not None and row.due.dated and row.due.last >= out.today:
            notes.append(f"今日（{dates.format_date(out.today)}）は、前の段階（{before.current}）の期限"
                         f"（{row.due.label()}）より前です。日付の差し替え（.hojokin/設定.json の「今日の日付」）が"
                         "合っているかを確かめてください")
        if not before.submitted:
            notes.append(f"前の段階（{before.current_folder}）の提出版が記録されていません。提出したときの申請書を、"
                         "差し戻しや実績報告で照らせるように、kiroku の「提出した」で残せます")
    seido = data.get("制度") if isinstance(data.get("制度"), dict) else {}
    data_round = deadlines.round_of(seido.get("公募回"))
    case_round = deadlines.round_of(out.case)
    if data_round is not None and case_round is not None and data_round != case_round:
        notes.append(f"制度データは第{data_round}回の資料から作ったもので、この案件は第{case_round}回です。"
                     f"第{case_round}回の交付申請の手引きなどが出たら、公式資料を取り直して、期限と書類を確かめてください")
    if out.status is not None:
        notes += out.status.notes
    return notes


# ---- 結果の文 ----


def _due_line(row: deadlines.StageRow, today: date) -> str:
    d = row.due
    if d is None:
        return "制度データに期限がありません"
    days = d.days_text(today)
    text = d.label() + (f"（{days}）" if days else "")
    if d.strong(today):
        text += status_view.STRONG_MARK
    return text


def _undated_hint(rule: Any) -> str:
    """期限の日付が出せないときに、次にすること。決め方に出来事があるときだけ、その日付を渡し直すよう促す。"""
    value = rule.get("値") if isinstance(rule, dict) else None
    events: List[str] = []
    _walk_rule(value, events)
    if events:
        return ("期限の日付はまだ出せません。決め方にある出来事（" + "・".join(events) + "）の日付を、通知の原本の日付か社長の答えで"
                "確かめて、--event で渡し直してください（推測で日付を入れない）")
    if isinstance(value, dict) and value.get("種類") == "繰り返し":
        return "毎年の期限は、事業の完了と決算の月が分かってから出します（期限の台帳で扱います）"
    return "制度データに、この段階の期限の決め方がありません。資料を確かめ、なければ事務局への問い合わせ文の案を作ってください"


def report(out: Outcome) -> str:
    today_text = dates.format_date(out.today) + ("（日付を差し替えています）" if out.substituted else "")
    name = str(out.target.get("名前") or out.target_folder)
    if out.year:
        name += f"（{out.year}{deadlines.YEAR_WORD}）"
    if out.show_only:
        head = f"{name}の書類の一覧と期限です（案件：{out.case}。何も書いていません）。"
    elif out.switched:
        head = f"採択後の次の段階「{name}」へ切り替えました（案件：{out.case}）。"
    else:
        head = f"今の段階「{name}」のままです（案件：{out.case}）。"
    lines = [head, "",
             f"- 今日：{today_text}。日時は日本時間。日付と日数は、この結果の値をそのまま使ってください（頭で計算し直さない）",
             f"- 制度データ：{out.data_rel}（{out.title}）"]
    for event, previous in out.recorded:
        fix = f"。前に残っていた {dates.format_date(previous.day)} から直しました" if previous and previous.day != event.day else ""
        lines.append(f"- 期限の台帳（{event_ledger.LEDGER_FILE}）に残した出来事：{event.name} {dates.format_date(event.day)}"
                     f"（{event.state}。出典：{event.source}）{fix}")
    if out.switched:
        lines.append(f"- 段階：{out.before or '（まだありません）'} → {name}（今の段階）")
    elif out.kept_for_event:
        lines.append("- 渡した出来事は、今の段階の期限の決め方にあるので、段階は進めていません"
                     "（次の段階へ進めるときは、その段階を --stage で渡す）")
    if not out.show_only:
        where = f"{deadlines.CASES_DIR}/{out.case}/{out.target_folder}/"
        if out.made:
            lines.append(f"- 段階のフォルダを作りました：{where}（中は「申請書」と「添付する書類」）")
        else:
            lines.append(f"- 段階のフォルダは、もうあります：{where}")
        if out.year:
            year_where = f"{deadlines.CASES_DIR}/{out.case}/{out.where()}/"
            lines.append(f"- {out.year}{deadlines.YEAR_WORD}の書類は {year_where} に置きます"
                         + ("（作りました。中は「申請書」と「添付する書類」）" if out.year_made else "（もうあります）"))
    if out.page_problem:
        lines.append(f"- {out.page_problem}")

    lines += ["", f"## {name}の期限", ""]
    row = out.target_row()
    rule = out.target.get("期限")
    if row is None:
        lines.append("- 今の状態の組み立てに、この段階が見つかりませんでした")
    else:
        lines.append(f"- {_due_line(row, out.today)}")
        d = row.due
        if d is not None and d.basis:
            lines.append(f"- もとにした日：{'、'.join(d.basis)}")
        if d is not None and d.sources:
            lines.append(f"- 出典：{'、'.join(d.sources)}")
        if isinstance(rule, dict) and isinstance(rule.get("注記"), str):
            lines.append(f"- 制度データの注記：{rule['注記']}")
        if d is not None and not d.dated:
            lines.append(f"- {_undated_hint(rule)}")
        if row.years:
            lines.append("- 回ごとの期限（5年先までの期限。提出版を記録した回は済み）：")
            for y in row.years:
                mark = "（提出済み）" if y.submitted else ("（次に出す回）" if y.number == row.next_year else "")
                days = "" if y.submitted else y.due.days_text(out.today)
                lines.append(f"  - {y.number}{deadlines.YEAR_WORD}：{y.due.label()}" + (f"（{days}）" if days else "") + mark)
    start = out.target.get("始まる条件")
    if isinstance(start, dict):
        lines.append(f"- 始まる条件：{_valued(start)}")
    if out.target.get("画面"):
        lines.append(f"- 出す所：{out.target['画面']}")

    lines += ["", f"## {name}の書類（制度データの書類のうち、手続きが「{out.target.get('id')}」のもの。{len(out.docs)}件）"]
    for group in DOC_GROUPS:
        rows = [r for r in out.docs if r.group == group]
        title = f"{group}（{len(rows)}件）" + ("。条件に当たるときだけ出す" if group == "条件付き" else "")
        lines += ["", f"### {title}"]
        if not rows:
            lines.append("- ありません")
            continue
        for r in rows:
            parts = [r.name, r.issuer or "発行元の記載なし", r.kind, r.state]
            text = "- " + "｜".join(parts)
            details = []
            if r.condition:
                details.append(f"条件：{r.condition}")
            if r.content:
                details.append(f"内容：{r.content}")
            details += r.extra
            if details:
                text += "。" + "。".join(details)
            lines.append(text)
    lines.append("")
    if out.unlisted:
        lines.append(f"- 段階の書類の名前のうち、制度データの書類の一覧にないもの：{'、'.join(out.unlisted)}"
                     "（読み取り役に、書類の章を読ませ直して確かめる）")
    if out.forms:
        lines.append(f"- この段階の様式：{'、'.join(out.forms)}")
    lines.append("- 「台帳にあり」は、書類の台帳に同じ種類の原本があるということです。期数・有効期限・中身は、書類の確かめ（shorui）で見ます")

    if out.prohibitions:
        lines += ["", "## 特に注意（交付決定の前）", ""]
        lines += [f"- {p}" for p in out.prohibitions]
    if out.cautions:
        lines += ["", f"## {name}の注意（制度データから）", ""]
        lines += [f"- {c}" for c in out.cautions]

    if out.status is not None:
        later = [r for r in out.status.stages if r.order > deadlines._int(out.target.get("順番")) and r.due is not None]
        if later:
            lines += ["", "## この後の段階の期限（今の状態の組み立てから）", ""]
            for r in later:
                cond = "（必要なときだけ）" if r.conditional else ""
                text = f"- {r.name}{cond}：{_due_line(r, out.today)}"
                if r.due is not None and r.due.basis:
                    text += f"。もとにした日：{'、'.join(r.due.basis)}"
                lines.append(text)
    if out.notes:
        lines += ["", "## 知らせること", ""]
        lines += [f"- {n}" for n in out.notes]
    return "\n".join(lines) + "\n"


__all__ = ["DocRow", "Outcome", "SwitchError", "doc_rows", "parse_event", "report", "rule_events", "switch"]
