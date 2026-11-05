"""T0-1 制度の追加（SPEC 共通の要件「制度データで動く」、DESIGN 9.1、TASKS B1b）。

合格ライン：持続化に対応したコミットの差分で、プログラムの変更0件（変わってよいのはテスト用の材料、正解、同梱の知見だけ）。

- 持続化に対応したコミットは、件名が「B1a 持続化：」「B1b 持続化：」で始まるもの（TASKS B1a・B1b の決まり）。
  持続化のために先に入れた直し（省力化でも同じく起きる不具合の直しと、制度の名前で分けない一般化）は、
  件名を「B1b の前の直し：」にして別のコミットにしてあり、ここでは数えない（数えるコミットと分けるため、印が重ならない）。
- 変わってよい場所：testdata/（テスト用の材料と正解）、evals/（振る舞いテストのケースと保存した状態）、
  tests/（自動のテストと開発の道具）、knowledge/（同梱の知見）。
  ほか（skills/・hooks/・lib/・agents/・schema/・mock/・.claude-plugin/ など）が1つでも変わっていれば落ちる。
- 当たるコミットが1件もなければ落ちる（調べた対象がないのに通らないように）。
- Git の履歴がない所（zip で取った写しなど）では、調べられないので飛ばす。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARKERS = ("B1a 持続化：", "B1b 持続化：")
ALLOWED = ("testdata/", "evals/", "tests/", "knowledge/")


def _git(*args: str) -> str:
    done = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8")
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip())
    return done.stdout


def jizokuka_commits() -> List[Tuple[str, str]]:
    """HEAD までの履歴のうち、持続化に対応したコミット（sha、件名）。"""
    try:
        lines = _git("log", "--no-merges", "--format=%H%x09%s", "HEAD").splitlines()
    except (OSError, RuntimeError) as e:
        pytest.skip(f"Git の履歴を読めません（{e}）")
    found = []
    for line in lines:
        sha, _tab, subject = line.partition("\t")
        if subject.startswith(MARKERS):
            found.append((sha, subject))
    return found


def changed_paths(sha: str) -> List[str]:
    out = _git("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", sha)
    return [p for p in out.split("\0") if p]


def test_jizokuka_commits_change_no_program() -> None:
    commits = jizokuka_commits()
    assert commits, f"持続化に対応したコミット（件名が {'・'.join(MARKERS)} で始まるもの）が見つかりません"
    program = []
    lines = []
    for sha, subject in commits:
        paths = changed_paths(sha)
        bad = [p for p in paths if not p.startswith(ALLOWED)]
        program += [(sha[:7], p) for p in bad]
        lines.append(f"{sha[:7]} {subject[:60]}：変えたファイル {len(paths)}、プログラムの変更 {len(bad)}")
    print("\n持続化に対応したコミット：\n" + "\n".join(lines))
    print(f"プログラムの変更：{len(program)}件")
    assert not program, "持続化に対応したコミットで、プログラムが変わっています：" + "、".join(f"{s} {p}" for s, p in program)


def test_markers_do_not_match_the_prefixes() -> None:
    """先に入れた直しの件名は、持続化に対応したコミットの印に当たらない（数えるコミットが混ざらない）。"""
    assert not "B1b の前の直し：入力先が申請画面の様式".startswith(MARKERS)
    assert "B1b 持続化：材料".startswith(MARKERS)
