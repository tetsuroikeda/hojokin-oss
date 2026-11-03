"""UserPromptSubmit（社長が送ったとき）。DESIGN 4.1 の処理。

- `/hojokin:nyuryoku` が呼ばれたときの画面入力の許可の記録（S4。lib/browser_guard.py）。
- 社長が手で変えたファイルを「社長」として履歴に残すこと、指摘らしい言葉への一言、
  発言にある外の場所の控えは、後のタスクでここに足す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib import browser_guard


def handle(data: dict, folder: Path) -> Optional[dict]:
    browser_guard.user_prompt_submit(data, folder)
    return None
