"""会社のフォルダを作る道具を、Claude が Bash で動かすのと同じ形で動かすための道具（テスト用）。

- プラグインの lib/ と skills/ を一時フォルダに写して動かす（__pycache__ などが書かれないかも見るため）。
- 道具は、社長の Mac と同じ /usr/bin/python3（3.9）で動かす。PATH には python3 と sh だけを置く（git も uv もない）。
- 補助プログラムの venv は、テストの間で使い回す（pytest の控えの場所に作る。2回目からは作り直さない）。
  空の置き場から pip で入れる試しは、slow を付けたテストで行う。
- 履歴の中身は、その venv の python と dulwich で読む（テストの Python には dulwich がないため）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import hook_runner as hr
import pytest

from lib import runtime

REPO_ROOT = hr.REPO_ROOT
SCRIPT = Path("skills") / "kiroku" / "scripts" / "init_company.py"


@pytest.fixture(scope="session")
def plugin_data(request, tmp_path_factory) -> Path:
    """補助プログラムを入れたデータの置き場（使い回す）。"""
    cache = request.config.cache
    data = Path(cache.mkdir("hojokin-plugin-data")) if cache is not None else tmp_path_factory.mktemp("plugin-data")
    runtime.ensure(data, base_python=hr.real_python())
    return data


def copy_plugin(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("lib", "skills"):
        shutil.copytree(REPO_ROOT / name, dest / name, ignore=ignore)
    return dest


class Env:
    """1つのテストで使う、プラグインの写し・HOME・PATH など。"""

    def __init__(self, tmp_path: Path, data: Path) -> None:
        self.root = tmp_path
        self.plugin = copy_plugin(tmp_path / "plugin")
        self.home = tmp_path / "home"
        self.tmp = tmp_path / "tmp"
        self.cwd = tmp_path / "どこか"
        for d in (self.home, self.tmp, self.cwd):
            d.mkdir()
        self.path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
        self.data = data

    def folder(self, name: str = "山田 製作所") -> Path:
        path = self.root / name
        path.mkdir()
        return path

    def run(self, folder: Path = None, *, data: Path = None, extra_env: dict = None, args: list = None,
            cwd: Path = None, timeout: int = 120) -> subprocess.CompletedProcess:
        """Claude が Bash で動かすのと同じく、環境変数に CLAUDE_* を入れずに、引数で渡す。"""
        if args is None:
            args = ["--data-dir", str(data or self.data)]
            if folder is not None:
                args += ["--folder", str(folder)]
        env = {"PATH": self.path, "HOME": str(self.home), "TMPDIR": str(self.tmp)}
        env.update(extra_env or {})
        return subprocess.run(
            [hr.real_python(), "-B", str(self.plugin / SCRIPT), *args],
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


def venv_json(data: Path, code: str, *args: str) -> object:
    """venv の python（dulwich あり）で code を動かし、標準出力の JSON を返す。code の中では lib を import できる。"""
    prelude = f"import json, sys\nsys.path.insert(0, {str(REPO_ROOT)!r})\n"
    r = subprocess.run(
        [str(runtime.venv_python(data)), "-B", "-c", prelude + code, *args],
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


def git_log(data: Path, folder: Path) -> list:
    """新しい順の版の一覧（作者、メッセージ、変わったファイル）。"""
    return venv_json(data, LOG_CODE, str(folder))


def changed(data: Path, folder: Path) -> list:
    """最後の版から変わったファイル（.gitignore にあるものは除く）。"""
    return venv_json(data, "from lib import history\nfrom pathlib import Path\n"
                           "print(json.dumps(history.changed_paths(Path(sys.argv[1])), ensure_ascii=False))",
                     str(folder))
