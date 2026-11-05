"""期限の台帳（`記録/期限の台帳.json`）の「作業」と、近い締切の日数の設定（SPEC F6、DESIGN 4.5・4.6・6章。TASKS K1・K2）。

期限の台帳は2つの並びを持つ。
- 「出来事」：採択発表日・交付決定日などの日付と、見込みか確定か、出典（lib/event_ledger.py。M10）。
- 「作業」：社長の言葉と届いた書類から変わる、作業ごとの状態（このファイル）。

締切と始める日は、読むたびに制度データの「期限の決め方」と出来事から計算し直す（lib/deadlines.py）。台帳には、計算できない
もの（状態・だれがするか・依頼した日・届いた日・目安の日数とその出どころ・出典）だけを残す（K1 で決めた。仮）。
計算した日付を台帳に書き戻すと、開くたびに版の履歴が増え、日付の差し替えでも中身が揺れるため。台帳を書くのは道具だけで、
開いたときの hook は読むだけにする（hook が書くと、次に社長が送ったときに「社長が手で変えた」と残ってしまう）。

作業の1件（いまは「依頼」の種類だけを道具が書く。K2）

    {"種類": "依頼", "案件": "2026_省力化（一般型）第9回", "書類": "金融機関確認書",
     "依頼先": "信用金庫", "目安の日数": 14, "目安の出どころ": "社長の答え（2026-11-16）",
     "状態": "依頼した", "頼む人": "社長", "依頼した日": "2026-11-18", "届いた日": "", "届いた書類": "",
     "記録した日": "2026-11-18"}

- 同じ案件・同じ種類・同じ書類の作業は1件。書くたびに、その1件を書き換える（前の中身は版の履歴に残る）。
- 状態は、まだ・依頼した・待っている・届いた・済み（DESIGN 4.5）。だれがするかは、社長・担当者・外部。
  依頼では、頼む人（社長か担当者）を「頼む人」に、書く人（外部）を「依頼先」から示す。
- ほかの欄・ほかの並び（出来事など）は、書くときに消さない。

近い締切の日数は、`.hojokin/設定.json` の「近い締切の日数」（はじめは30日。SPEC F6）。会社のフォルダの設定が `.hojokin/` の
Edit を拒むので、社長が会話で変えたときは、道具（skills/junbi/scripts/kigen.py）がここの set_near_days で書く。

場所の確かめ（lib/places.py。DESIGN 5章）：途中のフォルダか書く先そのものが別名なら、読まず、書かない。
hook（開いたときの期限の組み立て）からも読むので、標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import company, event_ledger, place_text, places

TASKS_KEY = "作業"
REQUEST = "依頼"
KINDS = ("提出", "取り直し", REQUEST, "証拠", "義務")  # DESIGN 4.5
NOT_YET = "まだ"
REQUESTED = "依頼した"
WAITING = "待っている"
ARRIVED = "届いた"
DONE = "済み"
STATES = (NOT_YET, REQUESTED, WAITING, ARRIVED, DONE)
FINISHED = (ARRIVED, DONE)
WHO = ("社長", "担当者", "外部")
ASKERS = ("社長", "担当者")  # 依頼を頼む人

NEAR_KEY = "近い締切の日数"
NEAR_DEFAULT = 30
NEAR_MAX = 366
NEAR_ACTION = "近い締切の日数を設定に残していません"
LEDGER_ACTION = "作業の状態を期限の台帳に残していません"


class TaskLedgerError(ValueError):
    """作業を読めない・書けない（別名、形が違う、値が違う）。書くときは何も書いていない。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _days(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@dataclass
class Request:
    """外部への依頼の1件（台帳の「作業」のうち、種類が「依頼」のもの）。"""

    case: str
    doc: str  # 書類の名前（制度データの書類の名前か、社長の言い方）
    to: str = ""  # 依頼先（信用金庫・業者・商工会議所 など）
    days: Optional[int] = None  # 頼んでから届くまでの目安の日数
    days_source: str = ""  # 目安の日数の出どころ（社長の答え・制度データ・会社の記録）
    state: str = NOT_YET
    asker: str = ""  # 頼む人（社長・担当者）
    requested: Optional[date] = None
    arrived: Optional[date] = None
    arrived_doc: str = ""  # 届いた書類（会社のフォルダからの場所）
    recorded: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)  # ほかの欄（消さずに残す）

    def to_json(self) -> Dict[str, Any]:
        out = dict(self.extra)
        out.update({
            "種類": REQUEST, "案件": self.case, "書類": self.doc, "依頼先": self.to,
            "目安の日数": self.days, "目安の出どころ": self.days_source, "状態": self.state,
            "頼む人": self.asker,
            "依頼した日": self.requested.isoformat() if self.requested else "",
            "届いた日": self.arrived.isoformat() if self.arrived else "",
            "届いた書類": self.arrived_doc, "記録した日": self.recorded,
        })
        return out

    @property
    def finished(self) -> bool:
        return self.state in FINISHED


KNOWN_FIELDS = ("種類", "案件", "書類", "依頼先", "目安の日数", "目安の出どころ", "状態", "頼む人", "依頼した日",
                "届いた日", "届いた書類", "記録した日")


def parse_request(entry: Any) -> Optional[Request]:
    if not isinstance(entry, dict) or entry.get("種類") != REQUEST:
        return None
    case, doc = entry.get("案件"), entry.get("書類")
    if not isinstance(case, str) or not case.strip() or not isinstance(doc, str) or not doc.strip():
        return None
    state = entry.get("状態") if entry.get("状態") in STATES else NOT_YET
    return Request(
        case=nfc(case.strip()), doc=nfc(doc.strip()), to=str(entry.get("依頼先") or ""),
        days=_days(entry.get("目安の日数")), days_source=str(entry.get("目安の出どころ") or ""), state=state,
        asker=str(entry.get("頼む人") or ""), requested=_date(entry.get("依頼した日")),
        arrived=_date(entry.get("届いた日")), arrived_doc=str(entry.get("届いた書類") or ""),
        recorded=str(entry.get("記録した日") or ""),
        extra={k: v for k, v in entry.items() if k not in KNOWN_FIELDS})


def same_doc(a: str, b: str) -> bool:
    """台帳の1件を見分けるための、書類の名前の比べ方（NFKC と空白だけをそろえる。似た名前の別の書類と混ぜない）。"""
    def key(text: str) -> str:
        return "".join(unicodedata.normalize("NFKC", text).split())
    return key(a) == key(b)


def _tasks(data: Dict) -> List[Any]:
    tasks = data.get(TASKS_KEY, [])
    if not isinstance(tasks, list):
        raise TaskLedgerError(f"期限の台帳（{event_ledger.LEDGER_FILE}）の「{TASKS_KEY}」の形が違います（[ ] にしてください）")
    return tasks


def load(folder: Path) -> Dict:
    """期限の台帳の全体（lib/event_ledger.load）。「作業」の形も確かめる。"""
    try:
        data = event_ledger.load(folder)
    except event_ledger.LedgerError as error:
        raise TaskLedgerError(str(error)) from error
    _tasks(data)
    return data


def requests_by_case(folder: Path) -> Tuple[Dict[str, List[Request]], str]:
    """案件ごとの依頼と、読めなかったわけ（読めたら空）。例外は出さない（開いたときの組み立てを止めないため）。"""
    try:
        data = load(Path(folder))
    except TaskLedgerError as error:
        return {}, f"{error}（記録した依頼の状態を使わずに、期限を組み立てました）"
    found: Dict[str, List[Request]] = {}
    for entry in data.get(TASKS_KEY) or []:
        req = parse_request(entry)
        if req is not None:
            found.setdefault(req.case, []).append(req)
    return found, ""


def find_request(requests: List[Request], doc: str) -> Optional[Request]:
    return next((r for r in requests if same_doc(r.doc, doc)), None)


def save_request(folder: Path, req: Request) -> Optional[Request]:
    """依頼を1件残す（同じ案件・同じ書類のものがあれば書き換える）。前に残っていた1件を返す（なければ None）。

    書く前に、`記録/` と台帳そのものに別名がないかを確かめる（lib/places.py）。別名があるとき、台帳が読めないときは、
    何も書かずに TaskLedgerError。
    """
    folder = Path(folder)
    if req.state not in STATES:
        raise TaskLedgerError(f"依頼の状態（{req.state}）は、{'・'.join(STATES)} のどれかにしてください")
    if req.asker and req.asker not in WHO:
        raise TaskLedgerError(f"頼む人（{req.asker}）は、{'・'.join(ASKERS)} のどちらかにしてください")
    problem = place_text.write_problem(folder, event_ledger.LEDGER_FILE, LEDGER_ACTION)
    if problem:
        raise TaskLedgerError(problem)
    data = load(folder)
    kept: List[Any] = []
    previous = None
    for entry in _tasks(data):
        old = parse_request(entry)
        if old is not None and old.case == nfc(req.case) and same_doc(old.doc, req.doc):
            previous = previous or old
            continue
        kept.append(entry)
    kept.append(req.to_json())
    data[TASKS_KEY] = kept
    try:
        event_ledger.write(folder, data)
    except event_ledger.LedgerError as error:
        raise TaskLedgerError(str(error)) from error
    return previous


# ---- 近い締切の日数 ----


def near_days(folder: Optional[Path]) -> int:
    """`.hojokin/設定.json` の近い締切の日数。なければはじめの値（30日）。形が違えば ValueError（黙って30日に戻さない）。"""
    value = company.load_settings(folder).get(NEAR_KEY)
    if value is None:
        return NEAR_DEFAULT
    where = f"{company.MARKER_DIR}/{company.SETTINGS_FILE} の「{NEAR_KEY}」"
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= NEAR_MAX:
        raise ValueError(f"{where}（{value}）は、1から{NEAR_MAX}までの日数（数字）で書いてください")
    return value


def set_near_days(folder: Path, days: int) -> Optional[int]:
    """近い締切の日数を設定に残す。前の値を返す（なかったら None）。別名・読めない設定のときは何も書かずに TaskLedgerError。"""
    folder = Path(folder)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= NEAR_MAX:
        raise TaskLedgerError(f"近い締切の日数（{days}）は、1から{NEAR_MAX}までの日数にしてください")
    rel = f"{company.MARKER_DIR}/{company.SETTINGS_FILE}"
    problem = place_text.write_problem(folder, rel, NEAR_ACTION)
    if problem:
        raise TaskLedgerError(problem)
    try:
        settings = company.load_settings(folder)
    except ValueError as error:
        raise TaskLedgerError(f"{error}。{NEAR_ACTION}") from error
    before = settings.get(NEAR_KEY)
    settings[NEAR_KEY] = days
    path = places.actual(folder, rel, partial=True)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError as error:
        raise TaskLedgerError(f"{rel} を書けませんでした（{error}）") from error
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return before if isinstance(before, int) and not isinstance(before, bool) else None
