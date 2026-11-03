"""PreToolUse（Claude が道具を使う前）。DESIGN 5章の止める決まりを、後のタスクでここに作る。

hooks.json の matcher で、書き込みの道具（Write・Edit・NotebookEdit）と、
ブラウザの道具・画面を操作する機能だけを受け取る（Python が動かないときは run.sh が拒む）。
版の名前のファイルを拒むこと、画面入力の守り（S4）を、ここに足す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def handle(data: dict, folder: Path) -> Optional[dict]:
    return None
