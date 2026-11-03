"""模擬の申請画面の「計算」で出す値（❼ 事業計画数値、❽ 経費明細｜資金調達内訳）。

式は第8回の公募要領に合わせる。
- 付加価値額 ＝ 営業利益 ＋ 人件費 ＋ 減価償却費
- 労働生産性 ＝ 付加価値額 ÷ 労働者数（役員数 ＋ 常勤従業員数）
- 年平均成長率 ＝ {（n年目の値 ÷ 基準年度の値）^(1/n) − 1} × 100
- 目標：労働生産性は年4.0%、1人当たり給与支給総額は年3.5%（大幅賃上げの特例を希望するときは6.0%）
補助金申請額（D）は模擬の計算で、上限額は見ない。
"""

from __future__ import annotations

import math
from typing import Optional

PRODUCTIVITY_RATE = 4.0
SALARY_RATE = 3.5
SALARY_RATE_SPECIAL = 6.0

YEAR_COLS = ["y0", "y1", "y2", "y3", "y4", "y5"]
EXPENSE_KEYS = ["machine", "transport", "tech", "ip", "outsourcing", "expert", "cloud"]


def to_number(text) -> Optional[float]:
    """欄の文字を数にする。空や数でないものは None。"""
    if text is None or isinstance(text, bool):
        return None
    s = str(text).strip().replace(",", "").replace("，", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def money(x: Optional[float]) -> str:
    return "" if x is None else f"{round(x):,}"


def decimal(x: Optional[float]) -> str:
    return "" if x is None else f"{x:,.2f}"


def growth(base: Optional[float], value: Optional[float], years: int) -> Optional[float]:
    if base is None or value is None or base <= 0 or value <= 0:
        return None
    return ((value / base) ** (1 / years) - 1) * 100


def add(*xs: Optional[float]) -> Optional[float]:
    """足し算。どれも空なら空、一部が空なら0とみなす。"""
    if all(x is None for x in xs):
        return None
    return sum(x or 0 for x in xs)


def sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def compute(values: dict) -> dict:
    """保存した値から、計算で出す欄の表示を作る。鍵は表の欄の id（grid_row_col）など。"""
    num = lambda key: to_number(values.get(key))  # noqa: E731
    out = {}

    salary_rate = SALARY_RATE_SPECIAL if values.get("special_raise") is True else SALARY_RATE
    out["target_productivity"] = f"{PRODUCTIVITY_RATE:.2f}%"
    out["target_salary"] = f"{salary_rate:.2f}%"

    va, prod, per = {}, {}, {}
    for col in YEAR_COLS:
        p = lambda row: num(f"plan_{row}_{col}")  # noqa: E731
        gross = sub(p("sales"), p("cogs"))
        operating = sub(gross, p("sga"))
        depreciation = add(p("dep_existing"), None if col == "y0" else p("dep_new"))
        value_added = None if operating is None else add(operating, p("personnel"), depreciation)
        workers = add(p("officers"), p("employees"))
        va[col] = value_added
        prod[col] = value_added / workers if value_added is not None and workers else None
        out[f"plan_gross_profit_{col}"] = money(gross)
        out[f"plan_operating_profit_{col}"] = money(operating)
        out[f"plan_depreciation_{col}"] = money(depreciation)
        out[f"plan_value_added_{col}"] = money(value_added)
        out[f"plan_productivity_{col}"] = decimal(prod[col])

        total, count = num(f"salary_salary_total_{col}"), num(f"salary_salary_count_{col}")
        per[col] = total / count if total is not None and count else None
        out[f"salary_salary_per_{col}"] = decimal(per[col])

    for n, col in enumerate(YEAR_COLS[1:], start=1):
        out[f"plan_va_growth_{col}"] = decimal(growth(va["y0"], va[col], n))
        target = None if prod["y0"] is None else prod["y0"] * (1 + PRODUCTIVITY_RATE / 100) ** n
        out[f"plan_productivity_target_{col}"] = decimal(target)
        out[f"salary_salary_growth_{col}"] = decimal(growth(per["y0"], per[col], n))
        target = None if per["y0"] is None else per["y0"] * (1 + salary_rate / 100) ** n
        out[f"salary_salary_target_{col}"] = decimal(target)

    total_a = add(*(num(f"expense_{k}_a") for k in EXPENSE_KEYS))
    total_b = add(*(num(f"expense_{k}_b") for k in EXPENSE_KEYS))
    out["expense_total_a"] = money(total_a)
    out["expense_total_b"] = money(total_b)
    two_thirds = values.get("small_business") is True or values.get("special_min_wage") is True
    subsidy = None if total_b is None else math.floor(total_b * (2 / 3 if two_thirds else 1 / 2))
    out["subsidy_amount"] = money(subsidy)
    out["fund_all_subsidy_amount"] = money(subsidy)
    out["fund_all_total_amount"] = money(add(num("fund_all_own_amount"), subsidy,
                                             num("fund_all_loan_amount"), num("fund_all_lease_amount")))
    out["fund_d_total_amount"] = money(add(num("fund_d_own_amount"), num("fund_d_loan_amount"),
                                           num("fund_d_lease_amount")))
    return out
