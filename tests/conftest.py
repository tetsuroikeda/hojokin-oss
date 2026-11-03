"""テストに共通の準備。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = REPO_ROOT / "downloads"

# lib/（スクリプトと hooks が共通に使うコード）を import できるようにする
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def repo_files() -> list[Path]:
    """リポジトリに入っているファイルと、まだコミットしていないが Git の外でないファイル。"""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    paths = [REPO_ROOT / p for p in out.decode("utf-8").split("\0") if p]
    return [p for p in paths if p.is_file()]


@pytest.fixture(scope="session")
def downloads_files() -> list[Path]:
    """公式サイトから取った資料（downloads/）。ないときは、そのテストを飛ばす。"""
    if not DOWNLOADS.is_dir():
        pytest.skip("downloads/ がありません（公式資料を取ってから流す）")
    files = [p for p in DOWNLOADS.rglob("*") if p.is_file() and p.name != ".DS_Store"]
    if not files:
        pytest.skip("downloads/ が空です（公式資料を取ってから流す）")
    return files
