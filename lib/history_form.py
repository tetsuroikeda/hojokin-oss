"""会社のフォルダの版の持ち方の見分け（DESIGN 10章「書類の版」。TASKS M0c）。

版の持ち方は2つ。どちらでも、版の操作は同じ道具の入口（lib/history.py）から行い、skill と hook は持ち方を気にしない。
- Git の形：会社のフォルダの .git に残す（lib/history.py）。
- 版のファイルの形（同期されるフォルダの形）：Git を使わず、版を1つずつ丸ごとのファイルとして `記録/版/<書類>/` に
  残し、1件ごとの記録を添える（lib/history_files.py）。

見分け方（仮。TASKS M0c の質問）：
- .git のフォルダがあれば Git の形。
- なくて `記録/版/` があれば（フォルダか、別名でも）、版のファイルの形。別名なら、版を残す処理が断って知らせる。
- どちらもなければ、版の履歴はない（hook は何も書かない）。

hook（PreToolUse など）でも読み込むので、標準のライブラリだけを使う（dulwich を読み込まない）。
/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

GIT = "git"
FILES = "files"
# 版のファイルの置き場（会社のフォルダからの場所）。版の履歴には入れない
STORE_DIR = "記録/版"


def form(folder: Union[str, Path]) -> Optional[str]:
    """会社のフォルダの版の持ち方（GIT・FILES）。版の履歴がなければ None。"""
    base = Path(folder)
    if (base / ".git").is_dir():
        return GIT
    store = base / STORE_DIR
    if os.path.isdir(str(store)) or os.path.islink(str(store)):
        return FILES
    return None


def enabled(folder: Union[str, Path]) -> bool:
    """版の履歴があるか（どちらの形でも）。ないときは、hook は何も書かない。"""
    return form(folder) is not None


def is_files(folder: Union[str, Path]) -> bool:
    return form(folder) == FILES
