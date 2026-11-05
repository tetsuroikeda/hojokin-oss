"""SessionStart（開いたとき）。DESIGN 4.7 の「開いたときの流れ」を、後のタスクでここに作る。

社長が手で変えたファイルの記録、原本と公式資料の照合、今日やることの組み立て、
公式サイトの確かめ、10,000字以内の情報を Claude に渡すこと、今の状態の画面の作り直し。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import originals_hooks
import record_hooks
import shorui_hooks
import status_hooks
import version_hooks
from lib import view_only


def handle(data: dict, folder: Path) -> Optional[dict]:
    notes = originals_hooks.check(data, folder)  # 原本と公式資料の照らしと戻し（M4）。版の記録より先に
    output = originals_hooks.session_start(view_only.session_start(data, folder, version_hooks.session_start(data, folder)), notes)
    output = record_hooks.session_start(data, folder, output)  # 会社の記録の要約（M11）
    output = shorui_hooks.session_start(data, folder, output)  # 前回から増えた・変わった書類（B9）
    return status_hooks.session_start(data, folder, output)  # 期限と作業・共通の決まり・今の状態の画面（M3）。最後に
