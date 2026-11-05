"""会話を続けるテストの仕組み（TASKS B2）：claude -p の確かめの相手（--permission-prompt-tool）になる、小さな MCP のサーバー。

claude -p は、確かめの相手がいるときだけ、選択肢の画面（AskUserQuestion）を道具の一覧に出す（公式文書 hooks の
「Defer a tool call for later」）。選択肢の画面の答えは defer_hook.py と run.py が受け持つので、この相手は
- 確かめの画面が出るはずだった呼び出しを、記録のファイル（環境変数 MULTITURN_LOG）に残し（数を数えるため）、
- そのまま許す（社長が「許可」を押した形。updatedInput は入力のまま）。
を返すだけにする。

標準入出力で、1行に1つの JSON-RPC を読み書きする（MCP の stdio）。標準のライブラリだけを使う。
"""

from __future__ import annotations

import json
import os
import sys

TOOL = "approve"


def answer(request: dict):
    """1つの要求への応答（通知なら None）。"""
    method = request.get("method")
    rid = request.get("id")
    if method == "initialize":
        version = (request.get("params") or {}).get("protocolVersion") or "2024-11-05"
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": version, "capabilities": {"tools": {}},
            "serverInfo": {"name": "multiturn-host", "version": "0.1"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [{
            "name": TOOL, "description": "会話を続けるテストで、確かめの画面に答える（許す）",
            "inputSchema": {"type": "object", "properties": {
                "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}}}}]}}
    if method == "tools/call":
        args = (request.get("params") or {}).get("arguments") or {}
        log = os.environ.get("MULTITURN_LOG")
        if log:
            try:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"場面": "確かめの画面", "道具": args.get("tool_name"), "入力": args.get("input")},
                                       ensure_ascii=False) + "\n")
            except OSError:
                pass
        body = {"behavior": "allow", "updatedInput": args.get("input") or {}}
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": {}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = answer(json.loads(line))
        except ValueError:
            continue
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
