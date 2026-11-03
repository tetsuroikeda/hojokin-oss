"""会社のフォルダでの hooks の起動（DESIGN 5章「補助プログラムが動かないときは止める」、TASKS S3・S3b）。

- 目印があり Python が動くときは、Python の hook に任せる（今止めるのは、会社のフォルダの外への書き込みと読み取り）。
- 目印があり Python が動かないとき（見つからない・終了コード1・途中で落ちる・版が古い・hook のコードが落ちる）、
  または hook の時間切れより前に終わらないとき（run.sh が見張って止める）は、
  - Write・Edit・NotebookEdit、Bash、ブラウザの道具（ページを読むだけのものも）を拒み、準備の案内を返す
  - 開いたとき（SessionStart）は、Python なしで決まった案内を渡す
  - ほかの場面と、読む道具（Read・Grep・Glob など）は、何もしない
- lib/・hooks/・skills/*/scripts/ のコードは、社長の Mac の /usr/bin/python3（3.9）で読み込める。
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import time

import hook_runner as hr
import pytest

PREPARE = "xcode-select --install"
CAUSE_NOT_WORKING = "補助プログラム（Python）が動かない"
CAUSE_TIMEOUT = "補助プログラム（Python）が時間内に終わらなかった"


def make_company_folder(tmp_path):
    folder = tmp_path / "試しの会社"
    (folder / ".hojokin").mkdir(parents=True)
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    return folder, home, data


def run_all(tmp_path, python, plugin=None, extra_env=None, only=None):
    """すべての場面の入力を流し、(場面, 道具の名前, 役割, 結果, かかった秒数) の一覧を返す。"""
    plugin = plugin or hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_company_folder(tmp_path)
    path = hr.make_bin(tmp_path / "bin", python, tmp_path / "python-ran")
    results = []
    for event, payload in hr.event_inputs(folder):
        tool = payload.get("tool_name", "")
        if only is not None and (tool or event) not in only:
            continue
        for command in hr.hook_commands(event, tool):
            role = command.split(event, 1)[1].strip()
            start = time.monotonic()
            r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data,
                       extra_env=extra_env)
            results.append((event, tool, role, r, time.monotonic() - start))
    return results


def pre_tool_use_entry(role: str) -> dict:
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    entries = [e for e in config["hooks"]["PreToolUse"]
               if e["hooks"][0]["command"].split("PreToolUse", 1)[1].strip() == role]
    assert len(entries) == 1, entries
    return entries[0]


def test_guard_matcher_covers_writes_bash_and_browser() -> None:
    """Python が動かないときに拒む道具：Write・Edit・NotebookEdit、Bash、ブラウザの道具（読むだけのものも）。"""
    matcher = pre_tool_use_entry("guard")["matcher"]
    for tool in hr.GUARDED_TOOLS:
        assert hr.claude_matches(matcher, tool), tool
    for tool in hr.UNGUARDED_TOOLS:
        assert not hr.claude_matches(matcher, tool), tool


def test_read_matcher_covers_read_tools_only() -> None:
    """外を読む道具は、guard を付けない別の PreToolUse で受け取る（Python が動かないときは拒まない）。"""
    matcher = pre_tool_use_entry("")["matcher"]
    for tool in hr.READ_TOOLS:
        assert hr.claude_matches(matcher, tool), tool
    for tool in hr.GUARDED_TOOLS + ("WebFetch", "mcp__x__Read", "ReadMcpResourceTool"):
        assert not hr.claude_matches(matcher, tool), tool
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    assert len(config["hooks"]["PreToolUse"]) == 2


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
    """Python が動けば Python の hook に任せる。外を読む道具だけを拒み、Bash を含めほかは通し、何も書かない。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    results = run_all(tmp_path, "本物", plugin)
    assert results
    denied = set()
    for event, tool, role, r, _ in results:
        assert r.returncode == 0, (event, tool, r)
        assert r.stderr == b"", (event, tool, r.stderr.decode("utf-8"))
        if tool in hr.READ_TOOLS:
            # 入力が Python まで届き、外を読むことを拒んだ（見張りの下でも、標準入力が渡る）
            hso = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]
            assert hso["permissionDecision"] == "deny", (tool, hso)
            assert "会社のフォルダの外は読めません" in hso["permissionDecisionReason"]
            denied.add(tool)
        else:
            assert r.stdout == b"", (event, tool, r.stdout.decode("utf-8"))
    assert denied == {"Read", "Grep", "Glob"}
    assert (tmp_path / "python-ran").exists()
    # -B で動かすので、プラグインのフォルダに __pycache__ を書かない
    assert not list(plugin.rglob("__pycache__"))


def assert_fallback(results, cause: str, python_stderr: bool = False) -> None:
    """Python が動かない・時間内に終わらないときの扱い。

    python_stderr：hook のコードが落ちたときは、Python の標準エラー（落ちた所）がそのまま出てよい。
    run.sh 自身は、止めた道具の知らせ（Killed など）を出さない。
    """
    denied = set()
    session_start = 0
    for event, tool, role, r, _ in results:
        assert r.returncode == 0, (event, tool, r)
        if python_stderr:
            assert b"Killed" not in r.stderr and b"Terminated" not in r.stderr, r.stderr
        else:
            assert r.stderr == b"", (event, tool, r.stderr.decode("utf-8"))
        if event == "PreToolUse" and role == "guard":
            output = json.loads(r.stdout.decode("utf-8"))
            hso = output["hookSpecificOutput"]
            assert hso["hookEventName"] == "PreToolUse"
            assert hso["permissionDecision"] == "deny"
            reason = hso["permissionDecisionReason"]
            assert cause in reason
            assert "Bash" in reason and "ブラウザの道具" in reason
            assert PREPARE in reason, reason
            denied.add(tool)
        elif event == "SessionStart":
            # 開いたときは、Python なしで決まった案内を渡す
            hso = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]
            assert hso["hookEventName"] == "SessionStart"
            assert cause in hso["additionalContext"]
            assert PREPARE in hso["additionalContext"]
            session_start += 1
        else:
            # 送ったとき・使った後・応答の終わり・外を読む道具は、何も出さない（Stop で差し戻さない）
            assert r.stdout == b"", (event, tool, r.stdout.decode("utf-8"))
    expected = {tool for event, tool, role, _, _ in results if event == "PreToolUse" and role == "guard"}
    assert denied == expected
    return denied, session_start


@pytest.mark.parametrize("python", ["なし", "壊れた", "半端", "古い"])
def test_python_not_working_denies_writes_bash_and_browser(tmp_path, python) -> None:
    denied, session_start = assert_fallback(run_all(tmp_path, python), CAUSE_NOT_WORKING)
    assert {"Write", "Edit", "NotebookEdit", "Bash", "mcp__Claude_Browser__computer",
            "mcp__claude-in-chrome__form_input", "mcp__computer-use__left_click"} <= denied
    assert not denied & set(hr.READ_TOOLS)
    assert session_start == 1


def test_hook_code_crash_denies_writes_bash_and_browser(tmp_path) -> None:
    """Python は動くが hook のコードが落ちたときも、動かないときと同じに扱う。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    (plugin / "lib" / "company.py").write_text("raise RuntimeError('壊れた lib')\n", encoding="utf-8")
    denied, session_start = assert_fallback(run_all(tmp_path, "本物", plugin), CAUSE_NOT_WORKING, python_stderr=True)
    assert {"Write", "Bash", "mcp__Claude_Browser__computer"} <= denied
    assert session_start == 1


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


def test_large_input_reaches_python_under_watch(tmp_path) -> None:
    """見張りの下でも、大きな入力がそのまま Python に渡る（会社のフォルダの中への Write は通す）。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_company_folder(tmp_path)
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
    outside = str(tmp_path / "外" / "a.md")
    for file_path, denied in ((str(folder / "a.md"), False), (outside, True)):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": file_path, "content": "長い文\n" * 50000}}
        (command,) = hr.hook_commands("PreToolUse", "Write")
        r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data)
        assert r.returncode == 0 and r.stderr == b"", r
        if denied:
            assert json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]["permissionDecision"] == "deny"
        else:
            assert r.stdout == b""


# ---- 時間切れ（実験 E5 の 4b：hook が時間切れになると、Claude Code は道具をそのまま通す） ----

def watch_limits() -> dict:
    """run.sh に書いた、場面ごとの見張りの秒数（"*" はほかの場面）。"""
    text = (hr.REPO_ROOT / "hooks" / "run.sh").read_text(encoding="utf-8")
    block = text[text.index('case "$event" in'):]
    block = block[:block.index("esac")]
    limits = {}
    for names, seconds in re.findall(r"^\s*([A-Za-z|*]+)\) limit=(\d+) ;;", block, flags=re.M):
        for name in names.split("|"):
            limits[name] = int(seconds)
    return limits


def test_watch_limits_are_shorter_than_hook_timeouts() -> None:
    """見張りの秒数は、どの場面でも hooks.json の timeout より2秒以上短い（PreToolUse は 10秒に対して8秒）。"""
    limits = watch_limits()
    assert "*" in limits
    timeouts = hr.hook_timeouts()
    assert {event for event, _ in timeouts} == set(hr.EVENTS)
    for (event, role), timeout in timeouts.items():
        limit = limits.get(event, limits["*"])
        assert limit + 2 <= timeout, (event, role, limit, timeout)
    assert limits.get("PreToolUse", limits["*"]) == 8


def test_hang_is_stopped_and_denied(tmp_path) -> None:
    """Python が固まったら、見張りが止め、書き込み・Bash・ブラウザの道具を拒み、開いたときは案内を渡す。

    見張りの秒数は、テストのために1秒に縮める（run.sh は短くすることだけを受け付ける）。
    """
    only = {"SessionStart", "UserPromptSubmit", "Write", "Bash", "mcp__Claude_Browser__computer",
            "mcp__claude-in-chrome__form_input", "Read", "Stop",
            "mcp__Claude_Browser__read_page"}  # 最後のものは PostToolUse の入力
    results = run_all(tmp_path, "固まる", extra_env={"HOJOKIN_WATCH_SECONDS": "1"}, only=only)
    assert {tool or event for event, tool, _, _, _ in results} == only
    denied, session_start = assert_fallback(results, CAUSE_TIMEOUT)
    assert denied == {"Write", "Bash", "mcp__Claude_Browser__computer", "mcp__claude-in-chrome__form_input"}
    assert session_start == 1
    timeouts = hr.hook_timeouts()
    for event, tool, role, r, seconds in results:
        # 1秒で止めた（固まった Python は60秒止まったまま。時間切れの秒数よりずっと前に返った）
        assert seconds < 5, (event, tool, seconds)
        assert seconds < timeouts[(event, role)], (event, tool, seconds)
    assert (tmp_path / "python-ran").exists()


@pytest.mark.slow
def test_hang_is_stopped_before_pre_tool_use_timeout(tmp_path) -> None:
    """縮めずに、本当の秒数（8秒）で止まり、PreToolUse の時間切れ（10秒）より前に拒む。

    HOJOKIN_WATCH_SECONDS で長くしようとしても、長くはならない。
    """
    results = run_all(tmp_path, "固まる", extra_env={"HOJOKIN_WATCH_SECONDS": "100"}, only={"Write"})
    ((event, tool, role, r, seconds),) = results
    assert 7.5 <= seconds < hr.hook_timeouts()[("PreToolUse", "guard")] - 0.5, seconds
    hso = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert CAUSE_TIMEOUT in hso["permissionDecisionReason"]


def test_watcher_does_not_linger(tmp_path) -> None:
    """Python がすぐ終わったときは、見張りもすぐ片付く（待たされず、後に残らない）。"""
    marker_seconds = "7"  # ほかと紛れない秒数にして、残っていないかを探す
    results = run_all(tmp_path, "本物", extra_env={"HOJOKIN_WATCH_SECONDS": marker_seconds}, only={"Write", "Bash"})
    assert len(results) == 2
    for event, tool, role, r, seconds in results:
        assert r.returncode == 0 and r.stdout == b"" and r.stderr == b"", (tool, r)
        assert seconds < 3, (tool, seconds)
    ps = subprocess.run(["/bin/ps", "-axo", "command"], capture_output=True, check=True).stdout.decode("utf-8")
    assert f"/bin/sleep {marker_seconds}\n" not in ps


# ---- 社長の Mac の Python（3.9）で読み込めるか（DESIGN 12章） ----

def python_sources() -> list:
    root = hr.REPO_ROOT
    lib = [p for p in sorted((root / "lib").rglob("*.py")) if "vendor" not in p.relative_to(root / "lib").parts]
    return sorted((root / "hooks").glob("*.py")) + lib + sorted(root.glob("skills/*/scripts/*.py"))


def source_id(path) -> str:
    return str(path.relative_to(hr.REPO_ROOT))


def test_sources_cover_hooks_lib_and_scripts() -> None:
    names = {source_id(p) for p in python_sources()}
    assert "hooks/main.py" in names and "hooks/outside_read.py" in names
    assert "lib/company.py" in names
    assert any(n.startswith("skills/") for n in names)
    assert not any("vendor" in n for n in names)


@pytest.mark.parametrize("path", python_sources(), ids=source_id)
def test_sources_parse_as_python39(path) -> None:
    """3.10 以降の書き方（match など）を使っていない。テストは 3.13 で流れるので、文法を 3.9 として読む。"""
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


# 1つのファイルを、本番と同じ形で読み込む（lib は lib.<名前>、hooks は hooks/ を前に置いて <名前>、
# skill のスクリプトはファイルの場所から。__main__ としては動かさない）
LOADER = r"""
import importlib, importlib.util, os, sys
root, kind, path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
name = os.path.splitext(os.path.basename(path))[0]
if kind == "lib":
    rel = os.path.relpath(path, root)[:-3].replace(os.sep, ".")
    if rel.endswith(".__init__"):
        rel = rel[: -len(".__init__")]
    importlib.import_module(rel)
elif kind == "hooks":
    sys.path.insert(0, os.path.dirname(path))
    importlib.import_module(name)
else:
    spec = importlib.util.spec_from_file_location("_check_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
print("読み込めた", sys.version_info[0], sys.version_info[1])
"""


@pytest.mark.parametrize("path", python_sources(), ids=source_id)
def test_sources_import_on_system_python(tmp_path, path) -> None:
    """社長の Mac と同じ /usr/bin/python3 で、実際に読み込む（注釈の評価など、文法の外の 3.10 以降の書き方も見つける）。"""
    python = hr.real_python()
    if python != "/usr/bin/python3":
        pytest.skip("/usr/bin/python3（3.9 以上）がありません")
    kind = source_id(path).split("/", 1)[0]
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run(
        [python, "-B", "-c", LOADER, str(hr.REPO_ROOT), kind, str(path)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    assert r.stdout.decode("utf-8").startswith("読み込めた 3 "), r.stdout


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
