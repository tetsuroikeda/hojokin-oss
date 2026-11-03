"""実験 E3 の hook。受け取った場面を作業フォルダの .e3/hooks.jsonl に1行ずつ書く。

あわせて、次のことを試す。
- SessionStart：開いたときの情報（合言葉）を Claude に渡す。
- PreToolUse：Bash のコマンドに E3_DENY があれば、JSON で拒む。
- PreToolUse：AskUserQuestion を、EVAL_E3_ANSWER の値で答える（値があるときだけ）。
- SubagentStop-save：審査役に見立てた subagent の最後の報告を、本体を通さずに保存する。
  控え（確かめの番号と計画書のハッシュ）と結び付け、ハッシュが今の計画書と合うかも書く。
- PreToolUse（SubagentHandback）：auto モードで subagent が報告を渡す道具。中身を別に保存する。

hook の python3 は Python 3.9 のことがある（E4）ので、3.9 で動く書き方にする。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

SESSION_WORD = "あさがお3"
DENY_WORD = "すすき8"
CUT = 2000


def project_dir(payload: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())


def cut(value, limit: int = CUT):
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"…（{len(text)}字を{limit}字に切った）"


def write_log(base: Path, event: str, payload: dict, note: str = "") -> None:
    keys = [
        "session_id", "permission_mode", "source", "tool_name", "tool_use_id",
        "agent_id", "agent_type", "agent_transcript_path", "transcript_path",
        "stop_hook_active", "error", "reason", "prompt",
    ]
    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "hook_event_name": payload.get("hook_event_name"),
        "cwd": payload.get("cwd"),
        "python": sys.version.split()[0],
        "env": {
            k: os.environ.get(k)
            for k in ["HOME", "CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA",
                      "CLAUDE_CODE_ENTRYPOINT", "EVAL_E3_ANSWER"]
        },
        "payload_keys": sorted(payload.keys()),
    }
    for k in keys:
        if k in payload:
            entry[k] = cut(payload[k], 500)
    for k in ["tool_input", "tool_response", "last_assistant_message"]:
        if k in payload:
            entry[k] = cut(payload[k])
    if note:
        entry["note"] = note
    log_dir = base / ".e3"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "hooks.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))


def on_pre_tool_use(base: Path, payload: dict) -> str:
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool == "Bash" and "E3_DENY" in str(tool_input.get("command", "")):
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"E3 の hook が JSON で拒みました（理由の合言葉：{DENY_WORD}）",
            }
        })
        return "deny(json)"
    if tool == "AskUserQuestion":
        answer = os.environ.get("EVAL_E3_ANSWER")
        if not answer:
            return "AskUserQuestion: 答えずに通す"
        questions = tool_input.get("questions") or []
        answers = {}
        for q in questions:
            labels = [o.get("label", "") for o in q.get("options") or []]
            chosen = next((label for label in labels if answer in label), labels[0] if labels else answer)
            answers[q.get("question", "")] = chosen
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {"questions": questions, "answers": answers},
            }
        })
        return f"AskUserQuestion: hook が答えた {json.dumps(answers, ensure_ascii=False)}"
    if tool == "SubagentHandback":
        save_review(base, payload, str(tool_input.get("message", "")), "PreToolUse.SubagentHandback.tool_input.message")
        return "SubagentHandback の報告を保存した"
    return ""


def save_review(base: Path, payload: dict, report: str, where: str) -> None:
    """審査役の報告を、控えと結び付けて 記録/審査役の結果/ に保存する。"""
    note_path = base / "記録" / "審査に渡すもの" / "控え.json"
    try:
        note = json.loads(note_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        note = {"控えが読めない": str(e)}
    plan_path = base / "記録" / "審査に渡すもの" / "計画書.md"
    try:
        current = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    except OSError:
        current = None
    number = str(note.get("確かめの番号") or "番号なし")
    out_dir = base / "記録" / "審査役の結果"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if where.startswith("SubagentStop") else "_handback"
    result = {
        "確かめの番号": number,
        "控えのハッシュ": note.get("計画書のハッシュ"),
        "今の計画書のハッシュ": current,
        "ハッシュが合う": bool(current) and note.get("計画書のハッシュ") == current,
        "取り出した所": where,
        "agent_type": payload.get("agent_type"),
        "agent_id": payload.get("agent_id"),
        "permission_mode": payload.get("permission_mode"),
        "報告": report,
    }
    (out_dir / f"{number}{suffix}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {"_raw": raw[:CUT]}
    base = project_dir(payload)
    note = ""
    try:
        if event == "SessionStart":
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"E3 の開いたときの合言葉は「{SESSION_WORD}」です。",
                }
            })
            note = "合言葉を渡した"
        elif event == "PreToolUse":
            note = on_pre_tool_use(base, payload)
        elif event == "SubagentStop-save":
            save_review(base, payload, str(payload.get("last_assistant_message") or ""),
                        "SubagentStop.last_assistant_message")
            note = "審査役の報告を保存した"
    except Exception as e:  # 試しの hook なので、失敗しても記録だけ残して通す
        note = f"hook の中で失敗：{type(e).__name__}: {e}"
    write_log(base, event, payload, note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
