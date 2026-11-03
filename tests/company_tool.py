"""会社のフォルダを作る道具を、Claude が Bash で動かすのと同じ形で動かすための道具（テスト用）。

- プラグインの lib/ と skills/ を一時フォルダに写して動かす（__pycache__ などが書かれないかも見るため）。
- 道具は、社長の Mac と同じ /usr/bin/python3（3.9）で動かす。PATH には python3 と sh だけを置く（git も uv もない）。
- 版の履歴に使う dulwich はプラグインに同梱している（lib/vendor/）。準備も通信も要らない。
  通信を切って動かすときは、macOS の sandbox-exec で包む（offline=True）。
- 履歴の中身も、同じ /usr/bin/python3 と同梱の dulwich で読む。テストの Python（pytest の中）では読み込まない
  （同梱の typing_extensions が sys.path の先頭に入り、開発用の環境と混ざらないように）。
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
import sys
from pathlib import Path

import hook_runner as hr
import pytest

REPO_ROOT = hr.REPO_ROOT
SCRIPT = Path("skills") / "kiroku" / "scripts" / "init_company.py"

# 通信をすべて断つ（名前の解決も含む）。ほかは変えない
NO_NETWORK_PROFILE = "(version 1)(allow default)(deny network*)"


@functools.lru_cache(maxsize=None)
def _sandbox_exec() -> str:
    """通信を断って動かせる sandbox-exec の場所。使えなければ空。"""
    path = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if not Path(path).exists():
        return ""
    try:
        r = subprocess.run([path, "-p", NO_NETWORK_PROFILE, "/usr/bin/true"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return path if r.returncode == 0 and r.stderr == b"" else ""


def offline_prefix() -> list:
    """コマンドの前に付けると、通信を断って動かす。

    Mac（社長のパソコンと開発の環境）では sandbox-exec が必ずあるので、使えなければ落とす
    （飛ばすと、通信を断った確かめをしないまま「すべて通った」に見えるため）。Mac でなければ飛ばす。
    """
    path = _sandbox_exec()
    if not path:
        if sys.platform == "darwin":
            pytest.fail("sandbox-exec で通信を断てません（sandbox の中から流したときなど）。外から流してください")
        pytest.skip("sandbox-exec のない環境です")
    return [path, "-p", NO_NETWORK_PROFILE]


def copy_plugin(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("lib", "skills"):
        shutil.copytree(REPO_ROOT / name, dest / name, ignore=ignore)
    return dest


class Env:
    """1つのテストで使う、プラグインの写し・HOME・PATH など。"""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.plugin = copy_plugin(tmp_path / "plugin")
        self.home = tmp_path / "home"
        self.tmp = tmp_path / "tmp"
        self.cwd = tmp_path / "どこか"
        for d in (self.home, self.tmp, self.cwd):
            d.mkdir()
        self.path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")

    def folder(self, name: str = "山田 製作所") -> Path:
        path = self.root / name
        path.mkdir()
        return path

    def run(self, folder: Path = None, *, extra_env: dict = None, args: list = None, cwd: Path = None,
            offline: bool = False, timeout: int = 120) -> subprocess.CompletedProcess:
        """Claude が Bash で動かすのと同じく、環境変数に CLAUDE_* を入れずに、引数で渡す。"""
        if args is None:
            args = ["--folder", str(folder)] if folder is not None else []
        env = {"PATH": self.path, "HOME": str(self.home), "TMPDIR": str(self.tmp)}
        env.update(extra_env or {})
        prefix = offline_prefix() if offline else []
        return subprocess.run(
            [*prefix, hr.real_python(), "-B", str(self.plugin / SCRIPT), *args],
            env=env,
            cwd=cwd or self.cwd,
            capture_output=True,
            timeout=timeout,
        )

    def outside(self) -> dict:
        """会社のフォルダの外で、変わってはいけないもの（プラグインの写し、HOME、一時ファイルの置き場、今いるフォルダ）。"""
        return hr.snapshot(self.plugin, self.home, self.tmp, self.cwd)


def ok(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out


def py_json(code: str, *args: str) -> object:
    """/usr/bin/python3 と同梱の dulwich で code を動かし、標準出力の JSON を返す。code の中では lib を import できる。"""
    # lib.history を先に読み込むと、同梱の dulwich が sys.path に入る
    prelude = f"import json, sys\nsys.path.insert(0, {str(REPO_ROOT)!r})\nfrom lib import history\n"
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", prelude + code, *args],
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    return json.loads(r.stdout.decode("utf-8"))


LOG_CODE = """
from dulwich.repo import Repo
repo = Repo(sys.argv[1])
rows = []
for entry in repo.get_walker():
    c = entry.commit
    files = sorted({(ch.new.path or ch.old.path).decode("utf-8") for ch in entry.changes()})
    rows.append({"author": c.author.decode("utf-8"), "committer": c.committer.decode("utf-8"),
                 "message": c.message.decode("utf-8"), "files": files})
print(json.dumps(rows, ensure_ascii=False))
"""


def git_log(folder: Path) -> list:
    """新しい順の版の一覧（作者、メッセージ、変わったファイル）。"""
    return py_json(LOG_CODE, str(folder))


def changed(folder: Path) -> list:
    """最後の版から変わったファイル（.gitignore にあるものは除く）。"""
    return py_json("from pathlib import Path\n"
                   "print(json.dumps(history.changed_paths(Path(sys.argv[1])), ensure_ascii=False))",
                   str(folder))
