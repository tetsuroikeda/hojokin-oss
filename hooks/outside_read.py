"""会社のフォルダの外を読まない（DESIGN 5章・4.7）の、PreToolUse の部分。

ファイルの道具が外を読むことは、設定の blockReadsOutsideWorkingDirectories で止める。
ただ、ユーザーの設定にある追加の作業フォルダは、会社のフォルダで開いても作業フォルダに数えられ、
設定では止まらないと見られる（実験 E6）。そのため、ここでも、外を読む Read・Grep・Glob などを拒む。

設定と同じく、Claude Code 自身が要るファイルは通す（公式文書の「apart from files Claude Code itself needs」）。
通すのは、計画のファイル（~/.claude/plans）と、このセッションの置き場（会話の記録の隣の
<セッションの ID>/。大きな道具の結果が tool-results/ に置かれ、Claude はそれを Read で読む）だけにする。
~/.claude の全体は通さない（認証情報などがあるため）。

場所の解き方（書き込みの判定 pre_tool_use._outside_write も同じ関数を使う）
- 相対の場所、Glob の型の起点、Grep・Glob で path を省いたときに探す場所は、hook の入力の cwd
  （Claude がいま居るフォルダ）から解く。cwd がなければ会社のフォルダから解く。
  会社のフォルダから解くと、cwd を追加の作業フォルダに移したときに、外を読めてしまうため。
- 道具の入力から読む場所が1つも取れないときは、cwd そのものを読む場所として照らす。
- 比べる前に、名前の文字の形を NFC（濁点の付いた1文字の形）にそろえる。macOS のファイルの仕組みは
  NFD（濁点が分かれた形。Finder で作った名前など。実験 E5）と NFC を同じものとして開くが、
  os.path.realpath は形をそろえないため、そろえないと会社のフォルダの中の書類まで拒んでしまう。

hooks.json の matcher で、読む道具だけを受け取る（Python が動かないときは拒まない。設定が止める）。
"""

from __future__ import annotations

import os
import unicodedata
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


def real_path(path) -> Path:
    """別名（シンボリックリンク）と「..」をたどり、名前の文字の形を NFC にそろえた場所。"""
    return Path(unicodedata.normalize("NFC", os.path.realpath(str(path))))


def is_inside(path: Path, folder: Path) -> bool:
    """path が folder か、その下か（どちらも real_path を通した場所で渡す）。"""
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def tool_cwd(data: dict, folder: Path) -> Path:
    """Claude がいま居るフォルダ（hook の入力の cwd）。なければ会社のフォルダ。"""
    cwd = data.get("cwd")
    if not cwd:
        return Path(folder)
    path = Path(os.path.expanduser(str(cwd)))
    if not path.is_absolute():
        path = Path(folder) / path
    return path


def resolve(raw: str, base: Path) -> Path:
    """~ と相対の場所を、base からの場所にし、real_path を通す。"""
    target = Path(os.path.expanduser(str(raw)))
    if not target.is_absolute():
        target = base / target
    return real_path(target)


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
    allowed = [real_path(Path.home() / ".claude" / "plans")]
    transcript = data.get("transcript_path")
    if transcript and str(transcript).endswith(".jsonl"):
        allowed.append(real_path(os.path.expanduser(str(transcript))[: -len(".jsonl")]))
    return allowed


def _targets(data: dict, cwd: Path) -> List[str]:
    """道具が読もうとしている場所の一覧。相対の場所は cwd から解く。1つも取れなければ cwd を読むとみなす。"""
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    targets = [str(tool_input[key]) for key in READ_TOOLS.get(tool, ()) if tool_input.get(key)]
    if tool == "Glob" and tool_input.get("pattern"):
        # 型の起点は path（なければ cwd）。記号のない部分が空なら、起点そのものを探す
        base = str(tool_input.get("path") or cwd)
        prefix = os.path.expanduser(_glob_prefix(str(tool_input["pattern"])))
        if os.path.isabs(prefix):
            targets.append(prefix)
        else:
            targets.append(os.path.join(base, prefix) if prefix else base)
    if not targets:
        # Grep・Glob は path を省くと、いま居るフォルダを探す
        targets.append(str(cwd))
    return targets


def check(data: dict, folder: Path) -> Optional[dict]:
    """会社のフォルダの外を読もうとしていれば、拒む判定を返す。"""
    real_folder = real_path(folder)
    cwd = tool_cwd(data, folder)
    allowed = None
    for raw in _targets(data, cwd):
        target = resolve(raw, cwd)
        if is_inside(target, real_folder):
            continue
        if allowed is None:
            allowed = _allowed_claude_files(data)
        if any(is_inside(target, place) for place in allowed):
            continue
        return _deny(
            f"会社のフォルダの外は読めません（{raw}）。"
            "外のファイルを使いたいときは、社長に場所を聞いて、取り込みの道具で会社のフォルダに写してから読んでください。"
        )
    return None
