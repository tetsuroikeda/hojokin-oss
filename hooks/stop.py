"""Stop（Claude が応答を終えたとき）。DESIGN 4.1・5章の処理を、後のタスクでここに作る。

ツールが変えたファイルを「ツール」として履歴に残すこと、結果の確かめと戻し
（原本と公式資料のハッシュ、Word・Excel の書式、版の名前のファイル、答えの引用）、
質問の記録、今の状態の画面の作り直し。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import originals_hooks
import version_hooks


def form_notes(folder: Path) -> List[str]:
    """申請書の Word・Excel の書式を照らし、範囲の外が変わったものを直前の版に戻す（B14b。lib/form_guard.py）。"""
    try:
        from lib import form_guard

        return form_guard.check(folder)
    except Exception:
        return []  # hook を落とさない（落ちると、run.sh が書き込みと Bash を拒んでしまう）


def record_questions(data: dict, folder: Path) -> None:
    """最後の応答の【質問】を、質問の記録に残す（B15。shitsumon_hooks.py）。版の記録より先に（同じ版に入れる）。"""
    try:
        import shitsumon_hooks

        shitsumon_hooks.stop(data, folder)
    except Exception:
        pass


def refresh_status(folder: Path) -> None:
    """今の状態の画面と Excel を作り直す（B27。DESIGN 4.6「Claude が応答を終えるたびに」）。版の記録の後に
    （どちらも .gitignore で版に入れない）。案件がなく画面もないときは作らない。"""
    try:
        from lib import status_view

        status_view.refresh_page(folder)
    except Exception:
        pass  # hook を落とさない


def handle(data: dict, folder: Path) -> Optional[dict]:
    notes = originals_hooks.check(data, folder)  # 原本と公式資料の照らしと戻し（M4）。版の記録より先に
    notes += form_notes(folder)  # Word・Excel の書式の照らしと戻し（B14b）。版の記録より先に
    record_questions(data, folder)
    result = originals_hooks.stop(data, folder, notes, version_hooks.stop(data, folder))
    refresh_status(folder)
    return result
