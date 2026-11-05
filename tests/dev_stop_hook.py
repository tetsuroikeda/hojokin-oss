"""開発用の Stop hook（DESIGN 12章）。プラグインには入れない。

Claude が応答を終えるたびに、前に通ったときからファイルが変わっていれば、
構成の検査と速いテスト（通信なし）を流す。落ちたら、直すまで続けさせる（2回まで）。

変わったかは、プラグインとテストに関わるファイル（WATCHED）の中身の指紋で見る。コミットしただけ、文書だけを直した、
別の worktree で同じ中身を確かめた、のときは流さない。通った指紋は、セッションと worktree をまたいで
1つのファイル（Git の共通のフォルダの hojokin-dev-stop.json）に持つ。

同じ Mac で並べて動くセッションが、同じテストを重ねて流さないようにする（負荷で時間切れになるため）。
- そのターン（最後の社長の発言の後）に編集の道具（Edit・Write・NotebookEdit）を使っていないセッションは、流さない
  （CLAUDE.md で、ファイルの編集は Edit・Write でする決まり。会話の記録が読めなければ、いつもどおり流す）。
- 1度に1本だけ流す。Git の共通のフォルダに錠（hojokin-dev-stop.lock。pid と指紋）を置き、ほかのセッションが流していれば
  少し待つ。終わったら通った指紋をもう一度見て、同じなら流さない。待っても終わらなければ、今回は流さずに知らせる
  （差し戻さない）。錠の pid が生きていなければ、錠を取り直す。
- 並べる数は6まで（-n 6）。
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MAX_BLOCKS = 2
# 指紋を作るファイル（ここが変わらなければ、検査とテストの結果も変わらない）
WATCHED = ["lib", "hooks", "skills", "agents", "schema", "tests", "evals", "mock", ".claude-plugin", "testdata",
           "knowledge", "pyproject.toml", "uv.lock"]
PASSED_FILE = "hojokin-dev-stop.json"
PASSED_KEEP = 50
LOCK_FILE = "hojokin-dev-stop.lock"
LOCK_WAIT = 30  # ほかのセッションの確かめを待つ秒数（hook の時間切れ 660秒の中で、自分の確かめの時間を残す）
LOCK_POLL = 2
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
# 速いテストは並べて4分ほど。Workflow の作業役が同じ Mac でテストを流している間は遅くなるので、余裕を持たせる
# （.claude/settings.json の hook の時間切れ 660秒より短くする）
CHECK_TIMEOUT = 600
OUTPUT_TAIL = 3000

CHECKS = [
    ("構成の検査", ["claude", "plugin", "validate", ".", "--strict"]),
    # 版の履歴（Git）を使うテストが増え、1つずつ流すと300秒を超えるので、CPU の数だけ並べて流す（pytest-xdist）
    # 並べるのは6まで（ほかの worktree の作業役も同じ Mac でテストを流すため）
    ("速いテスト", ["uv", "run", "pytest", "-q", "-m", "not slow", "-n", "6"]),
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


def _is_prompt(entry: dict) -> bool:
    """会話の記録の1行が、社長（利用者）の発言か（道具の結果の行は除く）。"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(c, dict) and c.get("type") == "text" for c in content) and \
            not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return False


def edited_this_turn(transcript: Path) -> bool | None:
    """最後の発言の後に、編集の道具を使ったか。会話の記録が読めなければ None（いつもどおり流す）。"""
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    used = False
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if _is_prompt(entry):
            used = False
            continue
        content = (entry.get("message") or {}).get("content") if entry.get("type") == "assistant" else None
        if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_use"
                                             and c.get("name") in EDIT_TOOLS for c in content):
            used = True
    return used


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def take_lock(path: Path, fingerprint: str) -> bool:
    """錠を取る。ほかの生きているプロセスが持っていれば False。持ち主が死んでいれば取り直す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid", 0))
            except (OSError, ValueError, AttributeError):
                pid = 0
            if pid and _alive(pid):
                return False
            try:
                path.unlink()  # 持ち主のいない錠
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "fingerprint": fingerprint}, f)
        return True
    return False


def release_lock(path: Path) -> None:
    try:
        if int(json.loads(path.read_text(encoding="utf-8")).get("pid", 0)) == os.getpid():
            path.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def wait_for_lock(path: Path, fingerprint: str, passed: Path, wait: float = LOCK_WAIT,
                  poll: float = LOCK_POLL) -> str:
    """錠を取れたら "run"、待つ間にほかのセッションで同じ指紋が通ったら "passed"、待っても取れなければ "busy"。"""
    deadline = time.monotonic() + wait
    while True:
        if fingerprint in load_passed(passed):
            return "passed"
        if take_lock(path, fingerprint):
            return "run"
        if time.monotonic() >= deadline:
            return "busy"
        time.sleep(poll)


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
    transcript = payload.get("transcript_path")
    if transcript and edited_this_turn(Path(transcript)) is False:
        # このターンにファイルを直していない（ほかのセッションが変えた中身は、そのセッションが確かめる）
        return 0
    path = state_path(str(payload.get("session_id", "")))
    state = load_state(path)
    fingerprint = tree_fingerprint(root)
    shared = passed_path(root)
    if fingerprint == state.get("passed") or fingerprint in load_passed(shared):
        # 前に通ったときから何も変わっていない（ほかのセッションや worktree で通った中身も含む）
        return 0
    lock = shared.with_name(LOCK_FILE)
    got = wait_for_lock(lock, fingerprint, shared)
    if got == "passed":
        return 0
    if got == "busy":
        print(json.dumps({"systemMessage": "開発の確かめ：ほかのセッションが確かめを流しているので、今回は流しませんでした"},
                         ensure_ascii=False))
        return 0
    try:
        new_state, output = decide(state, fingerprint, *run_checks(root))
    finally:
        release_lock(lock)
    save_state(path, new_state)
    if new_state.get("passed") == fingerprint:
        add_passed(shared, fingerprint)
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
