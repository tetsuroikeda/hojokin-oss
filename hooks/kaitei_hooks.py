"""SessionStart（開いたとき）：進行中の案件の公式資料が、公式サイトで更新されていないかを、短い時間で区切って確かめる
（SPEC F7・T7-2、DESIGN 4.7。TASKS B28）。

- 確かめるもの：`記録/資料の本文/<案件>/資料の一覧.json` の「資料」（前の回の資料は除く）の URL。1回に MAX_DOCS まで。
- 確かめ方：URL に HEAD を送り、応答の Last-Modified（更新日）が、資料を取った日（資料の一覧の「取得日」）より後なら、
  改訂かもしれないと知らせる。中身は取らない（開くたびに大きな PDF を取らないため）。取り直しと、変わったページ・制度データの差は、
  junbi の改訂の手順（fetch_documents.py → kaitei.py）で行う。
- 時間：1つの問い合わせは PER_REQUEST 秒、全部で TOTAL_SECONDS 秒まで。並べて送り、時間までに返らなかったものは待たない。
- 通信できないとき（名前を引けない、つながらない など）と、時間内に確かめ終わらないときは、「確かめられなかった」と伝える。
  どちらでも、開いたときのほかの処理は止めない（例外は握りつぶし、決まった時間で切り上げる）。
- 同じ日に確かめ終えた結果は `.hojokin/一時/公式サイトの確かめ.json` に控え、その日のうちは問い合わせ直さない
  （確かめられなかったときは控えず、次に開いたときにまた確かめる）。`.hojokin/一時/` は版の履歴に入れない。
- 環境変数 HOJOKIN_SITE_CHECK が "0" なら確かめない（開発のテストで、ほかの処理の出力を変えないため）。
会社のフォルダの中だけを読む・書く（lib/places.py）。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

HEAD_TITLE = "## 公式サイトの改訂の確かめ（開いたとき）"
TOTAL_SECONDS = 4.0
PER_REQUEST = 2.5
MAX_DOCS = 12
ENV_SWITCH = "HOJOKIN_SITE_CHECK"
CACHE_REL = ".hojokin/一時/公式サイトの確かめ.json"
TEXT_ROOT = ("記録", "資料の本文")
LIST_FILE = "資料の一覧.json"
USER_AGENT = "hojokin-plugin (official document check)"

OK = "変わっていない"
CHANGED = "更新された"
UNREACHABLE = "通信できない"
TIMEOUT = "時間切れ"
MISSING = "見つからない"
UNKNOWN = "更新日が分からない"


def documents(folder: Path) -> List[Tuple[str, Dict]]:
    """（案件、資料の一覧の1件）の並び。URL が http(s) のものだけ。"""
    from lib import place_text

    root = folder.joinpath(*TEXT_ROOT)
    if place_text.read_problem(folder, root, "資料の本文") or not root.is_dir():
        return []
    out: List[Tuple[str, Dict]] = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = case_dir / LIST_FILE
        if place_text.read_problem(folder, path, "資料の一覧") or not path.is_file():
            continue
        try:
            listed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in listed.get("資料") or [] if isinstance(listed, dict) else []:
            if isinstance(d, dict) and str(d.get("URL") or "").startswith(("https://", "http://")):
                out.append((case_dir.name, d))
    return out[:MAX_DOCS]


def head(url: str, timeout: float) -> Tuple[str, Optional[date]]:
    """URL に HEAD を送り、（結果、更新日）を返す。"""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            modified = response.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return MISSING, None
        if e.code in (403, 405, 501):  # HEAD を受け付けないサイト
            return UNKNOWN, None
        return UNREACHABLE, None
    except (socket.timeout, TimeoutError):
        return TIMEOUT, None
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            return TIMEOUT, None
        return UNREACHABLE, None
    except (OSError, ValueError):
        return UNREACHABLE, None
    if not modified:
        return UNKNOWN, None
    try:
        return OK, parsedate_to_datetime(modified).date()
    except (TypeError, ValueError, IndexError):
        return UNKNOWN, None


Header = Callable[[str, float], Tuple[str, Optional[date]]]


def run_checks(docs: List[Tuple[str, Dict]], fetch: Header = head, total: float = TOTAL_SECONDS,
               per_request: float = PER_REQUEST) -> List[Tuple[str, Dict, str, Optional[date]]]:
    """並べて確かめる。決めた時間までに返らなかったものは「時間切れ」。"""
    results: Dict[int, Tuple[str, Optional[date]]] = {}
    lock = threading.Lock()

    def work(i: int, url: str) -> None:
        try:
            got = fetch(url, per_request)
        except Exception:
            got = (UNREACHABLE, None)
        with lock:
            results[i] = got

    threads = []
    for i, (_case, d) in enumerate(docs):
        t = threading.Thread(target=work, args=(i, str(d.get("URL"))), daemon=True)
        t.start()
        threads.append(t)
    deadline = time.monotonic() + total
    for t in threads:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        t.join(left)
    with lock:
        done = dict(results)
    out = []
    for i, (case, d) in enumerate(docs):
        state, modified = done.get(i, (TIMEOUT, None))
        if state == OK and modified is not None:
            got_day = _day(d.get("取得日"))
            if got_day is not None and modified > got_day:
                state = CHANGED
        out.append((case, d, state, modified))
    return out


def _day(text) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def summary(results: List[Tuple[str, Dict, str, Optional[date]]]) -> Tuple[str, bool]:
    """（社長と Claude に渡す文、控えてよいか〈確かめ終えた〉）。"""
    def label(case: str, d: Dict) -> str:
        return f"{case}の「{d.get('名前') or d.get('id')}」（{d.get('公募回') or ''}）"

    lines = [HEAD_TITLE, ""]
    changed = [(c, d, m) for c, d, s, m in results if s == CHANGED]
    missing = [(c, d) for c, d, s, _m in results if s == MISSING]
    unreachable = [(c, d) for c, d, s, _m in results if s == UNREACHABLE]
    timeout = [(c, d) for c, d, s, _m in results if s == TIMEOUT]
    complete = not unreachable and not timeout
    if unreachable and len(unreachable) == len(results):
        lines.append("公式サイトを確かめられませんでした（通信できません）。公募要領の改訂や新しい公募回は、通信できるときに確かめます。"
                     "手元の作業は、このまま続けられます。")
    else:
        if changed:
            lines.append("公式サイトで、取った後に更新されたかもしれない資料があります（改訂か、新しい版の可能性）。"
                         "junbi の「公募要領の改訂や、新しい公募回の資料が出たとき」の手順で取り直し、変わった所と影響を社長に伝えてください：")
            for c, d, m in changed:
                lines.append(f"- {label(c, d)}：サイトの更新日 {m.isoformat()}、取った日 {d.get('取得日')}（{d.get('URL')}）")
        if missing:
            lines.append("公式サイトの場所に、資料が見つかりませんでした（場所が変わったか、新しい回に替わったかもしれません）。"
                         "ダウンロードのページで確かめてください：")
            for c, d in missing:
                lines.append(f"- {label(c, d)}（{d.get('URL')}）")
        if timeout or unreachable:
            names = "、".join(label(c, d) for c, d in timeout + unreachable)
            why = "時間内に応答がありませんでした" if timeout else "通信できませんでした"
            lines.append(f"次の資料は、確かめられませんでした（{why}）：{names}。次に開いたときに、また確かめます。")
        if not changed and not missing and not timeout and not unreachable:
            lines.append(f"公式サイトを確かめました（{len(results)}件）。取った後に更新された資料は、見つかりませんでした。")
    return "\n".join(lines), complete


def _cached(folder: Path, today: date) -> Optional[str]:
    from lib import places

    if places.first_link(folder, CACHE_REL) is not None:
        return None
    path = folder / CACHE_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("日") == today.isoformat() and isinstance(data.get("文"), str):
        return data["文"]
    return None


def _remember(folder: Path, today: date, text: str) -> None:
    from lib import place_text

    if place_text.write_problem(folder, CACHE_REL, "控えを書いていません"):
        return
    path = folder / CACHE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"日": today.isoformat(), "文": text}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def check_text(folder: Path, fetch: Header = head, total: float = TOTAL_SECONDS) -> Optional[str]:
    """開いたときに渡す文（確かめる資料がなければ None）。"""
    if os.environ.get(ENV_SWITCH) == "0":
        return None
    from lib import dates

    docs = documents(folder)
    if not docs:
        return None
    today = dates.today(folder)
    cached = _cached(folder, today)
    if cached:
        return cached
    text, complete = summary(run_checks(docs, fetch, total))
    if complete:
        _remember(folder, today, text)
    return text


def session_start(data: dict, folder: Path, output: Optional[dict]) -> Optional[dict]:
    """開いたときの出力に、公式サイトの確かめの結果を足す（ほかの処理が渡す情報は消さない。落ちても止めない）。"""
    if (data or {}).get("source") not in (None, "startup", "resume"):
        return output  # compact・clear のときは確かめ直さない
    try:
        text = check_text(folder)
    except Exception:
        text = f"{HEAD_TITLE}\n\n公式サイトを確かめられませんでした（確かめる途中で止まりました）。手元の作業は、このまま続けられます。"
    if not text:
        return output
    from lib import view_only

    return view_only.add_context(output, text)
