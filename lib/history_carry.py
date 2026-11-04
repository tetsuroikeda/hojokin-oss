"""版を残せなかった場面の、だれ・理由の控え（TASKS M0a。DESIGN 5章「版を自動で残す」、SPEC 共通の要件
「書類の版の管理」（だれが：ツールか社長か）、T0-6）。

同じ会社のフォルダで、ほかのセッションの hook が版を残している（版の錠を5秒より長く持つ）と、その場面では版を
残せない（lib/history.py の HistoryBusy）。版を残す処理が落ちたとき（.git に書けないなど）も同じ。変わった分を
そのまま次の場面に回すと、次の場面のだれ・理由で残ってしまう（応答の終わりに残せなかったツールの変更が、次に
送ったときや開いたときに「社長が手で変更」になり、送ったときに残せなかった社長の手直しが、応答の終わりに
「ツール」になる）。

そこで、版を残せなかった場面で、その時点で最後の版から変わっていたファイルと、その状態（種類・大きさ・時刻・
inode）を、その場面のだれ・理由とともに控える。読むだけなので錠は要らず、中身の印も計算しない（すぐ終わる）。
次に版を残す場面（どのセッションのどの場面でも）は、変わったファイルのだれ・理由を、次の順で決める。

1. 前の場面から回したファイルの控え（残り.json）にあるもの：その控えのだれ・理由（今までどおり）
2. 控えたときと状態が同じもの：いちばん古い控えのだれ・理由（その中身は、その控えのときにはもうあったため）
3. ほか（控えた後にまた変えられたものを含む）：その場面のだれ・理由

控えは `.hojokin/一時/版の記録/錠待ち/` に1件1ファイルで置く（錠を持たずに書くので、ほかの処理と書き合わない
ように。名前は書いた時刻の順）。版を残せた場面が、読んだ控えだけを消す（残しきれずに回したものは、決めた
だれ・理由で 残り.json に移る）。版の履歴には入れない（.hojokin/一時/ の中）。
Git の形でも、版のファイルの形（同期されるフォルダの形。lib/history_files.py）でも、同じ控えを使う（TASKS M0c）。
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lib import history

CARRY_DIR = f"{history.STATE_DIR}/錠待ち"
_SUFFIX = ".json"


def _carry_dir(folder: Path) -> Path:
    return Path(folder) / CARRY_DIR


def _state(ch: history.Change):
    """控えに書くファイルの状態。消したものは None。状態が分からないもの（中を読めないフォルダの中など）は False。"""
    if ch.kind == history.DELETED:
        return None
    if ch.fs_path is None:
        return False
    try:
        st = os.lstat(ch.fs_path)
    except OSError:
        return False
    return [st.st_mode, st.st_size, st.st_mtime_ns, st.st_ino]


def load(folder: Path) -> List[Tuple[str, dict]]:
    """控えの一覧（古い順。(名前, 中身)）。読めないものと形の合わないものは飛ばす。"""
    try:
        names = sorted(os.listdir(str(_carry_dir(folder))))
    except OSError:
        return []
    notes = []
    for name in names:
        if name.startswith(".") or not name.endswith(_SUFFIX):
            continue  # 書きかけ
        try:
            value = json.loads((_carry_dir(folder) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(value, dict) and value.get("だれ") in history.IDENTITIES
                and isinstance(value.get("理由"), str) and isinstance(value.get("書類"), dict)):
            continue
        notes.append((name, value))
    return notes


def attribute(changes: Sequence[history.Change], notes: Sequence[Tuple[str, dict]]) -> Dict[str, dict]:
    """変わったファイルのうち、控えたときと状態が同じもの（場所 → だれ・理由）。いちばん古い控えを使う。"""
    found: Dict[str, dict] = {}
    if not notes:
        return found
    for ch in changes:
        state = _state(ch)
        if state is False:
            continue
        for _name, note in notes:
            documents = note["書類"]
            if ch.path in documents and documents[ch.path] == state:
                found[ch.path] = {"だれ": note["だれ"], "理由": note["理由"]}
                break
    return found


def consume(folder: Path, notes: Sequence[Tuple[str, dict]]) -> None:
    """読んだ控えを消す（版を残せた場面の終わりに、lib/history.py の record_scene が呼ぶ）。"""
    for name, _note in notes:
        with contextlib.suppress(OSError):
            (_carry_dir(folder) / name).unlink()


def _write(folder: Path, value: dict) -> None:
    place = _carry_dir(folder)
    place.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{os.getpid()}{_SUFFIX}"
    tmp = place / f".{name}.tmp"
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(place / name))


def take(folder: Path, who: str, reason: str) -> Optional[history.Result]:
    """版を残せなかった場面で、最後の版から変わっていたファイルを、この場面のだれ・理由とともに控える。

    history.Result を返す（mine：この場面のだれに当たるもの。known_dirs：前の版にあったフォルダ）。応答の終わりの
    版の名前の確かめ（hooks/version_hooks.py の _found）に使う。控えられないとき（.git が読めないなど）は None。
    hook を落とさないよう、失敗はすべてここで受け止める。
    """
    try:
        earlier = load(folder)
        leftovers = history.load_leftovers(folder)
        # 中身の印を計算しない（時刻だけが変わったものも、変わったものとして控える。次の場面で中身が同じと分かれば、
        # 版にはならない）。Git の形でも版のファイルの形でも、同じ入口で読む（TASKS M0c）
        changes, known_dirs = history.quick_changes(folder)
        claimed = attribute(changes, earlier)
        mine: List[history.Change] = []
        documents: Dict[str, object] = {}
        for ch in changes:
            if ch.path in leftovers or ch.path in claimed:
                continue  # だれ・理由は、前の場面の控えで決まっている
            state = _state(ch)
            if state is not False:
                documents[ch.path] = state
            mine.append(ch)
        if documents:
            _write(folder, {"だれ": who, "理由": reason, "書類": documents})
        return history.Result(mine=mine, known_dirs=known_dirs)
    except Exception:
        return None
