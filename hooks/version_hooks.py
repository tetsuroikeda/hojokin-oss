"""版の記録と、版の名前のファイルの守り（DESIGN 5章「版を自動で残す」「版のファイルを増やさない」、
10章「書類の版」。TASKS M0a）。hook の場面ごとの入口で、それぞれの場面のファイルから1行で呼ぶ。

- SessionStart（startup・resume・clear）：閉じている間に社長が手で変えたファイルを「社長」として残す。
  理由は「社長が手で変更」。compact では残さない（応答の途中で自動の compact が走ると、ツールが変えた分を
  社長の分として残してしまうため。社長の分は、次に送ったときに残る）。
- UserPromptSubmit：社長が手で変えたファイルを「社長」として残し、社長の依頼の文を控える（Stop の理由に使う）。
  控えは `.hojokin/一時/版の記録/<セッション>.json`（版の履歴に入れない）。
  前の応答が終わらないまま次の発言が来たとき（応答を途中で止めたとき）は、それまでに変わった分は
  前の応答でツールが変えたものとして「ツール」で残す（仮。TASKS M0a の質問）。
- PreToolUse：Write・Edit・NotebookEdit で、版の名前の新しいファイルを拒む（lib/version_names.py）。
- Stop：ツールが変えたファイルを「ツール」として残す。理由は、控えた依頼の文。
  その応答で増えたファイルに版の名前のものがあれば、元のファイルにまとめるよう Claude に伝える
  （decision: block。Stop の hook で続けているとき（stop_hook_active）は、繰り返さないよう伝えない）。

会社のフォルダに Git の形の版の履歴（.git）がないときは、何もしない（.git を作らない）。
版の履歴は lib/history.py が扱う。dulwich を読み込むので、PreToolUse では読み込まない。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import outside_read
from lib import company, dates, version_names

WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
STATE_DIR = "版の記録"
RECORDED_SOURCES = ("startup", "resume", "clear")
FALLBACK_REASON = "Claude の作業（依頼の文を控えられなかった）"
INTERRUPTED_NOTE = "（応答が途中で止まったため、次の発言のときに残した）"
_SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


# ---- 社長の依頼の文の控え（版の履歴に入れない場所） ----

def _state_path(folder: Path, session_id) -> Optional[Path]:
    if not session_id:
        return None
    text = str(session_id)
    key = text if _SAFE_SESSION.match(text) else hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / STATE_DIR / f"{key}.json"


def _load_state(folder: Path, session_id) -> Optional[dict]:
    path = _state_path(folder, session_id)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _save_state(folder: Path, session_id, value: dict) -> None:
    path = _state_path(folder, session_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _now(folder: Path) -> datetime:
    """版の日時（今日の日付の差し替えを含む日本時間）。設定が読めないときは、今の時刻。"""
    try:
        return dates.now(folder)
    except ValueError:
        return datetime.now(timezone.utc)


def _record(folder: Path, who: str, reason: str) -> list:
    from lib import history  # dulwich を読み込むので、使うときだけ

    try:
        return history.record(folder, who, reason, when=_now(folder))
    except history.HistoryBusy:
        # ほかのセッションの hook が残しているところ。変わった分は、次の場面で残る
        return []


def _enabled(folder: Path) -> bool:
    return (Path(folder) / ".git").is_dir()


# ---- 場面ごとの入口 ----

def session_start(data: dict, folder: Path) -> None:
    if not _enabled(folder):
        return
    source = data.get("source")
    if source is not None and source not in RECORDED_SOURCES:
        return
    from lib import history

    _record(folder, history.OWNER, history.OWNER_REASON)


def user_prompt_submit(data: dict, folder: Path) -> None:
    if not _enabled(folder):
        return
    from lib import history

    session_id = data.get("session_id")
    state = _load_state(folder, session_id)
    if state and state.get("応答中"):
        _record(folder, history.TOOL, f"{state.get('依頼') or FALLBACK_REASON}{INTERRUPTED_NOTE}")
    else:
        _record(folder, history.OWNER, history.OWNER_REASON)
    prompt = data.get("prompt")
    _save_state(folder, session_id, {"依頼": prompt if isinstance(prompt, str) else "", "応答中": True})


def stop(data: dict, folder: Path) -> Optional[dict]:
    if not _enabled(folder):
        return None
    from lib import history

    session_id = data.get("session_id")
    state = _load_state(folder, session_id)
    reason = ((state or {}).get("依頼") or "").strip() or FALLBACK_REASON
    changes = _record(folder, history.TOOL, reason)
    if state and state.get("応答中"):
        _save_state(folder, session_id, {**state, "応答中": False})
    if data.get("stop_hook_active"):
        return None
    found = []
    for ch in changes:
        if ch.kind != history.ADDED or not version_names.checked_at_stop(ch.path):
            continue
        label = version_names.version_label(ch.path.rsplit("/", 1)[-1])
        if label is not None:
            found.append((ch.path, label, version_names.original_of(Path(folder), ch.path)))
    if not found:
        return None
    return {"decision": "block", "reason": version_names.stop_reason(found)}


def pre_tool_use(data: dict, folder: Path) -> Optional[dict]:
    """Write・Edit・NotebookEdit で、版の名前の新しいファイルを作ろうとしていれば拒む。

    会社のフォルダの外への書き込みは、先に pre_tool_use._outside_write が拒む（ここでは見ない）。
    """
    if data.get("tool_name") not in WRITE_TOOLS:
        return None
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    target = outside_read.resolve(str(raw), outside_read.tool_cwd(data, folder))
    real_folder = outside_read.real_path(folder)
    if not outside_read.is_inside(target, real_folder) or os.path.lexists(str(target)):
        return None
    label = version_names.version_label(target.name)
    if label is None:
        return None
    rel = target.relative_to(real_folder).as_posix()
    original = version_names.original_of(real_folder, rel)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": version_names.deny_reason(rel, label, original),
        }
    }
