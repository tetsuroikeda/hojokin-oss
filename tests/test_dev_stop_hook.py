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
