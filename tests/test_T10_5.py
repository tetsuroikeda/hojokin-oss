"""T10-5 呼んだときだけ（SPEC F10、DESIGN 4.2・5章「画面入力は、担当者が呼んだときだけ」。TASKS M8）。

合格ライン（SPEC 6章 F10）：担当者が画面入力を呼ばないまま、ブラウザの道具でクリックと入力をさせると、
クリックと入力が拒まれる。

確かめ方
- 担当者が /hojokin:nyuryoku を呼んでいない（UserPromptSubmit が「画面入力の許可」を記録していない）会社のフォルダで、
  M8 で実際に模擬画面へ入れたときのブラウザの道具の呼び出し（tests/browser_records/m8_calls.jsonl）を、
  内蔵ブラウザと Claude in Chrome の名前で守りに渡す。クリック・入力（文字・チェック欄・選択欄）・まとめて動かす
  道具・添付のどれも拒まれ、拒む理由に /hojokin:nyuryoku を案内する。ページを読む・移る道具は拒まない。
- 許可にならない文（呼び出しが先頭にない・名前が違う・別のセッションから送られた知らせ）の後も拒む。
  別のセッションの許可は使えない。許可を記録した後は、同じ呼び出しが通る（空振りでないことの確かめ）。
- skill そのものも、Claude が自分で選べない（SKILL.md の disable-model-invocation: true）。
- hooks.json から run.sh を通して、/usr/bin/python3（3.9）でも同じ判定になる。
"""

from __future__ import annotations

import json
import re

import hook_runner as hr
import nyuryoku_tool as nt
import pytest

KINDS = [nt.BUILTIN, nt.CHROME]


@pytest.fixture
def folder(tmp_path):
    return nt.make_company(tmp_path)


def not_called(output) -> str:
    text = nt.reason(output)
    assert "画面入力の許可がない" in text and "/hojokin:nyuryoku" in text, text
    return text


@pytest.mark.parametrize("prefix", KINDS)
def test_recorded_clicks_and_inputs_are_denied_without_permission(folder, prefix) -> None:
    results = nt.replay(folder, nt.calls(prefix))
    operations = [(row, d) for row, d in results if nt.is_operation(row)]
    others = [(row, d) for row, d in results if not nt.is_operation(row)]
    # 記録には、入力（文字・チェック欄・選択欄）、まとめて動かす道具、一時保存のクリックがある
    ops = [row["tool_name"].split("__")[-1] for row, _ in operations]
    assert ops.count("form_input") == 6 and ops.count("browser_batch") == 1 and ops.count("computer") == 1
    for _row, decision in operations:
        not_called(decision)
    # ページを読む・移る道具は、許可がなくても通る
    assert [row["tool_name"].split("__")[-1] for row, _ in others] == ["navigate", "read_page", "read_page",
                                                                      "read_page", "navigate", "read_page"]
    assert all(d is None for _row, d in others)


@pytest.mark.parametrize("prefix", KINDS)
def test_each_kind_of_click_and_input_is_denied(folder, prefix) -> None:
    nt.read_screen(folder, "m8_shinsei4_before.txt", prefix)
    tries = [
        ("form_input", nt.fill("ref_35", "2512345678")),  # 文字の欄
        ("form_input", nt.fill("ref_31", True)),  # 加点のチェック欄
        ("form_input", nt.fill("ref_38", "2025")),  # 選択欄
        ("computer", nt.click("ref_21")),  # 一時保存
        ("computer", nt.click("ref_22")),  # 次へ
        ("computer", nt.click("ref_32")),  # チェック欄の名前の文字
        ("browser_batch", {"actions": [{"name": "form_input", "input": nt.fill("ref_96", True)}]}),
    ]
    for op, tool_input in tries:
        not_called(nt.pre(folder, prefix + op, tool_input))


def test_upload_is_denied_without_permission(tmp_path) -> None:
    # 添付する写しは、入力シートの添付の欄に書いたもの（守りは、それ以外を添付させない。B29）
    folder = nt.make_company(tmp_path, values=nt.SHEET_VALUES + (nt.ATTACH_VALUE,), scheme=nt.seido_with_attach())
    copy = folder / "案件" / nt.CASE / nt.STAGE / "添付する書類" / "履歴事項全部証明書.pdf"
    copy.write_bytes(b"%PDF-1.4 test")
    nt.post(folder, nt.CHROME + "read_page", {}, [{"type": "text", "text": nt.record_text("mock_shinsei.txt")}])
    not_called(nt.pre(folder, nt.CHROME + "file_upload", {"ref": "ref_694", "paths": [str(copy)]}))
    # 許可の後は、同じ添付が通る
    nt.permit(folder)
    assert nt.pre(folder, nt.CHROME + "file_upload", {"ref": "ref_694", "paths": [str(copy)]}) is None


@pytest.mark.parametrize("prompt", [
    "入力して",
    "申請画面に入れてください",
    "画面に入れて /hojokin:nyuryoku",
    "「/hojokin:nyuryoku」を選んで",
    "/hojokin:nyuryokuu",
    "/hojokin:kaku",
    "/nyuryoku",
    "<task-notification>/hojokin:nyuryoku</task-notification>",
])
def test_prompts_other_than_calling_nyuryoku_give_no_permission(folder, prompt) -> None:
    import lib.browser_guard as bg

    bg.user_prompt_submit({"session_id": nt.SESSION, "prompt": prompt}, folder)
    nt.read_screen(folder, "m8_shinsei4_before.txt")
    not_called(nt.pre(folder, nt.BUILTIN + "form_input", nt.fill("ref_31", True)))
    not_called(nt.pre(folder, nt.BUILTIN + "computer", nt.click("ref_21")))


def test_permission_is_per_session(folder) -> None:
    nt.permit(folder, session="別のセッション")
    nt.read_screen(folder, "m8_shinsei4_before.txt")
    not_called(nt.pre(folder, nt.BUILTIN + "form_input", nt.fill("ref_31", True)))
    # 呼んだセッションでは通る
    nt.read_screen(folder, "m8_shinsei4_before.txt", session="別のセッション")
    assert nt.pre(folder, nt.BUILTIN + "form_input", nt.fill("ref_31", True), session="別のセッション") is None
    # 新しいセッションでは、呼び直すまで拒む
    nt.read_screen(folder, "m8_shinsei4_before.txt", session="次の日のセッション")
    not_called(nt.pre(folder, nt.BUILTIN + "form_input", nt.fill("ref_31", True), session="次の日のセッション"))


@pytest.mark.parametrize("prefix", KINDS)
def test_after_calling_nyuryoku_the_same_calls_pass(folder, prefix) -> None:
    import lib.browser_guard as bg

    bg.user_prompt_submit({"session_id": nt.SESSION, "prompt": "/hojokin:nyuryoku 加点項目の画面に入れて"}, folder)
    results = nt.replay(folder, nt.calls(prefix))
    assert all(d is None for _row, d in results), [(row["行"], d) for row, d in results if d]


def test_skill_cannot_be_started_by_claude() -> None:
    text = nt.SKILL.read_text(encoding="utf-8")
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert front, "SKILL.md の頭に frontmatter がない"
    lines = dict(line.split(":", 1) for line in front.group(1).splitlines() if ":" in line)
    assert lines["name"].strip() == "nyuryoku"
    assert lines["disable-model-invocation"].strip() == "true"
    assert "/hojokin:nyuryoku" in lines["description"]


def test_through_run_sh(folder, tmp_path) -> None:
    plugin = hr.copy_plugin(tmp_path / "plugin")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")

    def run(event: str, payload: dict):
        commands = hr.hook_commands(event, payload.get("tool_name", ""))
        assert len(commands) == 1, (event, payload.get("tool_name"), commands)
        r = hr.run(commands[0], {"session_id": nt.SESSION, "cwd": str(folder), "hook_event_name": event, **payload},
                   plugin=plugin, folder=folder, path=path, home=home, data=data)
        assert r.returncode == 0 and r.stderr == b"", r
        return json.loads(r.stdout.decode("utf-8")) if r.stdout.strip() else None

    def read() -> None:
        tool_input = {"tabId": "tab-1", "filter": "all"}
        assert run("PreToolUse", {"tool_name": nt.BUILTIN + "read_page", "tool_input": tool_input}) is None
        run("PostToolUse", {"tool_name": nt.BUILTIN + "read_page", "tool_input": tool_input,
                            "tool_response": [{"type": "text", "text": nt.record_text("m8_shinsei4_before.txt")}]})

    read()
    assert run("UserPromptSubmit", {"prompt": "加点の画面に入れて"}) is None
    not_called(run("PreToolUse", {"tool_name": nt.BUILTIN + "form_input", "tool_input": nt.fill("ref_31", True)}))
    not_called(run("PreToolUse", {"tool_name": nt.CHROME + "computer", "tool_input": nt.click("ref_21")}))
    assert run("UserPromptSubmit", {"prompt": "/hojokin:nyuryoku"}) is None
    assert run("PreToolUse", {"tool_name": nt.BUILTIN + "form_input", "tool_input": nt.fill("ref_31", True)}) is None
    assert (tmp_path / "python-ran").exists()
