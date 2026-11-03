"""実験 E1 の試しの hook。

目印（.hojokin/）のあるフォルダでだけ動く。記録は ~/.hojokin-e1/hooks.jsonl。
- PreToolUse・PostToolUse（ブラウザの道具と画面を操作する機能）：入力と結果を記録する。
  入力のどこかに「拒否テスト」を含む操作と、ダブルクリックは拒む（拒めるかを見るため）。
  まとめて動かす道具（browser_batch）の中の1つずつも記録する。
- UserPromptSubmit：送られた文を記録する。/e1-probe:nyuryoku を見分けたら、
  セッションごとの「画面入力の許可」の控え（~/.hojokin-e1/許可/<セッション>.json）を作る。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hojokin-e1"
LOG_FILE = LOG_DIR / "hooks.jsonl"
PERMIT_DIR = LOG_DIR / "許可"
RESPONSE_LIMIT = 30000


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_log(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def inner_actions(tool_input: dict) -> list:
    """browser_batch の中の動作を取り出す。"""
    actions = tool_input.get("actions")
    return actions if isinstance(actions, list) else []


def should_deny(tool_input: dict) -> str:
    text = json.dumps(tool_input, ensure_ascii=False)
    if "拒否テスト" in text:
        return "入力に「拒否テスト」がある"
    if tool_input.get("action") == "double_click":
        return "ダブルクリック"
    for item in inner_actions(tool_input):
        if (item.get("input") or {}).get("action") == "double_click":
            return "まとめて動かす道具の中のダブルクリック"
    return ""


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "?"
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    folder = Path(data.get("cwd") or os.getcwd())
    if not (folder / ".hojokin").is_dir():
        return 0

    session = data.get("session_id") or "?"
    record = {
        "time": now(),
        "event": event,
        "session_id": session,
        "permission_mode": data.get("permission_mode"),
    }

    if event == "UserPromptSubmit":
        prompt = data.get("prompt", "")
        record["prompt"] = prompt[:500]
        record["input_keys"] = sorted(data.keys())
        if prompt.strip().startswith("/e1-probe:nyuryoku"):
            PERMIT_DIR.mkdir(parents=True, exist_ok=True)
            (PERMIT_DIR / f"{session}.json").write_text(
                json.dumps({"session_id": session, "time": now(), "prompt": prompt[:200]}, ensure_ascii=False),
                encoding="utf-8",
            )
            record["permit"] = "recorded"
        write_log(record)
        return 0

    tool_input = data.get("tool_input") or {}
    record["tool_name"] = data.get("tool_name")
    record["tool_input"] = tool_input
    record["inner_count"] = len(inner_actions(tool_input))
    record["permit_exists"] = (PERMIT_DIR / f"{session}.json").exists()

    if event == "PreToolUse":
        why = should_deny(tool_input)
        record["decision"] = f"deny({why})" if why else "pass"
        write_log(record)
        if why:
            deny(f"E1 の hook が拒みました：{why}（理由の合言葉：くすのき2）")
        return 0

    if event == "PostToolUse":
        record["tool_response"] = json.dumps(data.get("tool_response"), ensure_ascii=False)[:RESPONSE_LIMIT]
        write_log(record)
        return 0

    write_log(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
