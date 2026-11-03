"""会社のフォルダの外に書かない・外を読まない（DESIGN 5章）の、PreToolUse の部分。

設定の blockWritesOutsideWorkingDirectories がデスクトップアプリの版では効かなかったので（実験 E6）、
PreToolUse の hook が、外への Write・Edit・NotebookEdit を拒む。
ユーザーの設定の追加の作業フォルダは blockReadsOutsideWorkingDirectories では止まらないと見られるので
（実験 E6、DESIGN 4.7）、外を読む Read・Grep・Glob なども拒む（TASKS S3b）。
hooks.json から run.sh を通して動かしたときの確かめは、tests/test_hooks_run.py にある。
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import pre_tool_use  # noqa: E402


@pytest.fixture
def folders(tmp_path):
    company = tmp_path / "会社のフォルダ"
    (company / ".hojokin").mkdir(parents=True)
    (company / "下書き").mkdir()
    outside = tmp_path / "別の会社"
    outside.mkdir()
    return company, outside


def decide(tool: str, folder: Path, cwd=None, **tool_input):
    """hook の入力を作って判定する。cwd を渡すと、hook の入力の cwd（Claude がいま居るフォルダ）にする。"""
    data = {"tool_name": tool, "tool_input": tool_input}
    if cwd is not None:
        data["cwd"] = str(cwd)
    return pre_tool_use.handle(data, folder)


def is_denied(output) -> bool:
    return bool(output) and output["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_inside_is_allowed(folders, tool) -> None:
    company, _ = folders
    assert decide(tool, company, file_path=str(company / "下書き" / "計画.md")) is None


def test_relative_inside_is_allowed(folders) -> None:
    company, _ = folders
    assert decide("Write", company, file_path="下書き/計画.md") is None


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_outside_is_denied(folders, tool) -> None:
    company, outside = folders
    output = decide(tool, company, file_path=str(outside / "メモ.txt"))
    assert is_denied(output)
    assert "会社のフォルダの外" in output["hookSpecificOutput"]["permissionDecisionReason"]


def test_notebook_outside_is_denied(folders) -> None:
    company, outside = folders
    assert is_denied(decide("NotebookEdit", company, notebook_path=str(outside / "a.ipynb")))


def test_dotdot_escape_is_denied(folders) -> None:
    company, _ = folders
    assert is_denied(decide("Write", company, file_path="下書き/../../別の会社/メモ.txt"))


def test_symlink_to_outside_is_denied(folders) -> None:
    company, outside = folders
    os.symlink(outside, company / "外への別名")
    assert is_denied(decide("Write", company, file_path=str(company / "外への別名" / "メモ.txt")))


def test_home_tilde_is_denied(folders, monkeypatch, tmp_path) -> None:
    company, _ = folders
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert is_denied(decide("Write", company, file_path="~/メモ.txt"))


def test_claude_plan_file_is_allowed(folders, monkeypatch, tmp_path) -> None:
    company, _ = folders
    home = tmp_path / "home"
    (home / ".claude" / "plans").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert decide("Write", company, file_path=str(home / ".claude" / "plans" / "plan.md")) is None


@pytest.mark.parametrize("tool", ["Bash", "WebFetch", "Skill"])
def test_other_tools_are_not_judged_here(folders, tool) -> None:
    company, outside = folders
    assert decide(tool, company, file_path=str(outside / "メモ.txt"), command=f"cat {outside}/メモ.txt") is None


# ---- 会社のフォルダの外を読まない（DESIGN 5章・4.7。TASKS S3b） ----
# ユーザーの設定にある追加の作業フォルダは、設定の blockReadsOutsideWorkingDirectories では止まらないと
# 見られるので（実験 E6）、PreToolUse の hook が、外を読む Read・Grep・Glob なども拒む。


def read_denied_reason(output) -> str:
    assert is_denied(output), output
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "会社のフォルダの外は読めません" in reason
    return reason


def test_read_inside_is_allowed(folders) -> None:
    company, _ = folders
    (company / "下書き" / "計画.md").write_text("x", encoding="utf-8")
    assert decide("Read", company, file_path=str(company / "下書き" / "計画.md")) is None
    assert decide("Read", company, file_path="下書き/計画.md") is None
    # 目印や設定のフォルダも、会社のフォルダの中なので読める
    assert decide("Read", company, file_path=str(company / ".hojokin")) is None


@pytest.mark.parametrize("tool,key", [("Read", "file_path"), ("NotebookRead", "notebook_path"),
                                      ("Grep", "path"), ("Glob", "path"), ("LS", "path")])
def test_read_outside_is_denied(folders, tool, key) -> None:
    company, outside = folders
    reason = read_denied_reason(decide(tool, company, **{key: str(outside / "決算書.pdf")}))
    # 取り込みの道具へ案内する（社長が伝えた場所は、写してから読む。SPEC F5）
    assert "取り込み" in reason


def test_grep_without_path_in_company_folder_is_allowed(folders) -> None:
    """path を省いた Grep は、いま居るフォルダ（cwd）を探す。cwd が会社のフォルダ（かその下）なら通す。"""
    company, _ = folders
    assert decide("Grep", company, cwd=company, pattern="売上") is None
    assert decide("Grep", company, cwd=company / "下書き", pattern="売上") is None
    assert decide("Grep", company, cwd=company, pattern="売上", path=str(company / "下書き"), glob="*.md") is None
    # cwd が渡らないときは、会社のフォルダに居るとみなす
    assert decide("Grep", company, pattern="売上") is None


# ---- いま居るフォルダ（hook の入力の cwd）が会社のフォルダの外のとき ----
# Bash の cd で追加の作業フォルダに移ると、path を省いた Grep・Glob や相対の場所は、そこを読む。
# 相対の場所と Glob の起点は cwd から解き、読む場所が取れないときは cwd そのものを照らす。


@pytest.mark.parametrize("tool,tool_input", [
    ("Grep", {"pattern": "売上"}),
    ("Grep", {"pattern": "売上", "glob": "*.xlsx"}),
    ("Glob", {"pattern": "**/*"}),
    ("Glob", {"pattern": "*.xlsx"}),
    ("Glob", {"pattern": "決算/*.pdf"}),
    ("Read", {"file_path": "決算書.pdf"}),
    ("NotebookRead", {"notebook_path": "a.ipynb"}),
    ("LS", {}),
    ("LS", {"path": "."}),
    ("Read", {}),
])
def test_read_from_outside_cwd_is_denied(folders, tool, tool_input) -> None:
    company, outside = folders
    read_denied_reason(decide(tool, company, cwd=outside, **tool_input))


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_relative_write_from_outside_cwd_is_denied(folders, tool) -> None:
    company, outside = folders
    output = decide(tool, company, cwd=outside, file_path="メモ.txt")
    assert is_denied(output)
    assert "会社のフォルダの外" in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert is_denied(decide("NotebookEdit", company, cwd=outside, notebook_path="a.ipynb"))


def test_absolute_inside_from_outside_cwd_is_allowed(folders) -> None:
    """cwd が外でも、会社のフォルダの中を絶対の場所で指せば通す（拒みすぎない）。"""
    company, outside = folders
    inside = company / "下書き"
    assert decide("Read", company, cwd=outside, file_path=str(inside / "計画.md")) is None
    assert decide("Grep", company, cwd=outside, pattern="売上", path=str(inside)) is None
    assert decide("Glob", company, cwd=outside, pattern=str(company / "**" / "*.md")) is None
    assert decide("Glob", company, cwd=outside, pattern="*.md", path=str(inside)) is None
    assert decide("Write", company, cwd=outside, file_path=str(inside / "計画.md")) is None
    # 外の cwd から「..」で会社のフォルダの中へ戻る相対の場所も、中なので通す
    assert decide("Read", company, cwd=outside, file_path="../会社のフォルダ/下書き/計画.md") is None


def test_relative_from_subfolder_cwd(folders) -> None:
    """cwd が会社のフォルダの下なら、相対の場所はそこから解く。「..」で外に出れば拒む。"""
    company, _ = folders
    sub = company / "下書き"
    assert decide("Read", company, cwd=sub, file_path="計画.md") is None
    assert decide("Glob", company, cwd=sub, pattern="../**/*.md") is None
    assert decide("Write", company, cwd=sub, file_path="計画.md") is None
    read_denied_reason(decide("Read", company, cwd=sub, file_path="../../別の会社/決算書.pdf"))
    read_denied_reason(decide("Glob", company, cwd=sub, pattern="../../別の会社/*.xlsx"))
    assert is_denied(decide("Write", company, cwd=sub, file_path="../../別の会社/メモ.txt"))


# ---- 名前の文字の形（NFD と NFC） ----
# Finder などで作った会社のフォルダの名前は、濁点が分かれた形（NFD）のことがある（実験 E5）。
# CLAUDE_PROJECT_DIR は NFD のまま、Claude が渡す場所は濁点の付いた1文字の形（NFC）になりやすい。

NAME = "株式会社グリーン"


@pytest.mark.parametrize("folder_form,path_form", [("NFD", "NFC"), ("NFC", "NFD"), ("NFD", "NFD")])
def test_nfd_and_nfc_names_are_the_same_folder(tmp_path, folder_form, path_form) -> None:
    company = tmp_path / unicodedata.normalize(folder_form, NAME)
    (company / ".hojokin").mkdir(parents=True)
    (company / "下書き").mkdir()
    (company / "下書き" / "計画.md").write_text("x", encoding="utf-8")
    as_path = tmp_path / unicodedata.normalize(path_form, NAME)
    sub = as_path / "下書き"
    for cwd in (None, company, as_path):
        assert decide("Read", company, cwd=cwd, file_path=str(sub / "計画.md")) is None
        assert decide("Grep", company, cwd=cwd, pattern="売上", path=str(sub)) is None
        assert decide("Glob", company, cwd=cwd, pattern=str(as_path / "**" / "*.md")) is None
        assert decide("LS", company, cwd=cwd, path=str(as_path)) is None
        assert decide("Write", company, cwd=cwd, file_path=str(sub / "計画.md")) is None
        assert decide("Edit", company, cwd=cwd, file_path=str(sub / "計画.md")) is None
    # cwd が別の形で渡っても、path を省いた Grep・Glob、相対の場所は中として通す
    assert decide("Grep", company, cwd=as_path, pattern="売上") is None
    assert decide("Glob", company, cwd=as_path, pattern="**/*.md") is None
    assert decide("Read", company, cwd=as_path, file_path="下書き/計画.md") is None
    assert decide("Write", company, cwd=as_path, file_path="下書き/計画.md") is None


def test_nfc_normalizing_does_not_open_outside(tmp_path) -> None:
    """形をそろえても、名前の違う外のフォルダ（似た名前、前方が同じ名前）は拒む。"""
    company = tmp_path / unicodedata.normalize("NFD", NAME)
    (company / ".hojokin").mkdir(parents=True)
    for other in ("株式会社クリーン", NAME + "2", "株式会社グリーン別"):
        for form in ("NFC", "NFD"):
            path = tmp_path / unicodedata.normalize(form, other) / "決算書.pdf"
            read_denied_reason(decide("Read", company, file_path=str(path)))
            assert is_denied(decide("Write", company, file_path=str(path)))


@pytest.mark.parametrize("pattern", ["**/*.md", "下書き/*.docx", "*.xlsx", "下書き/計画.md"])
def test_glob_relative_pattern_is_allowed(folders, pattern) -> None:
    company, _ = folders
    assert decide("Glob", company, pattern=pattern) is None
    assert decide("Glob", company, pattern=pattern, path=str(company)) is None


def test_glob_pattern_outside_is_denied(folders, monkeypatch, tmp_path) -> None:
    company, outside = folders
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    read_denied_reason(decide("Glob", company, pattern=str(outside / "**" / "*.xlsx")))
    read_denied_reason(decide("Glob", company, pattern="../別の会社/*.xlsx"))
    read_denied_reason(decide("Glob", company, pattern="~/Desktop/*.pdf"))
    read_denied_reason(decide("Glob", company, pattern="/*"))
    # 中を指す絶対の型は通す
    assert decide("Glob", company, pattern=str(company / "**" / "*.md")) is None


def test_read_dotdot_and_symlink_escape_is_denied(folders) -> None:
    company, outside = folders
    read_denied_reason(decide("Read", company, file_path="下書き/../../別の会社/メモ.txt"))
    os.symlink(outside, company / "外への別名")
    read_denied_reason(decide("Read", company, file_path=str(company / "外への別名" / "メモ.txt")))
    read_denied_reason(decide("Grep", company, pattern="x", path=str(company / "外への別名")))


def test_read_home_tilde_is_denied(folders, monkeypatch, tmp_path) -> None:
    company, _ = folders
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    read_denied_reason(decide("Read", company, file_path="~/.ssh/id_rsa"))


def test_read_plugin_files_is_denied(folders) -> None:
    """プラグインの中のファイル（knowledge/ など）も外として読まない。中身はスクリプトが出力して渡す（DESIGN 4.7）。"""
    company, _ = folders
    plugin = Path(__file__).resolve().parent.parent
    read_denied_reason(decide("Read", company, file_path=str(plugin / "knowledge")))
    read_denied_reason(decide("Grep", company, pattern="審査", path=str(plugin)))


def claude_session(tmp_path):
    """Claude Code の会話の記録と、このセッションの置き場（大きな道具の結果を置く tool-results/）。"""
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / "-会社のフォルダ"
    (project / "sess-1" / "tool-results").mkdir(parents=True)
    (project / "sess-2" / "tool-results").mkdir(parents=True)
    (home / ".claude" / "plans").mkdir(parents=True)
    return home, project


def test_claude_code_own_files_are_allowed(folders, monkeypatch, tmp_path) -> None:
    """設定の blockReads と同じく、Claude Code 自身が要るファイルは通す（計画のファイルと、このセッションの置き場）。"""
    company, _ = folders
    home, project = claude_session(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    data = {"tool_name": "Read", "transcript_path": str(project / "sess-1.jsonl"),
            "tool_input": {"file_path": str(project / "sess-1" / "tool-results" / "toolu_1.txt")}}
    assert pre_tool_use.handle(data, company) is None
    assert decide("Read", company, file_path=str(home / ".claude" / "plans" / "plan.md")) is None


def test_other_claude_files_are_denied(folders, monkeypatch, tmp_path) -> None:
    """~/.claude の全体は通さない。別のセッションの置き場、認証情報、会話の記録の一覧は読まない。"""
    company, _ = folders
    home, project = claude_session(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    transcript = str(project / "sess-1.jsonl")
    for path in (project / "sess-2" / "tool-results" / "toolu_9.txt",
                 home / ".claude" / ".credentials.json",
                 home / ".claude" / "settings.json",
                 project / "sess-2.jsonl",
                 project):
        data = {"tool_name": "Read", "transcript_path": transcript, "tool_input": {"file_path": str(path)}}
        read_denied_reason(pre_tool_use.handle(data, company))
    # 会話の記録の場所が渡らないときは、セッションの置き場も通さない
    data = {"tool_name": "Read", "tool_input": {"file_path": str(project / "sess-1" / "tool-results" / "t.txt")}}
    read_denied_reason(pre_tool_use.handle(data, company))
