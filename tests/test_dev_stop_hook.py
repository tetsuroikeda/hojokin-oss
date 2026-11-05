"""開発用の Stop hook の判定（DESIGN 12章）。検査そのものは流さない。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import dev_stop_hook as hook


def test_timeout_also_stops_children(tmp_path: Path) -> None:
    # uv が pytest を起こすのと同じく、子を起こして待つコマンド。時間切れのとき、子も残らないこと
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        hook.run_command([sys.executable, "-c", script], tmp_path, timeout=2)
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        pytest.fail("時間切れの後も、子のプロセスが残っている")


def test_pass_resets_count() -> None:
    state, output = hook.decide({"blocks": 3, "passed": ""}, "fp", [])
    assert state == {"blocks": 0, "passed": "fp"}
    assert "decision" not in output


def test_fail_blocks_up_to_max() -> None:
    state = {"blocks": 0, "passed": "old"}
    for n in range(1, hook.MAX_BLOCKS + 1):
        state, output = hook.decide(state, "fp", [("速いテスト", "終了コード 1")])
        assert output["decision"] == "block"
        assert f"{n}/{hook.MAX_BLOCKS}" in output["reason"]
        assert "速いテスト" in output["reason"]
    assert state["blocks"] == hook.MAX_BLOCKS


def test_missing_tool_does_not_block() -> None:
    state, output = hook.decide({"blocks": 2, "passed": "old"}, "fp", [("速いテスト", "x")], ["claude"])
    assert "decision" not in output
    assert "claude" in output["systemMessage"]
    # 通ったことにはせず、回数も変えない
    assert state == {"blocks": 2, "passed": "old"}


def test_stop_blocking_after_max() -> None:
    state, output = hook.decide({"blocks": hook.MAX_BLOCKS, "passed": "old"}, "fp", [("構成の検査", "x")])
    assert "decision" not in output
    assert "作者に知らせて" in output["systemMessage"]
    assert state["blocks"] == 0
    # 通ったことにはしない
    assert state["passed"] == "old"


# ---- 重ねて流さない（11/5。同じ Mac で並べて動くセッションの負荷を減らす） ----


def _transcript(tmp_path: Path, entries: list) -> Path:
    import json
    path = tmp_path / "会話.jsonl"
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
    return path


def _prompt(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool(name: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": {}}]}}


def _result() -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def test_edited_this_turn_looks_after_the_last_prompt(tmp_path: Path) -> None:
    # 前のターンに Edit があっても、最後の発言の後に編集の道具がなければ流さない
    path = _transcript(tmp_path, [_prompt("直して"), _tool("Edit"), _result(), _prompt("状態は？"), _tool("Bash"), _result()])
    assert hook.edited_this_turn(path) is False
    path = _transcript(tmp_path, [_prompt("直して"), _tool("Read"), _result(), _tool("Write"), _result()])
    assert hook.edited_this_turn(path) is True
    # 読めない会話の記録は、いつもどおり流す（None）
    assert hook.edited_this_turn(tmp_path / "ない.jsonl") is None


def test_lock_is_taken_once_and_stale_lock_is_retaken(tmp_path: Path) -> None:
    import json
    lock = tmp_path / hook.LOCK_FILE
    assert hook.take_lock(lock, "fp")
    # 自分が持っている間、ほかの持ち主（生きている pid）とみなして取れない
    lock.write_text(json.dumps({"pid": os.getppid(), "fingerprint": "fp"}), encoding="utf-8")
    assert not hook.take_lock(lock, "fp2")
    # 持ち主の pid が生きていなければ、取り直す
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.write_text(json.dumps({"pid": dead.pid, "fingerprint": "fp"}), encoding="utf-8")
    assert hook.take_lock(lock, "fp3")
    hook.release_lock(lock)
    assert not lock.exists()


def test_wait_for_lock_skips_when_the_same_fingerprint_passed(tmp_path: Path) -> None:
    import json
    lock = tmp_path / hook.LOCK_FILE
    passed = tmp_path / hook.PASSED_FILE
    lock.write_text(json.dumps({"pid": os.getppid(), "fingerprint": "fp"}), encoding="utf-8")
    # ほかのセッションが流している間：待っても終わらなければ busy（差し戻さない）
    assert hook.wait_for_lock(lock, "fp", passed, wait=0.2, poll=0.05) == "busy"
    # ほかのセッションで同じ指紋が通っていれば、流さない
    hook.add_passed(passed, "fp")
    assert hook.wait_for_lock(lock, "fp", passed, wait=0.2, poll=0.05) == "passed"
    # 錠が空けば、自分が流す
    lock.unlink()
    assert hook.wait_for_lock(lock, "fp-new", passed, wait=0.2, poll=0.05) == "run"


def test_fast_tests_use_at_most_six_workers() -> None:
    label, cmd = hook.CHECKS[1]
    assert cmd[cmd.index("-n") + 1] == "6"
