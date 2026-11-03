"""UserPromptSubmit（社長が送ったとき）。DESIGN 4.1 の処理を、後のタスクでここに作る。

社長が手で変えたファイルを「社長」として履歴に残すこと、指摘らしい言葉への一言、
発言にある外の場所の控え、`/hojokin:nyuryoku` が呼ばれたときの画面入力の許可の記録。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def handle(data: dict, folder: Path) -> Optional[dict]:
    return None
