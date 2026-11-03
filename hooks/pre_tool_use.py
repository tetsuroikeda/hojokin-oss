"""PreToolUse（Claude が道具を使う前）。DESIGN 5章の止める決まりを、ここに置く。

hooks.json の matcher で、書き込みの道具（Write・Edit・NotebookEdit）、Bash、
ブラウザの道具・画面を操作する機能を受け取る（Python が動かないときは run.sh が拒む）。
別の matcher で、読む道具（Read・Grep・Glob など）も受け取り、会社のフォルダの外を読むことを拒む（outside_read.py）。
ブラウザの道具・画面を操作する機能は、画面入力の守り（lib/browser_guard.py）が判定する。
版の名前のファイルを拒むことは、後のタスクでここに足す。

会社のフォルダの外への書き込みは、設定の blockWritesOutsideWorkingDirectories で止める決まりだが、
デスクトップアプリの Claude Code（2.1.309）では効かなかった（実験 E6）。そのため、ここでも拒む。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import outside_read
from lib import browser_guard

WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _outside_write(data: dict, folder: Path) -> Optional[dict]:
    """会社のフォルダの外に書こうとしていれば、拒む判定を返す。

    場所の解き方は、外を読む判定と同じにする（outside_read.py の説明）。
    相対の場所は hook の入力の cwd から解き、別名と「..」をたどり、名前の文字の形を NFC にそろえて比べる。
    """
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    real_target = outside_read.resolve(str(raw), outside_read.tool_cwd(data, folder))
    if outside_read.is_inside(real_target, outside_read.real_path(folder)):
        return None
    # Claude Code 自身の計画のファイルは、設定の blockWrites と同じく通す
    plans = outside_read.real_path(Path.home() / ".claude" / "plans")
    if outside_read.is_inside(real_target, plans):
        return None
    return _deny(
        f"会社のフォルダの外には書き込めません（{raw}）。"
        "会社のフォルダの中に書いてください。外のファイルを使いたいときは、社長に場所を聞いて、取り込みの道具で写してください。"
    )


def handle(data: dict, folder: Path) -> Optional[dict]:
    tool = data.get("tool_name")
    if browser_guard.is_browser_tool(tool):
        # 画面入力の守り（S4。lib/browser_guard.py）
        return browser_guard.pre_tool_use(data, folder)
    if tool in WRITE_TOOLS:
        return _outside_write(data, folder)
    if tool in outside_read.READ_TOOLS:
        return outside_read.check(data, folder)
    return None
