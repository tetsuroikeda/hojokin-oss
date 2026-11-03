"""PostToolUse（Claude が道具を使った後）。DESIGN 5章の部品の控え。

hooks.json の matcher で、ブラウザの道具だけを受け取る。
ページを読んだ結果から、部品の番号と種類・名前・囲むラベルの対応を控え、
クリックやページの移動の後は控えを捨てる（lib/browser_guard.py）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib import browser_guard


def handle(data: dict, folder: Path) -> Optional[dict]:
    browser_guard.post_tool_use(data, folder)
    return None
