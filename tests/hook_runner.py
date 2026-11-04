"""hooks を、Claude Code と同じように hooks.json のコマンドから動かすための道具（テスト用）。

- プラグインの hooks/ と lib/ を一時フォルダに写して動かす（__pycache__ などが書かれないかも見るため）。
- 環境変数は、渡したものだけにする（手元の PATH や HOME を使わない）。
- Python は、本物（/usr/bin/python3 が 3.9 以上ならそれ。なければテストの Python）、
  見つからない、壊れた（終了コード1）などに替えられる。どれも、動いたら印のファイルを作る。
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop")

# 書き込み、Bash、ブラウザの道具（Python が動かないときに拒むもの。DESIGN 5章）
GUARDED_TOOLS = (
    "Write",
    "Edit",
    "NotebookEdit",
    "Bash",
    "mcp__Claude_Browser__computer",
    "mcp__Claude_Browser__form_input",
    "mcp__Claude_Browser__read_page",
    "mcp__remote-devices__Claude_Browser__computer",
    "mcp__claude-in-chrome__computer",
    "mcp__claude-in-chrome__file_upload",
    "mcp__remote-devices__claude-in-chrome__computer",
    "mcp__computer-use__left_click",
    "mcp__remote-devices__computer-use__left_click",
)
# 会社のフォルダの外を読むかを Python が見る道具（Python が動かないときは拒まない）
READ_TOOLS = ("Read", "NotebookRead", "Grep", "Glob", "LS")
# 書き込みでもブラウザでもない道具（Python が動かないときも拒まない）
UNGUARDED_TOOLS = READ_TOOLS + ("WebSearch", "WebFetch", "Skill", "Task", "TodoWrite", "BashOutput")


def claude_matches(matcher: str, tool_name: str) -> bool:
    """Claude Code と同じ規則で、hooks.json の matcher が道具の名前に合うかを返す（公式文書の hooks）。

    英字・数字・_・-・空白・,・| だけの matcher は、名前そのもの（| か , で区切った一覧）と比べる。
    それ以外の文字を含むときだけ、正規表現として、名前のどこかに合えばよい。
    （実験 E1 で、`Claude_Browser|claude-in-chrome` がどの道具にも合わないことが分かった）
    """
    if matcher in ("", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_\- ,|]*", matcher):
        names = [n.strip() for n in re.split(r"[|,]", matcher)]
        return tool_name in names
    return re.search(matcher, tool_name) is not None


@functools.lru_cache(maxsize=None)
def real_python() -> str:
    """hook を動かす本物の Python。社長の Mac と同じ /usr/bin/python3（3.9）を優先する。"""
    system = Path("/usr/bin/python3")
    if system.exists():
        r = subprocess.run(
            [str(system), "-c", "import sys; print(sys.version_info >= (3, 9))"],
            capture_output=True,
        )
        if r.returncode == 0 and r.stdout.strip() == b"True":
            return str(system)
    return sys.executable


def copy_plugin(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("hooks", "lib"):
        shutil.copytree(REPO_ROOT / name, dest / name, ignore=ignore)
    return dest


def make_bin(bin_dir: Path, python: str, ran_marker: Path) -> str:
    """PATH に置くフォルダを作り、PATH の値を返す。

    python は "本物"・"なし"・"壊れた"・"半端"（途中まで出して落ちる）・
    "古い"（3.9 より古い版のとき main.py が終了コード3で終えるのと同じ動き）・
    "固まる"（途中まで出して、終わらない。hook の時間切れを試す）。
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    os.symlink("/bin/sh", bin_dir / "sh")
    bodies = {
        "本物": f'exec "{real_python()}" "$@"',
        "壊れた": "exit 1",
        "半端": "printf '%s' '{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", '\nexit 1",
        "古い": "exit 3",
        # 入力を読まずに止まったままになる（exec なので、止められるのはこの Python そのもの）
        "固まる": "printf '%s' '{\"hookSpecificOutput\": '\nexec /bin/sleep 60",
    }
    if python != "なし":
        script = bin_dir / "python3"
        # 外のコマンドを使わずに、動いた印を残す
        script.write_text(f'#!/bin/sh\n: > "{ran_marker}"\n{bodies[python]}\n', encoding="utf-8")
        script.chmod(0o755)
    return str(bin_dir)


def match_name(payload: dict) -> str:
    """matcher に当てる名前（道具の場面では道具の名前、SubagentStop では subagent の名前）。"""
    return payload.get("tool_name") or payload.get("agent_type") or ""


def hook_commands(event: str, tool_name: str = "") -> list:
    """hooks.json で、その場面（と道具）に当たるコマンドの一覧。matcher は Claude Code と同じ規則で照らす。"""
    config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    commands = []
    for entry in config["hooks"].get(event, []):
        matcher = entry.get("matcher", "")
        if matcher and not claude_matches(matcher, tool_name):
            continue
        commands.extend(h["command"] for h in entry["hooks"])
    return commands


def event_inputs(folder: Path) -> list:
    """場面ごとの入力の例（止められそうなものを選ぶ）。"""
    base = {"session_id": "test", "transcript_path": str(folder / "t.jsonl"), "cwd": str(folder)}

    def tool(name: str, tool_input: dict, cwd: Path = None) -> tuple:
        payload = {**base, "hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return ("PreToolUse", payload)

    # Bash の cd で移った先（追加の作業フォルダなど、会社のフォルダの外）
    outside_cwd = folder.parent / "別の会社"

    return [
        ("SessionStart", {**base, "hook_event_name": "SessionStart", "source": "startup"}),
        ("UserPromptSubmit", {**base, "hook_event_name": "UserPromptSubmit", "prompt": "/hojokin:nyuryoku 申請画面に入れて"}),
        tool("Write", {"file_path": str(folder / "計画書_v2.docx"), "content": "x"}),
        tool("Edit", {"file_path": str(folder / "原本" / "見積書.pdf"), "old_string": "a", "new_string": "b"}),
        tool("NotebookEdit", {"notebook_path": str(folder / "a.ipynb"), "new_source": "x"}),
        tool("mcp__Claude_Browser__computer", {"action": "left_click", "ref": "ref_12"}),
        tool("mcp__claude-in-chrome__form_input", {"ref": "ref_3", "value": "on"}),
        tool("mcp__computer-use__left_click", {"coordinate": [10, 10]}),
        tool("Bash", {"command": "echo hello"}),
        # 会社のフォルダの外を読む（会社のフォルダでは、Python が動けば拒む）
        tool("Read", {"file_path": str(folder.parent / "別の会社" / "決算書.pdf")}),
        tool("Grep", {"pattern": "売上", "path": str(folder.parent / "別の会社")}),
        tool("Glob", {"pattern": str(folder.parent / "別の会社" / "**" / "*.xlsx")}),
        # いま居るフォルダが外のとき、path を省いた Grep・Glob と相対の場所は、外を読む
        tool("Grep", {"pattern": "売上"}, cwd=outside_cwd),
        tool("Glob", {"pattern": "**/*"}, cwd=outside_cwd),
        tool("Read", {"file_path": "決算書.pdf"}, cwd=outside_cwd),
        ("PostToolUse", {**base, "hook_event_name": "PostToolUse", "tool_name": "mcp__Claude_Browser__read_page",
                         "tool_input": {}, "tool_response": "button \"提出する\" [ref_12]"}),
        ("Stop", {**base, "hook_event_name": "Stop", "stop_hook_active": False}),
        # 審査役の報告（default のモードは SubagentStop、auto モードは SubagentHandback の PreToolUse。M7）
        ("SubagentStop", {**base, "hook_event_name": "SubagentStop", "agent_type": "hojokin:shinsa",
                          "last_assistant_message": "```json\n{\"確かめの番号\": \"確かめ-0001\", \"指摘\": []}\n```"}),
        tool("SubagentHandback", {"message": "```json\n{\"確かめの番号\": \"確かめ-0001\", \"指摘\": []}\n```"}),
    ]


def run(command: str, payload: dict, *, plugin: Path, folder: Path, path: str, home: Path, data: Path,
        project_dir_env: bool = True, extra_env: dict = None, timeout: float = 30) -> subprocess.CompletedProcess:
    # 一時ファイルも HOME の隣に向け、書かれたら見つけられるようにする
    tmpdir = home.parent / "tmp"
    tmpdir.mkdir(exist_ok=True)
    env = {"PATH": path, "HOME": str(home), "TMPDIR": str(tmpdir),
           "CLAUDE_PLUGIN_ROOT": str(plugin), "CLAUDE_PLUGIN_DATA": str(data)}
    if project_dir_env:
        env["CLAUDE_PROJECT_DIR"] = str(folder)
    env.update(extra_env or {})
    return subprocess.run(
        ["/bin/sh", "-c", command],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        env=env,
        cwd=folder,
        capture_output=True,
        timeout=timeout,
    )


def hook_timeouts() -> dict:
    """hooks.json の、(場面, run.sh に渡す役割) ごとの timeout（秒）。"""
    config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    result = {}
    for event, entries in config["hooks"].items():
        for entry in entries:
            for h in entry["hooks"]:
                result[(event, h["command"].split(event, 1)[1].strip())] = h["timeout"]
    return result


def snapshot(*dirs: Path) -> dict:
    """フォルダの中のすべてのファイルとフォルダの、名前・大きさ・更新時刻・中身のハッシュ。"""
    result = {}
    for d in dirs:
        for p in sorted(d.rglob("*")):
            if p.is_dir():
                result[str(p)] = "dir"
            else:
                st = p.stat()
                result[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return result
