"""開いたときに、会社の記録の要約を渡す（DESIGN 4.7 の5「会社の記録の要約」、10章「学んだことを次に生かす仕組み」。TASKS M11）。

要約の中身は lib/company_record.py の session_note()：変わりうる情報、食い違いのある事実、最近増えた書き方の決まり、件数。
記録がまだなければ何も足さない。記録が読めない・形が違うときは、そのことを伝える。
どの開き方（startup・resume・clear・compact）でも渡す（compact の後は、前の要約が文脈から消えるため）。
どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が「Python が動かない」とみなし、書き込みと Bash を拒むため）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from lib import view_only


def session_start(data: dict, folder: Path, output: Optional[dict]) -> Optional[dict]:
    """開いたときの出力（additionalContext）に、会社の記録の要約を足して返す（ほかの処理が渡す情報は消さない）。"""
    try:
        from lib import company_record
        note = company_record.session_note(folder)
    except Exception as error:
        note = (f"【hojokin】会社の記録の要約を作れませんでした（{type(error).__name__}: {error}）。"
                "記録を使うときは、kiroku の道具（record.py list）で中身を確かめてください。")
    if not note:
        return output
    return view_only.add_context(output, note)
