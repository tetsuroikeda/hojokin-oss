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


def decide(tool: str, folder: Path, **tool_input):
    return pre_tool_use.handle({"tool_name": tool, "tool_input": tool_input}, folder)


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


def test_grep_without_path_reads_company_folder(folders) -> None:
    company, _ = folders
    assert decide("Grep", company, pattern="売上") is None
    assert decide("Grep", company, pattern="売上", path=str(company / "下書き"), glob="*.md") is None


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
