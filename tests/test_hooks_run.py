"""会社のフォルダでの hooks の起動（DESIGN 5章「補助プログラムが動かないときは止める」）。

- 目印があり Python が動くときは、Python の hook に任せる（骨組みなので、まだ何も止めない）。
- 目印があり Python が動かないとき（見つからない・終了コード1・途中で落ちる・版が古い・hook のコードが落ちる）は、
  書き込みとブラウザの操作の道具だけを拒み、ほかの場面では何もしない。
- hooks と lib/ のコードは、社長の Mac の Python 3.9 で動く書き方になっている。
"""

from __future__ import annotations

import ast
import json
import re
import subprocess

import hook_runner as hr
import pytest


def make_company_folder(tmp_path):
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    return folder, home, data


def run_all(tmp_path, python, plugin=None):
    """すべての場面の入力を流し、(場面, 道具の名前, 結果) の一覧を返す。"""
    plugin = plugin or hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_company_folder(tmp_path)
    path = hr.make_bin(tmp_path / "bin", python, tmp_path / "python-ran")
    results = []
    for event, payload in hr.event_inputs(folder):
        tool = payload.get("tool_name", "")
        for command in hr.hook_commands(event, tool):
            r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data)
            results.append((event, tool, r))
    return results


def guard_matcher() -> str:
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    (entry,) = config["hooks"]["PreToolUse"]
    assert entry["hooks"][0]["command"].endswith(" PreToolUse guard")
    return entry["matcher"]


def test_guard_matcher_covers_writes_and_browser() -> None:
    matcher = guard_matcher()
    for tool in hr.GUARDED_TOOLS:
        assert hr.claude_matches(matcher, tool), tool
    for tool in hr.UNGUARDED_TOOLS:
        assert not hr.claude_matches(matcher, tool), tool


def test_post_tool_use_only_for_browser() -> None:
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    (entry,) = config["hooks"]["PostToolUse"]
    # DESIGN 5章：名前に Claude_Browser か claude-in-chrome を含む道具が対象（前に何か付いた名前も）
    for tool in ("mcp__Claude_Browser__read_page", "mcp__remote-devices__Claude_Browser__read_page",
                 "mcp__claude-in-chrome__read_page", "mcp__remote-devices__claude-in-chrome__read_page"):
        assert hr.claude_matches(entry["matcher"], tool), tool
    for tool in ("Write", "Edit", "Read", "Bash"):
        assert not hr.claude_matches(entry["matcher"], tool), tool


def test_claude_matches_follows_claude_code_rules() -> None:
    """テストの判定が Claude Code の規則どおりか（英字などだけの matcher は、名前そのものと比べる）。"""
    assert not hr.claude_matches("Claude_Browser|claude-in-chrome", "mcp__Claude_Browser__read_page")
    assert hr.claude_matches("Bash|Write", "Write")
    assert not hr.claude_matches("Bash|Write", "NotebookWrite")
    assert hr.claude_matches("(Claude_Browser|claude-in-chrome)__", "mcp__Claude_Browser__read_page")


def test_company_folder_with_python_runs_python_hooks(tmp_path) -> None:
    """Python が動けば Python の hook に任せる。骨組みなので、まだ何も止めず、何も書かない。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    results = run_all(tmp_path, "本物", plugin)
    assert results
    for event, tool, r in results:
        assert r.returncode == 0, (event, tool, r)
        assert r.stdout == b"", (event, tool, r.stdout.decode("utf-8"))
        assert r.stderr == b"", (event, tool, r.stderr.decode("utf-8"))
    assert (tmp_path / "python-ran").exists()
    # -B で動かすので、プラグインのフォルダに __pycache__ を書かない
    assert not list(plugin.rglob("__pycache__"))


def assert_denies_only_guarded(results) -> None:
    denied = set()
    for event, tool, r in results:
        assert r.returncode == 0, (event, tool, r)
        if event == "PreToolUse":
            output = json.loads(r.stdout.decode("utf-8"))
            hso = output["hookSpecificOutput"]
            assert hso["hookEventName"] == "PreToolUse"
            assert hso["permissionDecision"] == "deny"
            assert "補助プログラム（Python）が動かない" in hso["permissionDecisionReason"]
            denied.add(tool)
        else:
            # 開いたとき・送ったとき・使った後・応答の終わりは、何も出さない（Stop で差し戻さない）
            assert r.stdout == b"", (event, tool, r.stdout.decode("utf-8"))
    expected = {tool for event, tool, _ in results if event == "PreToolUse"}
    assert denied == expected
    assert {"Write", "Edit", "NotebookEdit", "mcp__Claude_Browser__computer",
            "mcp__claude-in-chrome__form_input", "mcp__computer-use__left_click"} <= denied
    assert "Bash" not in denied


@pytest.mark.parametrize("python", ["なし", "壊れた", "半端", "古い"])
def test_python_not_working_denies_writes_and_browser(tmp_path, python) -> None:
    assert_denies_only_guarded(run_all(tmp_path, python))


def test_hook_code_crash_denies_writes_and_browser(tmp_path) -> None:
    """Python は動くが hook のコードが落ちたときも、動かないときと同じに扱う。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    (plugin / "lib" / "company.py").write_text("raise RuntimeError('壊れた lib')\n", encoding="utf-8")
    assert_denies_only_guarded(run_all(tmp_path, "本物", plugin))


def test_large_input_is_read_when_python_missing(tmp_path) -> None:
    """Python がなくても、大きな入力（長い文の Write）を読み捨てて、拒む判定を返す。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_company_folder(tmp_path)
    path = hr.make_bin(tmp_path / "bin", "なし", tmp_path / "python-ran")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(folder / "a.md"), "content": "長い文\n" * 50000}}
    (command,) = hr.hook_commands("PreToolUse", "Write")
    r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data)
    assert r.returncode == 0
    assert json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]["permissionDecision"] == "deny"


def python_sources() -> list:
    return sorted((hr.REPO_ROOT / "hooks").glob("*.py")) + sorted((hr.REPO_ROOT / "lib").glob("*.py"))


@pytest.mark.parametrize("path", python_sources(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_sources_parse_as_python39(path) -> None:
    """3.10 以降の書き方（match など）を使っていない。テストは 3.13 で流れるので、文法を 3.9 として読む。"""
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


def test_lib_runs_on_system_python(tmp_path) -> None:
    """社長の Mac と同じ /usr/bin/python3 で、lib/ を実際に動かす。"""
    python = hr.real_python()
    if python != "/usr/bin/python3":
        pytest.skip("/usr/bin/python3（3.9 以上）がありません")
    folder, home, _ = make_company_folder(tmp_path)
    (folder / ".hojokin" / "設定.json").write_text('{"今日の日付": "2027-03-01"}', encoding="utf-8")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from pathlib import Path; from lib import company, dates;"
        "f = company.company_folder();"
        "print(sys.version_info[:2], dates.format_date(dates.today(f)))"
    )
    r = subprocess.run(
        [python, "-B", "-c", code, str(hr.REPO_ROOT)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_PROJECT_DIR": str(folder)},
        cwd=folder,
        capture_output=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    assert r.stdout.decode("utf-8").strip().endswith("2027年3月1日（月）")
