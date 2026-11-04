"""版のファイルの形（同期されるフォルダの形）の版の履歴（SPEC 共通の要件「書類の版の管理」・T0-6、DESIGN 10章
「書類の版」。TASKS M0c）。

会社のフォルダを Google ドライブ・OneDrive・Dropbox などの同期されるフォルダに置くと経営者が決めたときは、Git を
使わず、版を1つずつ丸ごとのファイルとして `記録/版/<書類>/` に残し、1件ごとの記録を添える。版のファイルは足すだけで
書き換えないので、同期で食い違いにくく、社長も前の版を Finder で見られる。
入口は lib/history.py と同じ（skill と hook は持ち方を気にしない）。lib/history.py が、版のファイルの形の会社の
フォルダ（lib/history_form.py）のときに、ここに渡す。

置き場（仮。TASKS M0c の質問）

    記録/版/
    ├─ 案件/2026_省力化（一般型）第9回/1_申請/申請書/その1.docx/    書類ごとのフォルダ（会社のフォルダからの場所のまま）
    │    ├─ 2026年11月04日 15時30分12秒 ツール 3f2a1b9.docx            版のファイル（丸ごとの写し。読み取り専用）
    │    └─ 2026年11月04日 16時02分40秒 社長 8c41d0e.docx
    └─ _版の一覧/                                                     版ごとの記録（1件1ファイル。読み取り専用）
         └─ 01730701812000000000_3f2a1b9c0d4e.json

- 版ごとの記録（Git の版に当たる）：版の印（40桁の英数字）、順、日時（日本時間。今日の日付の差し替えを含む）、
  だれ（ツール・社長）、理由、書類ごとの 書類・変更（足した・変えた・消した）・案件・段階・版のファイル・大きさ・
  中身の印（sha256）・別名か。読み返すと、Git の形と同じ履歴の1件（lib/history.py の Record）になる。
- 版の印は、Git の形と同じ40桁の英数字にする（版の道具が、同じ形で選び・示せるように）。
- 何が変わったかを速く見分けるための控え（索引。書類ごとの今の版のファイル・大きさ・時刻・中身の印）は
  `.hojokin/一時/版の記録/版のファイルの索引.json` に置く。版の履歴そのものではないので、消えても、別のパソコンに
  移しても、`_版の一覧/` から作り直す（そのときは中身の印で比べる）。
- 版のファイルは、`.hojokin/一時/版の記録/書きかけ/` に写してから置き場に移す（途中で止められても、半端な版の
  ファイルが置き場に残らない）。書きかけは、次に版を残すときに片付ける（lib/history.py の locked）。
- 錠は `.hojokin/一時/版の記録/hojokin-record.lock`（lib/history.py の locked。Git の形の錠と同じ扱い）。
- 履歴に入れないものは、Git の形と同じく会社のフォルダの .gitignore で決める。.git、.hojokin/一時/、`記録/版/` は、
  .gitignore がなくても入れない。名前は NFC にそろえて残す（実験 E5）。
- 時間の上限（budget）、次の場面に回したファイルの控え（残り.json）、版の錠が取れない場面の控え（錠待ち。
  lib/history_carry.py）、大きすぎるファイル、読めないファイル・フォルダの扱いは、Git の形と同じ。
- `記録/版/` とその中のフォルダが別名（シンボリックリンク）なら、版を残さず・読まずに断る（lib/places.py。別名の先の、
  会社のフォルダの外に書かない・外を読まないため）。版のファイルを取り出すときは、中身の印が記録と同じことを
  確かめ、違えば HistoryDamaged で断る（社長が Finder で版のファイルを開いて直してしまったときなど）。

同じ会社のフォルダを2台のパソコンから同時に使わないよう案内する（DESIGN 10章）。同時に使ったときの食い違いは、
期間中は扱わない。標準のライブラリだけで動く（/usr/bin/python3 の 3.9）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat as stat_mode
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from lib import history, history_form, places

STORE_DIR = history_form.STORE_DIR
SCENE_DIR = f"{STORE_DIR}/_版の一覧"
STATE_DIR = history.STATE_DIR
INDEX_FILE = "版のファイルの索引.json"
WORK_DIR = f"{STATE_DIR}/書きかけ"
TMP_PREFIX = "hojokin-tmp-"
FILE_MODE = 0o444
SCENE_NAME = re.compile(r"^([0-9]{20})_([0-9a-f]{12})\.json$")
VERSION_ID = re.compile(r"^[0-9a-f]{40}$")
LINK_SUFFIX = "（別名）.txt"
KINDS = (history.ADDED, history.MODIFIED, history.DELETED)

# 読んだ版ごとの記録（版ごとの記録のファイルは書き換えないので、同じ処理の中では読み直さない）
_SCENES: Dict[Tuple[str, str], dict] = {}


@dataclass
class _State:
    """今の版の控え（索引）。docs は 書類 → {版のファイル, sha256, 大きさ, 別名, 時刻（あれば）}。"""

    version: str = ""
    order: int = 0
    docs: Dict[str, dict] = field(default_factory=dict)


def _damaged(text: str) -> history.HistoryDamaged:
    return history.HistoryDamaged(text)


# ---- 置き場の確かめ ----

def check_store(folder: Path) -> None:
    """`記録/版/` とその上（`記録/`）が別名でないかを確かめる（lib/places.py）。別名なら HistoryDamaged。"""
    try:
        places.no_link_on_the_way(folder, STORE_DIR)
    except places.PlaceError as error:
        raise _damaged(
            f"{error.link} が別名（シンボリックリンク）になっているため、版を残さず、読みもしません（別名の先の、"
            "会社のフォルダの外に書かない・外を読まないため）。別名を本物のフォルダに置き換えてください") from error


def init_store(folder: Path) -> List[str]:
    """版のファイルの置き場を作る（会社のフォルダを作る道具が呼ぶ）。作ったフォルダの場所（会社のフォルダから）を返す。"""
    made = []
    for rel in (STORE_DIR, SCENE_DIR):
        path = Path(folder) / rel
        if not path.is_dir():
            places.no_link_on_the_way(folder, rel)
            path.mkdir(parents=True)
            made.append(rel + "/")
    return made


def lock_path(folder: Path) -> Path:
    """版の錠の場所（lib/history.py の locked が使う）。"""
    place = Path(folder) / STATE_DIR
    place.mkdir(parents=True, exist_ok=True)
    return place / history.LOCK_NAME


def clear_leftovers(folder: Path, min_age: float = history.LEFTOVER_SECONDS) -> List[str]:
    """途中で止まった処理が残した書きかけの版のファイルを消す（版の錠を持っている間に、lib/history.py が呼ぶ）。"""
    work = Path(folder) / WORK_DIR
    try:
        entries = list(os.scandir(str(work)))
    except OSError:
        return []
    now = time.time()
    removed = []
    for entry in entries:
        if not entry.name.startswith(TMP_PREFIX):
            continue
        try:
            if now - entry.stat(follow_symlinks=False).st_mtime < min_age:
                continue
            os.unlink(entry.path)
        except OSError:
            continue
        removed.append(f"{WORK_DIR}/{entry.name}")
    return removed


# ---- 版ごとの記録 ----

def _scene_names(folder: Path) -> List[str]:
    """版ごとの記録のファイルの名前（古い順）。同期の食い違いで増えた「…(1).json」などは数えない。"""
    try:
        names = os.listdir(str(Path(folder) / SCENE_DIR))
    except FileNotFoundError:
        return []
    return sorted(n for n in names if SCENE_NAME.match(n))


def _valid_item(item) -> bool:
    if not (isinstance(item, dict) and isinstance(item.get("書類"), str) and item.get("変更") in KINDS):
        return False
    if item["変更"] == history.DELETED:
        return True
    return (isinstance(item.get("版のファイル"), str) and isinstance(item.get("sha256"), str)
            and isinstance(item.get("大きさ"), int) and isinstance(item.get("別名"), bool))


def _scene(folder: Path, name: str) -> dict:
    key = (str(folder), name)
    cached = _SCENES.get(key)
    if cached is not None:
        return cached
    rel = f"{SCENE_DIR}/{name}"
    try:
        value = json.loads((Path(folder) / rel).read_text(encoding="utf-8"))
    except ValueError as error:
        raise _damaged(f"版ごとの記録（{rel}）が JSON として読めません（{error}）") from error
    ok = (isinstance(value, dict) and isinstance(value.get("版"), str) and VERSION_ID.match(value["版"])
          and isinstance(value.get("順"), int) and isinstance(value.get("日時"), str)
          and value.get("だれ") in history.IDENTITIES and isinstance(value.get("理由"), str)
          and isinstance(value.get("書類"), list) and all(_valid_item(i) for i in value["書類"]))
    if not ok:
        raise _damaged(f"版ごとの記録（{rel}）の形が正しくありません")
    _SCENES[key] = value
    return value


def _scenes(folder: Path) -> List[dict]:
    """版ごとの記録（古い順）。"""
    check_store(folder)
    return [_scene(folder, name) for name in _scene_names(folder)]


def _when(scene: dict) -> datetime:
    try:
        moment = datetime.fromisoformat(scene["日時"])
    except ValueError:
        moment = datetime.fromtimestamp(scene["順"] / 1e9, timezone.utc)
    return moment.astimezone(history.JST)


# ---- 今の版の控え（索引） ----

def _index_path(folder: Path) -> Path:
    return Path(folder) / STATE_DIR / INDEX_FILE


def _read_index(folder: Path) -> Optional[_State]:
    try:
        value = json.loads(_index_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(value, dict) and isinstance(value.get("版"), str) and isinstance(value.get("順"), int)
            and isinstance(value.get("書類"), dict)):
        return None
    docs = {}
    for path, entry in value["書類"].items():
        fake = {"書類": path, "変更": history.ADDED, **entry} if isinstance(entry, dict) else None
        if fake is None or not _valid_item(fake):
            return None
        docs[path] = entry
    return _State(value["版"], value["順"], docs)


def _save_index(folder: Path, state: _State) -> None:
    path = _index_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"版": state.version, "順": state.order, "書類": state.docs}, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(str(tmp), str(path))


def _entry_of(item: dict) -> dict:
    return {k: item[k] for k in ("版のファイル", "sha256", "大きさ", "別名")}


def _apply(state: _State, scene: dict) -> None:
    for item in scene["書類"]:
        if item["変更"] == history.DELETED:
            state.docs.pop(item["書類"], None)
        else:
            state.docs[item["書類"]] = _entry_of(item)
    state.version = scene["版"]
    state.order = scene["順"]


def _load_state(folder: Path) -> _State:
    """今の版の控え。控えが最後の版と合わなければ（消えた・別のパソコンから来た・途中で止まった）、作り直す。"""
    check_store(folder)
    names = _scene_names(folder)
    latest = _scene(folder, names[-1])["版"] if names else ""
    cached = _read_index(folder)
    if cached is not None and cached.version == latest:
        return cached
    state = _State()
    for name in names:
        _apply(state, _scene(folder, name))
    return state


def _dirs_of(docs) -> Set[str]:
    dirs: Set[str] = set()
    for path in docs:
        parts = path.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


# ---- 作業のファイルと比べる ----

def _skipped(rel: str) -> bool:
    return history._under_skipped_dir(rel) or rel == STORE_DIR or rel.startswith(STORE_DIR + "/")


def _sha256_of(fs_path: str, st: os.stat_result, deadline: Optional[float]) -> Optional[str]:
    """中身の印（sha256）。時間の上限を過ぎたら None。読む間に大きさが変わったら空。"""
    if stat_mode.S_ISLNK(st.st_mode):
        return hashlib.sha256(os.readlink(os.fsencode(fs_path))).hexdigest()
    digest = hashlib.sha256()
    total = 0
    with open(fs_path, "rb") as f:
        while True:
            if history._past(deadline):
                return None
            chunk = f.read(history.CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    if total != st.st_size:
        return ""
    return digest.hexdigest()


def _same_as_entry(fs_path: str, entry: dict,
                   deadline: Optional[float]) -> Tuple[Optional[bool], Optional[dict]]:
    """作業のファイルが今の版と同じか。同じで時刻だけが違うときは、時刻をそろえた控えを返す。比べきれなければ (None, None)。"""
    st = os.lstat(fs_path)
    link = stat_mode.S_ISLNK(st.st_mode)
    if link != entry["別名"] or not (link or stat_mode.S_ISREG(st.st_mode)) or st.st_size != entry["大きさ"]:
        return False, None
    if entry.get("時刻") == [st.st_mtime_ns, st.st_ctime_ns]:
        return True, None
    sha = _sha256_of(fs_path, st, deadline)
    if sha is None:
        return None, None
    if sha != entry["sha256"]:
        return False, None
    return True, {**entry, "時刻": [st.st_mtime_ns, st.st_ctime_ns]}


def _compare(folder: Path, docs: Dict[str, dict],
             deadline: Optional[float]) -> Tuple[List[history.Change], Dict[str, dict], List[str]]:
    """今の版と作業のファイルを比べる（lib/history.py の _compare と同じ決まり）。"""
    files, unreadable_dirs = history._work_files(Path(folder), None, (STORE_DIR,))
    changes: List[history.Change] = []
    refresh: Dict[str, dict] = {}
    for name in sorted(set(files) | set(docs)):
        fs_path = files.get(name)
        if name not in docs:
            changes.append(history.Change(name, history.ADDED, fs_path=fs_path))
            continue
        if fs_path is None:
            # 今の版にあって一覧にないもの。.gitignore に後から足されたものは、Git の形と同じく続けて見る
            if history._under(name, unreadable_dirs):
                changes.append(history.Change(name, history.MODIFIED, unreadable=True))
                continue
            try:
                fs_path = None if _skipped(name) else history._exists_exactly(Path(folder), name)
            except history._UnreadableDir:
                changes.append(history.Change(name, history.MODIFIED, unreadable=True))
                continue
            if fs_path is None:
                changes.append(history.Change(name, history.DELETED))
                continue
        try:
            same, fresh = _same_as_entry(fs_path, docs[name], deadline)
        except OSError as error:
            if not history._vanished(error):
                changes.append(history.Change(name, history.MODIFIED, fs_path=fs_path, unreadable=True))
            continue
        if same is None:
            changes.append(history.Change(name, history.MODIFIED, fs_path=fs_path, unsure=True))
        elif not same:
            changes.append(history.Change(name, history.MODIFIED, fs_path=fs_path))
        elif fresh is not None:
            refresh[name] = fresh
    return changes, refresh, unreadable_dirs


def pending_changes(folder: Path) -> List[history.Change]:
    """最後の版から変わったファイル（読むだけ。何も書かない）。"""
    state = _load_state(Path(folder))
    changes, _refresh, _dirs = _compare(Path(folder), state.docs, None)
    return changes


def quick_changes(folder: Path) -> Tuple[List[history.Change], Set[str]]:
    """中身の印を計算せずに比べる（lib/history.py の quick_changes）。"""
    state = _load_state(Path(folder))
    changes, _refresh, _dirs = _compare(Path(folder), state.docs, time.monotonic() - 1)
    return changes, _dirs_of(state.docs)


def tracked_documents(folder: Path) -> List[str]:
    return sorted(_load_state(Path(folder)).docs)


# ---- 版のファイルを書く ----

def _write_version(folder: Path, fs_path: str,
                   deadline: Optional[float]) -> Tuple[str, Optional[os.stat_result], Optional[dict]]:
    """作業のファイルの中身を、書きかけの置き場に写す。(結果, 読んだときの状態, 写したものの控え) を返す。

    1MB ごとに読みながら中身の印を計算する（全部をメモリに読まない）。時間の上限を過ぎたら、途中でやめる。
    作業のファイルを読む所の失敗は、結果（消えた・読めない）で返す。書きかけの置き場に書く所の失敗は、そのまま上げる。
    """
    try:
        st = os.lstat(fs_path)
        if stat_mode.S_ISLNK(st.st_mode):
            target = os.readlink(os.fsencode(fs_path))
            src = None
        else:
            src = open(fs_path, "rb")
    except OSError as error:
        return (history.VANISHED if history._vanished(error) else history.UNREADABLE), None, None
    work = Path(folder) / WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    if src is None:
        fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(work))
        with os.fdopen(fd, "wb") as out:
            out.write(target)
        return history.WROTE, st, {"tmp": tmp, "sha256": hashlib.sha256(target).hexdigest(), "大きさ": len(target),
                                   "別名": True}
    with src:
        fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(work))
        kept = False
        try:
            digest = hashlib.sha256()
            total = 0
            with os.fdopen(fd, "wb") as out:
                while total <= st.st_size:
                    if history._past(deadline):
                        return history.OUT_OF_TIME, st, None
                    try:
                        chunk = src.read(history.CHUNK_BYTES)
                    except OSError:
                        return history.UNREADABLE, st, None  # 読む途中の失敗（同期の途中など）
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                    out.write(chunk)
            if total != st.st_size:
                return history.CHANGING, st, None
            kept = True
            return history.WROTE, st, {"tmp": tmp, "sha256": digest.hexdigest(), "大きさ": total, "別名": False}
        finally:
            if not kept:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(tmp)


def _version_file(document: str, moment: datetime, who: str, version: str, link: bool) -> str:
    """版のファイルの場所（会社のフォルダから）。例：記録/版/<書類>/2026年11月04日 15時30分12秒 ツール 3f2a1b9.docx"""
    name = document.rsplit("/", 1)[-1]
    ext = LINK_SUFFIX if link else os.path.splitext(name)[1]
    m = moment
    stamp = f"{m.year:04d}年{m.month:02d}月{m.day:02d}日 {m.hour:02d}時{m.minute:02d}分{m.second:02d}秒"
    return f"{STORE_DIR}/{document}/{stamp} {who} {version[:7]}{ext}"


def _place(folder: Path, rel: str, checker: places.LinkChecker) -> Path:
    """書く場所のフォルダを用意する（途中に別名があれば HistoryDamaged）。"""
    parent = rel.rsplit("/", 1)[0]
    try:
        checker.no_link_on_the_way(parent)
    except places.PlaceError as error:
        raise _damaged(f"{error.link} が別名（シンボリックリンク）になっているため、版のファイルを書きません") from error
    os.makedirs(str(Path(folder) / parent), exist_ok=True)
    return Path(folder) / rel


def _write_scene(folder: Path, scene: dict, checker: places.LinkChecker) -> str:
    name = f"{scene['順']:020d}_{scene['版'][:12]}.json"
    rel = f"{SCENE_DIR}/{name}"
    final = _place(folder, rel, checker)
    work = Path(folder) / WORK_DIR
    work.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(work))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(scene, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, str(final))
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    _SCENES[(str(folder), name)] = scene
    return rel


def _commit(folder: Path, state: _State, who: str, reason: str, moment: datetime,
            done: List[history.Change], checker: places.LinkChecker) -> List[history.Change]:
    """写した変更を、1件の版（版ごとの記録と版のファイル）として残す。中身が今の版と同じものは、時刻だけそろえる。"""
    real: List[history.Change] = []
    for ch in sorted(done, key=lambda c: c.path):
        if ch.kind == history.DELETED:
            if ch.path in state.docs:
                real.append(ch)
            continue
        info = ch.entry
        before = state.docs.get(ch.path)
        if before is not None and before["sha256"] == info["sha256"] and before["別名"] == info["別名"]:
            # 比べた後に元の中身に戻されたなど。版にはしない
            state.docs[ch.path] = {**before, "時刻": info["時刻"]}
            continue
        real.append(ch)
    if not real:
        return []
    order = max(time.time_ns(), state.order + 1)
    version = hashlib.sha1(f"{order}:{os.getpid()}:{os.urandom(16).hex()}".encode("ascii")).hexdigest()
    items = []
    for ch in real:
        case, stage = history.case_and_stage(ch.path)
        item = {"書類": ch.path, "変更": ch.kind, "案件": case, "段階": stage}
        if ch.kind != history.DELETED:
            info = ch.entry
            rel = _version_file(ch.path, moment, who, version, info["別名"])
            final = _place(folder, rel, checker)
            os.chmod(info["tmp"], FILE_MODE)
            os.replace(info["tmp"], str(final))
            item.update({"版のファイル": rel, "大きさ": info["大きさ"], "sha256": info["sha256"], "別名": info["別名"]})
        items.append(item)
    scene = {
        "版": version,
        "順": order,
        "日時": moment.isoformat(timespec="seconds"),
        "だれ": who,
        "理由": history.one_line(reason, history.REASON_MAX_CHARS),
        "書類": items,
    }
    _write_scene(folder, scene, checker)
    _apply(state, scene)
    for ch in real:
        if ch.kind != history.DELETED:
            state.docs[ch.path]["時刻"] = ch.entry["時刻"]
    return real


def record_scene(folder: Path, who: str, reason: str, when: Optional[datetime] = None,
                 budget: Optional[float] = None, only: Optional[Sequence[str]] = None) -> history.Result:
    """最後の版から変わったファイルを、だれ・理由を付けて版に残す（lib/history.py の record_scene と同じ決まり）。

    only を渡すと、その書類だけを残す（会社のフォルダを作る道具が、前からあったファイルと用意したものを分けるため）。
    """
    from lib import history_carry

    if who not in history.IDENTITIES:
        raise ValueError(f"だれ（{who}）が分かりません")
    folder = Path(folder)
    deadline = None if budget is None else time.monotonic() + budget
    moment = (when or datetime.now(timezone.utc)).astimezone(history.JST)
    result = history.Result()
    with history.locked(folder):
        check_store(folder)
        carried = history_carry.load(folder)  # 比べる前に読む（後から書かれた控えは消さない）
        state = _load_state(folder)
        result.known_dirs = _dirs_of(state.docs)
        changes, refresh, result.unreadable_dirs = _compare(folder, state.docs, deadline)
        if only is not None:
            wanted = set(only)
            changes = [ch for ch in changes if ch.path in wanted]
        for name, fresh in refresh.items():
            state.docs[name] = fresh
        wrote = bool(refresh)
        leftovers = history.load_leftovers(folder)
        kept: Dict[str, dict] = {}
        notes = {**history_carry.attribute(changes, carried), **leftovers}  # 残り.json の控えを先にする
        checker = places.LinkChecker(folder)
        temps: List[str] = []
        try:
            for g_who, g_reason, items, earlier in history._groups(changes, notes, who, reason):
                done: List[history.Change] = []
                deferred: List[history.Change] = []
                skipped: List[history.Change] = []

                def skip(ch: history.Change, note: dict) -> None:
                    ch.unreadable = True
                    skipped.append(ch)
                    result.unreadable.append(ch)
                    kept[ch.path] = note

                for ch in sorted(items, key=lambda c: (c.kind != history.DELETED, history._size(c), c.path)):
                    if ch.kind == history.DELETED:
                        done.append(ch)
                        continue
                    note: dict = {"だれ": g_who, "理由": g_reason}
                    if ch.unreadable or ch.fs_path is None:
                        skip(ch, note)
                        continue
                    try:
                        st = os.lstat(ch.fs_path)
                    except OSError as error:
                        if not history._vanished(error):
                            skip(ch, note)
                        continue
                    if not (stat_mode.S_ISREG(st.st_mode) or stat_mode.S_ISLNK(st.st_mode)):
                        continue
                    before = leftovers.get(ch.path) or {}
                    aborts = before.get("止めた回数", 0) if before.get("大きさ") == st.st_size else 0
                    if not isinstance(aborts, int):
                        aborts = 0
                    if aborts:
                        note.update({"大きさ": st.st_size, "止めた回数": aborts})
                    if st.st_size > history.LARGE_FILE_BYTES or aborts >= history.MAX_ABORTS:
                        result.too_large.append(ch)
                        if aborts:
                            kept[ch.path] = note
                        continue
                    if not ch.unsure and history._fits(st.st_size, deadline):
                        status, written, info = _write_version(folder, ch.fs_path, deadline)
                        if status == history.WROTE:
                            temps.append(info["tmp"])
                            info["時刻"] = [written.st_mtime_ns, written.st_ctime_ns]
                            ch.entry = info
                            done.append(ch)
                            continue
                        if status == history.VANISHED:
                            continue
                        if status == history.UNREADABLE:
                            skip(ch, {"だれ": g_who, "理由": g_reason})
                            continue
                        if status == history.OUT_OF_TIME:
                            note.update({"大きさ": st.st_size, "止めた回数": aborts + 1})
                    deferred.append(ch)
                    kept[ch.path] = note
                recorded: List[history.Change] = []
                if done:
                    recorded = _commit(folder, state, g_who, g_reason, moment, done, checker)
                    wrote = True
                result.recorded += recorded
                result.deferred += deferred
                if not earlier:
                    result.mine = recorded + deferred + skipped
            if wrote:
                _save_index(folder, state)
        finally:
            for tmp in temps:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
        if kept != leftovers:
            history._save_leftovers(folder, kept)
        history_carry.consume(folder, carried)
        return result


# ---- 読む ----

def log(folder: Path, document: Optional[str] = None, limit: Optional[int] = None) -> List[history.Record]:
    """履歴を、書類ごとの1件にして新しい順に返す（lib/history.py の log と同じ形）。"""
    target = history.nfc(document) if document is not None else None
    records: List[history.Record] = []
    for scene in reversed(_scenes(Path(folder))):
        when = _when(scene)
        for item in sorted(scene["書類"], key=lambda i: i["書類"]):
            if target is not None and item["書類"] != target:
                continue
            case, stage = history.case_and_stage(item["書類"])
            records.append(history.Record(
                version=scene["版"],
                time=when,
                document=item["書類"],
                change=item["変更"],
                reason=scene["理由"],
                who=scene["だれ"],
                case=item.get("案件", case) if isinstance(item.get("案件"), str) else case,
                stage=item.get("段階", stage) if isinstance(item.get("段階"), str) else stage,
            ))
            if limit is not None and len(records) >= limit:
                return records
    return records


def read_version(folder: Path, item: dict, checker: Optional[places.LinkChecker] = None) -> bytes:
    """版のファイルの中身。記録の中身の印（sha256）と合わなければ HistoryDamaged。

    checker を渡すと、別名の確かめでフォルダの中の一覧を使い回す（多くの版のファイルを続けて読むとき）。"""
    rel = item["版のファイル"]
    parts = rel.split("/")
    if not rel.startswith(STORE_DIR + "/") or any(p in ("", ".", "..") for p in parts):
        raise _damaged(f"版のファイルの場所（{rel}）が、版の置き場（{STORE_DIR}/）の中ではありません")
    try:
        if checker is None:
            places.no_link_on_the_way(folder, rel)
        else:
            checker.no_link_on_the_way(rel)
    except places.PlaceError as error:
        raise _damaged(f"{error.link} が別名（シンボリックリンク）になっているため、版のファイル（{rel}）を読みません"
                       ) from error
    # 版のファイルの名前は、このモジュールが NFC で作る。Mac の標準のディスクは、名前の文字の形（NFC・NFD）と、
    # 大文字と小文字（大文字と小文字だけが違う書類は、同じ書類のフォルダに入る）を区別せずに開ける
    path = Path(folder) / rel
    if not path.is_file():
        raise _damaged(f"版のファイル（{rel}）が見つかりません。消されたか、移されたおそれがあります")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise _damaged(f"版のファイル（{rel}）の中身が、残したときの印（sha256）と合いません。"
                       "版のファイルが書き換えられたおそれがあります")
    return data


def _find(folder: Path, version: str) -> Tuple[List[dict], int]:
    scenes = _scenes(Path(folder))
    for i, scene in enumerate(scenes):
        if scene["版"] == version:
            return scenes, i
    raise KeyError(version)


def item_at(folder: Path, version: str, document: str) -> Optional[dict]:
    """その版のときの、その書類の版の記録（版のファイル・中身の印など）。その版になければ None。
    版がなければ KeyError（Git の形の content_at と同じ）。"""
    scenes, index = _find(folder, version)
    target = history.nfc(document)
    for scene in reversed(scenes[: index + 1]):
        for item in scene["書類"]:
            if item["書類"] == target:
                return None if item["変更"] == history.DELETED else item
    return None


def content_at(folder: Path, version: str, document: str) -> Optional[bytes]:
    """その版の、その書類の中身。その版になければ None（消した後を含む）。"""
    item = item_at(Path(folder), version, document)
    return None if item is None else read_version(Path(folder), item)


def head(folder: Path) -> Tuple[str, Dict[str, dict]]:
    """今の版の印と、書類ごとの版の記録（版のファイル・大きさ・中身の印・別名）。版がなければ ("", {})。"""
    state = _load_state(Path(folder))
    return state.version, {path: dict(entry) for path, entry in state.docs.items()}


def version_list(folder: Path) -> List[dict]:
    """新しい順の版の一覧（lib/history.py の version_list と同じ形）。"""
    rows = []
    for scene in reversed(_scenes(Path(folder))):
        items = sorted(scene["書類"], key=lambda i: i["書類"])
        changes = [history.Change(i["書類"], i["変更"]) for i in items]
        rows.append({"author": history.IDENTITIES[scene["だれ"]],
                     "message": history.format_message(scene["だれ"], scene["理由"], changes),
                     "files": [i["書類"] for i in items], "版": scene["版"]})
    return rows


def verify(folder: Path) -> List[str]:
    """版の置き場が壊れていないかを確かめる（Git の形の fsck に当たる）。見つかった問題の一覧（なければ空）。

    版ごとの記録が読めること、版のファイルがあり、読み取り専用で、中身が記録の印と同じこと。
    """
    problems = []
    try:
        scenes = _scenes(Path(folder))
    except history.HistoryDamaged as error:
        return [str(error)]
    checker = places.LinkChecker(folder)
    for scene in scenes:
        for item in scene["書類"]:
            if item["変更"] == history.DELETED:
                continue
            path = Path(folder) / item["版のファイル"]
            with contextlib.suppress(OSError):
                if stat_mode.S_IMODE(os.lstat(str(path)).st_mode) & 0o222:
                    problems.append(f"版のファイル（{item['版のファイル']}）が書き込める形になっています")
            try:
                read_version(Path(folder), item, checker)
            except (history.HistoryDamaged, OSError) as error:
                problems.append(str(error))
    return problems
