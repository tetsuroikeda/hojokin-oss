"""開いたときに、期限と作業・どの段階にも共通の決まりを渡し、今の状態の画面を作り直す（DESIGN 4.2・4.6、
4.7 の「開いたときの流れ」の3と5、5章「開いたときに渡す情報を10,000字以内にする」。TASKS M3）。

中身は lib/status_view.py（組み立ては lib/deadlines.py）。hooks/session_start.py の最後に呼ぶ
（ほかの処理が渡す情報の後ろに置き、全体を10,000字以内に切るため）。
どの開き方（startup・resume・clear・compact）でも渡す（compact の後は、前の情報が文脈から消えるため）。
どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が「Python が動かない」とみなし、書き込みと Bash を拒むため）。
決まりの文は、失敗したときも渡す。
重い読み込みはここでしない（hooks/main.py は、どの場面でもこのファイルを読み込むため）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

FALLBACK_HEAD = "## hojokin：開いたときの期限と作業"  # lib/status_view.py の BRIEF_HEAD と同じ


def session_start(data: dict, folder: Path, output: Optional[dict]) -> Optional[dict]:
    """開いたときの出力（additionalContext）に、期限と作業・共通の決まりを足して返す（ほかの処理が渡す情報は消さない）。"""
    try:
        from lib import status_view
        return status_view.session_start(folder, output)
    except Exception as error:
        note = f"{FALLBACK_HEAD}\n\n期限と作業を組み立てられませんでした（{type(error).__name__}: {error}）。"
        try:
            from lib import common_rules
            note += "\n\n" + common_rules.TEXT.rstrip()
        except Exception:
            pass
        result = dict(output or {})
        hso = dict(result.get("hookSpecificOutput") or {"hookEventName": "SessionStart"})
        current = hso.get("additionalContext")
        hso["additionalContext"] = f"{current}\n{note}" if isinstance(current, str) and current else note
        result["hookSpecificOutput"] = hso
        return result
