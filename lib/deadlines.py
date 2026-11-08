"""開いたときに示す期限と作業の組み立て（SPEC F6・T6-1・T6-4・T6-5・T6-6、DESIGN 4.5・4.6・4.7 の3・6章。TASKS M3・K1・K2）。

案件ごとに次のものから組み立てる。締切と始める日は、読むたびに計算し直す（台帳には書き戻さない。lib/task_ledger.py）。
- 制度データ（`記録/制度データ/<略称>_<公募回>.json`。lib/seido_data.load_data）の「手続きの段階」の期限の決め方と、
  「決まった期日」、「書類」の取得の決まり・期数・依頼の締切・依頼の目安の日数
- 期限の台帳（`記録/期限の台帳.json`）：出来事の日付と見込みか確定か（lib/event_ledger.py）、作業の状態
  （外部への依頼の状態・頼む人・目安の日数。lib/task_ledger.py）
- 会社のフォルダの書類：案件の段階のフォルダ（どこまで進んだか）、提出版の一覧（`記録/提出版.json`。済んだ段階）、
  書類の台帳（`記録/書類の台帳.json`。集まった原本の種類と日付）と、段階のフォルダの「添付する書類」
- 会社の記録（`記録/会社の記録.json`）の事実：決算の月（期の入れ替わり）、前に社長に聞いた依頼の目安の日数
- 近い締切の日数：`.hojokin/設定.json` の「近い締切の日数」（はじめは30日。lib/task_ledger.near_days）

作業の種類（DESIGN 4.5）
- 提出：手続きの段階の期限（下の「作業」）。
- 取り直し：今の段階とこれからの段階で使う必須の書類のうち、取得の決まり（「発行から3か月以内」）があるもの。
  締切に間に合う取得の期間を、いちばん早い日（締切から期間を戻した日）といちばん遅い日（締切）で示す（SPEC F6・T6-5）。
  書類の台帳に、その期間の内の日付の原本があれば済んだものとする。制度データに取得の決まりがなく、有効期限の値が
  「発行から◯か月以内」の形の文なら、そこから期間を読む（仮）。
  締切は提出の締切の日なので、早く出すときは、いちばん早い日も早まる（作業に一言添える）。段階の締切を過ぎたものは
  作らない（段階の期限切れが知らせる）。
- 提出（日付で示された期限）：期限の台帳の作業のうち種類が「提出」のもの（差し戻しの出し直しの期限など。通知に書かれた
  日付）。日付は確定とし、出典を添える。状態が「済み」なら済んだものに並べる（fixed_tasks。11/7 の採択後の通し）。
- 依頼：外部への依頼（期限の台帳の作業。K2）。締切は、制度データの書類の「依頼の締切」、なければその書類を使う
  手続きの段階の期限。始める日（依頼する日）は、締切から目安の日数を戻した日。目安の日数は、台帳の値、制度データの
  「依頼の目安の日数」、会社の記録の「依頼の目安の日数：<書類>」（前の案件で社長に聞いたもの）の順に取る。
  どこにもなければ、始める日を出さずに「目安の日数をまだ聞いていません」と添える（Claude が社長に聞く）。
  「依頼した」のまま目安の日数を過ぎたものは「待っている」と示す。「届いた」「済み」は分け方に入れず、済んだものに並べる。
- 期の入れ替わり（決算日をまたぐとき）：期数のある必須の書類（納税証明書など）について、会社の記録の決算の月から、
  締切までに決算日を迎えるとき（前に取ったものが使えなくなる）と、決算日を過ぎたとき（決算日から DAYS_AFTER_CLOSING 日の間か、
  決算日より前の日付の原本があるとき）に、案件の「書類について」に知らせる（SPEC F6・T6-5）。申告の期限は会社によって
  違う（延長の特例など）ので、日付を計算しない。決算の月が会社の記録になければ、確かめていないことを知らせる。

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
  （名前に出来事の名前を含むもの）。予定の日付から出した期限は「見込み」、台帳の「確定」の日付から出した期限は「確定」と示す
  （SPEC F6「見込みと確定」・T6-4）。台帳の日付を使った期限には、もとにした日（basis）を添える。出来事の日付が分からなければ、
  日付を出さずに決め方を示す。決まった日付（公募要領の日付）は、見込みでないものとして扱い、「確定」の印は付けない。
  か月・年は、同じ日の数字の日（応当日）。その日がない月は、その月の終わりの日にする（仮）。
- 早いほう：日付の分かるもののうち早いほう。分からないものがあれば「遅くとも」その日（上限）とする。
- 繰り返し（効果報告など）：事業の完了の日（期限の台帳の出来事）と会社の記録の決算の月から、回ごとの提出期間を出す
  （Plan.repeat_dues。B31a）。完了した事業年度の翌年度を1年目とし、1年目が終わった後の最初の「始まりの月」から（仮）。
  回ごとの提出版（段階が「4_効果報告/1年目」の形）を数え、まだ出していない回のうち、いちばん前の回を作業にする
  （1年目を出すと2年目の期限が出る）。すべての回を出すまで、段階は済みにしない。完了の日か決算の月がなければ日付を出さない。
- 申請の段階（いちばん前の、フォルダのある段階）は、「決まった期日」のうち、名前に案件の回と締切を含むものを先に使う。
  制度データは直近回の資料で作ることがあり（M2c）、段階の期限が前の回の締切や「読み取れない」になっていることがあるため（仮）。
- 決まった期日の名前に公募回があるものは、案件の回のものだけを使う。名前に公募回がないものは、制度データの回と
  案件の回が同じときだけ使う（前の回の日付で、期限切れなどと示さないため）。
- 日が決まっていない期日（「12月下旬」）から出した期限は見込みとし、旬のはじめの日で並べて近い締切に入れ
  （早めに気づくため）、旬の終わりの日を過ぎてから期限切れにする（仮）。

分け方（classify）。示す順は、期限切れ・今日やること・近い締切・遅れている作業（DESIGN 4.6）
- 期限切れ：期限の日（旬なら終わりの日）が今日より前。いちばん上に分けて示す。
- 今日やること：期限が今日か、始める日が今日。
- 遅れている作業：始める日（逆算した、依頼する日）が今日より前で、まだ始めていない（依頼の状態が「まだ」）もの。
  期限はまだ。
- 近い締切：期限が今日から N 日以内（はじめは30日。設定で変えられる。7日以内は強めて示す）。
- それぞれの中は締切順（同じ日なら、案件の名前、段階の順）。どれにも入らないものは、N 日より先（later）と、
  日付がまだ出せないもの（undated）に分ける。済んだもの（届いた依頼、期間の内の原本がある取り直し）は done に並べる。

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

from lib import dates, event_ledger, place_text, places, task_ledger

NEAR_DAYS = task_ledger.NEAR_DEFAULT  # 近い締切の日数のはじめの値（SPEC F6。変えた値は `.hojokin/設定.json`）
STRONG_DAYS = 7  # この日数の内の期限は強めて示す（SPEC F6）
DAYS_AFTER_CLOSING = 92  # 決算日を過ぎたことを知らせる日数（申告をするまでの間。会社によって違うので、広めにとる。仮）
SUBMIT = "提出"
REACQUIRE = "取り直し"
REQUEST = task_ledger.REQUEST
RECORD_FILE = "記録/会社の記録.json"  # lib/company_record.py の RECORD_FILE と同じ
LEAD_FACT = "依頼の目安の日数"  # 会社の記録の事実の名前の頭（「依頼の目安の日数：見積書」）
CLOSING_WORDS = ("決算月", "決算の月")  # 会社の記録の事実の名前（決算の月）

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
    confirmed: bool = False  # 社長に確かめた出来事の日付（期限の台帳の「確定」）から出した（SPEC F6「見込みと確定」）
    window: bool = False  # 取る期間（取り直し）。first がいちばん早い日、last がいちばん遅い日
    term: bool = False  # 提出期間（繰り返しの報告。効果報告の4月から3か月の間など）。first がはじめの日、last が終わりの日
    term_word: str = "提出期間"  # term のときの呼び方（事業場内最低賃金の「確かめる時期」など。K3）

    @property
    def dated(self) -> bool:
        return self.first is not None and self.last is not None

    @property
    def state_word(self) -> str:
        """見込みか確定か（画面と期限の一覧の欄。DESIGN 4.6）。予定の日付から出したものは見込み、ほかは確定。"""
        if not self.dated:
            return "—"
        return "見込み" if self.estimate else "確定"

    def label(self) -> str:
        """社長に見せる日付の文。例：2026年10月16日（金）17:00、遅くとも 2028年11月16日（木）（見込み）"""
        if not self.dated:
            head = "日付はまだ出せません"
            return f"{head}（{self.how}）" if self.how else head
        if self.window:
            text = f"取る期間 {dates.format_date(self.first)}〜{dates.format_date(self.last)}"
        elif self.term:
            text = f"{self.term_word} {dates.format_date(self.first)}〜{dates.format_date(self.last)}"
        elif self.span:
            text = f"{self.span}（日はまだ決まっていません）"
        elif self.first != self.last:
            text = f"{dates.format_date(self.first)}〜{dates.format_date(self.last)}のどこか"
        else:
            text = dates.format_date(self.first) + self.time
        if self.bound:
            text = f"遅くとも {text}"
        if self.estimate:
            text += "（見込み）"
        elif self.confirmed:
            text += "（確定）"
        if self.check:
            text = "【要確認】" + text
        return text

    def days_text(self, today: date) -> str:
        """あと何日（過ぎた日数）の文。"""
        if not self.dated:
            return ""
        if self.last < today:
            return f"{(today - self.last).days}日過ぎています"
        if self.window or self.term:
            what = "取る期間" if self.window else self.term_word
            if self.first > today:
                return f"{what}まであと{(self.first - today).days}日"
            left = (self.last - today).days
            return f"今が{what}です（今日まで）" if left == 0 else f"今が{what}です（あと{left}日）"
        if self.first <= today < self.last:
            return "今がその時期です"
        days = (self.first - today).days
        return "今日まで" if days == 0 else f"あと{days}日"

    def strong(self, today: date) -> bool:
        """強めて示すか（今日から7日以内。取る期間は、いちばん遅い日まで7日以内）。"""
        if not self.dated or self.last < today:
            return False
        if self.window or self.term:
            return (self.last - today).days <= STRONG_DAYS
        return (self.first - today).days <= STRONG_DAYS


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


def sub_period(day: date, period: Any) -> Optional[date]:
    """day から期間だけ前の日（add_period の逆。か月・年は応当日、その日がない月は月の終わりの日。仮）。"""
    if not isinstance(period, dict):
        return None
    n, unit = period.get("数"), period.get("単位")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return None
    if unit == "日":
        return day - timedelta(days=n)
    if unit in ("か月", "年"):
        months = n if unit == "か月" else n * 12
        year, index = divmod(day.month - 1 - months, 12)
        year += day.year
        month = index + 1
        return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    return None


_LEAD = re.compile(r"([0-9]+)\s*(日|週間|週|か月|ヶ月|カ月|ケ月|箇月|年)")
_UNITS = {"日": "日", "週間": "週", "週": "週", "か月": "か月", "ヶ月": "か月", "カ月": "か月", "ケ月": "か月",
          "箇月": "か月", "年": "年"}


def parse_period(value: Any) -> Optional[Dict[str, Any]]:
    """期間の形（{"数": 3, "単位": "か月"}）か、「3か月」「2週間」「14日」の文から期間。数だけなら日数。読めなければ None。"""
    if isinstance(value, dict):
        n, unit = value.get("数"), value.get("単位")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0 and unit in ("日", "か月", "年"):
            return {"数": n, "単位": unit}
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return {"数": value, "単位": "日"} if value >= 0 else None
    if not isinstance(value, str):
        return None
    m = _LEAD.search(unicodedata.normalize("NFKC", value))
    if not m:
        return None
    n, unit = int(m.group(1)), _UNITS[m.group(2)]
    return {"数": n * 7, "単位": "日"} if unit == "週" else {"数": n, "単位": unit}


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
                 events: Optional[Sequence[event_ledger.Event]] = None, closing: Optional[int] = None) -> None:
        self.data = data if isinstance(data, dict) else {}
        seido = self.data.get("制度") if isinstance(self.data.get("制度"), dict) else {}
        self.data_round = round_of(seido.get("公募回"))
        self.case_round = case_round
        fixed = self.data.get("決まった期日")
        self.fixed = [e for e in fixed if isinstance(e, dict) and isinstance(e.get("名前"), str)] \
            if isinstance(fixed, list) else []
        self.events = list(events or [])  # 期限の台帳の、この案件の出来事（lib/event_ledger.py）
        self.closing = closing  # 会社の記録の決算の月（繰り返しの報告の年度を決める。なければ None）

    def ledger_due(self, event: Any) -> Optional[Due]:
        """出来事の日付を、期限の台帳から取る。なければ None。"""
        found = event_ledger.find(self.events, event) if isinstance(event, str) else None
        if found is None:
            return None
        source = f"。出典：{found.source}" if found.source else ""
        basis = f"{found.name} {dates.format_date(found.day)}（{found.state}{source}）"
        confirmed = found.state == event_ledger.CONFIRMED
        return Due(first=found.day, last=found.day, estimate=not confirmed, basis=[basis], confirmed=confirmed)

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
            estimate = base.estimate or base.first != base.last
            return Due(first=first, last=last, estimate=estimate,
                       check=base.check, sources=list(base.sources), basis=list(base.basis),
                       confirmed=base.confirmed and not estimate)
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
            estimate = any(p.estimate for p in known)
            return Due(first=first, last=last, time=times.pop() if len(times) == 1 else "",
                       estimate=estimate, bound=bool(unknown) or any(p.bound for p in known),
                       check=any(p.check for p in known), sources=sources, basis=basis,
                       confirmed=not estimate and any(p.confirmed for p in known))
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

    # ---- 繰り返しの報告（効果報告など。B31a） ----

    def completion_event(self) -> Optional[str]:
        """制度データの期限の決め方にある出来事のうち、事業の完了（終了）に当たる名前（はじめの1つ）。なければ None。"""
        for name in rule_event_names(self.data):
            if any(w in unicodedata.normalize("NFKC", name) for w in COMPLETION_WORDS):
                return name
        return None

    def completion_cap(self) -> Optional[Due]:
        """事業の完了の日が分からないときの見込みの起点：補助事業の実施の段階（id か名前に「実施」）の期限（完了の期限）。

        完了の期限から出した繰り返しの期限は「見込み」とし、完了の日を台帳に残したら計算し直す（B27。testdata/期限 の
        「完了日が分かるまで見込み」）。出せなければ None。
        """
        for stage in _stages(self.data):
            words = unicodedata.normalize("NFKC", f"{stage.get('id') or ''}{stage.get('名前') or ''}")
            node = stage.get("期限")
            if "実施" not in words or not isinstance(node, dict) or node.get("値") is None:
                continue
            due = self.compute(node["値"])
            if due.dated:
                return Due(first=due.last, last=due.last, estimate=True, check=due.check,
                           basis=list(due.basis) + [f"事業の完了の期限 {dates.format_date(due.last)}"
                                                     "（見込み。完了の日を残したら計算し直す）"])
        return None

    def repeat_dues(self, rule: Any) -> Tuple[List[Due], str]:
        """繰り返しの期限（{"種類": "繰り返し", "回数", "間隔", "提出期間"}）の、回ごとの提出期間と、決め方の文。

        1回目は、事業の完了の日の属する事業年度（会社の記録の決算の月で区切る）の翌年度を1年目とし、1年目が終わった後の
        最初の「始まりの月」の1日から、提出期間の長さの間（仮。省力化の効果報告の決め方。制度データに起点の欄がないため。
        DESIGN 9章の文案）。2回目からは、間隔ずつ後ろにずらす。日付が出せないときは（[], 決め方とわけの文）。
        """
        if not isinstance(rule, dict) or rule.get("種類") != "繰り返し":
            return [], "期限の決め方が繰り返しではありません"
        count, interval = rule.get("回数"), parse_period(rule.get("間隔"))
        window = rule.get("提出期間") if isinstance(rule.get("提出期間"), dict) else {}
        month, length = window.get("始まりの月"), parse_period(window.get("長さ"))
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or interval is None or length is None \
                or not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
            return [], "繰り返しの期限の決め方が読めません"
        how = f"{period_text(interval)}ごとに{count}回。{month}月から{period_text(length)}の間に出す"
        event = self.completion_event()
        if event is None:
            return [], f"{how}。制度データの期限の決め方に、事業の完了の出来事がないため、日付を出せません"
        base = self.event_due(event)
        if base is None or not base.dated:
            base = self.completion_cap() if self.closing is not None else None
        if base is None or not base.dated:
            return [], f"{how}。「{event}」の日付と決算の月が分かってから、日付を出します"
        if self.closing is None:
            return [], f"{how}。決算の月が会社の記録にないため、年度を決められません（社長に決算の月を聞いて、会社の記録に残す）"
        fiscal_end = _closing_day(base.last.year, self.closing)
        if fiscal_end < base.last:
            fiscal_end = _closing_day(base.last.year + 1, self.closing)
        first_year_end = _closing_day(fiscal_end.year + 1, self.closing)
        start = date(first_year_end.year, month, 1)
        if start <= first_year_end:
            start = date(first_year_end.year + 1, month, 1)
        basis = list(base.basis) + [f"決算の月 {self.closing}月（会社の記録）"]
        dues = []
        for i in range(count):
            step = {"数": interval["数"] * i, "単位": interval["単位"]}
            first = add_period(start, step) if i else start
            end = add_period(first, length) if first is not None else None
            if first is None or end is None:
                return [], f"{how}（期間が読めません）"
            dues.append(Due(first=first, last=end - timedelta(days=1), term=True, estimate=base.estimate,
                            check=base.check, sources=list(base.sources), basis=list(basis),
                            confirmed=base.confirmed and not base.estimate))
        return dues, how


COMPLETION_WORDS = ("完了", "終了")  # 繰り返しの報告の起点にする出来事の名前の語
YEAR_WORD = "年目"  # 繰り返しの報告の年のフォルダ（「4_効果報告/1年目」。lib/history.py の YEAR_DIR）


def _rule_names(rule: Any, out: List[str]) -> None:
    if not isinstance(rule, dict):
        return
    if rule.get("種類") == "出来事からの期間" and isinstance(rule.get("出来事"), str):
        if rule["出来事"] not in out:
            out.append(rule["出来事"])
    elif rule.get("種類") == "早いほう" and isinstance(rule.get("期限"), list):
        for part in rule["期限"]:
            _rule_names(part, out)


def rule_event_names(data: Dict) -> List[str]:
    """制度データの手続きの段階の期限の決め方にある、出来事の名前（段階の順）。"""
    out: List[str] = []
    stages = data.get("手続きの段階") if isinstance(data, dict) else None
    for stage in sorted((s for s in stages if isinstance(s, dict)), key=lambda s: _int(s.get("順番"))) \
            if isinstance(stages, list) else []:
        node = stage.get("期限")
        _rule_names(node.get("値") if isinstance(node, dict) else None, out)
    return out


def start_event(stage: Dict, known: Sequence[str]) -> str:
    """段階が始まる出来事の名前。始まる条件の値に、期限の決め方にある出来事の名前（「交付決定日」。末尾の「日」を除いた
    「交付決定」でもよい）があればそれ、なければ期限の決め方の出来事（出来事からの期間はその出来事、早いほうは初めの出来事）。
    どちらもなければ空（工程表の帯は、前の段階の期限の次の日から）。"""
    node = stage.get("始まる条件") if isinstance(stage, dict) else None
    text = node.get("値") if isinstance(node, dict) else node
    if isinstance(text, str):
        flat = unicodedata.normalize("NFKC", text)
        for name in sorted(known, key=len, reverse=True):
            core = unicodedata.normalize("NFKC", name).rstrip("日")
            if unicodedata.normalize("NFKC", name) in flat or (len(core) >= 2 and core in flat):
                return name
    found: List[str] = []
    rule = stage.get("期限") if isinstance(stage, dict) else None
    _rule_names(rule.get("値") if isinstance(rule, dict) else None, found)
    return found[0] if found else ""


def repeat_rule(stage: Dict) -> Optional[Dict]:
    """段階の期限の決め方が繰り返しなら、その決め方。ほかは None。"""
    node = stage.get("期限") if isinstance(stage, dict) else None
    rule = node.get("値") if isinstance(node, dict) else None
    return rule if isinstance(rule, dict) and rule.get("種類") == "繰り返し" else None


def year_folder(folder: str, number: int) -> str:
    return f"{folder}/{number}{YEAR_WORD}"


# ---- 作業と案件 ----


@dataclass
class Task:
    case: str  # 案件のフォルダの名前
    order: int  # 段階の順番
    stage: str  # 段階の名前
    what: str  # すること（期限の名前）
    due: Due
    start: Optional[date] = None  # 始める日（依頼する日。締切から目安の日数を戻した日）
    notes: List[str] = field(default_factory=list)
    remedies: List[str] = field(default_factory=list)  # 期限を過ぎたときの手（制度データの注意。出典つき）
    kind: str = SUBMIT  # 提出・取り直し・依頼（DESIGN 4.5）
    state: str = ""  # 依頼の状態（まだ・依頼した・待っている・届いた）。取り直しは、期間の内の原本があれば「済み」
    who: str = ""  # だれがするか（社長・担当者・外部。依頼は「社長が頼む／外部（信用金庫）が書く」の形）
    doc: str = ""  # 取り直し・依頼の書類の名前
    lead: str = ""  # 依頼の目安の日数の文（「14日（社長の答え）」）。分からなければ空
    fixed: bool = False  # 期限の台帳に日付で残した期限（差し戻しの出し直しなど。fixed_tasks）

    @property
    def done(self) -> bool:
        return self.state in task_ledger.FINISHED

    def start_label(self) -> str:
        if self.start is None:
            return ""
        return dates.format_date(self.start) + ("（見込み）" if self.due.estimate else "")

    def sort_key(self) -> Tuple:
        d = self.due
        return (d.first or date.max, d.last or date.max, self.case, self.order, self.what)


@dataclass
class YearRow:
    """繰り返しの報告の1回（効果報告の1年目など）。"""

    number: int
    due: Due
    submitted: bool = False  # 提出版（段階が「4_効果報告/1年目」の形）が記録されている


@dataclass
class StageRow:
    order: int
    name: str
    folder: str
    state: str  # 済み・今・これから
    due: Optional[Due]  # 繰り返しの段階は、まだ出していない回のうち、いちばん前の回の期限
    conditional: bool = False
    years: List[YearRow] = field(default_factory=list)  # 繰り返しの段階の、回ごとの期限（日付が出せないときは空）
    next_year: int = 0  # 繰り返しの段階で、次に出す回（すべて出したら 0）
    start_event: str = ""  # 段階が始まる出来事（始まる条件にある出来事、なければ期限の決め方の出来事。工程表の帯の始まり）
    start: Optional[Due] = None  # その出来事の日付（分からなければ None）


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
    duties: List[str] = field(default_factory=list)  # 事業期間中・事業後の義務の知らせ（lib/obligations.py。K3）
    evidence: list = field(default_factory=list)  # 経費ごとの証拠の揃い具合（obligations.EvidenceRow）
    evidence_note: str = ""  # 揃い具合を出せないわけ
    period: str = ""  # 事業期間中・事業後（交付決定の前は空）
    event_days: List[date] = field(default_factory=list)  # 期限の台帳に残した、この案件の出来事の日付（工程表の見込みの帯の下限）

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
    done: List[Task] = field(default_factory=list)  # 済んだもの（届いた依頼、期間の内の原本がある取り直し）

    def requests(self) -> List[Task]:
        """外部への依頼（済んだものを含む）。案件・締切の順。"""
        found = [t for c in self.cases for t in c.tasks if t.kind == REQUEST]
        return sorted(found, key=lambda t: (t.case, t.due.first or date.max, t.doc))


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
    """様式で作る書類か（申請書として作るもの。集める書類ではない）。段階の様式か制度データの様式の名前に当たれば様式。
    外の機関が出す書類（商工会議所の事業支援計画書〈様式4〉など）は、様式の名前に当たっても、人に頼んで集める書類とする
    （11/7 の通し：制度データの「様式」に様式4 が入り、依頼の締切 12/4 が期限の一覧と依頼の候補から落ちた）。"""
    name = str(doc.get("名前") or "")
    if doc.get("発行元") == "外部機関" or isinstance(doc.get("依頼先"), dict):
        return False
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


@dataclass
class Original:
    """書類の台帳の原本の1件（種類・日付・場所）。日付は、書類の日付（証明書なら発行日）。"""

    kind: str
    day: Optional[date]
    place: str
    partner: str = ""  # 相手先（見積書・請求書などの相手の会社。経費ごとの証拠の揃い具合に使う。K3）


def _ledger_originals(folder: Path) -> Tuple[Optional[List[Original]], str]:
    """書類の台帳にある原本。読めなければ (None, わけ)。"""
    try:
        from lib import seiri
        ledger = seiri.load_ledger(folder)
    except Exception as error:  # 台帳の問題は、開いたときの照らし（M4）が伝える。ここでは揃い具合を出さないだけ
        return None, f"書類の台帳を読めないため、書類の揃い具合は分かりません（{error}）"
    found = []
    for entry in ledger.get("原本") or []:
        if isinstance(entry, dict) and isinstance(entry.get("種類"), str):
            day, _time = parse_point(entry.get("日付"))
            found.append(Original(kind=entry["種類"], day=day, place=str(entry.get("場所") or ""),
                                  partner=str(entry.get("相手先") or "")))
    return found, ""


def _ledger_kinds(folder: Path) -> Tuple[Optional[List[str]], str]:
    """書類の台帳にある原本の種類。読めなければ (None, わけ)。"""
    originals, problem = _ledger_originals(folder)
    return (None if originals is None else [o.kind for o in originals]), problem


def _company_facts(folder: Path) -> List[Dict]:
    """会社の記録の事実（読めなければ空。読めないことは、開いたときの会社の記録の要約が伝える）。

    lib/company_record.py はスキーマの検査を読み込むので、ここでは同じファイルを標準のライブラリだけで読む。
    途中のフォルダかそのものが別名なら、読まない（lib/places.py）。
    """
    if places.first_link(folder, RECORD_FILE) is not None:
        return []
    path = places.actual(folder, RECORD_FILE)
    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    items = data.get("項目") if isinstance(data, dict) else None
    return [it for it in items if isinstance(it, dict) and it.get("種類") == "事実"
            and isinstance(it.get("名前"), str)] if isinstance(items, list) else []


def closing_month(facts: List[Dict]) -> Optional[int]:
    """会社の記録の「決算の月」（「3月」「3」）。なければ None。"""
    for fact in facts:
        name = unicodedata.normalize("NFKC", fact["名前"])
        if not any(w in name for w in CLOSING_WORDS):
            continue
        value = fact.get("値")
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12:
            return value
        m = re.search(r"([0-9]{1,2})\s*月", unicodedata.normalize("NFKC", str(value)))
        if m and 1 <= int(m.group(1)) <= 12:
            return int(m.group(1))
    return None


def recorded_lead(facts: List[Dict], doc: str) -> Optional[Tuple[Dict[str, Any], str]]:
    """会社の記録の「依頼の目安の日数：<書類>」のうち、書類の名前が当たるもの（期間と、出どころの文）。"""
    for fact in facts:
        name = unicodedata.normalize("NFKC", fact["名前"]).strip()
        if not name.startswith(LEAD_FACT):
            continue
        target = name[len(LEAD_FACT):].lstrip("：:（(").rstrip("）)").strip()
        if not target or not names_match(target, doc):
            continue
        period = parse_period(fact.get("値"))
        if period is not None:
            return period, f"会社の記録 {fact.get('id') or ''}（前に社長に聞いた日数）".replace(" （", "（")
    return None


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
                ledger_problem: str, events: Optional[Sequence[event_ledger.Event]] = None,
                originals: Optional[List[Original]] = None,
                requests: Optional[Sequence[task_ledger.Request]] = None,
                facts: Optional[List[Dict]] = None, today: Optional[date] = None) -> CaseStatus:
    """1つの案件の段階・期限・作業・今の段階の必須の書類。events は期限の台帳の、この案件の出来事、requests は依頼。

    originals（書類の台帳の原本）・facts（会社の記録の事実）・today があれば、取り直しの作業、期の入れ替わりの知らせ、
    依頼の作業も作る（K1・K2）。
    """
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
    plan = Plan(data, _case_round(folder, case), events, closing=closing_month(facts or []))
    status.event_days = sorted(e.day for e in plan.events)
    # 始まる出来事の候補：期限の決め方にある出来事と、台帳に残した出来事（持続化の交付決定のように、期限の決め方にないもの）
    known_events = rule_event_names(data)
    known_events += [e.name for e in plan.events if e.name not in known_events]
    with_folder = [s for s in stages if _folder_of(s)]
    base = f"{CASES_DIR}/{case}"
    existing = set(_list_dirs(folder, base))
    reached = [s for s in with_folder if _folder_of(s) in existing]
    current = reached[-1] if reached else (with_folder[0] if with_folder else stages[0])
    application = with_folder[0] if with_folder else stages[0]
    current_order = _int(current.get("順番"))
    status.current = str(current.get("名前") or "")
    status.current_folder = _folder_of(current)
    mine = [e for e in submissions if isinstance(e, dict) and nfc(str(e.get("案件") or "")) == case]
    sent = {nfc(str(e.get("段階") or "")).strip().strip("/") for e in mine}
    if status.current_folder:
        status.submitted = any(s == status.current_folder or s.startswith(status.current_folder + "/") for s in sent)

    open_stages: List[Tuple[Dict, StageRow]] = []  # 済んでいない段階（取り直しと依頼の締切に使う）
    for stage in stages:
        order = _int(stage.get("順番"))
        name = str(stage.get("名前") or stage.get("id") or "")
        repeat = repeat_rule(stage)
        years: List[YearRow] = []
        if repeat is not None:
            dues, how = plan.repeat_dues(repeat)
            for d in dues:
                d.sources = source_text(stage.get("期限")) or d.sources
                d.check = d.check or (isinstance(stage.get("期限"), dict) and stage["期限"].get("状態") in CHECK_STATES)
            years = [YearRow(number=i + 1, due=d, submitted=year_folder(_folder_of(stage), i + 1) in sent)
                     for i, d in enumerate(dues)]
            if stage is current:  # 繰り返しの段階は、すべての回を出してはじめて済み
                status.submitted = bool(years) and all(y.submitted for y in years)
        if order < current_order or (stage is current and status.submitted):
            state = "済み"
        elif stage is current:
            state = "今"
        else:
            state = "これから"
        due = plan.stage_due(stage, application=stage is application)
        row = StageRow(order=order, name=name, folder=_folder_of(stage), state=state, due=due,
                       conditional=stage.get("条件付き") is True, years=years)
        row.start_event = start_event(stage, known_events)
        begin = plan.event_due(row.start_event) if row.start_event else None
        row.start = begin if begin is not None and begin.dated else None
        if repeat is not None:
            pending = next((y for y in years if not y.submitted), None)
            row.next_year = pending.number if pending is not None else 0
            if pending is not None:
                row.due = due = pending.due
            elif not years:
                row.due = due = Due(how=how, check=due.check if due is not None else False,
                                    sources=list(due.sources) if due is not None else [])
        status.stages.append(row)
        if state != "済み":
            open_stages.append((stage, row))
        if due is None or state == "済み":
            continue
        what = f"{name}（{row.next_year}{YEAR_WORD}）の期限" if row.next_year else f"{name}の期限"
        task = Task(case=case, order=order, stage=name, what=what, due=due, remedies=_remedies(stage))
        if stage.get("条件付き") is True:
            task.notes.append("必要なときだけの手続きです")
        if state == "今":
            where = year_folder(status.current_folder, row.next_year) if row.next_year else status.current_folder
            task.notes += _document_notes(folder, status, data, stage, ledger, ledger_problem, where)
        status.tasks.append(task)
    if today is not None:
        status.tasks += _reacquire_tasks(status, data, open_stages, originals, today)
        status.notes += _period_notes(data, open_stages, originals, facts or [], today)
        status.tasks += _request_tasks(status, data, plan, open_stages, list(requests or []), facts or [], today)
        from lib import obligations  # 事業期間中と事業後の義務（K3）
        duty = obligations.build(folder, status, data, plan, today, originals)
        status.tasks += duty.tasks
        status.duties, status.evidence, status.evidence_note, status.period = \
            duty.notes, duty.evidence, duty.evidence_note, duty.period
    return status


# ---- 取り直しと期の入れ替わり（K1。SPEC F6・T6-5） ----


def acquisition_period(doc: Dict) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """書類の取得の決まり（発行からの期間）と出典。制度データの「取得の決まり」が期間の形ならそれ、なければ
    有効期限の値が「発行から◯か月以内」の形の文ならそこから読む（仮）。どちらもなければ (None, [])。"""
    rule = doc.get("取得の決まり")
    if isinstance(rule, dict):
        period = parse_period(rule.get("値"))
        if period is not None and period["数"] > 0:
            return period, source_text(rule)
    valid = doc.get("有効期限")
    if isinstance(valid, dict) and isinstance(valid.get("値"), str) and "発行" in valid["値"]:
        period = parse_period(valid["値"])
        if period is not None and period["数"] > 0:
            return period, source_text(valid)
    return None, []


def _docs_for(data: Dict, open_stages: List[Tuple[Dict, StageRow]], required_only: bool = True
              ) -> List[Tuple[Dict, Dict, StageRow]]:
    """済んでいない段階で使う、集める書類（様式で作る書類を除く）と、その書類を使ういちばん前の段階。"""
    found = []
    docs = data.get("書類")
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict) or not isinstance(doc.get("名前"), str):
            continue
        if required_only and doc.get("区分") != REQUIRED:
            continue
        uses = doc.get("手続き") if isinstance(doc.get("手続き"), list) else []
        for stage, row in open_stages:
            if stage.get("id") in uses:
                if not _is_form(doc, stage, data):
                    found.append((doc, stage, row))
                break
    return found


def _latest_original(originals: Optional[List[Original]], name: str) -> Optional[Original]:
    dated = [o for o in originals or [] if o.day is not None and names_match(name, o.kind)]
    return max(dated, key=lambda o: o.day) if dated else None


def _reacquire_tasks(status: CaseStatus, data: Dict, open_stages: List[Tuple[Dict, StageRow]],
                     originals: Optional[List[Original]], today: date) -> List[Task]:
    """取得の決まりのある必須の書類の、取る期間（いちばん早い日〜いちばん遅い日）。

    段階の締切を過ぎたもの（段階の期限切れが知らせる）と、締切の日付がまだ出せないものは作らない。
    """
    tasks = []
    for doc, _stage, row in _docs_for(data, open_stages):
        period, sources = acquisition_period(doc)
        due = row.due
        if period is None or due is None or not due.dated or due.last < today:
            continue
        first = sub_period(due.last, period)
        if first is None:
            continue
        name = doc["名前"]
        window = Due(first=first, last=due.last, window=True, estimate=due.estimate, check=due.check,
                     sources=sources or list(due.sources), basis=list(due.basis), confirmed=due.confirmed)
        task = Task(case=status.name, order=row.order, stage=row.name, what=f"{name}を取る（{row.name}に出す）",
                    due=window, kind=REACQUIRE, doc=name, who="社長")
        task.notes.append(f"発行から{period_text(period)}以内のものを出します。いちばん遅い日は{row.name}の締切で、"
                          "早く出すときは、いちばん早い日も早まります")
        found = _latest_original(originals, name)
        if found is not None and first <= found.day <= due.last:
            task.state = task_ledger.DONE
            task.notes.append(f"今ある原本（{dates.format_date(found.day)}の日付。{found.place}）は取る期間の内です")
        elif found is not None and found.day < first:
            task.notes.append(f"今ある原本（{dates.format_date(found.day)}の日付）は取る期間より前のものなので、"
                              "取る期間の内に取り直します")
        elif found is None and originals is not None:
            task.notes.append("書類の台帳に、まだこの書類の原本がありません")
        tasks.append(task)
    return tasks


def _closing_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _period_notes(data: Dict, open_stages: List[Tuple[Dict, StageRow]], originals: Optional[List[Original]],
                  facts: List[Dict], today: date) -> List[str]:
    """期数のある必須の書類（納税証明書など）の、決算日をまたぐときの知らせ（期の入れ替わり）。"""
    targets = [(doc, row) for doc, _stage, row in _docs_for(data, open_stages)
               if isinstance(doc.get("期数"), dict) and row.due is not None and row.due.dated
               and row.due.last >= today]
    if not targets:
        return []
    month = closing_month(facts)
    if month is None:
        names = "、".join(dict.fromkeys(doc["名前"] for doc, _row in targets))
        return [f"決算の月が会社の記録にないため、決算日をまたぐときの期の入れ替わり（{names}）は確かめていません。"
                "社長に決算の月を聞いて、会社の記録に残してください"]
    closed = _closing_day(today.year, month)
    if closed > today:
        closed = _closing_day(today.year - 1, month)
    coming = _closing_day(closed.year + 1, month)
    notes = []
    groups: Dict[Tuple[str, date], List[Dict]] = {}
    for doc, row in targets:
        groups.setdefault((row.name, row.due.last), []).append(doc)
    for (stage_name, deadline), docs in groups.items():
        head = f"{stage_name}の締切（{dates.format_date(deadline)}）"
        passed, stale, newer = [], [], []
        for doc in docs:
            found = _latest_original(originals, doc["名前"])
            covered = found.day if found is not None else None
            own = doc.get("発行元") == "自社"
            if covered is not None and own:
                # 自社の決算書の日付は事業年度の始めの日（shorui の決まり）。その期の終わりの日で比べ、
                # 決算日までの期のものなら、直近の期がそろっているとみなす
                end = add_period(covered, {"数": 1, "単位": "年"})
                covered = end - timedelta(days=1) if end is not None else covered
            if covered is not None and (covered >= closed if own else covered > closed):
                if not own:  # 証明書は、決算日の後に取っても、申告の前なら前の期のまま
                    newer.append(f"{doc['名前']}（{dates.format_date(found.day)}の日付）")
                continue
            if found is not None:
                stale.append(f"{doc['名前']}（{dates.format_date(found.day)}の日付）")
            passed.append(doc["名前"])
        if passed and closed <= deadline and ((today - closed).days <= DAYS_AFTER_CLOSING or stale):
            text = (f"決算日（{dates.format_date(closed)}）を過ぎました。この決算の申告をした後は、直近の期が入れ替わります"
                    f"（期の入れ替わり）。{head}までに申告をするなら、{'、'.join(passed)}は申告の後に取ったもので出してください")
            if stale:
                text += f"。今ある原本の {'、'.join(stale)} は決算日より前に取ったもので、申告の後は直近の期に足りなくなります"
            notes.append(text)
        if newer and (today - closed).days <= DAYS_AFTER_CLOSING:
            notes.append(f"今ある原本の {'、'.join(newer)} は、決算日（{dates.format_date(closed)}）の後に取ったものです。"
                         "直近の期（この決算の期）が入っているかを確かめてください")
        if coming <= deadline:
            names = "、".join(doc["名前"] for doc in docs)
            notes.append(f"{head}までに決算日（{dates.format_date(coming)}）を迎えます。その決算の申告の後は直近の期が"
                         f"入れ替わる（期の入れ替わり）ので、申告の前に取った{names}は使えなくなります。取るのは申告の後にしてください")
    return notes


# ---- 外部への依頼と待ち（K2。SPEC F6・T6-6） ----


def find_doc(data: Dict, name: str) -> Optional[Dict]:
    """制度データの書類のうち、名前が同じもの（なければ、見比べる形で当たるもの）。"""
    docs = [d for d in data.get("書類") or [] if isinstance(d, dict) and isinstance(d.get("名前"), str)] \
        if isinstance(data.get("書類"), list) else []
    exact = [d for d in docs if task_ledger.same_doc(d["名前"], name)]
    if exact:
        return exact[0]
    near = [d for d in docs if names_match(d["名前"], name)]
    return near[0] if near else None


def request_due(data: Dict, plan: "Plan", open_stages: List[Tuple[Dict, StageRow]], doc: Optional[Dict]
                ) -> Tuple[Due, str]:
    """依頼の締切（制度データの「依頼の締切」、なければその書類を使う、済んでいない段階の期限）と、何の締切かの文。"""
    if doc is None:
        return Due(how="制度データにない書類なので、締切が分かりません"), ""
    node = doc.get("依頼の締切")
    if isinstance(node, dict) and node.get("値") is not None:
        due = plan.compute(node["値"])
        due.check = due.check or node.get("状態") in CHECK_STATES
        due.sources = source_text(node) or due.sources
        return due, "依頼の締切"
    uses = doc.get("手続き") if isinstance(doc.get("手続き"), list) else []
    for stage, row in open_stages:
        if stage.get("id") in uses:
            if row.due is None:
                return Due(how=f"{row.name}に期限の決め方がありません"), f"{row.name}の締切"
            return row.due, f"{row.name}の締切"
    return Due(how="この書類を使う段階は、もう済んでいます"), ""


def request_lead(req: task_ledger.Request, doc: Optional[Dict], facts: List[Dict]
                 ) -> Tuple[Optional[Dict[str, Any]], str]:
    """依頼の目安の日数（期間）と出どころ。台帳の値、制度データ、会社の記録の順。分からなければ (None, "")。"""
    if req.days is not None:
        return {"数": req.days, "単位": "日"}, req.days_source or "期限の台帳"
    node = doc.get("依頼の目安の日数") if isinstance(doc, dict) else None
    if isinstance(node, dict):
        period = parse_period(node.get("値"))
        if period is not None:
            where = "、".join(source_text(node))
            return period, f"制度データ（{where}）" if where else "制度データ"
    found = recorded_lead(facts, req.doc)
    if found is None and isinstance(doc, dict):
        found = recorded_lead(facts, doc["名前"])
    if found is not None:
        return found
    return None, ""


def _request_tasks(status: CaseStatus, data: Dict, plan: "Plan", open_stages: List[Tuple[Dict, StageRow]],
                   requests: List[task_ledger.Request], facts: List[Dict], today: date) -> List[Task]:
    tasks = []
    for req in requests:
        doc = find_doc(data, req.doc)
        due, what_due = request_due(data, plan, open_stages, doc)
        lead, lead_source = request_lead(req, doc, facts)
        name = req.doc
        to = req.to  # 依頼先（台帳の値、なければ制度データの依頼先。「出す人」は申請する人の区分なので使わない）
        if not to and isinstance(doc, dict):
            node = doc.get("依頼先")
            to = str(node.get("値") or "") if isinstance(node, dict) else ""
        order = next((row.order for stage, row in open_stages
                      if isinstance(doc, dict) and stage.get("id") in (doc.get("手続き") or [])), 0)
        task = Task(case=status.name, order=order, stage=what_due, what=f"{name}を頼む" + (f"（{to}へ）" if to else ""),
                    due=due, kind=REQUEST, doc=name, state=req.state)
        asker = req.asker or "（まだ決めていません）"
        task.who = f"頼む：{asker}／書く：外部" + (f"（{to}）" if to else "")
        if lead is not None:
            task.lead = f"{period_text(lead)}（{lead_source}）" if lead_source else period_text(lead)
            if due.dated:
                task.start = sub_period(due.first, lead)
        if req.state == task_ledger.REQUESTED and req.requested is not None and lead is not None:
            expected = add_period(req.requested, lead)
            if expected is not None and expected < today:
                task.state = task_ledger.WAITING
                task.notes.append(f"頼んだ日（{dates.format_date(req.requested)}）から目安の{period_text(lead)}を過ぎました。"
                                  "届いたかを確かめてください")
        if what_due:
            task.notes.append(f"締切は{what_due}")
        if lead is None and not req.finished:
            task.notes.append("目安の日数をまだ聞いていません（頼んでから届くまでの日数を社長に聞くと、始める日を出せます）")
        if req.requested is not None:
            task.notes.append(f"頼んだ日：{dates.format_date(req.requested)}")
        if req.arrived is not None:
            task.notes.append(f"届いた日：{dates.format_date(req.arrived)}"
                              + (f"（{req.arrived_doc}）" if req.arrived_doc else ""))
        tasks.append(task)
    return tasks


FIXED_NOTE = "通知に書かれた日付"  # 日付で示された期限の作業に添える文の頭


def fixed_tasks(status: CaseStatus, dues: Sequence[task_ledger.FixedDue]) -> List[Task]:
    """期限の台帳の「提出」（事務局などが日付で示した期限。差し戻しの出し直しの期限など）を作業にする。

    日付は通知の中の事実なので「確定」とし、出典を添える。段階は今の段階（段階が分からなければ空）。
    """
    now = next((row for row in status.stages if row.state == "今"), None)
    tasks = []
    for d in dues:
        due = Due(first=d.day, last=d.day, confirmed=True, sources=[d.source] if d.source else [])
        task = Task(case=status.name, order=now.order if now is not None else 0, stage=now.name if now is not None else "",
                    what=f"{d.name}の期限", due=due, kind=SUBMIT, state=d.state if d.finished else "", fixed=True)
        task.notes.append(FIXED_NOTE)  # 出典は Due.sources から「出典：」として添える
        tasks.append(task)
    return tasks


def _document_notes(folder: Path, status: CaseStatus, data: Dict, stage: Dict, ledger: Optional[List[str]],
                    ledger_problem: str, where: str = "") -> List[str]:
    """今の段階の必須の書類の揃い具合を status.documents に入れ、作業に添える文を返す。

    where は段階のフォルダ（繰り返しの報告は年のフォルダ「4_効果報告/2年目」）。省けば今の段階のフォルダ。
    """
    stage_id = stage.get("id")
    docs = data.get("書類")
    where = where or status.current_folder
    attached = _list_files(folder, f"{CASES_DIR}/{status.name}/{where}/{ATTACH_DIR}") if where else []
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
    """作業を、期限切れ・今日やること・近い締切・遅れている作業と、それより先（later）、日付のないもの（undated）に分ける。

    始める日で分けるのは、まだ始めていない作業だけ（依頼した・待っているものは、締切で分ける）。始める日が近い締切の日数の
    内なら、締切が先でも近い締切に入れる（頼むのが遅れないように）。済んだもの（task.done）は渡さない（build が分ける）。
    """
    groups: Dict[str, List[Task]] = {g: [] for g in GROUPS}
    later: List[Task] = []
    undated: List[Task] = []
    for task in tasks:
        d = task.due
        start = task.start if task.state in ("", task_ledger.NOT_YET) else None
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
        elif (min(d.first, start) if start is not None else d.first) <= today + timedelta(days=near_days):
            groups[NEAR].append(task)
        else:
            later.append(task)
    for items in groups.values():
        items.sort(key=Task.sort_key)
    later.sort(key=Task.sort_key)
    undated.sort(key=lambda t: (t.case, t.order, t.what))
    return groups, later, undated


def build(folder: Path, today: Optional[date] = None, near_days: Optional[int] = None) -> Overview:
    """会社のフォルダの、すべての案件の期限と作業をまとめる。今日は差し替えた日付を含む（lib/dates.py）。

    近い締切の日数は、渡されなければ `.hojokin/設定.json` から取る（なければ30日。lib/task_ledger.near_days）。
    今日の日付の差し替えや近い締切の日数が読めないときは ValueError（呼ぶ側が伝える）。
    """
    folder = Path(folder)
    substituted = dates.substituted_today(folder) is not None
    day = today or dates.today(folder)
    days = task_ledger.near_days(folder) if near_days is None else near_days
    names, problem = list_cases(folder)
    problems = [problem] if problem else []
    cases: List[CaseStatus] = []
    tasks: List[Task] = []
    if names:
        submissions, sub_problem = _submissions(folder)
        if sub_problem:
            problems.append(sub_problem)
        originals, ledger_problem = _ledger_originals(folder)
        ledger = None if originals is None else [o.kind for o in originals]
        events, events_problem = event_ledger.events_by_case(folder)
        if events_problem:
            problems.append(events_problem)
        requests, requests_problem = task_ledger.requests_by_case(folder)
        if requests_problem and requests_problem not in problems:
            problems.append(requests_problem)
        fixed, fixed_problem = task_ledger.dues_by_case(folder)
        if fixed_problem and fixed_problem not in problems:
            problems.append(fixed_problem)
        facts = _company_facts(folder)
        for name in names:
            status = case_status(folder, name, submissions, ledger, ledger_problem, events.get(name),
                                 originals=originals, requests=requests.get(name), facts=facts, today=day)
            status.tasks += fixed_tasks(status, fixed.get(name) or [])
            cases.append(status)
            tasks += status.tasks
        known = set(names)
        for case, items in requests.items():
            if case not in known:
                problems.append(f"期限の台帳の依頼（{'、'.join(r.doc for r in items)}）の案件「{case}」の"
                                "フォルダがありません")
        for case, dues in fixed.items():
            if case not in known:
                problems.append(f"期限の台帳の期限（{'、'.join(d.name for d in dues)}）の案件「{case}」の"
                                "フォルダがありません")
    done = sorted((t for t in tasks if t.done), key=Task.sort_key)
    groups, later, undated = classify([t for t in tasks if not t.done], day, days)
    return Overview(today=day, near_days=days, substituted=substituted, cases=cases, groups=groups,
                    later=later, undated=undated, problems=problems, done=done)
