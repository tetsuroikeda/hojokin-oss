"""会社のフォルダの目印と設定（DESIGN 4.5・4.7・5章）。

目印は、会社のフォルダの直下にある `.hojokin/` フォルダ。
目印のないフォルダでは、hooks は何もせず、スクリプトも探すことと会社のフォルダを作ること以外は動かない。
どのフォルダを見るかは、hooks/run.sh と同じ規則にする（CLAUDE_PROJECT_DIR、なければ今いるフォルダ）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Union

MARKER_DIR = ".hojokin"
SETTINGS_FILE = "設定.json"


def project_dir() -> Path:
    """Claude Code を開いたフォルダ。hook とスクリプトに渡る CLAUDE_PROJECT_DIR を先に見る。"""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def is_company_folder(folder: Union[str, Path]) -> bool:
    return (Path(folder) / MARKER_DIR).is_dir()


def company_folder(folder: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """会社のフォルダなら、そのフォルダを返す。目印がなければ None。

    親のフォルダはさかのぼらない（skill も今のフォルダの目印だけを確かめる）。
    """
    path = Path(folder) if folder is not None else project_dir()
    return path if is_company_folder(path) else None


def settings_path(folder: Path) -> Path:
    return folder / MARKER_DIR / SETTINGS_FILE


def load_settings(folder: Optional[Path]) -> dict:
    """`.hojokin/設定.json` を読む。会社のフォルダでないときと、ファイルがないときは空。

    中身が JSON として読めないときは、黙って無視せずに ValueError にする
    （日付の差し替えが効いていないことに気づかないまま、デモやテストが進まないように）。
    """
    if folder is None:
        return {}
    path = settings_path(folder)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{MARKER_DIR}/{SETTINGS_FILE} が JSON として読めません（{e}）") from e
    if not isinstance(data, dict):
        raise ValueError(f"{MARKER_DIR}/{SETTINGS_FILE} の中身は、{{ }} で囲んだ形にしてください")
    return data
