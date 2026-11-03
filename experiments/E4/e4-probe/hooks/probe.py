"""実験 E4 の試しの hook。

場面ごとに、受け取った情報をログ（~/.hojokin-e4/hooks.jsonl）に1行ずつ書く。
目印（.hojokin/）のあるフォルダでだけ、次の試しをする。
- SessionStart：合言葉を、開いたときの情報として Claude に渡す
- PreToolUse：合言葉を含む Bash と、名前に「_v2」を含む Write を拒む（拒み方を2つ並べる）
- Stop：社長役が「E4_STOP_TEST」と送った応答の終わりに、1回だけ差し戻す
目印のないフォルダでは、場面・cwd・道具の名前だけを書き、何もしない。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hojokin-e4"
LOG_FILE = LOG_DIR / "hooks.jsonl"
STOP_FLAG = LOG_DIR / "stop-test.flag"
PASSWORD = "さくら42"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_log(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def has_marker(cwd: str) -> bool:
    return (Path(cwd) / ".hojokin").is_dir()


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "?"
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {"_raw": raw[:500]}

    cwd = data.get("cwd") or os.getcwd()
    marker = has_marker(cwd)
    record = {
        "time": now(),
        "event": event,
        "cwd": cwd,
        "marker": marker,
        "tool_name": data.get("tool_name"),
        "permission_mode": data.get("permission_mode"),
        "session_id": data.get("session_id"),
        "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
    }

    # 目印のないフォルダでは、中身を書かずに終える（ほかの会話をログに入れない）
    if not marker:
        write_log(record)
        return 0

    record["input_keys"] = sorted(data.keys())

    if event == "SessionStart":
        record["source"] = data.get("source")
        record["model"] = data.get("model")
        write_log(record)
        context = (
            f"【E4 の試し】これは SessionStart hook が {record['time']} に渡した情報です。"
            f"合言葉は「{PASSWORD}」です。社長役に合言葉を聞かれたら、この合言葉と時刻を答えてください。"
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }, ensure_ascii=False))
        return 0

    if event == "UserPromptSubmit":
        prompt = data.get("prompt", "")
        record["prompt"] = prompt[:300]
        if "E4_STOP_TEST" in prompt:
            STOP_FLAG.write_text(now(), encoding="utf-8")
            record["stop_flag"] = "set"
        write_log(record)
        return 0

    if event == "PreToolUse":
        tool_input = data.get("tool_input") or {}
        record["tool_input"] = {k: str(v)[:300] for k, v in tool_input.items()}
        command = str(tool_input.get("command", ""))
        file_path = str(tool_input.get("file_path", ""))

        if "E4_DENY_JSON" in command:
            record["decision"] = "deny(json)"
            write_log(record)
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "E4 の hook が JSON で拒みました（理由の合言葉：もみじ7）",
                }
            }, ensure_ascii=False))
            return 0

        if "E4_DENY_EXIT2" in command:
            record["decision"] = "deny(exit2)"
            write_log(record)
            print("E4 の hook が終了コード2で拒みました（理由の合言葉：いちょう3）", file=sys.stderr)
            return 2

        if data.get("tool_name") == "Write" and "_v2" in Path(file_path).name:
            record["decision"] = "deny(json,Write)"
            write_log(record)
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "E4 の hook が版の名前のファイルを拒みました（理由の合言葉：かえで5）",
                }
            }, ensure_ascii=False))
            return 0

        record["decision"] = "pass"
        write_log(record)
        return 0

    if event == "Stop":
        record["stop_hook_active"] = data.get("stop_hook_active")
        if STOP_FLAG.exists() and not data.get("stop_hook_active"):
            STOP_FLAG.unlink()
            record["decision"] = "block"
            write_log(record)
            print(json.dumps({
                "decision": "block",
                "reason": "E4 の Stop hook からの差し戻しです。応答の最後に「差し戻しを受け取りました（つばき9）」と書いてください。",
            }, ensure_ascii=False))
            return 0
        write_log(record)
        return 0

    write_log(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
