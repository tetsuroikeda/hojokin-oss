"""開いたときに、前回から増えた・変わった書類を見つけて Claude に渡す（SPEC F5、DESIGN 4.7 の2。TASKS B9）。

見つけ方は lib/seiri.py の opening_changes（中身のハッシュで見る。動かしただけ・名前を変えただけは除く）。
ここは、開いたときに渡す文と、開き方による違いだけを持つ。
- 書類の整理と不備の確かめは、Claude が社長の最初の発言のときに行う（hook は情報を渡せるだけのため。DESIGN 4.7）。
- 会話を縮めた後（compact）と消した後（clear）は、前に見つけた変化のうち、まだ整理していないものも続けて渡す。
- どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が「Python が動かない」とみなし、書き込みと Bash を拒むため）。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from lib import view_only

HEAD = "## hojokin：前回から増えた・変わった書類"
LIST_MAX = 20  # 開いたときに並べる数。超えた分は件数だけにする（開いたときの情報を10,000字以内にするため）


def opening_text(found: dict) -> str:
    """開いたときに渡す文。変化がなければ空。"""
    changes: List[dict] = found.get("変化") or []
    if not changes:
        return ""
    lines = [HEAD, ""]
    for c in changes[:LIST_MAX]:
        line = f"- {c['場所']}（{c['変化']}）"
        if c.get("同じ中身の書類"):
            line += f"。原本の {c['同じ中身の書類']} と同じ中身"
        lines.append(line)
    if len(changes) > LIST_MAX:
        lines.append(f"- ほか {len(changes) - LIST_MAX}件")
    lines.append("")
    lines.append(
        "社長の最初の発言のときに、shorui の手順で、上の書類だけを整理し、不備を確かめてください"
        "（社長が別のことを頼んだら、そちらを先に）。中身のハッシュで比べたので、動かしただけ・名前を変えただけの書類は入っていません。")
    earlier = found.get("前からある数") or 0
    if earlier:
        lines.append(f"ほかに、前からある整理していない書類が{earlier}件あります。これは、社長に頼まれたときに整理します。")
    return "\n".join(lines)


def session_start(data: dict, folder: Path, output: Optional[dict]) -> Optional[dict]:
    """開いたときの出力に、増えた・変わった書類の文を足す（ほかの処理が渡す情報は消さない）。"""
    source = (data or {}).get("source")
    try:
        from lib import seiri
        found = seiri.opening_changes(folder, keep_previous=source in ("compact", "clear"))
        text = opening_text(found)
    except Exception as error:
        text = f"{HEAD}\n\n書類の変化を確かめられませんでした（{type(error).__name__}: {error}）。shorui の scan で確かめてください。"
    if not text:
        return output
    return view_only.add_context(output, text)
