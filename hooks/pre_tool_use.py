"""PreToolUse（Claude が道具を使う前）。DESIGN 5章の止める決まりを、ここに置く。

hooks.json の matcher で、書き込みの道具（Write・Edit・NotebookEdit）、Bash、
ブラウザの道具・画面を操作する機能を受け取る（Python が動かないときは run.sh が拒む）。
別の matcher で、読む道具（Read・Grep・Glob など）も受け取り、会社のフォルダの外を読むことを拒む（outside_read.py）。
版の名前のファイルを拒むこと、画面入力の守り（S4）を、後のタスクでここに足す。

会社のフォルダの外への書き込みは、設定の blockWritesOutsideWorkingDirectories で止める決まりだが、
デスクトップアプリの Claude Code（2.1.309）では効かなかった（実験 E6）。そのため、ここでも拒む。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import outside_read

WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _is_inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _outside_write(data: dict, folder: Path) -> Optional[dict]:
    """会社のフォルダの外に書こうとしていれば、拒む判定を返す。"""
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    target = Path(os.path.expanduser(str(raw)))
    if not target.is_absolute():
        target = folder / target
    # 別名（シンボリックリンク）と「..」をたどった先で比べる
    real_target = Path(os.path.realpath(target))
    real_folder = Path(os.path.realpath(folder))
    if _is_inside(real_target, real_folder):
        return None
    # Claude Code 自身の計画のファイルは、設定の blockWrites と同じく通す
    plans = Path(os.path.realpath(Path.home() / ".claude" / "plans"))
    if _is_inside(real_target, plans):
        return None
    return _deny(
        f"会社のフォルダの外には書き込めません（{raw}）。"
        "会社のフォルダの中に書いてください。外のファイルを使いたいときは、社長に場所を聞いて、取り込みの道具で写してください。"
    )


def handle(data: dict, folder: Path) -> Optional[dict]:
    tool = data.get("tool_name")
    if tool in WRITE_TOOLS:
        return _outside_write(data, folder)
    if tool in outside_read.READ_TOOLS:
        return outside_read.check(data, folder)
    return None
