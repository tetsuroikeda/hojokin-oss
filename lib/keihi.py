"""経費明細を作る（SPEC F8「経費明細は、照合を通った見積書の金額から作る。メモや聞き取りからの金額には仮の印を付け…
迷うものや対象外になりそうなものは「要確認」として資料のページを示す」、DESIGN 8.4。TASKS B20。T8-13）。

- 経費の区分と、対象外になりそうかの判断は Claude が行い（制度データの補助の対象になる経費・ならない経費に照らす）、
  ここは答えが1つに決まる確かめと記録だけを行う。
  - 根拠が見積書の行は、照合済み（lib/kingaku.py の記録で「照合済み」）の見積書の明細を指し（明細の番号。まとめるときは番号の一覧）、
    金額がその明細の金額（の和）と1円も違わないこと。有効期限が今日より前の見積書は使わない。
  - 根拠がメモ・聞き取りの行は、状態を「仮」にする（見積書がそろったら差し替える）。数字の欄には文字を入れない（DESIGN 6章）。
  - 要確認の行は、資料のページ（出典）がないと残さない。
  - 金額は税抜の円の整数。
- 記録は `記録/経費明細.json`（案件ごと）。入力シートの経費明細の欄は、ここから書く（入力シートへの書き込みは B14b の道具）。
  一度作った後は、案件の行だけを置き換える（前の版は版の履歴に残る）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Dict, List

from lib import dates, kingaku, place_text
from lib.company_init import RECORDS_DIR

RECORD_PATH = f"{RECORDS_DIR}/経費明細.json"
QUOTE = "見積書"
SOFT_SOURCES = ("メモ", "聞き取り", "カタログ")
SOURCES = (QUOTE,) + SOFT_SOURCES
FIXED = "確定"
TENTATIVE = "仮"


class KeihiError(ValueError):
    """経費明細を残さなかった。何も書いていない。"""


def nfc(text) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def _int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise KeihiError(f"{what}（{value}）は、円の整数にしてください（「,」「円」「約」などの文字を入れない）")
    return int(value)


def _expired(reading: dict, today: date) -> bool:
    text = str(reading.get("有効期限") or "")[:10]
    try:
        return date.fromisoformat(text) < today
    except ValueError:
        return False


def build(folder: Path, case: str, rows: List[dict]) -> dict:
    """行を確かめて、記録に残す形にする（書かない）。外れがあれば、すべてを並べて KeihiError。"""
    folder = Path(folder)
    if not nfc(case).strip():
        raise KeihiError("案件を渡してください")
    if not isinstance(rows, list) or not rows:
        raise KeihiError("「行」に、経費の行を1つ以上入れてください")
    today = dates.today(folder)
    problems: List[str] = []
    out: List[dict] = []
    readings: Dict[str, dict] = {}
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            problems.append(f"{i}行目が {{ }} の形ではありません")
            continue
        try:
            source = nfc(row.get("根拠")).strip()
            if source not in SOURCES:
                raise KeihiError(f"根拠（{row.get('根拠')}）は、{'・'.join(SOURCES)} のどれかにしてください")
            name = nfc(row.get("品名")).strip()
            if not name:
                raise KeihiError("品名がありません")
            amount = _int(row.get("金額"), "金額（税抜）")
            entry = {"経費の区分": nfc(row.get("経費の区分")).strip(), "品名": name, "型番": row.get("型番"),
                     "数量": row.get("数量"), "単位": row.get("単位"), "単価": row.get("単価"), "金額": amount,
                     "根拠": source, "原本": nfc(row.get("原本")).strip(), "出典": nfc(row.get("出典")).strip()}
            if source == QUOTE:
                original = entry["原本"]
                if not original:
                    raise KeihiError("根拠が見積書の行には、見積書の原本の場所（原本）を入れてください")
                numbers = row.get("明細の番号")
                numbers = numbers if isinstance(numbers, list) else [numbers]
                if not numbers or not all(isinstance(n, int) and not isinstance(n, bool) for n in numbers):
                    raise KeihiError("根拠が見積書の行には、見積書の明細の番号（まとめるときは番号の一覧）を入れてください")
                try:
                    detail = kingaku.verified_rows(folder, original)
                except kingaku.KingakuError as e:
                    raise KeihiError(str(e)) from e
                record = kingaku.find(kingaku.load(folder), kingaku._original(folder, original)["場所"])
                readings[original] = record["読み取り"]
                if _expired(record["読み取り"], today):
                    raise KeihiError(f"見積書（{original}）は有効期限（{record['読み取り'].get('有効期限')}）が切れています。"
                                     "取り直した見積書を使ってください")
                try:
                    picked = [detail[n - 1] for n in numbers]
                except IndexError:
                    raise KeihiError(f"見積書（{original}）に、明細の番号 {numbers} がありません（明細は {len(detail)} 行）")
                expected = sum(int(kingaku._num(p.get("金額")) or 0) for p in picked)
                if amount != expected:
                    raise KeihiError(f"金額 {amount:,} が、見積書（{original}）の明細 {numbers} の金額 {expected:,} と合いません"
                                     "（税抜の明細の金額を、そのまま使ってください）")
                entry["明細の番号"] = numbers
                entry["状態"] = FIXED
            else:
                entry["状態"] = TENTATIVE
                if not entry["出典"] and not entry["原本"]:
                    raise KeihiError("メモ・聞き取りの行には、出典（どのメモのどこか、だれの話か）を入れてください")
            caution = row.get("要確認")
            if caution:
                if isinstance(caution, dict):
                    reason, page = nfc(caution.get("わけ")), nfc(caution.get("資料のページ"))
                else:
                    reason, page = nfc(caution), nfc(row.get("資料のページ"))
                if not page.strip():
                    raise KeihiError("要確認の行には、資料のページ（例：要領8 p.23）を入れてください")
                entry["要確認"] = {"わけ": reason.strip(), "資料のページ": page.strip()}
            out.append(entry)
        except KeihiError as e:
            problems.append(f"{i}行目（{nfc(row.get('品名'))}）：{e}")
    if problems:
        raise KeihiError("経費明細を残していません：\n- " + "\n- ".join(problems))
    fixed = sum(e["金額"] for e in out if e["状態"] == FIXED and "要確認" not in e)
    tentative = sum(e["金額"] for e in out if e["状態"] == TENTATIVE and "要確認" not in e)
    caution = sum(e["金額"] for e in out if "要確認" in e)
    return {"案件": nfc(case).strip(), "作った日時": dates.now(folder).isoformat(timespec="seconds"), "行": out,
            "合計": {"見積書から": fixed, "仮（メモ・聞き取りから）": tentative, "要確認": caution,
                    "全体（要確認を除く）": fixed + tentative},
            "使った見積書": sorted(readings)}


def load(folder: Path) -> dict:
    path = Path(folder) / RECORD_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"説明": "経費明細（lib/keihi.py が書く）。案件ごとに、行・状態（確定・仮）・要確認・合計を持つ", "案件": []}
    except (OSError, ValueError) as e:
        raise KeihiError(f"{RECORD_PATH} が読めません（{type(e).__name__}）") from e
    if not isinstance(data, dict) or not isinstance(data.get("案件"), list):
        raise KeihiError(f"{RECORD_PATH} の形が違います")
    return data


def save(folder: Path, case: str, rows: List[dict]) -> dict:
    """行を確かめて、記録に残す（同じ案件の前の明細は置き換える）。残した案件の1件を返す。"""
    folder = Path(folder)
    entry = build(folder, case, rows)
    data = load(folder)
    data["案件"] = [c for c in data["案件"] if c.get("案件") != entry["案件"]] + [entry]
    problem = place_text.write_problem(folder, RECORD_PATH, f"{RECORD_PATH} を書いていません")
    if problem:
        raise KeihiError(problem)
    path = folder / RECORD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".経費明細_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return entry
