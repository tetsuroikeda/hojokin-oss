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

from lib import places  # 標準のライブラリだけを使う、軽い道具（hook からも読み込む）

MARKER_DIR = ".hojokin"
SETTINGS_FILE = "設定.json"
# `.hojokin/` の中で、版の履歴に入れない、その場限りのものを置くフォルダ
# （画面入力の許可、ブラウザの部品の控えなど。DESIGN 4.5）。会社のフォルダの .gitignore に書く。
TEMP_DIR = "一時"


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


# hooks が会社のフォルダで動いた合図（`.hojokin/一時/hookの合図.json`）。hooks/main.py が、開いたとき・社長が送ったとき・
# 応答の終わりに書き、確かめの道具（skills/kaku/scripts/kakunin.py）が読む。Claude を会社のフォルダの親などで開くと、
# hooks は何もしない（目印のないフォルダ）ため、道具に --folder で会社のフォルダを渡して進めても、質問の記録・審査役の
# 結果・版の記録が残らない（11/6 のリハーサル）。道具がこの合図の有無と古さで、そのことに気づけるようにする。
HOOK_SIGNAL = "hookの合図.json"
HOOK_SIGNAL_HOURS = 24  # これより古い合図は「最近 hooks が動いていない」とみなす


def write_hook_signal(folder: Path, event: str) -> None:
    """合図を書く。書けなくても hook は止めない（例外を外に出さない）。別名（シンボリックリンク）は通らない。"""
    try:
        from datetime import datetime, timezone

        if places.first_link(folder, f"{MARKER_DIR}/{TEMP_DIR}/{HOOK_SIGNAL}") is not None:
            return
        target = Path(folder) / MARKER_DIR / TEMP_DIR / HOOK_SIGNAL
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {"時刻": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "場面": event,
                "開いたフォルダ": os.environ.get("CLAUDE_PROJECT_DIR") or ""}
        tmp = target.with_name(target.name + ".書きかけ")
        tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(target))
    except Exception:
        pass


def hook_signal_problem(folder: Path) -> str:
    """hooks が最近この会社のフォルダで動いていないとき、その説明（動いていれば空）。時刻は実際の時計で比べる。"""
    from datetime import datetime, timezone

    path = Path(folder) / MARKER_DIR / TEMP_DIR / HOOK_SIGNAL
    howto = ("このままでは、審査役の結果（記録/審査役の結果/）・質問の記録（記録/質問の記録.json）・版の記録が残りません。"
             "Claude を会社のフォルダ（このフォルダ）で開き直してから続けてください（親のフォルダで開き、道具に --folder で"
             "会社のフォルダを渡しても、hooks は動きません）")
    try:
        if places.first_link(folder, f"{MARKER_DIR}/{TEMP_DIR}/{HOOK_SIGNAL}") is not None:
            return f"hooks の合図（{MARKER_DIR}/{TEMP_DIR}/{HOOK_SIGNAL}）が別名になっていて、読みません。" + howto
        data = json.loads(path.read_text(encoding="utf-8"))
        when = datetime.fromisoformat(str(data["時刻"]))
    except FileNotFoundError:
        return "hojokin の hooks が、この会社のフォルダで一度も動いていません（Claude を会社のフォルダで開いていない疑い）。" + howto
    except (OSError, ValueError, KeyError, TypeError):
        return f"hooks の合図（{MARKER_DIR}/{TEMP_DIR}/{HOOK_SIGNAL}）が読めません。" + howto
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    if hours > HOOK_SIGNAL_HOURS:
        return (f"hojokin の hooks が、この会社のフォルダで{int(hours)}時間動いていません（最後は {data['時刻']}。"
                "Claude を会社のフォルダで開いていない疑い）。" + howto)
    return ""


def settings_path(folder: Path) -> Path:
    return folder / MARKER_DIR / SETTINGS_FILE


def load_settings(folder: Optional[Path]) -> dict:
    """`.hojokin/設定.json` を読む。会社のフォルダでないときと、ファイルがないときは空。

    中身が JSON として読めないときは、黙って無視せずに ValueError にする
    （日付の差し替えが効いていないことに気づかないまま、デモやテストが進まないように）。
    `.hojokin/` か `設定.json` が別名（シンボリックリンク）なら、別名の先（会社のフォルダの外かもしれない）を読まず、
    空（差し替えのないもの）として扱う（lib/places.py。DESIGN 5章）。断らないのは、多くの hook と道具が呼ぶので、
    止めずに今の日付で動かすため（仮。作者に確かめる）。
    """
    if folder is None:
        return {}
    if places.first_link(folder, f"{MARKER_DIR}/{SETTINGS_FILE}") is not None:
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
