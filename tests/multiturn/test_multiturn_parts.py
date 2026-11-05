"""会話を続けるテストの仕組み（TASKS B2）の部品を、モデルを使わずに確かめる。

- defer_hook：答えがなければ defer、この呼び出しの答えがあれば allow と answers を入れた updatedInput。
  ほかの道具には何も返さない。
- host：確かめの画面に許すと答え、記録に残す。MCP の初めのやりとりに答える。
- run：社長役の答えの JSON から、問いの文ごとの答えを取り出す（読めない問いは「分かりません」）。
本物の claude -p で3往復を流す確かめは、TASKS B2 の終わりの確かめで行う（利用枠を使うので、ここでは流さない）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import defer_hook  # noqa: E402
import host  # noqa: E402
import run  # noqa: E402

QUESTIONS = [{"question": "決済の会社はどこにしますか？", "header": "決済", "options": [{"label": "A社"}, {"label": "B社"}],
              "multiSelect": False}]


def _hook(tmp_path: Path, data: dict, answers: dict) -> str:
    path = tmp_path / "答え.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([sys.executable, "-B", str(HERE / "defer_hook.py")], input=json.dumps(data, ensure_ascii=False),
                          capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, MULTITURN_ANSWERS=str(path), MULTITURN_LOG=str(tmp_path / "記録.jsonl")))
    assert done.returncode == 0
    return done.stdout


def test_hook_defers_until_the_owner_answers(tmp_path: Path) -> None:
    data = {"tool_name": "AskUserQuestion", "tool_use_id": "toolu_1", "tool_input": {"questions": QUESTIONS}}
    first = json.loads(_hook(tmp_path, data, {}))
    assert first["hookSpecificOutput"]["permissionDecision"] == "defer"
    second = json.loads(_hook(tmp_path, data, {"toolu_1": {"決済の会社はどこにしますか？": "分かりません"}}))
    out = second["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert out["updatedInput"] == {"questions": QUESTIONS, "answers": {"決済の会社はどこにしますか？": "分かりません"}}
    # 前の呼び出しの答えは、別の呼び出しに使わない
    other = dict(data, tool_use_id="toolu_2")
    assert json.loads(_hook(tmp_path, other, {"toolu_1": {"x": "y"}}))["hookSpecificOutput"]["permissionDecision"] == "defer"
    assert len((tmp_path / "記録.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_hook_says_nothing_for_other_tools(tmp_path: Path) -> None:
    assert _hook(tmp_path, {"tool_name": "Bash", "tool_input": {"command": "ls"}}, {}) == ""


def test_host_answers_mcp_and_allows_prompts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MULTITURN_LOG", str(tmp_path / "記録.jsonl"))
    init = host.answer({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    tools = host.answer({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in tools["result"]["tools"]] == ["approve"]
    called = host.answer({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "approve", "arguments": {"tool_name": "WebSearch", "input": {"query": "持続化"}}}})
    body = json.loads(called["result"]["content"][0]["text"])
    assert body == {"behavior": "allow", "updatedInput": {"query": "持続化"}}
    assert "確かめの画面" in (tmp_path / "記録.jsonl").read_text(encoding="utf-8")
    assert host.answer({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_owner_answers_are_taken_per_question() -> None:
    text = '答えます。{"決済の会社はどこにしますか？": "A社"}'
    assert run.parse_answers(text, QUESTIONS) == {"決済の会社はどこにしますか？": "A社"}
    assert run.parse_answers("よく分からない", QUESTIONS) == {"決済の会社はどこにしますか？": "分かりません"}


def test_owner_sees_only_the_answer_table_and_rules() -> None:
    system = run.owner_system("| A-01 | 社名 | 架空の会社 |", "台本の発言は書いてあるとおりに言う")
    assert "分かりません" in system and "架空の会社" in system and "台本の決まり" in system
    command = run.main_command("sonnet", 1.0, None)
    assert "--permission-prompt-tool" in command and "--resume" not in command
    assert "--resume" in run.main_command("sonnet", 1.0, "abc")
