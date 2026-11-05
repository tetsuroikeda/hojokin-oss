"""UserPromptSubmit（社長が送ったとき）。DESIGN 4.1 の処理。

- `/hojokin:nyuryoku` が呼ばれたときの画面入力の許可の記録（S4。lib/browser_guard.py）。
- 社長が手で変えたファイルを「社長」として履歴に残すこと（version_hooks）、発言にある外の場所の控え（B10）、
  【質問】の答え（B15）、社長が申請書を手で直した差分（B5）。
- 指摘らしい言葉への一言（B4。shiteki_hooks）。手直しの差分の一言と並べて渡す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import hand_edit_hooks
import version_hooks
from lib import browser_guard, view_only


def handle(data: dict, folder: Path) -> Optional[dict]:
    browser_guard.user_prompt_submit(data, folder)
    version_hooks.user_prompt_submit(data, folder)
    try:  # 発言にある外の場所を、取り込みのために控える（B10。lib/torikomi.py）。落ちても、ほかの処理は止めない
        from lib import torikomi
        torikomi.remember(data, folder)
    except Exception:
        pass
    # 【質問】の答え（B15）。社長の手直しの版を残した後に書く（質問の記録の変化は、次の応答の終わりに「ツール」で残る）
    try:
        import shitsumon_hooks

        shitsumon_hooks.user_prompt_submit(data, folder)
    except Exception:
        pass
    # 指摘・訂正らしい言葉があれば、「記録に残すか判断する」という一言を添える（B4）。落ちても、ほかの処理は止めない
    output: Optional[dict] = None
    try:
        import shiteki_hooks

        text = shiteki_hooks.note(data)
        if text:
            output = view_only.add_context(None, text)
            output["hookSpecificOutput"]["hookEventName"] = "UserPromptSubmit"
    except Exception:
        output = None
    # 社長が申請書を手で直していれば、前の版との差分を渡す（B5。版の記録が「社長」で残した後に）
    return hand_edit_hooks.add(output, folder, "UserPromptSubmit")
