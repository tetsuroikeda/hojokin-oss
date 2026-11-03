"""PostToolUse（Claude が道具を使った後）。DESIGN 5章の部品の控えを、後のタスク（S4）でここに作る。

hooks.json の matcher で、ブラウザの道具だけを受け取る。
ページを読んだ結果から、部品の番号と種類・名前・囲むラベルの対応を控える。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def handle(data: dict, folder: Path) -> Optional[dict]:
    return None
