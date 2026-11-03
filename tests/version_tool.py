"""版の記録のテストに共通の道具（TASKS M0a）。

- 会社のフォルダは、会社のフォルダを作る道具（init_company.py）で、Claude が Bash で動かすのと同じ形で用意する
  （目印・フォルダの形・.gitignore・送り先のない Git・最初の版がそろう）。
- hook は、hooks.json のコマンド（run.sh → /usr/bin/python3 -B main.py）から、Claude Code と同じ入力で動かす。
- 履歴は、同じ /usr/bin/python3 と同梱の dulwich で、lib/history.py の log から読む
  （テストの Python では dulwich を読み込まない。tests/company_tool.py の説明）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import company_tool as ct
import hook_runner as hr

SESSION = "session-m0a"
CASE = "2026_省力化（一般型）第9回"
STAGE = "1_申請"
APPLICATION = f"案件/{CASE}/{STAGE}/申請書"


class Company:
    """道具で用意した会社のフォルダと、そこで hook を動かす道具。"""

    def __init__(self, tmp_path: Path, name: str = "山田 製作所", before_init=None) -> None:
        self.env = ct.Env(tmp_path)
        self.folder = self.env.folder(name)
        if before_init is not None:
            before_init(self.folder)
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

    def hook(self, event: str, payload: Optional[dict] = None, tool: str = "", session: str = SESSION):
        base = {"session_id": session, "transcript_path": str(self.env.home / "t.jsonl"),
                "cwd": str(self.folder), "hook_event_name": event}
        if tool:
            base["tool_name"] = tool
        commands = hr.hook_commands(event, tool)
        assert len(commands) == 1, commands
        r = hr.run(commands[0], {**base, **(payload or {})}, plugin=self.plugin, folder=self.folder,
                   path=self.env.path, home=self.env.home, data=self.data)
        assert r.returncode == 0, (event, r)
        assert r.stderr == b"", (event, r.stderr.decode("utf-8"))
        out = r.stdout.decode("utf-8").strip()
        return json.loads(out) if out else None

    def start(self, source: str = "startup", session: str = SESSION):
        return self.hook("SessionStart", {"source": source}, session=session)

    def say(self, prompt: str, session: str = SESSION):
        return self.hook("UserPromptSubmit", {"prompt": prompt}, session=session)

    def stop(self, active: bool = False, session: str = SESSION):
        return self.hook("Stop", {"stop_hook_active": active}, session=session)

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
        code = ("repo = history.open_or_init(__import__('pathlib').Path(sys.argv[1]))\n"
                "print(json.dumps(history.tracked_paths(repo), ensure_ascii=False))")
        return ct.py_json(code, str(self.folder))

    def versions(self) -> list:
        """新しい順の版の一覧（作者、メッセージ、変わったファイル）。"""
        return ct.git_log(self.folder)


def denied_reason(output) -> str:
    assert output is not None, "拒まれていない"
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny", hso
    return hso["permissionDecisionReason"]
