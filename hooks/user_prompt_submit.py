"""UserPromptSubmit（社長が送ったとき）。DESIGN 4.1 の処理。

- `/hojokin:nyuryoku` が呼ばれたときの画面入力の許可の記録（S4。lib/browser_guard.py）。
- 社長が手で変えたファイルを「社長」として履歴に残すこと、指摘らしい言葉への一言、
  発言にある外の場所の控えは、後のタスクでここに足す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import version_hooks
from lib import browser_guard


def handle(data: dict, folder: Path) -> Optional[dict]:
    browser_guard.user_prompt_submit(data, folder)
    version_hooks.user_prompt_submit(data, folder)
    # 【質問】の答え（B15）。社長の手直しの版を残した後に書く（質問の記録の変化は、次の応答の終わりに「ツール」で残る）
    try:
        import shitsumon_hooks

        shitsumon_hooks.user_prompt_submit(data, folder)
    except Exception:
        pass
    return None
