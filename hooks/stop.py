"""Stop（Claude が応答を終えたとき）。DESIGN 4.1・5章の処理を、後のタスクでここに作る。

ツールが変えたファイルを「ツール」として履歴に残すこと、結果の確かめと戻し
（原本と公式資料のハッシュ、Word・Excel の書式、版の名前のファイル、答えの引用）、
質問の記録、今の状態の画面の作り直し。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def handle(data: dict, folder: Path) -> Optional[dict]:
    return None
