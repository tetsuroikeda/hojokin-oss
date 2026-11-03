"""実験 E6 の試しの hook。

目印（.hojokin/）のあるフォルダでだけ動く。
- PreToolUse・PostToolUse：道具の名前と入力（Bash は打ったコマンドの全文）、結果の頭を記録するだけで、何も止めない
- Stop：台帳（.hojokin/台帳.json）にある原本のハッシュと今のハッシュを比べ、違えば Git の履歴から戻す。
  戻したときは、その応答で1回だけ Claude に知らせる（stop_hook_active なら知らせずに戻すだけ）
記録は ~/.hojokin-e6/hooks.jsonl に書く。
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hojokin-e6"
LOG_FILE = LOG_DIR / "hooks.jsonl"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_log(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_originals(folder: Path) -> list:
    """台帳と違う原本を Git から戻し、戻したものの記録を返す。"""
    ledger_path = folder / ".hojokin" / "台帳.json"
    if not ledger_path.is_file():
        return []
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    restored = []
    for rel, expected in ledger.items():
        target = folder / rel
        actual = sha256(target) if target.is_file() else None
        if actual == expected:
            continue
        result = subprocess.run(
            ["git", "-C", str(folder), "checkout", "HEAD", "--", rel],
            capture_output=True,
            text=True,
        )
        after = sha256(target) if target.is_file() else None
        restored.append({
            "file": rel,
            "before": actual,
            "after_matches_ledger": after == expected,
            "git_returncode": result.returncode,
            "git_stderr": result.stderr.strip()[:200],
        })
    return restored


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

    record = {
        "time": now(),
        "event": event,
        "folder": folder.name,
        "session_id": data.get("session_id"),
        "permission_mode": data.get("permission_mode"),
    }

    if event in ("PreToolUse", "PostToolUse"):
        record["tool_name"] = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        record["tool_input"] = {k: str(v)[:500] for k, v in tool_input.items()}
        if event == "PostToolUse":
            record["tool_response"] = str(data.get("tool_response"))[:300]
        write_log(record)
        return 0

    if event == "Stop":
        record["stop_hook_active"] = data.get("stop_hook_active")
        restored = check_originals(folder)
        record["restored"] = restored
        write_log(record)
        if restored and not data.get("stop_hook_active"):
            names = "、".join(r["file"] for r in restored)
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"E6 の Stop hook：原本（{names}）が台帳と違っていたので、履歴から戻しました。"
                    "原本は書き換えないでください（合言葉：すみれ4）。戻したことを報告して応答を終えてください。"
                ),
            }, ensure_ascii=False))
        return 0

    write_log(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
