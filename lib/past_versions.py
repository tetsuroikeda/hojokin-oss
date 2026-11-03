"""書類の前の版を見る・戻す（SPEC 共通の要件「書類の版の管理」、DESIGN 10章「書類の版」。TASKS M0b）。

社長は Git の操作を覚えなくてよく、頼めば前の版を見たり戻したりできる。
- 見る：前の版の中身を `見るだけ/` に読み取り専用で出す（lib/view_only.py）。作業のファイルは変えない。
  名前は「その1（2026年11月4日 15時30分の版）.docx」の形。
- 戻す：前の版の中身を、作業のファイルに書き戻し、戻したこと自体を新しい版として残す（「ツール」。理由に
  「…の版に戻した」と書く）。履歴は書き換えない。原本・公式資料・審査役の結果・プラグインの設定は戻さない
  （原本と公式資料は入れたときの1版だけで、変わっていれば開いたときと応答の終わりに戻される。DESIGN 5章）。
- 書類は、会社のフォルダからの場所で指す。場所でなく名前（「その1.docx」「その1」）だけでも、
  版の履歴の中で1つに決まれば、それにする。

版の履歴は lib/history.py が扱う（Git の形。同期されるフォルダの形は M0c で、同じ入口から動かす）。
"""

from __future__ import annotations

import os
import re
import stat as stat_mode
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from lib import case_folder, dates, history, view_only

# 戻さない場所（会社のフォルダからの場所の始まり）
PROTECTED_TOP = ("原本", ".hojokin", ".claude", ".git", "見るだけ", "記録/審査役の結果")
PENDING_REASON = "前の版に戻す前の変更"
VERSION_PREFIX = re.compile(r"^[0-9a-f]{7,40}$")
CANDIDATES_MAX = 10


class VersionError(Exception):
    """書類や版が見つからない、戻せない。文は、そのまま社長への説明に使える形にする。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _now(folder: Path) -> datetime:
    try:
        return dates.now(folder)
    except ValueError:
        return datetime.now(timezone.utc).astimezone(dates.JST)


# ---- 書類を決める ----

def _relative(folder: Path, raw: str) -> str:
    text = nfc(str(raw)).strip()
    if not text:
        raise VersionError("書類を指してください（会社のフォルダからの場所か、ファイルの名前）")
    path = Path(text)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(Path(folder).resolve())
        except ValueError as error:
            raise VersionError(f"会社のフォルダの外の場所です（{raw}）") from error
    rel = nfc(path.as_posix())
    if rel in ("", ".") or any(p in ("..",) for p in rel.split("/")):
        raise VersionError(f"書類の場所が正しくありません（{raw}）")
    return rel[2:] if rel.startswith("./") else rel


def _known_documents(folder: Path) -> List[str]:
    """版の履歴に出てくる書類の一覧（消したものも含む）。"""
    return sorted({r.document for r in history.log(folder)})


def resolve_document(folder: Path, raw: str) -> str:
    """書類の、会社のフォルダからの場所（NFC）。名前だけのときは、版の履歴の中で1つに決まるものにする。"""
    rel = _relative(folder, raw)
    known = _known_documents(folder)
    if rel in known:
        return rel
    name = rel.rsplit("/", 1)[-1]
    matched = [d for d in known if d.rsplit("/", 1)[-1] == name]
    if not matched and "." not in name:
        matched = [d for d in known if os.path.splitext(d.rsplit("/", 1)[-1])[0] == name]
    if "/" in rel:
        matched = [d for d in matched if d.endswith("/" + rel)]
    if len(matched) == 1:
        return matched[0]
    if matched:
        listed = "、".join(matched[:CANDIDATES_MAX])
        raise VersionError(f"「{raw}」に当たる書類がいくつかあります。場所で指してください：{listed}")
    raise VersionError(f"「{raw}」の版の履歴がありません（会社のフォルダからの場所で指してください）")


# ---- 版を選ぶ ----

def records(folder: Path, document: str) -> List[history.Record]:
    """その書類の履歴（新しい順）。"""
    return history.log(Path(folder), document)


def pick(found: List[history.Record], version: Optional[str] = None, back: Optional[int] = None) -> history.Record:
    """版を選ぶ。version は版の印（7桁以上の先頭でよい）。back は新しい方から数えた番号（0 が今の版、1 が1つ前）。"""
    if not found:
        raise VersionError("その書類の版の履歴がありません")
    document = found[0].document
    if version is not None:
        key = version.strip().lower()
        if not VERSION_PREFIX.match(key):
            raise VersionError(f"版の印（{version}）は、履歴に出た7桁以上の英数字で指してください")
        hits = [r for r in found if r.version.startswith(key)]
        if len(hits) != 1:
            raise VersionError(f"{document} の履歴に、版「{version}」が" + ("いくつもあります" if hits else "ありません"))
        return hits[0]
    index = 1 if back is None else back
    if index < 0 or index >= len(found):
        raise VersionError(f"{document} の履歴は {len(found)} 件です（新しい方から0〜{len(found) - 1}で選んでください）")
    return found[index]


def shown(record: history.Record) -> str:
    """例：2026年11月4日（水）15:30"""
    return dates.format_datetime(record.time)


def _name_time(moment: datetime, seconds: bool = False) -> str:
    jst = dates.to_jst(moment)
    text = f"{jst.year}年{jst.month}月{jst.day}日 {jst.hour}時{jst.minute:02d}分"
    return text + (f"{jst.second:02d}秒" if seconds else "")


def view_names(record: history.Record) -> List[str]:
    """見るだけに出すときの名前の候補（同じ分に2つの版があれば、秒、版の印の先頭を足す）。"""
    name = record.document.rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(name)
    return [
        f"{stem}（{_name_time(record.time)}の版）{ext}",
        f"{stem}（{_name_time(record.time, seconds=True)}の版）{ext}",
        f"{stem}（{_name_time(record.time, seconds=True)}の版 {record.version[:7]}）{ext}",
    ]


def _content(folder: Path, record: history.Record) -> bytes:
    data = history.content_at(Path(folder), record.version, record.document)
    if data is None:
        raise VersionError(f"{shown(record)} の版では、{record.document} は消されています")
    return data


# ---- 見る ----

def show(folder: Path, document: str, version: Optional[str] = None,
         back: Optional[int] = None) -> Tuple[history.Record, str]:
    """前の版を `見るだけ/` に読み取り専用で出す。(選んだ版, 出した場所) を返す。"""
    folder = Path(folder)
    doc = resolve_document(folder, document)
    record = pick(records(folder, doc), version, back)
    data = _content(folder, record)
    return record, view_only.export_file(folder, view_names(record), data)


# ---- 戻す ----

def protected(document: str) -> bool:
    parts = document.split("/")
    if any(document == top or document.startswith(top + "/") for top in PROTECTED_TOP):
        return True
    return len(parts) >= 3 and parts[0] == case_folder.CASES_DIR and parts[2] == case_folder.OFFICIAL_DIR


def _actual_path(folder: Path, document: str) -> Path:
    """作業のファイルの実際の場所（名前が NFD のこともある）。なければ NFC の名前の場所。"""
    current = Path(folder)
    parts = document.split("/")
    for i, part in enumerate(parts):
        try:
            names = os.listdir(str(current))
        except OSError:
            return Path(folder).joinpath(*parts)
        match = next((n for n in names if nfc(n) == part), None)
        if match is None:
            return current.joinpath(*parts[i:])
        current = current / match
    return current


def _write_back(path: Path, data: bytes) -> None:
    """書き戻す（書きかけのファイルは .gitignore の「~*.tmp」の名前にして、置き換える）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = None
    if path.exists():
        mode = stat_mode.S_IMODE(path.stat().st_mode)
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    try:
        with open(str(tmp), "wb") as f:
            f.write(data)
        if mode is not None:
            os.chmod(str(tmp), mode)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def revert(folder: Path, document: str, version: Optional[str] = None, back: Optional[int] = None,
           reason: Optional[str] = None, when: Optional[datetime] = None) -> Tuple[history.Record, bool]:
    """前の版に戻す。(戻した版, 中身を変えたか) を返す。今の中身がその版と同じなら、何も変えない。"""
    folder = Path(folder)
    if not history.enabled(folder):
        raise VersionError("この会社のフォルダには版の履歴（Git の形）がないため、戻せません")
    doc = resolve_document(folder, document)
    if protected(doc):
        raise VersionError(f"{doc} は戻せません（原本・公式資料・審査役の結果・設定は、ツールが入れたときの形を守ります）")
    record = pick(records(folder, doc), version, back)
    data = _content(folder, record)
    moment = (when or _now(folder)).astimezone(dates.JST)
    words = history.one_line(reason, history.REASON_MAX_CHARS) if reason and reason.strip() else ""
    # 1. まだ版にしていない変更を、先に残す（戻した後も、戻す前の中身を取り出せるように）
    history.record_scene(folder, history.TOOL, words or PENDING_REASON, when=moment)
    path = _actual_path(folder, doc)
    try:
        if path.is_file() and path.read_bytes() == data:
            return record, False
    except OSError:
        pass
    # 2. 書き戻して、戻したことを新しい版として残す
    _write_back(path, data)
    done = f"{shown(record)} の版に戻した"
    history.record_scene(folder, history.TOOL, f"{words}（{done}）" if words else done, when=moment)
    return record, True
