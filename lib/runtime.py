"""補助プログラム（Python のライブラリ）の準備（実験 E5）。

- プラグインのデータの置き場（CLAUDE_PLUGIN_DATA）に venv を作り、pip で決まった版のライブラリを入れる。
  uv も git も使わない（社長のパソコンにないことがあるため）。
- venv が動かなくなったとき（開発ツールの更新で Python の版が変わったときなど）は、作り直す。
- 入れたライブラリの一覧を venv の中に控え、一覧が変わったら入れ直す。
- skill のスクリプトは、標準のライブラリだけで動き始め、ensure() で venv を用意してから、
  reexec() でその venv の python で自分を動かし直す。

venv を用意する前に動くので、標準のライブラリだけで書き、Python 3.9 で動く書き方にする。
python は -B で動かす（Mac の python3 は、ふだん ~/Library/Caches/com.apple.python に控えを書くため）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

DATA_ENV = "CLAUDE_PLUGIN_DATA"
VENV_DIR = "venv"
STAMP_FILE = "hojokin-requirements.txt"

# 入れるライブラリと版。E5 で、Python 3.9.6 に uv も git もなしで入ることを確かめた版。
# 版を上げるときや足すときは、ここを直す（次に動いたときに入れ直す）。
REQUIREMENTS = (
    "dulwich==0.24.10",
    "python-docx==1.2.0",
    "openpyxl==3.1.5",
)

VENV_TIMEOUT = 120
PIP_TIMEOUT = 600
OUTPUT_TAIL = 1500


class SetupError(Exception):
    """補助プログラムを用意できなかった。メッセージは、そのまま Claude に返せる日本語にする。"""


def data_dir(explicit: Optional[str] = None) -> Path:
    """プラグインのデータの置き場。引数で渡されたもの、なければ環境変数 CLAUDE_PLUGIN_DATA。"""
    value = explicit or os.environ.get(DATA_ENV)
    if not value:
        raise SetupError(
            "プラグインのデータの置き場（CLAUDE_PLUGIN_DATA）が分からないため、補助プログラムを用意できませんでした。"
            "skill に書かれたコマンドを、形を変えずにそのまま実行してください。"
        )
    return Path(value).expanduser()


def venv_dir(data: Path) -> Path:
    return data / VENV_DIR


def venv_python(data: Path) -> Path:
    if os.name == "nt":
        return venv_dir(data) / "Scripts" / "python.exe"
    return venv_dir(data) / "bin" / "python3"


def running_in_venv(data: Path) -> bool:
    """今動いている Python が、データの置き場の venv のものか。"""
    try:
        return Path(sys.prefix).resolve() == venv_dir(data).resolve()
    except OSError:
        return False


def _tail(text: str) -> str:
    text = text.strip()
    return text[-OUTPUT_TAIL:] if len(text) > OUTPUT_TAIL else text


def _works(python: Path) -> bool:
    """venv の python が動き、3.9 以上か。"""
    if not python.exists():
        return False
    try:
        r = subprocess.run(
            [str(python), "-B", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _stamp_text() -> str:
    return "\n".join(REQUIREMENTS) + "\n"


def _stamp_ok(data: Path) -> bool:
    try:
        return (venv_dir(data) / STAMP_FILE).read_text(encoding="utf-8") == _stamp_text()
    except OSError:
        return False


def _run(cmd: List[str], timeout: int, failure: str) -> None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SetupError(f"{failure}（{timeout}秒で終わりませんでした）") from None
    except OSError as e:
        raise SetupError(f"{failure}（{e}）") from None
    if r.returncode != 0:
        detail = _tail(r.stderr or r.stdout)
        raise SetupError(f"{failure}\n\n--- 出力の終わり ---\n{detail}")


def ensure(data: Path, base_python: Optional[str] = None) -> Path:
    """venv を用意し、決まった版のライブラリを入れて、その python の場所を返す。

    すでに動く venv があり、ライブラリの一覧も変わっていなければ、何もしない。
    base_python は venv を作る元の Python（ふだんは、このスクリプトを動かしている Python）。
    """
    python = venv_python(data)
    working = _works(python)
    if working and _stamp_ok(data):
        return python
    venv = venv_dir(data)
    if not working:
        # 壊れた venv は作り直す
        shutil.rmtree(venv, ignore_errors=True)
        data.mkdir(parents=True, exist_ok=True)
        _run(
            [base_python or sys.executable, "-B", "-m", "venv", str(venv)],
            VENV_TIMEOUT,
            "補助プログラムの置き場（venv）を作れませんでした。",
        )
    stamp = venv / STAMP_FILE
    if stamp.exists():
        stamp.unlink()
    _run(
        [str(python), "-B", "-m", "pip", "install", "--disable-pip-version-check", "--quiet", *REQUIREMENTS],
        PIP_TIMEOUT,
        "補助プログラムのライブラリを入れられませんでした。初めて使うときは、インターネットへの接続が要ります。"
        "つながっているかを確かめて、もう一度試してください。",
    )
    stamp.write_text(_stamp_text(), encoding="utf-8")
    return python


def reexec(python: Path, script: str, args: List[str]) -> int:
    """venv の python で、スクリプトを同じ引数で動かし直す。戻り値は終了コード（Windows のときだけ戻る）。

    -B：会社のフォルダやプラグインの場所に __pycache__ を書かない。
    """
    cmd = [str(python), "-B", script, *args]
    if os.name == "nt":
        return subprocess.run(cmd).returncode
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(str(python), cmd)
    return 0  # ここには来ない
