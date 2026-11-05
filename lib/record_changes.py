"""会社の記録の項目ごとの変更の履歴（SPEC F13「変わった内容の履歴（いつ、何から何に、だれが直したか）は、
共通の要件の書類の版の管理の履歴から見られる」、DESIGN 10章「変更の履歴は、版の履歴を項目ごとにたどって作る。
同じ情報を2か所に持たない」。TASKS B3）。

- `記録/会社の記録.json` の版を古い順にたどり、隣り合う版どうしで、項目（id ごと）の中身を比べる。
  変わった欄（事実の値・状態・出典、書き方の決まりの区分・内容）ごとに、日時・だれ（ツール・社長）・前・後・理由を返す。
  項目が消えたときも「消えた」として返す。足されたことは、一覧の「覚えた日・出典」で分かるので、ここでは返さない。
- 版の履歴は lib/history.py の入口から読む（Git の形でも、版のファイルの形でも同じ）。読めない版（壊れた JSON など）は飛ばす。
- まだ版に残っていない変更（同じ応答の中で直した分）は、応答の終わりに hook が版に残してから出る。
- この部品は dulwich を読み込むので、開いたときの hook（会社の記録の要約）からは使わない（record.py の list だけが使う）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib import company_record

RECORD_FILE = company_record.RECORD_FILE
# 比べる欄（種類ごと）。覚えた日・最後に確かめた日は、確かめただけでも変わるので比べない。
# 事実の出典は、値と一緒に変わる（新しい出典は一覧の行に出る）ので比べない
WATCHED = {
    company_record.FACT: ("値", "状態"),
    company_record.RULE: ("区分", "内容"),
    company_record.DEFECT: ("内容", "原因", "次に注意する書類", "照合の決まり"),
    company_record.RESULT: ("結果", "指摘された審査項目"),
}
REMOVED = "消えた"


def _items(data: Any) -> Dict[str, dict]:
    if not isinstance(data, dict) or not isinstance(data.get("項目"), list):
        raise ValueError("会社の記録の形ではありません")
    return {str(it.get("id")): it for it in data["項目"] if isinstance(it, dict) and it.get("id")}


def _text(field: str, value: Any) -> str:
    if value is None:
        return "（なし）"
    if field == "出典" and isinstance(value, dict):
        return company_record.source_text(value)
    return company_record.value_text(value)


def _when(moment: datetime) -> str:
    return f"{moment.year}年{moment.month}月{moment.day}日 {moment.hour:02d}:{moment.minute:02d}"


def changes(folder: Path) -> Dict[str, List[dict]]:
    """項目の id ごとの変更の一覧（古い順）。履歴がない・読めないときは空。"""
    from lib import history  # dulwich を読み込むので、使うときだけ

    try:
        if not history.enabled(folder):
            return {}
        records = history.log(folder, RECORD_FILE)
    except Exception:
        return {}
    out: Dict[str, List[dict]] = {}
    before: Optional[Dict[str, dict]] = None
    for rec in reversed(records):  # 古い順
        try:
            blob = history.content_at(folder, rec.version, RECORD_FILE)
            now = _items(json.loads(blob.decode("utf-8"))) if blob is not None else {}
        except Exception:
            continue  # 読めない版（社長の手直しで形が崩れた版など）は飛ばし、次の読める版と比べる
        if before is not None:
            for item_id, old in before.items():
                new = now.get(item_id)
                base = {"日時": _when(rec.time), "だれ": rec.who, "理由": rec.reason}
                if new is None:
                    out.setdefault(item_id, []).append(dict(base, 欄=REMOVED, 前=_label(old), 後="（なし）"))
                    continue
                for field in WATCHED.get(old.get("種類"), ()):
                    if old.get(field) != new.get(field):
                        out.setdefault(item_id, []).append(
                            dict(base, 欄=field, 前=_text(field, old.get(field)), 後=_text(field, new.get(field))))
        before = now
    return out


def _label(item: dict) -> str:
    if item.get("種類") == company_record.FACT:
        return f"{item.get('名前')}＝{company_record.value_text(item.get('値'))}"
    return str(item.get("内容") or item.get("結果") or item.get("id"))


def change_lines(found: Dict[str, List[dict]], item_id: str) -> List[str]:
    """一覧に添える行（「変更の履歴：…」）。"""
    lines = []
    for ch in found.get(item_id, []):
        what = "項目が消えた" if ch["欄"] == REMOVED else f"{ch['欄']}を「{company_record.short(ch['前'], 80)}」から「{company_record.short(ch['後'], 80)}」に"
        lines.append(f"  - 変更の履歴：{ch['日時']} {ch['だれ']}が{what}（理由：{company_record.short(ch['理由'], 60)}）")
    return lines


def removed_lines(found: Dict[str, List[dict]], current_ids: List[str]) -> List[str]:
    """今の記録にない（消えた）項目の行。"""
    lines = []
    for item_id, entries in found.items():
        if item_id in current_ids:
            continue
        for ch in entries:
            if ch["欄"] == REMOVED:
                lines.append(f"- [{item_id}] {company_record.short(ch['前'], 80)}：{ch['日時']} {ch['だれ']}が消した"
                             f"（理由：{company_record.short(ch['理由'], 60)}）")
    return lines
