"""段階ごとに保存した会社のフォルダと、eval で戻す道具（TASKS M13、DESIGN 11章。evals/_lib/fukugen.py）。

- 保存した状態（evals/状態/<段階>/）に、公式資料とその写し（資料の本文、読み取り役の読み取り、版の履歴）を入れない。
- 戻す道具が、downloads/ から公式資料を写し、製品の道具で資料の本文・制度データ・段階のフォルダ・版の履歴を作る。
- 戻したフォルダを開いたとき、原本と公式資料の照らしで「変わっていた」と言われず、社長が手で変えたものも出ない。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import DOWNLOADS, REPO_ROOT
from hook_runner import real_python

STATES = REPO_ROOT / "evals" / "状態"
FUKUGEN_SH = REPO_ROOT / "evals" / "_lib" / "fukugen.sh"
# 保存した状態に入れてはいけない場所（公式資料と、その写しになるもの）
FORBIDDEN_PARTS = ("公式資料", "資料の本文", "読み取り", ".git", "版")
PLACEHOLDER_WORDS = ("写さない",)


def _stages() -> list:
    return sorted(p.stem for p in STATES.glob("*.json") if (STATES / p.stem).is_dir())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_there_is_a_saved_state() -> None:
    assert "書く前" in _stages()


@pytest.mark.parametrize("stage", _stages())
def test_saved_state_has_no_official_copies(stage: str) -> None:
    """保存した状態に、公式資料・資料の本文・読み取り・版の履歴・制度データの根拠の文がない。"""
    saved = STATES / stage
    for path in saved.rglob("*"):
        rel = path.relative_to(saved)
        assert not any(part in FORBIDDEN_PARTS for part in rel.parts), f"保存した状態に入れない場所です：{stage}/{rel}"
        assert not rel.as_posix().startswith("記録/制度データ"), f"制度データは保存しない（正解から置く）：{stage}/{rel}"
        if path.suffix == ".json":
            text = path.read_text(encoding="utf-8")
            assert "根拠の文" not in text or all(w in text for w in PLACEHOLDER_WORDS), \
                f"根拠の文（資料の文の写し）が入っています：{stage}/{rel}"


@pytest.mark.parametrize("stage", _stages())
def test_recipe_points_to_files_in_repo(stage: str) -> None:
    """戻し方が指す制度データと取る資料の一覧が、リポにある。"""
    recipe = json.loads((STATES / f"{stage}.json").read_text(encoding="utf-8"))
    for item in recipe.get("制度データ", []):
        assert (REPO_ROOT / item["元"]).is_file(), item["元"]
    for item in recipe.get("公式資料", []):
        listed = json.loads((REPO_ROOT / item["取る資料"]).read_text(encoding="utf-8"))
        urls = {doc["URL"] for doc in listed["資料"]}
        assert urls == set(item["ファイル"]), "取る資料の一覧の URL と、downloads/ のファイルの対応がそろっていない"


def _restore(stage: str, folder: Path) -> subprocess.CompletedProcess:
    folder.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent), "LANG": "ja_JP.UTF-8"}
    return subprocess.run(["bash", str(FUKUGEN_SH), stage, str(folder)], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=120)


def _open(folder: Path) -> dict:
    """開いたときの hook を、Claude Code と同じく hooks/main.py で動かす。"""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent), "CLAUDE_PROJECT_DIR": str(folder),
           "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}
    payload = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "m13-test", "cwd": str(folder)}
    done = subprocess.run([real_python(), "-B", str(REPO_ROOT / "hooks" / "main.py"), "SessionStart"],
                          input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", env=env,
                          cwd=str(folder), timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout) if done.stdout.strip() else {}


@pytest.fixture(scope="module")
def restored(tmp_path_factory) -> Path:
    if not DOWNLOADS.is_dir():
        pytest.skip("downloads/ がありません（公式資料を取ってから流す）")
    folder = tmp_path_factory.mktemp("fukugen") / "会社"
    done = _restore("書く前", folder)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "fukugen: ok" in done.stdout
    return folder


def test_official_documents_come_from_downloads(restored: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    recipe = json.loads((STATES / "書く前.json").read_text(encoding="utf-8"))
    item = recipe["公式資料"][0]
    official = restored / "案件" / item["案件"] / "公式資料"
    placed = sorted(p for p in official.iterdir() if p.is_file())
    assert len(placed) == len(item["ファイル"])
    want = {_sha256(DOWNLOADS / rel) for rel in item["ファイル"].values()}
    assert {_sha256(p) for p in placed} == want
    assert all(not os.access(str(p), os.W_OK) for p in placed), "公式資料は読み取り専用で置く"
    texts = restored / "記録" / "資料の本文" / item["案件"]
    listed = json.loads((texts / "資料の一覧.json").read_text(encoding="utf-8"))
    assert {d["id"] for d in listed["資料"]} >= {"要領8", "応募手引8"}
    assert (texts / "要領8" / "ページの対応.json").is_file()


def test_records_and_folders_are_restored(restored: Path) -> None:
    assert (restored / ".hojokin").is_dir()
    settings = json.loads((restored / ".hojokin" / "設定.json").read_text(encoding="utf-8"))
    assert settings == {"今日の日付": "2026-11-05"}
    seido = restored / "記録" / "制度データ" / "省力化_第8回.json"
    assert _sha256(seido) == _sha256(REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json")
    case = restored / "案件" / "2026_省力化（一般型）第9回"
    assert (case / "1_申請" / "申請書").is_dir() and (case / "1_申請" / "添付する書類").is_dir()
    assert (case / "概要と流れ.docx").is_file()
    ledger = json.loads((restored / "記録" / "書類の台帳.json").read_text(encoding="utf-8"))
    for entry in ledger["原本"]:
        path = restored / entry["場所"]
        assert _sha256(path) == entry["ハッシュ"]
        assert not os.access(str(path), os.W_OK), "原本は読み取り専用で置く"


def test_history_has_one_tool_version_and_nothing_left(restored: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from lib import history

    rows = history.version_list(restored)
    assert len(rows) == 2  # 会社のフォルダを用意した版と、戻した版
    assert all(r["author"].startswith(history.TOOL) for r in rows)
    assert "保存した状態（書く前）から戻した" in rows[0]["message"]
    assert history.pending_changes(restored) == []
    assert history.remotes(history.open_or_init(restored)) == []


def test_opening_the_restored_folder_finds_nothing_changed(restored: Path) -> None:
    """開いたとき、原本・公式資料の照らしで何も言われず、社長が手で変えた版も残らない。"""
    sys.path.insert(0, str(REPO_ROOT))
    from lib import history

    output = _open(restored)
    context = output.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "開いたときの期限と作業" in context
    assert "原本・公式資料" not in context, context
    assert "2026_省力化（一般型）第9回" in context
    assert len(history.version_list(restored)) == 2
    assert (restored / "今の状態.html").is_file()
