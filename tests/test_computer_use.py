"""会社のフォルダでは、画面を操作する機能（computer use）を拒む（DESIGN 5章「提出ボタンを押さない」の
すり抜けへの備え。TASKS M8）。

確かめること
- 名前に computer-use を含む道具（画面の写し・クリック・打ち込み・まとめて動かす道具・クリップボード・アプリを開く
  など。デスクトップアプリの道具の名前と、つないだ別のパソコンの名前）は、会社のフォルダでは、担当者が
  /hojokin:nyuryoku を呼んだ後でも、すべて拒む。拒む理由は、Claude in Chrome か内蔵ブラウザの道具を案内する。
- hooks.json の PreToolUse の matcher が、これらの道具を画面入力の守りに渡す（Claude Code と同じ照らし方）。
  PostToolUse は控えを作らない。
- hooks.json から run.sh を通して、/usr/bin/python3（3.9）でも拒む。Python が動かないときも拒む。
- 会社のフォルダでない（目印 .hojokin/ がない）ところでは、hook は何もしない（Python も動かさない）。
"""

from __future__ import annotations

import json

import hook_runner as hr
import nyuryoku_tool as nt
import pytest

from lib import browser_guard as bg

COMPUTER_USE_TOOLS = [
    "mcp__computer-use__screenshot",
    "mcp__computer-use__left_click",
    "mcp__computer-use__double_click",
    "mcp__computer-use__type",
    "mcp__computer-use__key",
    "mcp__computer-use__computer_batch",
    "mcp__computer-use__app_click",
    "mcp__computer-use__app_type",
    "mcp__computer-use__app_key",
    "mcp__computer-use__app_screenshot",
    "mcp__computer-use__app_batch",
    "mcp__computer-use__open_application",
    "mcp__computer-use__request_access",
    "mcp__computer-use__read_clipboard",
    "mcp__computer-use__write_clipboard",
    "mcp__computer-use__list_apps",
    "mcp__remote-devices__computer-use__left_click",
    "mcp__remote-devices__computer-use__screenshot",
]
INPUTS = {
    "left_click": {"coordinate": [512, 238]},
    "double_click": {"coordinate": [512, 238]},
    "type": {"text": "2512345678"},
    "key": {"text": "Return"},
    "app_click": {"app": "Google Chrome", "coordinate": [512, 238]},
    "app_type": {"app": "Google Chrome", "text": "2512345678"},
    "computer_batch": {"actions": [{"action": "left_click", "coordinate": [512, 238]}]},
    "open_application": {"app": "Safari"},
    "request_access": {"apps": ["Google Chrome"]},
    "write_clipboard": {"text": "2512345678"},
}


def tool_input(name: str) -> dict:
    return INPUTS.get(name.split("__")[-1], {})


@pytest.fixture
def folder(tmp_path):
    return nt.make_company(tmp_path)


def computer_use_reason(output) -> str:
    text = nt.reason(output)
    assert "画面を操作する機能（computer use）は使えません" in text, text
    assert "Claude in Chrome か内蔵ブラウザ" in text
    return text


@pytest.mark.parametrize("tool", COMPUTER_USE_TOOLS)
def test_computer_use_is_denied_in_company_folder(folder, tool) -> None:
    computer_use_reason(nt.pre(folder, tool, tool_input(tool)))


@pytest.mark.parametrize("tool", COMPUTER_USE_TOOLS)
def test_computer_use_is_denied_even_after_calling_nyuryoku(folder, tool) -> None:
    nt.permit(folder)
    nt.read_screen(folder, "m8_shinsei4_before.txt")
    computer_use_reason(nt.pre(folder, tool, tool_input(tool)))
    # 同じ許可で、ブラウザの道具の入力は通る（空振りでないことの確かめ）
    assert nt.pre(folder, nt.BUILTIN + "form_input", nt.fill("ref_31", True)) is None


def test_post_tool_use_keeps_no_snapshot_for_computer_use(folder) -> None:
    nt.post(folder, "mcp__computer-use__screenshot", {}, [{"type": "text", "text": nt.record_text("m8_shinsei12.txt")}])
    state = bg.state_dir(folder, nt.SESSION)
    assert not (state / bg.SNAPSHOT_FILE).exists()


@pytest.mark.parametrize("tool", COMPUTER_USE_TOOLS)
def test_hooks_json_routes_computer_use_to_the_guard(tool) -> None:
    commands = hr.hook_commands("PreToolUse", tool)
    assert commands == ['sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" PreToolUse guard'], commands


def _run_sh(tmp_path, folder, python: str):
    plugin = hr.copy_plugin(tmp_path / f"plugin-{python}")
    home = tmp_path / f"home-{python}"
    data = tmp_path / f"data-{python}"
    home.mkdir()
    data.mkdir()
    marker = tmp_path / f"python-ran-{python}"
    path = hr.make_bin(tmp_path / f"bin-{python}", python, marker)

    def run(tool: str):
        (command,) = hr.hook_commands("PreToolUse", tool)
        payload = {"session_id": nt.SESSION, "cwd": str(folder), "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": tool_input(tool)}
        r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data)
        assert r.returncode == 0, r
        return json.loads(r.stdout.decode("utf-8")) if r.stdout.strip() else None

    return run, marker


def test_through_run_sh_with_system_python(folder, tmp_path) -> None:
    nt.permit(folder)
    run, marker = _run_sh(tmp_path, folder, "本物")
    for tool in ("mcp__computer-use__left_click", "mcp__computer-use__app_type", "mcp__computer-use__screenshot"):
        computer_use_reason(run(tool))
    assert marker.exists()


def test_through_run_sh_when_python_does_not_work(folder, tmp_path) -> None:
    run, _marker = _run_sh(tmp_path, folder, "壊れた")
    text = nt.reason(run("mcp__computer-use__left_click"))
    assert "補助プログラム（Python）が動かない" in text and "ブラウザの道具" in text


def test_outside_company_folder_hooks_do_nothing(tmp_path) -> None:
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    run, marker = _run_sh(tmp_path, plain, "本物")
    assert run("mcp__computer-use__left_click") is None
    assert not marker.exists()


def test_skill_tells_not_to_use_computer_use() -> None:
    text = nt.SKILL.read_text(encoding="utf-8")
    assert "computer use" in text and "使わない" in text
