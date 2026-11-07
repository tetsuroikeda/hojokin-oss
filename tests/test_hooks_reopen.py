"""会社のフォルダの親で開いたときの案内と、hooks が動いた合図（11/6 のリハーサルの不具合）。

リハーサルでは、Claude を会社のフォルダの親（目印のないフォルダ）で開き、道具に --folder で会社のフォルダを渡して
進めた。hooks は開いたフォルダ（CLAUDE_PROJECT_DIR）しか見ないので黙って何もせず、質問の記録・審査役の結果・版の記録が
残らないまま、確かめの道具が「社長に返す」「まだ届いていない」で止まった。
- run.sh：すぐ下のフォルダに目印があれば、開いたとき・社長が送ったときに、会社のフォルダで開き直す案内を渡す
  （Python は動かさない。何も止めず、何も書かない）。ほかの場面と、子にも目印のないフォルダでは、今までどおり何もしない。
- main.py：会社のフォルダで動いたら、合図（.hojokin/一時/hookの合図.json）を残す。
- 確かめの道具（kakunin.py count・prepare・result）：合図がない・古いときは【注意】で知らせる。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import hook_runner as hr
import pytest
from lib import company

SCRIPT = hr.REPO_ROOT / "skills" / "kaku" / "scripts" / "kakunin.py"


def _env(tmp_path):
    plugin = hr.copy_plugin(tmp_path / "plugin")
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    data.mkdir()
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
    return plugin, home, data, path


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_parent_of_company_folder_gets_reopen_note(tmp_path, event) -> None:
    parent = tmp_path / "リハーサル"
    child = parent / "やまぶき\"惣菜\\"  # 名前の " と \ も JSON の文字列として正しく出す
    (child / ".hojokin").mkdir(parents=True)
    (parent / "ほかのフォルダ").mkdir()
    plugin, home, data, path = _env(tmp_path)
    command = hr.hook_commands(event)[0]
    r = hr.run(command, {"hook_event_name": event, "prompt": "続けて"}, plugin=plugin, folder=parent, path=path,
               home=home, data=data)
    assert r.returncode == 0 and r.stderr == b""
    hso = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert hso["hookEventName"] == event
    note = hso["additionalContext"]
    assert "会社のフォルダではありません" in note and "開き直す" in note
    assert "「やまぶき\"惣菜\\」" in note and "ほかのフォルダ" not in note
    assert not (tmp_path / "python-ran").exists()  # Python は動かさない
    assert not (child / ".hojokin" / "一時").exists()  # 何も書かない


def test_parent_other_events_and_plain_folder_stay_silent(tmp_path) -> None:
    parent = tmp_path / "親"
    (parent / "会社" / ".hojokin").mkdir(parents=True)
    plain = tmp_path / "ふつう"
    (plain / "子").mkdir(parents=True)
    plugin, home, data, path = _env(tmp_path)
    for event, payload in hr.event_inputs(parent):
        for command in hr.hook_commands(event, hr.match_name(payload)):
            if event in ("SessionStart", "UserPromptSubmit"):
                continue
            r = hr.run(command, payload, plugin=plugin, folder=parent, path=path, home=home, data=data)
            assert (r.returncode, r.stdout, r.stderr) == (0, b"", b""), (event, payload.get("tool_name"))
    for event in ("SessionStart", "UserPromptSubmit"):
        r = hr.run(hr.hook_commands(event)[0], {"hook_event_name": event}, plugin=plugin, folder=plain, path=path,
                   home=home, data=data)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b""), event
    assert not (tmp_path / "python-ran").exists()


def test_hooks_leave_signal_in_company_folder(tmp_path) -> None:
    folder = tmp_path / "会社"
    (folder / ".hojokin").mkdir(parents=True)
    assert "一度も動いていません" in company.hook_signal_problem(folder)
    plugin, home, data, path = _env(tmp_path)
    r = hr.run(hr.hook_commands("UserPromptSubmit")[0], {"hook_event_name": "UserPromptSubmit", "prompt": "はい"},
               plugin=plugin, folder=folder, path=path, home=home, data=data)
    assert r.returncode == 0
    signal = json.loads((folder / ".hojokin" / "一時" / company.HOOK_SIGNAL).read_text(encoding="utf-8"))
    assert signal["場面"] == "UserPromptSubmit" and str(folder) not in json.dumps(signal, ensure_ascii=False)
    assert company.hook_signal_problem(folder) == ""
    # 古い合図は「動いていない」とみなす
    signal["時刻"] = "2020-01-01T00:00:00+09:00"
    (folder / ".hojokin" / "一時" / company.HOOK_SIGNAL).write_text(json.dumps(signal), encoding="utf-8")
    assert "時間動いていません" in company.hook_signal_problem(folder)


def test_kakunin_warns_when_hooks_have_not_run(tmp_path) -> None:
    folder = tmp_path / "会社"
    (folder / ".hojokin").mkdir(parents=True)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path))
    r = subprocess.run([sys.executable, "-B", str(SCRIPT), "result", "--folder", str(folder)], env=env,
                       capture_output=True)
    text = r.stdout.decode("utf-8")
    assert text.startswith("【注意】hojokin の hooks が、この会社のフォルダで一度も動いていません"), text
    assert "開き直して" in text
    company.write_hook_signal(folder, "UserPromptSubmit")
    r = subprocess.run([sys.executable, "-B", str(SCRIPT), "result", "--folder", str(folder)], env=env,
                       capture_output=True)
    assert "【注意】" not in r.stdout.decode("utf-8")


def test_question_log_keeps_option_descriptions(tmp_path) -> None:
    """選択肢の画面の答えに、選択肢の説明（勧める案の中身）も残す（11/7 のリハーサルで、見出ししか残らず、
    審査役が「答えにない中身」として要修正にした）。"""
    folder = tmp_path / "会社"
    (folder / ".hojokin").mkdir(parents=True)
    plugin, home, data, path = _env(tmp_path)
    q = "保守の契約はいつ結びますか。（理由：体制を書くため）"
    payload = {"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
               "tool_input": {"questions": [{"question": q, "header": "保守", "multiSelect": False, "options": [
                   {"label": "納品のとき（推奨）", "description": "2027年12月の納品に合わせて結ぶ"},
                   {"label": "分からない", "description": ""}]}]},
               "tool_response": {"answers": {q: "納品のとき（推奨）"}}}
    r = hr.run(hr.hook_commands("PostToolUse", "AskUserQuestion")[0], payload, plugin=plugin, folder=folder, path=path,
               home=home, data=data)
    assert r.returncode == 0
    log = json.loads((folder / "記録" / "質問の記録.json").read_text(encoding="utf-8"))["質問"][0]
    assert log["答え"] == "納品のとき（推奨）"
    assert log["答えの説明"] == "2027年12月の納品に合わせて結ぶ"
    assert log["選択肢の説明"] == {"納品のとき（推奨）": "2027年12月の納品に合わせて結ぶ"}
