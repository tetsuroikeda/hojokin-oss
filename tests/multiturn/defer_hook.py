"""会話を続けるテストの仕組み（TASKS B2、DESIGN 11章）：選択肢の画面（AskUserQuestion）を、社長役が答えるまで止める hook。

claude -p の PreToolUse で動かす（run.py が --settings で足す。プラグインの hooks には入れない）。
- AskUserQuestion のとき、答えのファイル（環境変数 MULTITURN_ANSWERS）に、この呼び出し（tool_use_id）の答えがあれば、
  allow と、答えを入れた updatedInput（questions はそのまま、answers は問いの文 → 選んだ選択肢の名前か社長役の文）を返す。
- 答えがなければ defer を返す。claude -p は、その呼び出しの前で止まり、結果に stop_reason "tool_deferred" と
  deferred_tool_use（id・name・input）を返す。run.py が社長役に答えさせ、答えのファイルに書いて --resume で続ける。
  続けたとき、同じ呼び出しでこの hook がもう一度動き、今度は allow を返す（公式文書 hooks の「Defer a tool call for later」）。
- 呼び出しごとに、入力を記録のファイル（環境変数 MULTITURN_LOG。あれば）に1行ずつ足す。
- ほかの道具には何も返さない（プラグインの hook と会社のフォルダの設定に任せる）。
- 標準のライブラリだけを使う。落ちたときは何も返さない（ふつうの確かめの流れになる）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def decide(data: dict, answers: dict) -> dict:
    """hook の入力と答えの一覧（tool_use_id → {問いの文: 答え}）から、返す JSON を決める（AskUserQuestion のとき）。"""
    tool_input = data.get("tool_input") or {}
    mine = answers.get(str(data.get("tool_use_id") or ""))
    if isinstance(mine, dict) and mine:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"questions": tool_input.get("questions"), "answers": mine},
        }}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}}


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    log = os.environ.get("MULTITURN_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"場面": "PreToolUse", "道具": data.get("tool_name"), "tool_use_id": data.get("tool_use_id"),
                                    "入力": data.get("tool_input")}, ensure_ascii=False) + "\n")
        except OSError:
            pass
    if data.get("tool_name") != "AskUserQuestion":
        return 0
    answers = {}
    path = os.environ.get("MULTITURN_ANSWERS")
    if path and Path(path).is_file():
        try:
            answers = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            answers = {}
    sys.stdout.write(json.dumps(decide(data, answers), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
