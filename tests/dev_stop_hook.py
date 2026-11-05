"""開発用の Stop hook（DESIGN 12章）。プラグインには入れない。

Claude が応答を終えるたびに、前に通ったときからファイルが変わっていれば、
構成の検査と速いテスト（通信なし）を流す。落ちたら、直すまで続けさせる（2回まで）。

変わったかは、プラグインとテストに関わるファイル（WATCHED）の中身の指紋で見る。コミットしただけ、文書だけを直した、
別の worktree で同じ中身を確かめた、のときは流さない。通った指紋は、セッションと worktree をまたいで
1つのファイル（Git の共通のフォルダの hojokin-dev-stop.json）に持つ。
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BLOCKS = 2
# 指紋を作るファイル（ここが変わらなければ、検査とテストの結果も変わらない）
WATCHED = ["lib", "hooks", "skills", "agents", "schema", "tests", "evals", "mock", ".claude-plugin", "testdata",
           "knowledge", "pyproject.toml", "uv.lock"]
PASSED_FILE = "hojokin-dev-stop.json"
PASSED_KEEP = 50
# 速いテストは並べて4分ほど。Workflow の作業役が同じ Mac でテストを流している間は遅くなるので、余裕を持たせる
# （.claude/settings.json の hook の時間切れ 660秒より短くする）
CHECK_TIMEOUT = 600
OUTPUT_TAIL = 3000

CHECKS = [
    ("構成の検査", ["claude", "plugin", "validate", ".", "--strict"]),
    # 版の履歴（Git）を使うテストが増え、1つずつ流すと300秒を超えるので、CPU の数だけ並べて流す（pytest-xdist）
    ("速いテスト", ["uv", "run", "pytest", "-q", "-m", "not slow", "-n", "auto"]),
]


def repo_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent)


def state_path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
    return Path(tempfile.gettempdir()) / "hojokin-dev-stop" / f"{safe}.json"


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"blocks": 0, "passed": ""}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def passed_path(root: Path) -> Path:
    """通った指紋を持つファイル。Git の共通のフォルダ（worktree でも同じ所）に置く。Git でなければ一時のフォルダ。"""
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True).stdout.strip()
    if out:
        common = Path(out)
        return (common if common.is_absolute() else root / common) / PASSED_FILE
    return Path(tempfile.gettempdir()) / "hojokin-dev-stop" / PASSED_FILE


def load_passed(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add_passed(path: Path, fingerprint: str) -> None:
    passed = [x for x in load_passed(path) if x != fingerprint] + [fingerprint]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(passed[-PASSED_KEEP:]), encoding="utf-8")
    except OSError:
        pass  # 持てなくても、次にもう一度流すだけ


def tree_fingerprint(root: Path) -> str:
    """WATCHED のファイルの中身（Git の索引、コミットしていない変更、Git の外のファイル）から指紋を作る。

    今のコミットそのものは入れない（コミットしただけでは中身が変わらないため）。
    """

    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args, "--", *WATCHED], cwd=root, capture_output=True).stdout

    h = hashlib.sha256()
    h.update(git("ls-files", "-s"))
    h.update(git("diff", "--binary"))
    for name in git("ls-files", "-z", "--others", "--exclude-standard").split(b"\0"):
        if not name:
            continue
        h.update(name)
        try:
            h.update(hashlib.sha256((root / name.decode("utf-8")).read_bytes()).digest())
        except OSError:
            pass
    return h.hexdigest()


def run_command(cmd: list[str], root: Path, timeout: float) -> subprocess.CompletedProcess:
    """コマンドを別のプロセスの組で流す。時間切れのときは、子（pytest とその作業役）まで組ごと止める。

    subprocess.run の時間切れは uv だけを止め、子の pytest が置き去りになって増えていくため。
    """
    proc = subprocess.Popen(
        cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def run_checks(root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """落ちた検査の名前と出力の終わり、見つからなかった道具の名前を返す。"""
    failures = []
    missing = []
    for label, cmd in CHECKS:
        try:
            result = run_command(cmd, root, CHECK_TIMEOUT)
        except FileNotFoundError:
            missing.append(cmd[0])
            continue
        except subprocess.TimeoutExpired:
            failures.append((label, f"{CHECK_TIMEOUT}秒で終わりませんでした"))
            continue
        if result.returncode != 0:
            output = (result.stdout + result.stderr)[-OUTPUT_TAIL:]
            failures.append((label, f"終了コード {result.returncode}\n{output}"))
    return failures, missing


def decide(
    state: dict, fingerprint: str, failures: list[tuple[str, str]], missing: list[str] | None = None
) -> tuple[dict, dict]:
    """新しい状態と、hook の出力（JSON）を返す。"""
    if missing:
        # Claude には直せないので差し戻さない。通ったことにもしない
        return {"blocks": state.get("blocks", 0), "passed": state.get("passed", "")}, {
            "systemMessage": f"開発の確かめ：{'、'.join(missing)} が見つからないため、確かめられませんでした",
        }
    if not failures:
        return {"blocks": 0, "passed": fingerprint}, {
            "systemMessage": "開発の確かめ：構成の検査と速いテストが通りました",
        }
    detail = "\n\n".join(f"■ {label}\n{out}" for label, out in failures)
    blocks = state.get("blocks", 0)
    if blocks >= MAX_BLOCKS:
        return {"blocks": 0, "passed": state.get("passed", "")}, {
            "systemMessage": f"開発の確かめ：{MAX_BLOCKS}回続けても直りませんでした。作者に知らせてください。\n{detail}",
        }
    return {"blocks": blocks + 1, "passed": state.get("passed", "")}, {
        "decision": "block",
        "reason": (
            f"開発の確かめが落ちました（{blocks + 1}/{MAX_BLOCKS}回目）。直してから応答を終えてください。\n\n{detail}"
        ),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    root = repo_root()
    path = state_path(str(payload.get("session_id", "")))
    state = load_state(path)
    fingerprint = tree_fingerprint(root)
    shared = passed_path(root)
    if fingerprint == state.get("passed") or fingerprint in load_passed(shared):
        # 前に通ったときから何も変わっていない（ほかのセッションや worktree で通った中身も含む）
        return 0
    new_state, output = decide(state, fingerprint, *run_checks(root))
    save_state(path, new_state)
    if new_state.get("passed") == fingerprint:
        add_passed(shared, fingerprint)
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
