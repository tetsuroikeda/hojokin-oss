"""PostToolUse（Claude が道具を使った後）。DESIGN 5章の部品の控えと、6章の質問の記録。

hooks.json の matcher で、ブラウザの道具と、選択肢の画面（AskUserQuestion）だけを受け取る。
- ブラウザの道具：ページを読んだ結果から、部品の番号と種類・名前・囲むラベルの対応を控え、
  クリックやページの移動の後は控えを捨てる（lib/browser_guard.py）。
- AskUserQuestion：問いと答えを、案件と段階を付けて質問の記録に残す（shitsumon_hooks.py。TASKS B15）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import shitsumon_hooks
from lib import browser_guard


def handle(data: dict, folder: Path) -> Optional[dict]:
    if data.get("tool_name") == "AskUserQuestion":
        shitsumon_hooks.post_tool_use(data, folder)
        return None
    browser_guard.post_tool_use(data, folder)
    return None
