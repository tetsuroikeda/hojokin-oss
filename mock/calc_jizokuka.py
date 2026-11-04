"""持続化の模擬画面の「自動計算」で出す値（画面10 経費明細表・資金調達方法。手引き p.45–46）。

- (a) 補助対象経費小計（ウェブサイト関連費を除く）、(c) ウェブサイト関連費の小計
- (2) の目安 ＝ (a) × 補助率（円未満切捨て）。(b) は担当者・ツールが入れる値で、空なら目安を使う
- (d) ＝ (c) × 補助率（円未満切捨て）。50万円まで
- (e) ＝ (a)＋(c)、(f) ＝ (b)＋(d)、(g) ＝ (e)−(f)
- (d) が (f) の1/4以内で50万円以下か（はい・いいえ）
- 資金調達方法：1.持続化補助金 ＝ (f)、合計額 ＝ 1＋2＋3＋4
補助率は2/3（賃金引上げ特例の赤字事業者は3/4。公募要領 第20回 p.3）。補助上限額は見ない（模擬）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from calc import money, to_number  # noqa: E402
import screen_jizokuka as sj  # noqa: E402

WEB_CAP = 500_000


def rate(values: dict) -> Tuple[int, int]:
    """補助率（分子, 分母）。"""
    return (3, 4) if values.get("wage_tokurei") == sj.WAGE_DEFICIT else (2, 3)


def whole(x: Optional[float]) -> int:
    return int(round(x)) if x is not None else 0


def compute(values: dict) -> dict:
    out = {}
    rows = [(values.get(f"exp{k}_category", ""), to_number(values.get(f"exp{k}_amount")))
            for k in range(1, sj.EXPENSE_ROWS + 1)]
    subsidy = None
    if any(amount is not None for _category, amount in rows):
        num, den = rate(values)
        a = sum(whole(x) for c, x in rows if x is not None and c != sj.WEB_CATEGORY)
        c = sum(whole(x) for cat, x in rows if x is not None and cat == sj.WEB_CATEGORY)
        b_max = a * num // den
        b_in = to_number(values.get("subsidy_b"))
        b = whole(b_in) if b_in is not None else b_max
        d = min(c * num // den, WEB_CAP)
        e, subsidy = a + c, b + d
        out.update({
            "exp_sum_a": money(a), "subsidy_b_max": money(b_max), "exp_sum_c": money(c), "exp_sub_d": money(d),
            "exp_total_e": money(e), "exp_total_f": money(subsidy), "exp_diff_g": money(e - subsidy),
            "web_check": "はい" if d * 4 <= subsidy and d <= WEB_CAP else "いいえ",
            "fund_subsidy_amount": money(subsidy),
        })
    parts = [subsidy] + [to_number(values.get(f"fund_{key}_amount")) for key in ("own", "loan", "other")]
    if any(x is not None for x in parts):
        out["fund_total_amount"] = money(sum(x or 0 for x in parts))
    return out
