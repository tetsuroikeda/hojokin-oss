"""会社のフォルダの外を読まない（DESIGN 5章・4.7）の、PreToolUse の部分。

ファイルの道具が外を読むことは、設定の blockReadsOutsideWorkingDirectories で止める。
ただ、ユーザーの設定にある追加の作業フォルダは、会社のフォルダで開いても作業フォルダに数えられ、
設定では止まらないと見られる（実験 E6）。そのため、ここでも、外を読む Read・Grep・Glob などを拒む。

設定と同じく、Claude Code 自身が要るファイルは通す（公式文書の「apart from files Claude Code itself needs」）。
通すのは、計画のファイル（~/.claude/plans）と、このセッションの置き場（会話の記録の隣の
<セッションの ID>/。大きな道具の結果が tool-results/ に置かれ、Claude はそれを Read で読む）だけにする。
~/.claude の全体は通さない（認証情報などがあるため）。

hooks.json の matcher で、読む道具だけを受け取る（Python が動かないときは拒まない。設定が止める）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

# 道具の名前と、場所を受け取る欄
READ_TOOLS = {
    "Read": ("file_path",),
    "NotebookRead": ("notebook_path",),
    "Grep": ("path",),
    "Glob": ("path",),
    "LS": ("path",),
}
GLOB_CHARS = set("*?[{")


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _is_inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def _resolve(raw: str, base: Path) -> Path:
    """~ と相対の場所を、base からの場所にし、別名（シンボリックリンク）と「..」をたどる。"""
    target = Path(os.path.expanduser(raw))
    if not target.is_absolute():
        target = base / target
    return _real(target)


def _glob_prefix(pattern: str) -> str:
    """Glob の型のうち、* などの記号が出る前の部分（どのフォルダの下を探すか）。"""
    parts = pattern.split("/")
    fixed: List[str] = []
    for part in parts:
        if GLOB_CHARS & set(part):
            break
        fixed.append(part)
    if len(fixed) == len(parts):
        # 記号がない型は、最後の部分もファイルの名前として含める
        return pattern
    if fixed == [""]:
        return "/"
    return "/".join(fixed)


def _allowed_claude_files(data: dict) -> List[Path]:
    """Claude Code 自身が要るファイルの置き場（設定の blockReads と同じく通す）。"""
    allowed = [_real(Path.home() / ".claude" / "plans")]
    transcript = data.get("transcript_path")
    if transcript and str(transcript).endswith(".jsonl"):
        allowed.append(_real(Path(os.path.expanduser(str(transcript))[: -len(".jsonl")])))
    return allowed


def _targets(data: dict, folder: Path) -> List[str]:
    """道具が読もうとしている場所の一覧（指定がなければ空。そのときは今いるフォルダを読む）。"""
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    targets = [str(tool_input[key]) for key in READ_TOOLS.get(tool, ()) if tool_input.get(key)]
    if tool == "Glob" and tool_input.get("pattern"):
        base = str(tool_input.get("path") or folder)
        pattern = str(tool_input["pattern"])
        prefix = _glob_prefix(pattern)
        if prefix:
            expanded = os.path.expanduser(prefix)
            targets.append(expanded if os.path.isabs(expanded) else os.path.join(base, expanded))
    return targets


def check(data: dict, folder: Path) -> Optional[dict]:
    """会社のフォルダの外を読もうとしていれば、拒む判定を返す。"""
    real_folder = _real(folder)
    allowed = None
    for raw in _targets(data, folder):
        target = _resolve(raw, folder)
        if _is_inside(target, real_folder):
            continue
        if allowed is None:
            allowed = _allowed_claude_files(data)
        if any(_is_inside(target, place) for place in allowed):
            continue
        return _deny(
            f"会社のフォルダの外は読めません（{raw}）。"
            "外のファイルを使いたいときは、社長に場所を聞いて、取り込みの道具で会社のフォルダに写してから読んでください。"
        )
    return None
