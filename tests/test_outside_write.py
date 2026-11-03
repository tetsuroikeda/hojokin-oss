"""会社のフォルダの外に書かない（DESIGN 5章）の、PreToolUse の部分。

設定の blockWritesOutsideWorkingDirectories がデスクトップアプリの版では効かなかったので（実験 E6）、
PreToolUse の hook が、外への Write・Edit・NotebookEdit を拒む。
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


def test_other_tools_are_not_judged_here(folders) -> None:
    company, outside = folders
    assert decide("Read", company, file_path=str(outside / "メモ.txt")) is None
