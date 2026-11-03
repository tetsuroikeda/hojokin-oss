"""T0-13 会社のフォルダでないフォルダ（hooks の部分）。

SPEC：会社のフォルダでないフォルダで、プラグインの hooks を動かす。
合格ライン：hooks は何も止めず、何も書かない。
（道具の部分は R2 で足し、Z1 で全体を確かめる）

hooks.json にあるコマンドを、Claude Code と同じように場面ごとの入力を渡して動かす。
Python が動くとき・見つからないとき・壊れているときのどれでも、
- 終了コードは0で、標準出力にも標準エラーにも何も出さない（止める判定も、差し戻しも、文もない）
- 目印のないフォルダ、HOME、一時ファイルの置き場、プラグインのデータの置き場、プラグインのフォルダの中身が変わらない
- Python を動かさない（目印の確かめは run.sh が先に行う）
hook は hooks/hooks.json にしか書かない（plugin.json・skill・subagent には書かない）ことも確かめる。
"""

from __future__ import annotations

import json
import subprocess

import hook_runner as hr
import pytest


def make_plain_folder(tmp_path):
    folder = tmp_path / "ふつうのフォルダ"
    folder.mkdir()
    (folder / "メモ.txt").write_text("会社のフォルダではない", encoding="utf-8")
    # 目印と紛らわしい名前のファイル（フォルダではない）があっても、会社のフォルダとみなさない
    (folder / ".hojokin").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    return folder, home, data


def test_every_scene_goes_through_run_sh() -> None:
    """どの場面の hook も run.sh から動く（目印の確かめを通らずに動くものがない）。"""
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    assert set(config["hooks"]) == set(hr.EVENTS)
    for event, entries in config["hooks"].items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command"
                assert h["command"].startswith('sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" ' + event), h["command"]


def frontmatter(path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ""
    return text[4:text.index("\n---", 4)]


def test_hooks_only_in_hooks_json() -> None:
    """hooks/hooks.json のほかに hook を書いた所がない（あれば、run.sh を通らずに動くおそれがある）。"""
    manifest = json.loads((hr.REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest.get("hooks") in (None, "./hooks/hooks.json"), manifest.get("hooks")
    docs = sorted(hr.REPO_ROOT.glob("skills/*/SKILL.md")) + sorted(hr.REPO_ROOT.glob("agents/*.md"))
    assert docs
    for doc in docs:
        keys = [line.split(":", 1)[0] for line in frontmatter(doc).splitlines() if line and not line[0].isspace()]
        assert "hooks" not in keys, doc


@pytest.mark.parametrize("python", ["本物", "なし", "壊れた"])
@pytest.mark.parametrize("project_dir_env", [True, False], ids=["CLAUDE_PROJECT_DIRあり", "今いるフォルダだけ"])
def test_hooks_do_nothing_outside_company_folder(tmp_path, python, project_dir_env) -> None:
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_plain_folder(tmp_path)
    ran = tmp_path / "python-ran"
    path = hr.make_bin(tmp_path / "bin", python, ran)
    (tmp_path / "tmp").mkdir()
    # 目印のないフォルダ・HOME・一時ファイルの置き場・プラグインのデータ・プラグインの写しを、まとめて見る
    before = hr.snapshot(tmp_path)

    count = 0
    for event, payload in hr.event_inputs(folder):
        for command in hr.hook_commands(event, payload.get("tool_name", "")):
            r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data,
                       project_dir_env=project_dir_env)
            assert r.returncode == 0, (event, payload.get("tool_name"), r)
            assert r.stdout == b"", (event, payload.get("tool_name"), r.stdout.decode("utf-8"))
            assert r.stderr == b"", (event, payload.get("tool_name"), r.stderr.decode("utf-8"))
            count += 1

    # 5つの場面と、守る道具の PreToolUse をすべて動かした
    assert count >= len(hr.EVENTS) + 5
    assert not ran.exists(), "目印のないフォルダで Python が動いた"
    assert hr.snapshot(tmp_path) == before


def test_python_side_also_checks_marker(tmp_path) -> None:
    """run.sh を通さずに main.py を動かしても、目印がなければ何もしない（DESIGN 5章）。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_plain_folder(tmp_path)
    before = hr.snapshot(folder, home, data, plugin)
    for event, payload in hr.event_inputs(folder):
        r = subprocess.run(
            [hr.real_python(), "-B", str(plugin / "hooks" / "main.py"), event, "guard"],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_PROJECT_DIR": str(folder)},
            cwd=folder,
            capture_output=True,
            timeout=30,
        )
        assert r.returncode == 0, r
        assert r.stdout == b"" and r.stderr == b"", r
    assert hr.snapshot(folder, home, data, plugin) == before
