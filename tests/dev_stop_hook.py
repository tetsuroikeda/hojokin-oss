"""開発用の Stop hook（DESIGN 12章）。プラグインには入れない。

Claude が応答を終えるたびに、前に通ったときからファイルが変わっていれば、
構成の検査と速いテスト（通信なし）を流す。落ちたら、直すまで続けさせる（8回まで）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BLOCKS = 8
CHECK_TIMEOUT = 300
OUTPUT_TAIL = 3000

CHECKS = [
    ("構成の検査", ["claude", "plugin", "validate", ".", "--strict"]),
    ("速いテスト", ["uv", "run", "pytest", "-q", "-m", "not slow"]),
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


def tree_fingerprint(root: Path) -> str:
    """今のコミットと、コミットしていない変更（Git の外のファイルを除く）から指紋を作る。"""

    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=root, capture_output=True).stdout

    h = hashlib.sha256()
    h.update(git("rev-parse", "HEAD"))
    h.update(git("diff", "HEAD", "--binary"))
    for name in git("ls-files", "-z", "--others", "--exclude-standard").split(b"\0"):
        if not name:
            continue
        h.update(name)
        try:
            h.update(hashlib.sha256((root / name.decode("utf-8")).read_bytes()).digest())
        except OSError:
            pass
    return h.hexdigest()


def run_checks(root: Path) -> list[tuple[str, str]]:
    """落ちた検査の名前と出力の終わりを返す。道具がないときは、その旨を出力にする。"""
    failures = []
    for label, cmd in CHECKS:
        try:
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        except FileNotFoundError:
            failures.append((label, f"{cmd[0]} が見つかりません"))
            continue
        except subprocess.TimeoutExpired:
            failures.append((label, f"{CHECK_TIMEOUT}秒で終わりませんでした"))
            continue
        if result.returncode != 0:
            output = (result.stdout + result.stderr)[-OUTPUT_TAIL:]
            failures.append((label, f"終了コード {result.returncode}\n{output}"))
    return failures


def decide(state: dict, fingerprint: str, failures: list[tuple[str, str]]) -> tuple[dict, dict]:
    """新しい状態と、hook の出力（JSON）を返す。"""
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
    if fingerprint == state.get("passed"):
        # 前に通ったときから何も変わっていない
        return 0
    new_state, output = decide(state, fingerprint, run_checks(root))
    save_state(path, new_state)
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
