"""原本と公式資料の照らしと戻しを、hook の場面につなぐ（DESIGN 4.7 の2・5章、TASKS M4）。

照らしと戻しの中身は lib/originals_guard.py。ここは、場面ごとの順番と、Claude への伝え方だけを持つ。
- 開いたとき（SessionStart）と応答の終わり（Stop）に、版の記録（version_hooks）より先に照らして戻す。
  書き換わった中身を「社長」や「ツール」の版として残さず、原本と公式資料の版を入れたときの1版のままにするため。
  そのため、場面のファイル（session_start.py・stop.py）では、照らした結果を先に受けてから、版の記録を動かす。
- 開いたときは、開いたときに渡す情報（additionalContext）に足す。社長の最初の発言のときに Claude が伝える。
- 応答の終わりは、戻したことを Claude に伝えて続けさせる（decision: block）。version_hooks の控えを
  「応答中」にする（version_hooks.continue_response）。Stop の hook で続けているとき（stop_hook_active）は、
  続けさせすぎないよう、社長の画面に直接出す（systemMessage）。
- どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が「Python が動かない」とみなし、
  書き込みと Bash を拒んでしまうため）。照らせなかったことを伝える。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import version_hooks
from lib import originals_guard, view_only


def check(data: dict, folder: Path) -> List[str]:
    """原本と公式資料を照らして戻し、Claude に伝える文の一覧を返す（何もなければ空）。"""
    at_start = (data or {}).get("hook_event_name") == "SessionStart"
    try:
        report = originals_guard.check(folder)
        return originals_guard.notes(report, at_start)
    except Exception as error:
        return [f"【hojokin】原本と公式資料を照らせませんでした（{type(error).__name__}: {error}）。次の場面で、また照らします。"]


def session_start(output: Optional[dict], notes: List[str]) -> Optional[dict]:
    """開いたときの出力に、照らした結果を足す。"""
    for note in notes:
        output = view_only.add_context(output, note)
    return output


def stop(data: dict, folder: Path, notes: List[str], output: Optional[dict]) -> Optional[dict]:
    """応答の終わりの出力に、照らした結果を足す。"""
    if not notes:
        return output
    text = "\n".join(notes)
    result = dict(output or {})
    if (data or {}).get("stop_hook_active"):
        current = result.get("systemMessage")
        result["systemMessage"] = f"{current}\n{text}" if isinstance(current, str) and current else text
        return result
    current = result.get("reason") if result.get("decision") == "block" else None
    result["decision"] = "block"
    result["reason"] = f"{current}\n{text}" if isinstance(current, str) and current else text
    try:
        version_hooks.continue_response(data, folder)
    except Exception:
        pass  # 控えを直せなくても、伝えることは伝える
    return result
