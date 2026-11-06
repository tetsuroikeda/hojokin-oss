"""テストに共通の準備。"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = REPO_ROOT / "downloads"

# lib/（スクリプトと hooks が共通に使うコード）を import できるようにする
sys.path.insert(0, str(REPO_ROOT))

# 開いたときの公式サイトの確かめ（B28。hooks/kaitei_hooks.py）は、テストでは止める。環境を受け継いで hook を動かす
# テストの補助（tests/jizokuka_tool.py など）にも効く。確かめるテスト（tests/test_T7_2.py）は、その場で "1" にする
os.environ.setdefault("HOJOKIN_SITE_CHECK", "0")

# 前の回の一時フォルダ（pytest-of-<ユーザー>/pytest-<番号>）を片付ける。テストは原本を読み取り専用にし、
# 開発用の Stop hook は時間切れの pytest を止める。そのため pytest 自身の片付けが消せずに残り（止めた回は錠が3日残る）、
# 1回 7〜11GB がたまってディスクがいっぱいになった（11/5 21:45、11/7 0:30）。ほかのセッションが同じ Mac で流している回を
# 消さないよう、3時間より前に変わったものだけを、書き込めるように戻してから消す。
OLD_BASETEMP_SECONDS = 3 * 60 * 60


def _lock_is_alive(numbered: Path) -> bool:
    """pytest がその回の錠（.lock）に書いた pid が、まだ動いているか（負荷で3時間を超えた回を消さない）。"""
    try:
        pid = int((numbered / ".lock").read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_old_basetemps() -> None:
    root = Path(tempfile.gettempdir()) / f"pytest-of-{getpass.getuser()}"
    if not root.is_dir():
        return
    current = (root / "pytest-current").resolve() if (root / "pytest-current").exists() else None
    limit = time.time() - OLD_BASETEMP_SECONDS
    for old in root.iterdir():
        if not re.fullmatch(r"pytest-\d+", old.name) or old.is_symlink() or old.resolve() == current:
            continue
        try:
            if old.stat().st_mtime > limit or _lock_is_alive(old):
                continue
            for dirpath, dirnames, filenames in os.walk(old):
                for name in dirnames + filenames:
                    path = os.path.join(dirpath, name)
                    if not os.path.islink(path):
                        os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
            shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue


def pytest_configure(config) -> None:
    # 並べて流すとき（pytest-xdist）は、まとめ役の1回だけで片付ける
    if not hasattr(config, "workerinput"):
        _remove_old_basetemps()


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
