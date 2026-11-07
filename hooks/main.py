"""hook の入り口（DESIGN 4.1・5章）。hooks/run.sh から `python3 -B main.py <場面> [guard]` で動かす。

- 最初に会社のフォルダの目印を確かめ、なければ何もしない（run.sh でも先に確かめている）。
- 場面ごとの処理は、同じフォルダの <場面>.py の handle() に置く。
- 判定は JSON で標準出力に返し、終了コードはいつも0にする。
  0以外で終わったとき（時間内に終わらず run.sh が止めたときも）は、run.sh が「Python が動かない」とみなし、
  書き込み・Bash・ブラウザの道具を拒み、開いたときは準備の案内を渡す。
  そのため、途中で落ちたときは、ここで握りつぶさずにそのまま落とす。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 3.9 より古い Python では動かさない（run.sh が、動かないときの扱いにする）
if sys.version_info < (3, 9):
    sys.exit(3)

HOOKS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS_DIR.parent))

import post_tool_use  # noqa: E402
import pre_tool_use  # noqa: E402
import session_start  # noqa: E402
import shinsa_hooks  # noqa: E402
import stop  # noqa: E402
import user_prompt_submit  # noqa: E402
from lib import company  # noqa: E402

HANDLERS = {
    "SessionStart": session_start.handle,
    "UserPromptSubmit": user_prompt_submit.handle,
    "PreToolUse": pre_tool_use.handle,
    "PostToolUse": post_tool_use.handle,
    "Stop": stop.handle,
    "SubagentStop": shinsa_hooks.subagent_stop,
}


# hooks が会社のフォルダで動いた合図を残す場面（道具が、hooks が動いているかを確かめるのに使う。lib/company.py）
SIGNAL_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")


def main(argv: list) -> int:
    event = argv[1] if len(argv) > 1 else ""
    folder = company.company_folder()
    if folder is None:
        return 0
    handler = HANDLERS.get(event)
    if handler is None:
        return 0
    if event in SIGNAL_EVENTS:
        company.write_hook_signal(folder, event)
    raw = sys.stdin.buffer.read().decode("utf-8")
    data = json.loads(raw) if raw.strip() else {}
    output = handler(data, folder)
    if output:
        sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
