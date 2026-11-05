"""見積書・請求書・納品書の金額と明細を、計算で照合する（SPEC F5「金額は…計算で照合する。合わなければ読み直し、
それでも合わなければ、その部分の画像と読み取った数字を並べて社長に確かめる。推測で埋めない」、DESIGN 8.4。TASKS B11。T5-8）。

- 読み取るのは読み取り役（yomitori。金額と明細は Sonnet 5.5、外れた所の読み直しは Opus 5.5）。ここは答えが1つに決まる
  照合と、読み取りの記録だけを行う。読めない値（null）を、ほかの数から計算して埋めない。
- 照合すること（DESIGN 8.4）：明細ごとの「数量 × 単価 ＝ 金額」、税率ごとの明細の和 ＝ 対象額、対象額 × 税率 ＝ 消費税
  （端数の処理が書いてあればそのとおり。なければ切り捨て・四捨五入・切り上げのどれかで合えばよい）、明細の和 ＝ 小計、
  小計 ＋ 消費税 ＝ 合計、税率は 10%・8% のどちらか。
- 記録：`記録/金額の読み取り.json` に、原本ごとに1件（原本の場所と id、何回目か、読んだモデル、読み取り、照合の結果、状態）。
  状態は「照合済み」（外れも読めない所もない）、「読み直す」（1回目で外れた）、「要確認」（読み直しても外れた・読めない所がある。
  社長に確かめる）。社長が答えた値は confirm で入れ、出典を「社長の答え」にして照合し直す。
- 経費明細（B20。lib/keihi.py）は、照合済みの見積書の明細だけを使う。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

from lib import dates, place_text, seiri
from lib.company_init import RECORDS_DIR

RECORD_FILE = "金額の読み取り.json"
RECORD_PATH = f"{RECORDS_DIR}/{RECORD_FILE}"
VERIFIED = "照合済み"
REREAD = "読み直す"
ASK = "要確認"
RATES = (10, 8)
MODELS = ("haiku", "sonnet", "opus")


class KingakuError(ValueError):
    """照合しなかった（原本でない、読み取りの形が違う など）。記録は変えていない。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def _num(value) -> Optional[float]:
    """数の欄の値。null・空・数でないものは None（読めない）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = unicodedata.normalize("NFKC", str(value)).replace(",", "").replace("円", "").replace("¥", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _taxes(base: float, rate: float, rounding: str) -> List[int]:
    raw = base * rate / 100
    if "切り捨" in rounding or "切捨" in rounding:
        return [math.floor(raw + 1e-9)]
    if "四捨五入" in rounding:
        return [math.floor(raw + 0.5)]
    if "切り上" in rounding or "切上" in rounding:
        return [math.ceil(raw - 1e-9)]
    return sorted({math.floor(raw + 1e-9), math.floor(raw + 0.5), math.ceil(raw - 1e-9)})


def check(reading: dict) -> dict:
    """読み取りを計算で照合する。{"外れ": [...], "読めない": [...]} を返す（どちらも空なら照合を通った）。"""
    misses: List[dict] = []
    unread: List[dict] = []
    rows = reading.get("明細")
    if not isinstance(rows, list) or not rows:
        return {"外れ": [], "読めない": [{"欄": "明細", "理由": "明細がありません"}]}
    rounding = nfc(str(reading.get("端数の処理") or ""))
    by_rate: Dict[float, float] = {}
    row_sum = 0.0
    rows_complete = True
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            unread.append({"欄": f"明細{i}", "理由": "明細の形が違います"})
            rows_complete = False
            continue
        qty, price, amount = _num(row.get("数量")), _num(row.get("単価")), _num(row.get("金額"))
        rate = _num(row.get("税率"))
        label = f"明細{i}（{nfc(str(row.get('品名') or ''))}）"
        for key, value in (("数量", qty), ("単価", price), ("金額", amount)):
            if value is None:
                unread.append({"欄": f"明細{i}.{key}", "品名": row.get("品名"), "理由": "読めない値（null）"})
        if rate is not None and rate not in RATES:
            misses.append({"欄": f"明細{i}.税率", "内容": f"{label}の税率 {rate:g}% は、10% か 8% ではありません"})
        if qty is not None and price is not None and amount is not None and abs(qty * price - amount) > 0.5:
            misses.append({"欄": f"明細{i}", "内容": f"{label}：数量 {qty:g} × 単価 {price:,.0f} ＝ {qty * price:,.0f} で、"
                                                f"金額 {amount:,.0f} と合いません"})
        if amount is None:
            rows_complete = False
        else:
            row_sum += amount
            if rate is not None:
                by_rate[rate] = by_rate.get(rate, 0.0) + amount
    subtotal, tax, total = _num(reading.get("小計")), _num(reading.get("消費税")), _num(reading.get("合計"))
    for key, value in (("小計", subtotal), ("消費税", tax), ("合計", total)):
        if value is None:
            unread.append({"欄": key, "理由": "読めない値（null）"})
    if rows_complete and subtotal is not None and abs(row_sum - subtotal) > 0.5:
        misses.append({"欄": "小計", "内容": f"明細の金額の和 {row_sum:,.0f} が、小計 {subtotal:,.0f} と合いません"})
    if subtotal is not None and tax is not None and total is not None and abs(subtotal + tax - total) > 0.5:
        misses.append({"欄": "合計", "内容": f"小計 {subtotal:,.0f} ＋ 消費税 {tax:,.0f} ＝ {subtotal + tax:,.0f} で、合計 {total:,.0f} と合いません"})
    per_rate = reading.get("税率ごと") if isinstance(reading.get("税率ごと"), list) else []
    if per_rate:
        tax_sum = 0.0
        for item in per_rate:
            rate, base, part = _num(item.get("税率")), _num(item.get("対象額")), _num(item.get("消費税"))
            if rate is None or base is None or part is None:
                unread.append({"欄": f"税率ごと（{item.get('税率')}%）", "理由": "読めない値（null）"})
                continue
            tax_sum += part
            if rows_complete and abs(by_rate.get(rate, 0.0) - base) > 0.5:
                misses.append({"欄": f"税率ごと（{rate:g}%）.対象額",
                               "内容": f"{rate:g}% の明細の和 {by_rate.get(rate, 0.0):,.0f} が、対象額 {base:,.0f} と合いません"})
            if int(round(part)) not in _taxes(base, rate, rounding):
                misses.append({"欄": f"税率ごと（{rate:g}%）.消費税",
                               "内容": f"{rate:g}% の対象額 {base:,.0f} の消費税は {'・'.join(f'{t:,}' for t in _taxes(base, rate, rounding))} で、"
                                       f"書類の {part:,.0f} と合いません"})
        if tax is not None and abs(tax_sum - tax) > 0.5:
            misses.append({"欄": "消費税", "内容": f"税率ごとの消費税の和 {tax_sum:,.0f} が、消費税 {tax:,.0f} と合いません"})
    elif rows_complete and tax is not None:
        expected = set()
        for rate, base in by_rate.items():
            expected = {a + b for a in (expected or {0}) for b in _taxes(base, rate, rounding)}
        if expected and int(round(tax)) not in expected:
            misses.append({"欄": "消費税", "内容": f"明細の税率から出した消費税（{'・'.join(f'{t:,}' for t in sorted(expected))}）が、"
                                                f"書類の消費税 {tax:,.0f} と合いません"})
    return {"外れ": misses, "読めない": unread}


# ---- 記録 ----


def record_path(folder: Path) -> Path:
    return Path(folder) / RECORD_PATH


def load(folder: Path) -> dict:
    path = record_path(folder)
    problem = place_text.read_problem(folder, path, RECORD_PATH) if os.path.lexists(str(path)) else None
    if problem:
        raise KingakuError(problem)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"説明": "見積書・請求書・納品書の金額と明細の読み取りと、計算の照合の結果（lib/kingaku.py が書く）", "書類": []}
    except (OSError, ValueError) as e:
        raise KingakuError(f"{RECORD_PATH} が読めません（{type(e).__name__}）") from e
    if not isinstance(data, dict) or not isinstance(data.get("書類"), list):
        raise KingakuError(f"{RECORD_PATH} の形が違います")
    return data


def _save(folder: Path, data: dict) -> None:
    problem = place_text.write_problem(folder, RECORD_PATH, f"{RECORD_PATH} を書いていません")
    if problem:
        raise KingakuError(problem)
    path = record_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".金額の読み取り_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _original(folder: Path, given: str) -> dict:
    ledger = seiri.load_ledger(Path(folder))
    given = nfc(given).strip()
    for e in seiri.originals(ledger):
        if given in (e.get("id"), nfc(e["場所"])):
            return e
    raise KingakuError(f"{given} は、書類の台帳の原本ではありません。先に shorui の organize で原本の置き場へ移してから照合します")


def find(data: dict, original_place: str) -> Optional[dict]:
    return next((d for d in data["書類"] if d.get("原本") == original_place), None)


def _state(result: dict, round_no: int) -> str:
    if not result["外れ"] and not result["読めない"]:
        return VERIFIED
    if round_no <= 1 and result["外れ"] and not result["読めない"]:
        return REREAD
    return ASK


def save_reading(folder: Path, given: str, reading: dict, model: str = "", round_no: int = 1) -> dict:
    """読み取りを照合し、記録に残す（同じ原本の前の記録は置き換える。前の版は版の履歴に残る）。記録の1件を返す。

    2回目（読み直し）で渡す読み取りは、外れた所を読み直した全体（明細の全部と小計・消費税・合計）にする。
    """
    folder = Path(folder)
    if not isinstance(reading, dict):
        raise KingakuError("読み取りは { } で囲んだ JSON にしてください（yomitori の返す形）")
    if model and model not in MODELS:
        raise KingakuError(f"モデル（{model}）は {'・'.join(MODELS)} のどれかにしてください")
    original = _original(folder, given)
    data = load(folder)
    previous = find(data, original["場所"])
    result = check(reading)
    models = list((previous or {}).get("読んだモデル") or []) if round_no > 1 else []
    if model:
        models.append(model)
    entry = {
        "原本": original["場所"],
        "原本の id": original.get("id"),
        "種類": reading.get("種類") or original.get("種類"),
        "回目": round_no,
        "読んだモデル": models,
        "読み取り": reading,
        "照合": result,
        "状態": _state(result, round_no),
        "社長の答え": (previous or {}).get("社長の答え", []) if round_no > 1 else [],
        "確かめた日時": dates.now(folder).isoformat(timespec="seconds"),
    }
    data["書類"] = [d for d in data["書類"] if d.get("原本") != original["場所"]] + [entry]
    _save(folder, data)
    return entry


def _set_field(reading: dict, field: str, value) -> None:
    """「明細7.単価」「小計」の形の欄に値を入れる。"""
    parts = nfc(field).strip().split(".")
    if parts[0].startswith("明細") and len(parts) == 2:
        try:
            index = int(parts[0][2:]) - 1
            row = reading["明細"][index]
        except (ValueError, IndexError, KeyError, TypeError) as e:
            raise KingakuError(f"欄（{field}）が見つかりません（例：明細7.単価）") from e
        row[parts[1]] = value
        return
    if len(parts) == 1 and parts[0] in ("小計", "消費税", "合計"):
        reading[parts[0]] = value
        return
    raise KingakuError(f"欄（{field}）は「明細<番号>.<欄>」か、小計・消費税・合計にしてください")


def confirm(folder: Path, given: str, field: str, value: str) -> dict:
    """社長が確かめた値を入れ、出典を「社長の答え」にして照合し直す。記録の1件を返す。"""
    folder = Path(folder)
    original = _original(folder, given)
    data = load(folder)
    entry = find(data, original["場所"])
    if entry is None:
        raise KingakuError(f"{original['場所']} の読み取りがまだありません。先に check で読み取りを照合してください")
    number = _num(value)
    if number is None:
        raise KingakuError(f"値（{value}）は数にしてください")
    reading = json.loads(json.dumps(entry["読み取り"]))
    _set_field(reading, field, int(number) if number == int(number) else number)
    result = check(reading)
    entry = dict(entry, 読み取り=reading, 照合=result,
                 状態=VERIFIED if not result["外れ"] and not result["読めない"] else ASK,
                 確かめた日時=dates.now(folder).isoformat(timespec="seconds"))
    entry["社長の答え"] = list(entry.get("社長の答え") or []) + [
        {"欄": field, "値": value, "日時": entry["確かめた日時"]}]
    data["書類"] = [d for d in data["書類"] if d.get("原本") != original["場所"]] + [entry]
    _save(folder, data)
    return entry


def verified_rows(folder: Path, given: str) -> List[dict]:
    """照合済みの原本の明細（経費明細が使う）。照合済みでなければ KingakuError。"""
    original = _original(Path(folder), given)
    entry = find(load(Path(folder)), original["場所"])
    if entry is None or entry.get("状態") != VERIFIED:
        state = "読み取りがありません" if entry is None else f"状態が「{entry.get('状態')}」です"
        raise KingakuError(f"{original['場所']} は照合を通っていません（{state}）。照合を通った見積書の金額だけを使います")
    return entry["読み取り"]["明細"]
