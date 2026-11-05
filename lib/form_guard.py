"""応答の終わりに、申請書の Word・Excel の書式を照らし、書いてよい範囲の外が変わっていたら直前の版に戻す
（DESIGN 5章「Word・Excel の様式と申請書類の書式を壊さない」のすり抜けへの備え。TASKS B14b）。

決まった書き込みは skill の道具（yoshiki.py）が行い、範囲の外が変わる書き込みは保存しない。それでも Claude が
その場で書いたコード（Python など）で書き換えた場合に備え、Stop で同じ物差しで比べる。

- 照らすのは、最後の版から変わった `案件/<案件>/<段階>/申請書/` の .docx・.xlsx だけ（版の履歴にあるもの）。
  直前の版は、版の履歴の最後の版（社長が手で直した後なら、開いたとき・社長の発言のときに残したその版）。
- 物差し：その1・2 などの Word は、制度データの様式の項目と欄の書き込む位置（lib/yoshiki_word.py）。
  入力シート.xlsx は、値の列（lib/input_sheet.py）。そのほかの Excel の様式は、入力のシートのロックを外したセル
  （lib/yoshiki_excel.py）。保護したシートのない Excel（根拠対照表.xlsx など、道具が作り直すもの）は比べない。
- 範囲の外が変わっていれば、直前の版の中身に書き戻し、Claude に伝える文を返す。版の記録（version_hooks.stop）より
  先に動かすので、書き換えた中身は版に残らない。
- 読めない・比べられないときは戻さない（誤って社長の書類を戻さないため）。

/usr/bin/python3（3.9）で動く。標準のライブラリと同梱の dulwich（lib/history.py）だけを使う。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

APPLICATION = re.compile(r"^案件/[^/]+/[^/]+/申請書/[^/]+\.(docx|xlsx|xlsm)$")
SEIDO_DIR = "記録/制度データ"
INPUT_SHEET = "入力シート.xlsx"
MAX_SHOWN = 5


def _positions(folder: Path) -> List[Tuple[str, dict]]:
    """制度データのすべての様式の、項目と欄の書き込む位置（見つからない位置は比べるときに飛ばされる）。"""
    from lib import places
    from lib import yoshiki_word as yw

    top = places.actual(folder, SEIDO_DIR)
    out: List[Tuple[str, dict]] = []
    if top is None or not top.is_dir():
        return out
    for path in sorted(top.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for form in data.get("様式") or [] if isinstance(data, dict) else []:
            if isinstance(form, dict):
                out += yw.item_positions(form)
    return out


def _is_mapped_form(blob: bytes, positions: List[Tuple[str, dict]]) -> bool:
    """制度データの様式の書き込む位置が、1つでもこの Word に見つかるか（様式から写した申請書か）。"""
    from lib import xml_spans
    from lib import yoshiki_word as yw

    try:
        root = xml_spans.parse(yw.read_parts(blob)[1][yw.DOC])
    except Exception:
        return False
    for label, pos in positions:
        try:
            yw.resolve(root, pos, label)
            return True
        except Exception:
            continue
    return False


def readable(rel: str, blob: bytes) -> bool:
    """Word・Excel のファイルとして読めるか（本文かブックの部品がある）。"""
    from lib import yoshiki_word as yw

    try:
        _infos, parts = yw.read_parts(blob)
    except Exception:
        return False
    return (yw.DOC if rel.endswith(".docx") else "xl/workbook.xml") in parts


def differences(rel: str, before: bytes, after: bytes, positions: List[Tuple[str, dict]]) -> List[str]:
    """申請書のファイルの、直前の版と今の中身の、書いてよい範囲の外の差。

    直前の版が Word・Excel として読めないときは比べない（空を返す）。今の中身だけが読めないときは、壊れたものとして差を返す。
    """
    from lib import input_sheet, yoshiki_excel
    from lib import yoshiki_word as yw

    if not readable(rel, before):
        return []
    if not readable(rel, after):
        return ["Word・Excel のファイルとして読めなくなりました"]
    name = rel.rsplit("/", 1)[-1]
    if rel.endswith(".docx"):
        if not _is_mapped_form(before, positions):
            return []  # 様式の項目を対応づけていない Word（道具が作り直す報告書など）は比べない
        return yw.compare_docx(before, after, positions)
    if name == INPUT_SHEET:
        return input_sheet.compare_xlsx(before, after)
    try:
        is_form = any(s.protected for s in yoshiki_excel.Book(before).sheets)
    except Exception:
        return []
    if not is_form:
        return []  # 根拠対照表.xlsx など、道具が作り直す Excel（入力の欄を保護で示した様式ではない）は比べない
    return yoshiki_excel.compare_xlsx(before, after)


def _write_back(path: Path, data: bytes) -> None:
    mode = None
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.戻す")
    with open(tmp, "wb") as f:
        f.write(data)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def check(folder: Path) -> List[str]:
    """変わった申請書の Word・Excel を照らし、範囲の外が変わったものを戻す。Claude に伝える文の一覧を返す。"""
    from lib import history, places

    try:
        changes, _dirs = history.quick_changes(folder)
    except Exception:
        return []
    targets = [c for c in changes if c.kind == history.MODIFIED and c.fs_path and APPLICATION.match(c.path)]
    if not targets:
        return []
    positions = _positions(folder)
    notes = []
    for change in targets:
        try:
            places.no_link_on_the_way(folder, change.path)
            records = history.log(folder, change.path, limit=1)
            if not records:
                continue
            before = history.content_at(folder, records[0].version, change.path)
            if before is None:
                continue
            path = Path(change.fs_path)
            after = path.read_bytes()
            if after == before:
                continue
            found = differences(change.path, before, after, positions)
            if not found:
                continue
            _write_back(path, before)
        except Exception:
            continue  # 読めない・比べられないときは戻さない
        shown = "／".join(found[:MAX_SHOWN]) + ("ほか" if len(found) > MAX_SHOWN else "")
        notes.append(f"{change.path} が、書いてよい範囲の外まで変わっていました（{shown}）。様式の書式を守るため、"
                     "直前の版に戻しました。その場のコードで Word・Excel を書き換えず、kaku の道具（yoshiki.py）で"
                     "書き直してください。")
    return notes
