"""出来事の日付（採択発表日・交付決定日など）を、期限の台帳（`記録/期限の台帳.json`）の「出来事」に持つ
（SPEC F6「見込みと確定」・F12、DESIGN 4.5・4.7・6章。TASKS M10）。

期限の台帳の全体（作業ごとの締切・始める日・状態・だれが・出典、見込みと確定の計算し直し）は K1 で作る。
M10 では、採択後の段階へ切り替えるときに、社長の答えか通知の原本で確かめた出来事の日付を、「出来事」の1件として
残すところだけを作る（仮。形は K1 で決め直す）。

    {
      "出来事": [
        {"案件": "2026_省力化（一般型）第9回", "名前": "採択発表日", "日付": "2027-03-10", "状態": "確定",
         "出典": "社長の答え", "記録した日": "2027-03-16"}
      ]
    }

- 名前は、制度データの期限の決め方にある「出来事」の名前（道具が決め方から選ぶ）。
  見比べるときは、NFKC にそろえ、前後の空白と終わりの「日」を除いた形で比べる（lib/deadlines.py の決まった期日の引き方と同じ）。
- 状態は「確定」（社長に確かめた日付）か「見込み」。M10 の道具が書くのは「確定」だけ。
- 同じ案件・同じ名前の出来事は1件。日付を直すと、その1件を書き換える（前の日付は版の履歴に残る）。
- ほかの欄・ほかの項目（K1 が足すもの）は、書くときに消さない。

場所の確かめ（lib/places.py。DESIGN 5章）：途中のフォルダか台帳そのものが別名なら、読まず、書かない。
hook（SessionStart の期限の組み立て）からも読むので、標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib import place_text, places

LEDGER_FILE = "記録/期限の台帳.json"
EVENTS_KEY = "出来事"
CONFIRMED = "確定"
ESTIMATE = "見込み"
STATES = (CONFIRMED, ESTIMATE)


class LedgerError(ValueError):
    """期限の台帳を読めない・書けない（別名、JSON として読めない、形が違う）。書くときは何も書いていない。"""


@dataclass
class Event:
    case: str
    name: str
    day: date
    state: str
    source: str
    recorded: str = ""

    def to_json(self) -> Dict[str, str]:
        return {"案件": self.case, "名前": self.name, "日付": self.day.isoformat(), "状態": self.state,
                "出典": self.source, "記録した日": self.recorded}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def key_of(name: Any) -> str:
    """出来事の名前を見比べる形（「採択発表日」と「採択発表」を同じものとして扱う）。"""
    if not isinstance(name, str):
        return ""
    return unicodedata.normalize("NFKC", name).strip().rstrip("日")


def _parse(entry: Any) -> Optional[Event]:
    if not isinstance(entry, dict):
        return None
    case, name, day, state = entry.get("案件"), entry.get("名前"), entry.get("日付"), entry.get("状態")
    if not isinstance(case, str) or not isinstance(name, str) or not key_of(name) or state not in STATES:
        return None
    try:
        parsed = date.fromisoformat(day) if isinstance(day, str) else None
    except ValueError:
        parsed = None
    if parsed is None:
        return None
    return Event(case=nfc(case), name=name, day=parsed, state=state, source=str(entry.get("出典") or ""),
                 recorded=str(entry.get("記録した日") or ""))


def load(folder: Path) -> Dict:
    """期限の台帳の全体。ファイルがなければ空。別名・読めない・形が違うときは LedgerError。"""
    folder = Path(folder)
    link = places.first_link(folder, LEDGER_FILE)
    if link is not None:
        raise LedgerError(f"{link} が別名（シンボリックリンク）のため、期限の台帳（{LEDGER_FILE}）を読んでいません。"
                          f"{place_text.AGAIN}")
    path = places.actual(folder, LEDGER_FILE)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LedgerError(f"期限の台帳（{LEDGER_FILE}）が JSON として読めません（{type(error).__name__}）") from error
    if not isinstance(data, dict) or not isinstance(data.get(EVENTS_KEY, []), list):
        raise LedgerError(f"期限の台帳（{LEDGER_FILE}）の形が違います（いちばん外側を {{ }}、「{EVENTS_KEY}」を [ ] にしてください）")
    return data


def events_by_case(folder: Path) -> Tuple[Dict[str, List[Event]], str]:
    """案件ごとの出来事と、読めなかったわけ（読めたら空）。例外は出さない（開いたときの組み立てを止めないため）。"""
    try:
        data = load(folder)
    except LedgerError as error:
        return {}, f"{error}（記録した出来事の日付を使わずに、期限を組み立てました）"
    found: Dict[str, List[Event]] = {}
    for entry in data.get(EVENTS_KEY) or []:
        event = _parse(entry)
        if event is not None:
            found.setdefault(event.case, []).append(event)
    return found, ""


def find(events: List[Event], name: str) -> Optional[Event]:
    key = key_of(name)
    return next((e for e in events if key_of(e.name) == key), None)


def record(folder: Path, event: Event) -> Optional[Event]:
    """出来事を1件残す（同じ案件・同じ名前のものがあれば書き換える）。前に残っていた同じ出来事を返す（なければ None）。

    書く前に、`記録/` と台帳そのものに別名がないかを確かめる（lib/places.py）。別名があるとき、今の台帳が読めないときは、
    何も書かずに LedgerError。
    """
    folder = Path(folder)
    problem = place_text.write_problem(folder, LEDGER_FILE, "出来事の日付を期限の台帳に残していません")
    if problem:
        raise LedgerError(problem)
    data = load(folder)
    entries = list(data.get(EVENTS_KEY) or [])
    previous = None
    kept = []
    for entry in entries:
        old = _parse(entry)
        if old is not None and old.case == nfc(event.case) and key_of(old.name) == key_of(event.name):
            previous = previous or old
            continue
        kept.append(entry)
    kept.append(event.to_json())
    data[EVENTS_KEY] = kept
    write(folder, data)
    return previous


def write(folder: Path, data: Dict) -> None:
    """台帳を書く（書きかけを残さないよう、一時のファイルに書いてから置き換える）。"""
    path = places.actual(folder, LEDGER_FILE, partial=True)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    # 「~*.tmp」は会社のフォルダの .gitignore にあるので、書きかけが版に残らない
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError as error:
        raise LedgerError(f"期限の台帳（{LEDGER_FILE}）を書けませんでした（{error}）") from error
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
