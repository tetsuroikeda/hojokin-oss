"""書類のケース（タグ F5・F8 の T5-*・T8-13）の準備に共通の道具（TASKS B9〜B12・B20）。

ケースの setup.py が読み込む。保存した状態を戻し（fukugen.py）、testdata/ の架空の材料を会社のフォルダに写し、
今日の日付を差し替え、開いたときの控えを作り、ここまでを「ツール」の版として残す。
- 材料は testdata/ のうち、会社のフォルダに写してよい書類だけ（答えの文書・スクリプトは写さない。各材料の一覧.md）。
- 標準のライブラリと、プラグインの lib/ だけで動く（/usr/bin/python3 の 3.9 でも動く書き方にする）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

sys.dont_write_bytecode = True

LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent.parent
TESTDATA = PLUGIN_ROOT / "testdata"
for p in (str(PLUGIN_ROOT), str(LIB_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import fukugen  # noqa: E402

CASE = "2026_省力化（一般型）第9回"


def restore(stage: str, target: Optional[Path] = None) -> Path:
    """保存した状態を target に戻す。target がなければ、setup.py の引数のフォルダ、それもなければ今いるフォルダ
    （eval の scaffold は今いるフォルダ。試すときは `setup.py <フォルダ>`）。"""
    if target is None and len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.mkdir(parents=True, exist_ok=True)
    target = (target or Path.cwd()).resolve()
    fukugen.restore(stage, target)
    return target


def put(target: Path, files: Dict[str, str]) -> None:
    """testdata/ の材料（値）を、会社のフォルダの場所（キー）に写す。"""
    for dest, source in files.items():
        src = TESTDATA / source
        if not src.is_file():
            raise fukugen.RestoreError(f"材料がありません（testdata/{source}）")
        path = target / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(src), str(path))


def put_folder(target: Path, source: str, under: str = "") -> None:
    """testdata/<source>/ の中の書類を、中の場所のまま、会社のフォルダ（under の下）に写す。"""
    base = TESTDATA / source
    for src in sorted(base.rglob("*")):
        if src.is_file() and src.name != ".DS_Store":
            rel = src.relative_to(base).as_posix()
            put(target, {(f"{under}/{rel}" if under else rel): f"{source}/{rel}"})


def set_today(target: Path, day: str) -> None:
    from lib import company, dates

    path = target / company.MARKER_DIR / company.SETTINGS_FILE
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[dates.TODAY_KEY] = day
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def remember_opening(target: Path) -> dict:
    """開いたときの控え（lib/seiri.py の opening_changes）を、今の書類で作る（前回開いたときの形にする）。"""
    from lib import seiri

    return seiri.opening_changes(target)


def record(target: Path, reason: str) -> None:
    """ここまでを「ツール」の版として残す（開いたときに、社長が手で変えたものに数えないため）。"""
    from lib import dates, history

    history.record(target, history.TOOL, reason, when=dates.now(target))


def done(summary: dict) -> None:
    print("shorui_case: ok " + json.dumps(summary, ensure_ascii=False))
