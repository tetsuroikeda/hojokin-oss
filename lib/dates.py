"""今日の日付（差し替えを含む）と、日本時間での表示（SPEC 共通の要件、DESIGN 6章）。

- 今日の日付は、`.hojokin/設定.json` の「今日の日付」（例：「2027-03-01」）で差し替えられる。
  差し替えたときは、日付だけをその日にし、時刻は日本時間の今の時刻を使う。
- 日本時間は、固定の +9 時間で表す。日本には夏時間がなく、Windows には時刻帯のデータがないことがあるため。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from lib import company

JST = timezone(timedelta(hours=9), "JST")
TODAY_KEY = "今日の日付"
WEEKDAYS = "月火水木金土日"

Clock = Callable[[], datetime]


def _real_clock() -> datetime:
    return datetime.now(timezone.utc)


def to_jst(dt: datetime) -> datetime:
    """日本時間に直す。時刻帯のない日時は、日本時間として扱う。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def substituted_today(folder: Optional[Path]) -> Optional[date]:
    """差し替えた今日の日付。差し替えていなければ None。"""
    value = company.load_settings(folder).get(TODAY_KEY)
    if value is None:
        return None
    where = f"{company.MARKER_DIR}/{company.SETTINGS_FILE} の「{TODAY_KEY}」"
    if not isinstance(value, str):
        raise ValueError(f"{where}は、「2027-03-01」の形の文字で書いてください")
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"{where}（{value}）が、「2027-03-01」の形の日付ではありません") from e


def now(folder: Optional[Path], clock: Optional[Clock] = None) -> datetime:
    """日本時間の今。会社のフォルダで今日の日付を差し替えていれば、日付だけをその日にする。"""
    real = to_jst((clock or _real_clock)())
    day = substituted_today(folder)
    if day is None:
        return real
    return real.replace(year=day.year, month=day.month, day=day.day)


def today(folder: Optional[Path], clock: Optional[Clock] = None) -> date:
    """日本時間の今日の日付（差し替えを含む）。"""
    return now(folder, clock).date()


def format_date(d: date) -> str:
    """例：2026年11月3日（火）"""
    return f"{d.year}年{d.month}月{d.day}日（{WEEKDAYS[d.weekday()]}）"


def format_datetime(dt: datetime) -> str:
    """日本時間で示す。例：2026年10月16日（金）17:00"""
    jst = to_jst(dt)
    return f"{format_date(jst.date())}{jst.hour}:{jst.minute:02d}"
