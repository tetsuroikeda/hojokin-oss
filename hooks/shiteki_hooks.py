"""社長の発言に、指摘・訂正らしい言葉があるときに、「記録に残すか判断する」という一言を添える（SPEC F13「指摘から学ぶ」
「一度きりの指示は残さない」、DESIGN 10章「学ぶきっかけと、残し方」。TASKS B4）。

- UserPromptSubmit（社長が送ったとき）に、発言の文字を決まった言葉と照らすだけ（モデルは使わない）。
  見つけたら、見つけた言葉と、残し方の決まり（kiroku の SKILL.md「社長が会話で指摘・訂正したとき」）を一言で渡す。
  記録に残すかどうかは Claude が判断する（言葉が当たっても、指摘でなければ何もしない）。
- 「今回だけ」などの一度きりの言葉と、「次から」「いつも」などの次からも当てはまる言葉は、どちらに当たるかも添える
  （「今回だけ」は残さない。どちらとも取れるときは「次からもそうしますか」と確かめてから残す）。
- 社長の発言を記録しない（言葉の一覧だけを使う）。どんな失敗でも例外を外に出さない（何も足さないだけにする）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List

# 指摘・訂正らしい言葉（DESIGN 10章の「直して」「違う」「〜ではなく」と、その仲間）
CORRECTION = ("直して", "違います", "違う", "ではなく", "じゃなく", "使わないで", "使いません", "使わない", "やめて",
              "書かないで", "書かない", "間違", "誤り", "誤字", "おかしい", "変えて", "にしてください", "と書いて", "で書いて",
              "分けて", "言い方")
ONCE = ("今回だけ", "今回は", "この申請だけ", "この計画書だけ", "今だけ", "一度だけ")
ALWAYS = ("次から", "次回から", "これからは", "今後は", "いつも", "どの計画書でも", "どの申請書でも", "毎回", "うちでは")
QUOTE_LIMIT = 4


def _found(text: str, words) -> List[str]:
    return [w for w in words if w in text]


def note(data: Dict[str, Any]) -> str:
    """社長の発言に指摘らしい言葉があれば、Claude に渡す一言。なければ空。"""
    try:
        prompt = unicodedata.normalize("NFKC", str(data.get("prompt") or ""))
    except Exception:
        return ""
    if not prompt.strip() or prompt.lstrip().startswith("/"):
        return ""
    once = _found(prompt, ONCE)
    always = _found(prompt, ALWAYS)
    words = _found(prompt, CORRECTION) + once + always
    if not words:
        return ""
    shown = "」「".join(list(dict.fromkeys(words))[:QUOTE_LIMIT])
    if once:
        kind = "「今回だけ」の言葉があるので、今回の書類にだけ当て、記録には残さない。"
    elif always:
        kind = "次からも当てはまる言葉があるので、聞き返さずに記録に残す。"
    else:
        kind = ("事実・数字の訂正は、そのまま記録を直す。表現・方針・構成で、今回だけか次からもか分からないときは、"
                "今回の書類に当てたうえで「次からもそうしますか」と確かめ、「次からも」と答えてもらってから残す"
                "（答える前に残さない）。")
    return ("【hojokin】社長の発言に、指摘・訂正らしい言葉（「" + shown + "」）があります。記録に残すかを判断してください。"
            "指摘なら、事実・数字の訂正（record.py update-fact か add-fact。出典は社長の発言）、表現（避けたい言い方と"
            "好む言い方に分けて add-rule。「」の中には、それぞれの言い回しだけを書く）、書き方の方針、構成のどれかとして、"
            "kiroku の記録の道具で残します（kiroku の SKILL.md「社長が会話で指摘・訂正したとき」）。" + kind +
            "指摘でなければ、何もしません。")
