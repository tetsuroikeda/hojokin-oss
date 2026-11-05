"""版の記録のテストに共通の道具（TASKS M0a）。

- 会社のフォルダは、会社のフォルダを作る道具（init_company.py）で、Claude が Bash で動かすのと同じ形で用意する
  （目印・フォルダの形・.gitignore・送り先のない Git・最初の版がそろう）。
- hook は、hooks.json のコマンド（run.sh → /usr/bin/python3 -B main.py）から、Claude Code と同じ入力で動かす。
- 履歴は、同じ /usr/bin/python3 と同梱の dulwich で、lib/history.py の log から読む
  （テストの Python では dulwich を読み込まない。tests/company_tool.py の説明）。
- 版の持ち方は2つ（DESIGN 10章。TASKS M0c）。Company(form="files") は、版のファイルの形（同期されるフォルダの形）の
  会社のフォルダを、lib/company_init.py の init(form=FILES) で用意する（道具の引数で選ぶ形は、init_company.py の
  後のタスク）。履歴を読む道具（log・content・pending・tracked・versions）は、どちらの形でも同じ入口で読む。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator, Optional

import company_tool as ct
import hook_runner as hr
from lib import status_view

SESSION = "session-m0a"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"
CASE_DIR = f"案件/{CASE}"
APPLICATION = f"{CASE_DIR}/{STAGE}/申請書"
GIT = "git"
FILES = "files"
FORMS = (GIT, FILES)
# 版のファイルの形の置き場（lib/history_form.py・lib/history_files.py と同じ）
STORE = "記録/版"
STATE = ".hojokin/一時/版の記録"
WORK = f"{STATE}/書きかけ"
LOCK_NAME = "hojokin-record.lock"

INIT_FILES_CODE = (
    "from pathlib import Path\n"
    "from lib import company_init\n"
    "result = company_init.init(Path(sys.argv[1]), form='files')\n"
    "print(json.dumps(company_init.report(result), ensure_ascii=False))"
)


class Company:
    """道具で用意した会社のフォルダと、そこで hook を動かす道具。form は版の持ち方（"git"・"files"）。"""

    def __init__(self, tmp_path: Path, name: str = "山田 製作所", before_init=None, form: str = GIT) -> None:
        assert form in FORMS, form
        self.form = form
        self.env = ct.Env(tmp_path)
        self.folder = self.env.folder(name)
        if before_init is not None:
            before_init(self.folder)
        if form == FILES:
            ct.py_json(INIT_FILES_CODE, str(self.folder))
        else:
            ct.ok(self.env.run(self.folder))
        self.plugin = hr.copy_plugin(tmp_path / "hook-plugin")
        self.data = tmp_path / "plugin-data"
        self.data.mkdir()

    # ---- ファイル（ツールや社長が変えたことにする） ----

    def write(self, rel: str, content="") -> Path:
        path = self.folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    # ---- hook ----

    def hook(self, event: str, payload: Optional[dict] = None, tool: str = "", session: str = SESSION,
             env: Optional[dict] = None):
        """hooks.json のコマンドで hook を動かし、出力の JSON を返す（なければ None）。

        env は足す環境変数（見張りの秒数 HOJOKIN_WATCH_SECONDS、版を残す秒数 HOJOKIN_RECORD_SECONDS を短くする）。
        """
        base = {"session_id": session, "transcript_path": str(self.env.home / "t.jsonl"),
                "cwd": str(self.folder), "hook_event_name": event}
        if tool:
            base["tool_name"] = tool
        commands = hr.hook_commands(event, tool)
        assert len(commands) == 1, commands
        r = hr.run(commands[0], {**base, **(payload or {})}, plugin=self.plugin, folder=self.folder,
                   path=self.env.path, home=self.env.home, data=self.data, extra_env=env, timeout=90)
        assert r.returncode == 0, (event, r)
        assert r.stderr == b"", (event, r.stderr.decode("utf-8"))
        out = r.stdout.decode("utf-8").strip()
        return json.loads(out) if out else None

    def start(self, source: str = "startup", session: str = SESSION, env: Optional[dict] = None):
        """開いたとき。M3 が毎回添える「期限と作業・共通の決まり」（lib/status_view.py）は除いて返す
        （版や原本の照らしのテストが見るのは、ほかの処理が渡す情報のため）。除いて何も残らなければ None。
        そのままの出力は start_raw。"""
        return without_brief(self.start_raw(source, session=session, env=env))

    def start_raw(self, source: str = "startup", session: str = SESSION, env: Optional[dict] = None):
        return self.hook("SessionStart", {"source": source}, session=session, env=env)

    def say(self, prompt: str, session: str = SESSION, env: Optional[dict] = None):
        return self.hook("UserPromptSubmit", {"prompt": prompt}, session=session, env=env)

    def stop(self, active: bool = False, session: str = SESSION, env: Optional[dict] = None):
        return self.hook("Stop", {"stop_hook_active": active}, session=session, env=env)

    def pre(self, tool: str, tool_input: dict, cwd: Optional[Path] = None):
        payload = {"tool_input": tool_input}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return self.hook("PreToolUse", payload, tool=tool)

    # ---- 履歴 ----

    def log(self, document: Optional[str] = None) -> list:
        code = ("from pathlib import Path\n"
                "doc = sys.argv[2] if len(sys.argv) > 2 else None\n"
                "print(json.dumps([r.as_dict() for r in history.log(Path(sys.argv[1]), doc)], ensure_ascii=False))")
        args = [str(self.folder)] + ([document] if document is not None else [])
        return ct.py_json(code, *args)

    def content(self, version: str, document: str) -> Optional[str]:
        code = ("from pathlib import Path\n"
                "data = history.content_at(Path(sys.argv[1]), sys.argv[2], sys.argv[3])\n"
                "print(json.dumps(None if data is None else data.decode('utf-8'), ensure_ascii=False))")
        return ct.py_json(code, str(self.folder), version, document)

    def pending(self) -> list:
        code = ("from pathlib import Path\n"
                "print(json.dumps([[c.path, c.kind] for c in history.pending_changes(Path(sys.argv[1]))], "
                "ensure_ascii=False))")
        return ct.py_json(code, str(self.folder))

    def tracked(self) -> list:
        """版の履歴にある今の書類（どちらの形でも。.git も `記録/版/` も作らない）。"""
        code = ("print(json.dumps(history.tracked_documents(__import__('pathlib').Path(sys.argv[1])), "
                "ensure_ascii=False))")
        return ct.py_json(code, str(self.folder))

    def versions(self) -> list:
        """新しい順の版の一覧（作者、メッセージ、変わったファイル）。"""
        if self.form == FILES:
            code = ("print(json.dumps(history.version_list(__import__('pathlib').Path(sys.argv[1])), "
                    "ensure_ascii=False))")
            return ct.py_json(code, str(self.folder))
        return ct.git_log(self.folder)

    def store_problems(self) -> list:
        """版の置き場が壊れていないか（Git の形は本物の git の fsck、版のファイルの形は lib/history_files.py の verify）。
        見つかった問題の一覧。手元に git がなければ、Git の形は空。"""
        if self.form == FILES:
            code = ("from lib import history_files\n"
                    "print(json.dumps(history_files.verify(__import__('pathlib').Path(sys.argv[1])), ensure_ascii=False))")
            return ct.py_json(code, str(self.folder))
        git = shutil.which("git")
        if git is None:
            return []
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.env.home), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull}
        r = subprocess.run([git, "fsck", "--no-progress", "--strict"], cwd=self.folder, env=env, capture_output=True,
                           timeout=120)
        return [] if r.returncode == 0 else [r.stderr.decode("utf-8")]

    def lock_path(self) -> Path:
        """版の錠の場所（Git の形は .git の中、版のファイルの形は .hojokin/一時/版の記録/ の中）。"""
        if self.form == FILES:
            place = self.folder / STATE
            place.mkdir(parents=True, exist_ok=True)
            return place / LOCK_NAME
        return self.folder / ".git" / LOCK_NAME

    def store_dir(self) -> Path:
        """版を書く置き場（書けなくすると、版を残す処理が落ちる）。Git の形は .git/objects、版のファイルの形は 記録/版。"""
        return self.folder / (STORE if self.form == FILES else ".git/objects")

    def leftovers(self) -> list:
        """途中で止まった処理の残り（錠と書きかけ）。"""
        if self.form == FILES:
            found = [f"{WORK}/{p.name}" for p in (self.folder / WORK).iterdir()] if (self.folder / WORK).is_dir() else []
            if (self.folder / STATE / LOCK_NAME).exists():
                found.append(f"{STATE}/{LOCK_NAME}")
            return sorted(found)
        return git_leftovers(self.folder)


def denied_reason(output) -> str:
    assert output is not None, "拒まれていない"
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny", hso
    return hso["permissionDecisionReason"]


SHORUI_HEAD = "## hojokin：前回から増えた・変わった書類"  # hooks/shorui_hooks.py の HEAD（B9）


def _without_shorui(text: str) -> str:
    """開いたときの、前回から増えた・変わった書類のまとまり（B9）を除く。版の履歴のテストが見るのは、ほかの処理の情報のため。"""
    start = text.find(SHORUI_HEAD)
    if start < 0:
        return text
    end = text.find("\n## ", start + len(SHORUI_HEAD))
    rest = text[:start] + (text[end + 1:] if end >= 0 else "")
    return rest.strip("\n")


def without_brief(output):
    """開いたときの出力から、期限と作業・共通の決まりのまとまり（lib/status_view.py の BRIEF_HEAD から後ろ）と、
    前回から増えた・変わった書類のまとまり（B9）を除く。除いて何も残らなければ None。"""
    if output is None:
        return None
    hso = output.get("hookSpecificOutput") or {}
    text = hso.get("additionalContext")
    if not isinstance(text, str) or status_view.BRIEF_HEAD not in text:
        return output
    rest = _without_shorui(status_view.without_brief(text))
    if not rest and set(output) == {"hookSpecificOutput"} and set(hso) <= {"hookEventName", "additionalContext"}:
        return None
    result = dict(output)
    result["hookSpecificOutput"] = {**hso, "additionalContext": rest}
    return result


def start_context(output) -> str:
    """開いたとき（SessionStart）に Claude に渡した情報。渡さなければ空。"""
    if output is None:
        return ""
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    return hso["additionalContext"]


@contextlib.contextmanager
def held_lock(folder: Path) -> Iterator[Path]:
    """ほかのセッションの hook が版を残している間（版の錠を、動いている処理が持っている）にする。

    錠には、このテストの処理（動いている）の番号を書く。hook は5秒待っても錠を取れず、その場面では版を残せない。
    版のファイルの形（.git がない）では、錠は .hojokin/一時/版の記録/ の中。
    """
    if (folder / ".git").is_dir():
        lock = folder / ".git" / LOCK_NAME
    else:
        (folder / STATE).mkdir(parents=True, exist_ok=True)
        lock = folder / STATE / LOCK_NAME
    lock.write_text(f"{os.getpid()}\n", encoding="ascii")
    try:
        yield lock
    finally:
        lock.unlink()


def carried_notes(folder: Path) -> list:
    """版の錠が取れなかった場面の控え（.hojokin/一時/版の記録/錠待ち/）の名前の一覧。"""
    place = folder / ".hojokin" / "一時" / "版の記録" / "錠待ち"
    return sorted(p.name for p in place.iterdir()) if place.is_dir() else []


def git_leftovers(folder: Path) -> list:
    """.git に残った錠と書きかけの中身（途中で止まった処理の残り）。"""
    git = folder / ".git"
    found = [p for p in git.rglob("*.lock")]
    found += [p for p in (git / "objects").iterdir() if p.name.startswith("hojokin-tmp-")]
    return sorted(p.relative_to(git).as_posix() for p in found)
