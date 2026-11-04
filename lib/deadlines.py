"""開いたときに示す期限と作業の組み立て（SPEC F6・T6-1、DESIGN 4.6・4.7 の3・6章。TASKS M3）。

期限の台帳（`記録/期限の台帳.json`）は K1 で足す。それまでは、案件ごとに次のものから組み立てる（仮。TASKS M3）。
- 制度データ（`記録/制度データ/<略称>_<公募回>.json`。lib/seido_data.load_data）の「手続きの段階」の期限の決め方と、
  「決まった期日」
- 会社のフォルダの書類：案件の段階のフォルダ（どこまで進んだか）、提出版の一覧（`記録/提出版.json`。済んだ段階）、
  書類の台帳（`記録/書類の台帳.json`。集まった原本の種類）と、段階のフォルダの「添付する書類」

作業（Task）
- 期限の決め方を持つ手続きの段階を、1つの作業（「<段階>の期限」）にする。期限の決め方のない段階（採択発表など）は
  出来事なので、作業にしない。
- 済んだ段階は出さない。段階のフォルダのうちいちばん進んだもの（今の段階）より前の段階は済んだものとし、
  今の段階は、提出版が記録されていれば済んだものとする（仮）。段階のフォルダがまだなければ、いちばん前の
  フォルダのある段階（申請）を今の段階とする。
- 今の段階の作業には、集める必須の書類（様式で作る書類を除く）のうち、書類の台帳と「添付する書類」に
  見当たらないものを添える。名前の見比べは、【】・括弧の中・空白を除いた形で、同じか、一方が他方で始まるか（仮）。

期限の日付（Due）
- 決まった日付：その日（と時刻）。
- 出来事からの期間：出来事の日付を、期限の台帳の「出来事」（`記録/期限の台帳.json`。lib/event_ledger.py。社長の答えか
  通知の原本で確かめて、採択後の切り替えの道具が残したもの。M10）から先に取り、なければ制度データの「決まった期日」から取る
  （名前に出来事の名前を含むもの）。予定の日付から出した期限は「見込み」、台帳の「確定」の日付から出した期限は見込みとしない。
  台帳の日付を使った期限には、もとにした日（basis）を添える。出来事の日付が分からなければ、日付を出さずに決め方を示す
  （見込みと確定の計算し直しの全体は、K1 の期限の台帳で作る）。
  か月・年は、同じ日の数字の日（応当日）。その日がない月は、その月の終わりの日にする（仮）。
- 早いほう：日付の分かるもののうち早いほう。分からないものがあれば「遅くとも」その日（上限）とする。
- 繰り返し（効果報告など）：事業の完了と決算の月が要るので、M3 では日付を出さない（K1）。
- 申請の段階（いちばん前の、フォルダのある段階）は、「決まった期日」のうち、名前に案件の回と締切を含むものを先に使う。
  制度データは直近回の資料で作ることがあり（M2c）、段階の期限が前の回の締切や「読み取れない」になっていることがあるため（仮）。
- 決まった期日の名前に公募回があるものは、案件の回のものだけを使う。名前に公募回がないものは、制度データの回と
  案件の回が同じときだけ使う（前の回の日付で、期限切れなどと示さないため）。
- 日が決まっていない期日（「12月下旬」）から出した期限は見込みとし、旬のはじめの日で並べて近い締切に入れ
  （早めに気づくため）、旬の終わりの日を過ぎてから期限切れにする（仮）。

分け方（classify）。示す順は、期限切れ・今日やること・近い締切・遅れている作業（DESIGN 4.6）
- 期限切れ：期限の日（旬なら終わりの日）が今日より前。いちばん上に分けて示す。
- 今日やること：期限が今日か、始める日が今日。
- 遅れている作業：始める日（逆算した、依頼する日など）が今日より前で、期限はまだ。始める日は K1・K2 の期限の台帳が
  持つ（M3 の作業には始める日がないので、M3 ではいつも空）。
- 近い締切：期限が今日から N 日以内（はじめは30日。7日以内は強めて示す）。日数を変える設定は K1。
- それぞれの中は締切順（同じ日なら、案件の名前、段階の順）。どれにも入らないものは、N 日より先（later）と、
  日付がまだ出せないもの（undated）に分ける。

hook（SessionStart）から呼ぶので、標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
会社のフォルダの中を読むときは、場所の確かめを lib/places.py（と、その文の lib/place_text.py）で行う。
"""

from __future__ import annotations

import calendar
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lib import dates, event_ledger, place_text, places

NEAR_DAYS = 30  # 近い締切の日数のはじめの値（SPEC F6。経営者・担当者が変える設定は K1）
STRONG_DAYS = 7  # この日数の内の期限は強めて示す（SPEC F6）

OVERDUE = "期限切れ"
TODAY = "今日やること"
NEAR = "近い締切"
LATE = "遅れている作業"
GROUPS = (OVERDUE, TODAY, NEAR, LATE)  # 示す順（DESIGN 4.6）

CASES_DIR = "案件"  # lib/case_folder.py の CASES_DIR と同じ
ATTACH_DIR = "添付する書類"  # lib/case_folder.py の STAGE_SUBDIRS
SUBMISSIONS_FILE = "記録/提出版.json"  # lib/submission.py の RECORD_FILE と同じ
REQUIRED = "必須"
CHECK_STATES = ("要確認", "資料で食い違い")
UNREADABLE = "読み取れない"
TEN_DAYS = {"上旬": (1, 10), "中旬": (11, 20), "下旬": (21, 31)}
# 決まった期日のうち、申請の締切とみなす名前（「依頼」を含むものは、依頼の締切なので除く。仮）
DEADLINE_WORDS = ("締切", "締め切り", "〆切")
NOT_APPLICATION_WORDS = ("依頼",)
APPLICATION_WORDS = ("公募", "申請", "応募")
NOTE_NAMES_MAX = 5  # 作業に添える、見当たらない書類の名前の数
REMEDY_MAX = 2  # 期限切れに添える手の数

_ROUND = re.compile(r"第\s*([0-9]+)\s*回")
_POINT = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:T([0-9]{2}):([0-9]{2}))?")
_STAGE_FOLDER = re.compile(r"^[0-9]+_[^/\\]+$")
_BRACKETS = re.compile(r"【[^】]*】|（[^）]*）|\([^)]*\)|〔[^〕]*〕")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def round_of(text: Any) -> Optional[int]:
    """「第9回」の 9。なければ None。"""
    if not isinstance(text, str):
        return None
    m = _ROUND.search(unicodedata.normalize("NFKC", text))
    return int(m.group(1)) if m else None


def rounds_in(text: str) -> List[int]:
    return [int(n) for n in _ROUND.findall(unicodedata.normalize("NFKC", text))]


# ---- 期限の日付 ----


@dataclass
class Due:
    """1つの期限の日付。日付が出せないときは first が None で、how に決め方を書く。"""

    first: Optional[date] = None  # 並べる日・あと何日を数える日
    last: Optional[date] = None  # 期限切れかを決める日（日が決まっていれば first と同じ）
    time: str = ""  # 時刻（「17:00」）。分かるときだけ
    estimate: bool = False  # 見込み（予定の日付から出した）
    bound: bool = False  # 遅くとも（早いほうの一部の日付が分からない）
    span: str = ""  # 日が決まっていないときの文（「2026年12月下旬」）
    how: str = ""  # 日付を出せないときの決め方の文
    check: bool = False  # 制度データで「要確認」か「資料で食い違い」
    sources: List[str] = field(default_factory=list)  # 出典（「要領8 p.26」）
    basis: List[str] = field(default_factory=list)  # もとにした出来事の日付（期限の台帳のもの。「採択発表日 2027年3月10日（水）（確定。…）」）

    @property
    def dated(self) -> bool:
        return self.first is not None and self.last is not None

    def label(self) -> str:
        """社長に見せる日付の文。例：2026年10月16日（金）17:00、遅くとも 2028年11月16日（木）（見込み）"""
        if not self.dated:
            head = "日付はまだ出せません"
            return f"{head}（{self.how}）" if self.how else head
        if self.span:
            text = f"{self.span}（日はまだ決まっていません）"
        elif self.first != self.last:
            text = f"{dates.format_date(self.first)}〜{dates.format_date(self.last)}のどこか"
        else:
            text = dates.format_date(self.first) + self.time
        if self.bound:
            text = f"遅くとも {text}"
        if self.estimate:
            text += "（見込み）"
        if self.check:
            text = "【要確認】" + text
        return text

    def days_text(self, today: date) -> str:
        """あと何日（過ぎた日数）の文。"""
        if not self.dated:
            return ""
        if self.last < today:
            return f"{(today - self.last).days}日過ぎています"
        if self.first <= today < self.last:
            return "今がその時期です"
        days = (self.first - today).days
        return "今日まで" if days == 0 else f"あと{days}日"

    def strong(self, today: date) -> bool:
        """強めて示すか（今日から7日以内）。"""
        return self.dated and self.last >= today and (self.first - today).days <= STRONG_DAYS


def parse_point(text: Any) -> Tuple[Optional[date], str]:
    """「2026-10-16T17:00+09:00」→ (2026-10-16, "17:00")、「2026-10-16」→ (2026-10-16, "")。読めなければ (None, "")。"""
    if not isinstance(text, str):
        return None, ""
    m = _POINT.match(text.strip())
    if not m:
        return None, ""
    try:
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None, ""
    time = f"{int(m.group(4))}:{m.group(5)}" if m.group(4) else ""
    return day, time


def month_span(year_month: Any, part: Any) -> Optional[Tuple[date, date, str]]:
    """「2026-12」と「下旬」→ (2026-12-21, 2026-12-31, "2026年12月下旬")。旬がなければ月のはじめから終わり。"""
    if not isinstance(year_month, str):
        return None
    m = re.match(r"^([0-9]{4})-([0-9]{2})$", year_month.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    end = calendar.monthrange(year, month)[1]
    first_day, last_day = TEN_DAYS.get(part, (1, end)) if isinstance(part, str) else (1, end)
    label = f"{year}年{month}月" + (part if isinstance(part, str) and part in TEN_DAYS else "")
    return date(year, month, first_day), date(year, month, min(last_day, end)), label


def add_period(day: date, period: Any) -> Optional[date]:
    """day から期間（{"数": 2, "単位": "か月"}）だけ後の日。か月・年は応当日、その日がない月は月の終わりの日（仮）。"""
    if not isinstance(period, dict):
        return None
    n, unit = period.get("数"), period.get("単位")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return None
    if unit == "日":
        return day + timedelta(days=n)
    if unit in ("か月", "年"):
        months = n if unit == "か月" else n * 12
        year, index = divmod(day.month - 1 + months, 12)
        year += day.year
        month = index + 1
        return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    return None


def period_text(period: Any) -> str:
    if isinstance(period, dict):
        return f"{period.get('数')}{period.get('単位')}"
    return "（期間が読めません）"


def source_text(node: Any) -> List[str]:
    """出典つきの値の出典を「資料 p.ページ」の並びにする。"""
    found: List[str] = []
    sources = node.get("出典") if isinstance(node, dict) else None
    for s in sources if isinstance(sources, list) else []:
        if not isinstance(s, dict):
            continue
        doc = str(s.get("資料") or "").strip()
        if not doc:
            continue
        page, end = s.get("ページ"), s.get("終わりのページ")
        if isinstance(page, int) and not isinstance(page, bool):
            doc += f" p.{page}"
            if isinstance(end, int) and not isinstance(end, bool) and end != page:
                doc += f"–{end}"
        if doc not in found:
            found.append(doc)
    return found


class Plan:
    """1つの案件の制度データから、期限の日付を出す。"""

    def __init__(self, data: Dict, case_round: Optional[int],
                 events: Optional[Sequence[event_ledger.Event]] = None) -> None:
        self.data = data if isinstance(data, dict) else {}
        seido = self.data.get("制度") if isinstance(self.data.get("制度"), dict) else {}
        self.data_round = round_of(seido.get("公募回"))
        self.case_round = case_round
        fixed = self.data.get("決まった期日")
        self.fixed = [e for e in fixed if isinstance(e, dict) and isinstance(e.get("名前"), str)] \
            if isinstance(fixed, list) else []
        self.events = list(events or [])  # 期限の台帳の、この案件の出来事（lib/event_ledger.py）

    def ledger_due(self, event: Any) -> Optional[Due]:
        """出来事の日付を、期限の台帳から取る。なければ None。"""
        found = event_ledger.find(self.events, event) if isinstance(event, str) else None
        if found is None:
            return None
        source = f"。出典：{found.source}" if found.source else ""
        basis = f"{found.name} {dates.format_date(found.day)}（{found.state}{source}）"
        return Due(first=found.day, last=found.day, estimate=found.state != event_ledger.CONFIRMED, basis=[basis])

    # ---- 決まった期日 ----

    def round_ok(self, name: str) -> bool:
        """決まった期日の名前が、案件の回のものか（名前に回がなければ、制度データの回が案件の回と同じときだけ）。"""
        if self.case_round is None:
            return True
        found = rounds_in(name)
        if found:
            return self.case_round in found
        return self.data_round is None or self.data_round == self.case_round

    def fixed_due(self, entry: Dict) -> Optional[Due]:
        """決まった期日の1件の日付。値がなければ None。"""
        node = entry.get("日時")
        value = node.get("値") if isinstance(node, dict) else None
        if not isinstance(value, dict):
            return None
        note = str(entry.get("注記") or "")
        estimate = "予定" in note
        check = isinstance(node, dict) and node.get("状態") in CHECK_STATES
        sources = source_text(node)
        if "日時" in value:
            day, time = parse_point(value.get("日時"))
            if day is None:
                return None
            return Due(first=day, last=day, time=time, estimate=estimate, check=check, sources=sources)
        if "年月" in value:
            span = month_span(value.get("年月"), value.get("旬"))
            if span is None:
                return None
            first, last, label = span
            return Due(first=first, last=last, span=label, estimate=True, check=check, sources=sources)
        return None

    def event_due(self, event: Any) -> Optional[Due]:
        """出来事（「採択発表日」など）の日付を、決まった期日から取る。分からなければ None。"""
        if not isinstance(event, str) or not event.strip():
            return None
        key = unicodedata.normalize("NFKC", event).strip().rstrip("日")
        if not key:
            return None
        recorded = self.ledger_due(event)  # 社長に確かめて残した日付を、制度データの予定より先に使う
        if recorded is not None:
            return recorded
        for entry in self.fixed:
            name = unicodedata.normalize("NFKC", entry["名前"])
            if key in name and self.round_ok(entry["名前"]):
                due = self.fixed_due(entry)
                if due is not None:
                    return due
        return None

    def application_fixed(self, explicit_only: bool) -> Optional[Tuple[Due, str]]:
        """申請の締切とみなす決まった期日（日付と名前）。explicit_only なら、名前に案件の回があるものだけ。"""
        candidates = []
        for entry in self.fixed:
            name = entry["名前"]
            if not any(w in name for w in DEADLINE_WORDS) or any(w in name for w in NOT_APPLICATION_WORDS):
                continue
            if not self.round_ok(name):
                continue
            explicit = self.case_round is not None and self.case_round in rounds_in(name)
            if explicit_only and not explicit:
                continue
            rank = 0 if any(w in name for w in APPLICATION_WORDS) else 1
            candidates.append((rank, entry))
        for _rank, entry in sorted(candidates, key=lambda c: c[0]):
            due = self.fixed_due(entry)
            if due is not None:
                return due, entry["名前"]
        return None

    # ---- 期限の決め方 ----

    def compute(self, rule: Any) -> Due:
        """期限の決め方（DESIGN 9章。決まった日付／出来事からの期間／早いほう／繰り返し）から、日付を出す。"""
        if not isinstance(rule, dict):
            return Due(how="期限の決め方が読めません")
        kind = rule.get("種類")
        if kind == "決まった日付":
            day, time = parse_point(rule.get("日時"))
            if day is None:
                return Due(how=f"日付（{rule.get('日時')}）が読めません")
            return Due(first=day, last=day, time=time)
        if kind == "出来事からの期間":
            event = rule.get("出来事")
            text = f"「{event}」から{period_text(rule.get('期間'))}"
            base = self.event_due(event)
            if base is None:
                return Due(how=f"{text}。「{event}」の日付が分かってから出します")
            first = add_period(base.first, rule.get("期間"))
            last = add_period(base.last, rule.get("期間"))
            if first is None or last is None:
                return Due(how=f"{text}（期間が読めません）")
            return Due(first=first, last=last, estimate=base.estimate or base.first != base.last,
                       check=base.check, sources=list(base.sources), basis=list(base.basis))
        if kind == "早いほう":
            parts = [self.compute(r) for r in rule.get("期限") or []] if isinstance(rule.get("期限"), list) else []
            known = [p for p in parts if p.dated]
            unknown = [p for p in parts if not p.dated]
            if not known:
                hows = "／".join(p.how for p in parts if p.how)
                return Due(how=f"次の早いほう：{hows}" if hows else "期限の決め方が読めません")
            first = min(p.first for p in known)
            last = min(p.last for p in known)
            times = {p.time for p in known if p.first == first and p.last == last}
            sources: List[str] = []
            basis: List[str] = []
            for p in known:
                sources += [s for s in p.sources if s not in sources]
                basis += [b for b in p.basis if b not in basis]
            return Due(first=first, last=last, time=times.pop() if len(times) == 1 else "",
                       estimate=any(p.estimate for p in known), bound=bool(unknown) or any(p.bound for p in known),
                       check=any(p.check for p in known), sources=sources, basis=basis)
        if kind == "繰り返し":
            window = rule.get("提出期間") if isinstance(rule.get("提出期間"), dict) else {}
            return Due(how=(f"{period_text(rule.get('間隔'))}ごとに{rule.get('回数')}回。"
                            f"{window.get('始まりの月')}月から{period_text(window.get('長さ'))}の間に出す。"
                            "事業の完了と決算の月が分かってから日付を出します"))
        return Due(how=f"期限の決め方（{kind}）が読めません")

    def stage_due(self, stage: Dict, application: bool) -> Optional[Due]:
        """手続きの段階の期限。期限の決め方を持たない段階（出来事）は None。"""
        node = stage.get("期限")
        if application:
            found = self.application_fixed(explicit_only=True)
            if found is not None:
                return found[0]
        if not isinstance(node, dict):
            if application:
                found = self.application_fixed(explicit_only=False)
                if found is not None:
                    return found[0]
            return None
        rule = node.get("値")
        if rule is not None:
            due = self.compute(rule)
            due.check = due.check or node.get("状態") in CHECK_STATES
            due.sources = source_text(node) or due.sources
            return due
        if application:
            found = self.application_fixed(explicit_only=False)
            if found is not None:
                return found[0]
        reason = str(node.get("理由") or "").strip()
        return Due(how=f"資料から読み取れませんでした（{reason}）" if reason else "資料から読み取れませんでした")


# ---- 作業と案件 ----


@dataclass
class Task:
    case: str  # 案件のフォルダの名前
    order: int  # 段階の順番
    stage: str  # 段階の名前
    what: str  # すること（期限の名前）
    due: Due
    start: Optional[date] = None  # 始める日（K1・K2 の期限の台帳で足す）
    notes: List[str] = field(default_factory=list)
    remedies: List[str] = field(default_factory=list)  # 期限を過ぎたときの手（制度データの注意。出典つき）

    def sort_key(self) -> Tuple:
        d = self.due
        return (d.first or date.max, d.last or date.max, self.case, self.order, self.what)


@dataclass
class StageRow:
    order: int
    name: str
    folder: str
    state: str  # 済み・今・これから
    due: Optional[Due]
    conditional: bool = False


@dataclass
class DocumentRow:
    name: str
    issuer: str
    kind: str  # 集める書類・様式で作る書類
    state: str  # 台帳にあり・添付する書類にあり・見当たらない・様式で作る・分からない


@dataclass
class CaseStatus:
    name: str
    title: str = ""
    current: str = ""
    current_folder: str = ""
    submitted: bool = False
    stages: List[StageRow] = field(default_factory=list)
    documents: List[DocumentRow] = field(default_factory=list)
    tasks: List[Task] = field(default_factory=list)
    problem: str = ""
    notes: List[str] = field(default_factory=list)

    def next_task(self) -> Optional[Task]:
        dated = sorted((t for t in self.tasks if t.due.dated), key=Task.sort_key)
        return dated[0] if dated else None


@dataclass
class Overview:
    today: date
    near_days: int
    substituted: bool
    cases: List[CaseStatus]
    groups: Dict[str, List[Task]]
    later: List[Task]
    undated: List[Task]
    problems: List[str] = field(default_factory=list)


def _int(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _core(text: str) -> str:
    """書類の名前を見比べる形（NFKC、【】と括弧の中、空白、「写し」を除く）。"""
    t = unicodedata.normalize("NFKC", text)
    t = _BRACKETS.sub("", t)
    t = re.sub(r"\s+", "", t)
    return t.replace("写し", "")


def names_match(a: str, b: str) -> bool:
    x, y = _core(a), _core(b)
    if len(x) < 2 or len(y) < 2:
        return False
    return x == y or x.startswith(y) or y.startswith(x)


def _is_form(doc: Dict, stage: Dict, data: Dict) -> bool:
    """様式で作る書類か（申請書として作るもの。集める書類ではない）。段階の様式か制度データの様式の名前に当たれば様式。"""
    name = str(doc.get("名前") or "")
    if "様式" in str(doc.get("形式") or ""):
        return True
    if re.match(r"^【[^】]*様式】", name):
        return True
    forms = [f for f in stage.get("様式") or [] if isinstance(f, str)] if isinstance(stage.get("様式"), list) else []
    if isinstance(data.get("様式"), list):
        forms += [f["名前"] for f in data["様式"] if isinstance(f, dict) and isinstance(f.get("名前"), str)]
    return any(names_match(name, f) for f in forms)


def _list_dirs(folder: Path, rel: str) -> List[str]:
    """会社のフォルダからの場所 rel の中のフォルダの名前（NFC、点で始まるものを除く）。外を指すときは読まない。"""
    path = places.actual(folder, rel)
    if path is None or not places.is_inside(folder, path):
        return []
    try:
        return sorted(nfc(p.name) for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []


def _list_files(folder: Path, rel: str) -> List[str]:
    path = places.actual(folder, rel)
    if path is None or not path.is_dir() or not places.is_inside(folder, path):
        return []
    found = []
    try:
        for p in sorted(path.rglob("*")):
            if p.is_file() and not p.name.startswith((".", "~")) and places.is_inside(folder, p):
                found.append(nfc(p.stem))
    except OSError:
        return found
    return found


def list_cases(folder: Path) -> Tuple[List[str], Optional[str]]:
    """案件のフォルダの名前と、読めなかったわけ（`案件/` が外を指すとき）。"""
    path = places.actual(folder, CASES_DIR)
    if path is None:
        return [], None
    problem = place_text.read_problem(folder, path, f"{CASES_DIR}/")
    if problem:
        return [], problem
    names = []
    for name in _list_dirs(folder, CASES_DIR):
        if place_text.read_problem(folder, folder / CASES_DIR / name, f"{CASES_DIR}/{name}") is None:
            names.append(name)
    return names, None


def _ledger_kinds(folder: Path) -> Tuple[Optional[List[str]], str]:
    """書類の台帳にある原本の種類。読めなければ (None, わけ)。"""
    try:
        from lib import seiri
        ledger = seiri.load_ledger(folder)
    except Exception as error:  # 台帳の問題は、開いたときの照らし（M4）が伝える。ここでは揃い具合を出さないだけ
        return None, f"書類の台帳を読めないため、書類の揃い具合は分かりません（{error}）"
    kinds = []
    for entry in ledger.get("原本") or []:
        if isinstance(entry, dict) and isinstance(entry.get("種類"), str):
            kinds.append(entry["種類"])
    return kinds, ""


def _submissions(folder: Path) -> Tuple[List[Dict], str]:
    """提出版の一覧（`記録/提出版.json`）の記録。読めなければ (空, わけ)。

    lib/submission.py は同梱の dulwich を読み込むので、ここでは同じファイルを標準のライブラリだけで読む。
    途中のフォルダかそのものが別名なら、読まない（lib/places.py。lib/submission.py と同じ）。
    """
    try:
        places.no_link_on_the_way(folder, SUBMISSIONS_FILE)
    except places.PlaceError as error:
        return [], (f"{error.link} が別名（シンボリックリンク）のため、提出版の一覧（{SUBMISSIONS_FILE}）を読んでいません"
                    "（提出した段階が分かりません）")
    path = places.actual(folder, SUBMISSIONS_FILE)
    if path is None:
        return [], ""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [], f"提出版の一覧（{SUBMISSIONS_FILE}）を読めないため、提出した段階が分かりません（{type(error).__name__}）"
    entries = value.get("提出版") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        return [], f"提出版の一覧（{SUBMISSIONS_FILE}）の形が違うため、提出した段階が分かりません"
    return [e for e in entries if isinstance(e, dict)], ""


def _case_round(folder: Path, case: str) -> Optional[int]:
    try:
        from lib import seido_data
        listed = seido_data.load_doc_list(folder, case)
        found = round_of(listed.get("案件の回")) or round_of((listed.get("制度") or {}).get("公募回"))
        if found is not None:
            return found
    except Exception:
        pass
    return round_of(case)


def _stages(data: Dict) -> List[Dict]:
    stages = data.get("手続きの段階")
    found = [s for s in stages if isinstance(s, dict)] if isinstance(stages, list) else []
    return sorted(found, key=lambda s: _int(s.get("順番")))


def _folder_of(stage: Dict) -> str:
    name = stage.get("フォルダ")
    return nfc(name) if isinstance(name, str) and _STAGE_FOLDER.match(name) else ""


def _title(data: Dict) -> str:
    seido = data.get("制度") if isinstance(data.get("制度"), dict) else {}
    name = str(seido.get("名前") or "")
    frame = str(seido.get("枠") or "")
    round_ = str(seido.get("公募回") or "")
    head = f"{name}（{frame}）" if frame else name
    return f"{head}。制度データは{round_}の資料から" if round_ else head


def _remedies(stage: Dict) -> List[str]:
    """期限を過ぎたときの手：段階の注意のうち、期限に触れるもの（出典つき）。"""
    found = []
    notes = stage.get("注意")
    for node in notes if isinstance(notes, list) else []:
        if not isinstance(node, dict) or not isinstance(node.get("値"), str):
            continue
        if "期限" not in node["値"]:
            continue
        sources = "、".join(source_text(node))
        found.append(f"{node['値']}（{sources}）" if sources else node["値"])
        if len(found) >= REMEDY_MAX:
            break
    return found


def case_status(folder: Path, case: str, submissions: List[Dict], ledger: Optional[List[str]],
                ledger_problem: str, events: Optional[Sequence[event_ledger.Event]] = None) -> CaseStatus:
    """1つの案件の段階・期限・作業・今の段階の必須の書類。events は期限の台帳の、この案件の出来事。"""
    status = CaseStatus(name=case)
    try:
        from lib import seido_data
        _path, data = seido_data.load_data(folder, case)
    except Exception as error:
        status.problem = f"制度データを読めないため、期限を組み立てられませんでした（{error}）"
        return status
    if not isinstance(data, dict):
        status.problem = "制度データの形が違うため、期限を組み立てられませんでした"
        return status
    status.title = _title(data)
    stages = _stages(data)
    if not stages:
        status.problem = "制度データに手続きの段階がないため、期限を組み立てられませんでした"
        return status
    plan = Plan(data, _case_round(folder, case), events)
    with_folder = [s for s in stages if _folder_of(s)]
    base = f"{CASES_DIR}/{case}"
    existing = set(_list_dirs(folder, base))
    reached = [s for s in with_folder if _folder_of(s) in existing]
    current = reached[-1] if reached else (with_folder[0] if with_folder else stages[0])
    application = with_folder[0] if with_folder else stages[0]
    current_order = _int(current.get("順番"))
    status.current = str(current.get("名前") or "")
    status.current_folder = _folder_of(current)
    if status.current_folder:
        mine = [e for e in submissions if isinstance(e, dict) and nfc(str(e.get("案件") or "")) == case]
        status.submitted = any(
            nfc(str(e.get("段階") or "")) == status.current_folder
            or nfc(str(e.get("段階") or "")).startswith(status.current_folder + "/") for e in mine)

    for stage in stages:
        order = _int(stage.get("順番"))
        name = str(stage.get("名前") or stage.get("id") or "")
        if order < current_order or (stage is current and status.submitted):
            state = "済み"
        elif stage is current:
            state = "今"
        else:
            state = "これから"
        due = plan.stage_due(stage, application=stage is application)
        status.stages.append(StageRow(order=order, name=name, folder=_folder_of(stage), state=state, due=due,
                                      conditional=stage.get("条件付き") is True))
        if due is None or state == "済み":
            continue
        task = Task(case=case, order=order, stage=name, what=f"{name}の期限", due=due, remedies=_remedies(stage))
        if stage.get("条件付き") is True:
            task.notes.append("必要なときだけの手続きです")
        if state == "今":
            task.notes += _document_notes(folder, status, data, stage, ledger, ledger_problem)
        status.tasks.append(task)
    return status


def _document_notes(folder: Path, status: CaseStatus, data: Dict, stage: Dict, ledger: Optional[List[str]],
                    ledger_problem: str) -> List[str]:
    """今の段階の必須の書類の揃い具合を status.documents に入れ、作業に添える文を返す。"""
    stage_id = stage.get("id")
    docs = data.get("書類")
    attached = _list_files(folder, f"{CASES_DIR}/{status.name}/{status.current_folder}/{ATTACH_DIR}") \
        if status.current_folder else []
    missing = []
    forms = 0
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict) or doc.get("区分") != REQUIRED or not isinstance(doc.get("名前"), str):
            continue
        uses = doc.get("手続き")
        if not isinstance(uses, list) or stage_id not in uses:
            continue
        name = doc["名前"]
        issuer = str(doc.get("発行元") or "")
        if _is_form(doc, stage, data):
            status.documents.append(DocumentRow(name, issuer, "様式で作る書類", "様式で作る（申請書）"))
            forms += 1
            continue
        if ledger is not None and any(names_match(name, k) for k in ledger):
            state = "台帳にあり"
        elif any(names_match(name, f) for f in attached):
            state = "添付する書類にあり"
        elif ledger is None:
            state = "分からない"
        else:
            state = "見当たらない"
            missing.append(name)
        status.documents.append(DocumentRow(name, issuer, "集める書類", state))
    notes = []
    if ledger is None and ledger_problem:
        status.notes.append(ledger_problem)
    if missing:
        shown = "、".join(missing[:NOTE_NAMES_MAX]) + ("ほか" if len(missing) > NOTE_NAMES_MAX else "")
        notes.append(f"集める必須の書類のうち、書類の台帳と添付する書類に見当たらないもの {len(missing)}件（{shown}）")
    if forms:
        # 実験 E9 で、この件数に入らない様式の書類を「もうある」と読んだ応答があったため、数えていないことを書き添える（M10）
        notes.append(f"様式で作る必須の書類 {forms}件は、これから作る申請書なので、集める書類の数には入れていません")
    return notes


def classify(tasks: Sequence[Task], today: date, near_days: int = NEAR_DAYS
             ) -> Tuple[Dict[str, List[Task]], List[Task], List[Task]]:
    """作業を、期限切れ・今日やること・近い締切・遅れている作業と、それより先（later）、日付のないもの（undated）に分ける。"""
    groups: Dict[str, List[Task]] = {g: [] for g in GROUPS}
    later: List[Task] = []
    undated: List[Task] = []
    for task in tasks:
        d = task.due
        start = task.start
        if not d.dated:
            if start is not None and start == today:
                groups[TODAY].append(task)
            elif start is not None and start < today:
                groups[LATE].append(task)
            else:
                undated.append(task)
            continue
        if d.last < today:
            groups[OVERDUE].append(task)
        elif (d.first == today and d.last == today) or start == today:
            groups[TODAY].append(task)
        elif start is not None and start < today:
            groups[LATE].append(task)
        elif (d.first - today).days <= near_days:
            groups[NEAR].append(task)
        else:
            later.append(task)
    for items in groups.values():
        items.sort(key=Task.sort_key)
    later.sort(key=Task.sort_key)
    undated.sort(key=lambda t: (t.case, t.order, t.what))
    return groups, later, undated


def build(folder: Path, today: Optional[date] = None, near_days: int = NEAR_DAYS) -> Overview:
    """会社のフォルダの、すべての案件の期限と作業をまとめる。今日は差し替えた日付を含む（lib/dates.py）。

    今日の日付の差し替えが読めないときは ValueError（呼ぶ側が伝える）。
    """
    folder = Path(folder)
    substituted = dates.substituted_today(folder) is not None
    day = today or dates.today(folder)
    names, problem = list_cases(folder)
    problems = [problem] if problem else []
    cases: List[CaseStatus] = []
    tasks: List[Task] = []
    if names:
        submissions, sub_problem = _submissions(folder)
        if sub_problem:
            problems.append(sub_problem)
        ledger, ledger_problem = _ledger_kinds(folder)
        events, events_problem = event_ledger.events_by_case(folder)
        if events_problem:
            problems.append(events_problem)
        for name in names:
            status = case_status(folder, name, submissions, ledger, ledger_problem, events.get(name))
            cases.append(status)
            tasks += status.tasks
    groups, later, undated = classify(tasks, day, near_days)
    return Overview(today=day, near_days=near_days, substituted=substituted, cases=cases, groups=groups,
                    later=later, undated=undated, problems=problems)
