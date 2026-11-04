"""審査役の結果の保存（DESIGN 4.1・8章「結果の保存」、実験 E3b。TASKS M7）。hook の場面ごとの入口から1行で呼ぶ。

- SubagentStop（main.py に登録）：hooks.json の matcher（`^hojokin:shinsa$`）で、審査役が終わったときだけ動く。
  default のモードと eval（dontAsk）では、最後の報告が `last_assistant_message` に入っている。
- PreToolUse（pre_tool_use.py から呼ぶ）：hooks.json の matcher（`^SubagentHandback$`）で受け取る。auto モードでは、
  審査役は報告を SubagentHandback の道具で渡し、SubagentStop には報告が来ないため。
どちらも、本体（Claude）を通さずに、控えと結び付けて `記録/審査役の結果/` に保存する（lib/shinsa_result.py）。
何も出力しない（道具も、subagent の終わりも止めない）。保存できないとき（控えがない、別名がある など）も止めず、
確かめの道具（skills/kaku/scripts/kakunin.py result）が「まだ届いていない」と伝える。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib import places, shinsa_result


def _save(folder: Path, report, where: str, data: dict, trusted: bool) -> None:
    try:
        shinsa_result.save_report(folder, report, where, data, trusted)
    except (places.PlaceError, OSError, ValueError):
        # 保存できなくても、審査役の終わりや道具は止めない（hook が落ちると、run.sh が「Python が動かない」とみなすため）
        pass


def subagent_stop(data: dict, folder: Path) -> Optional[dict]:
    agent = data.get("agent_type")
    if agent and not shinsa_result.is_shinsa(agent):
        return None
    _save(folder, data.get("last_assistant_message"), shinsa_result.FROM_STOP, data, trusted=True)
    return None


def handback(data: dict, folder: Path) -> Optional[dict]:
    agent = data.get("agent_type")
    if agent and not shinsa_result.is_shinsa(agent):
        return None
    tool_input = data.get("tool_input") or {}
    message = tool_input.get("message") if isinstance(tool_input, dict) else None
    _save(folder, message, shinsa_result.FROM_HANDBACK, data, trusted=bool(agent))
    return None
