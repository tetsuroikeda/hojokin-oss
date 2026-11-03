"""見るだけ（SPEC 共通の要件「書類の版の管理」、DESIGN 4.5・4.7・10章。TASKS M0b）。

前の版や提出版を、会社のフォルダの `見るだけ/` に読み取り専用で出す。作業のファイルは増やさない。
- `見るだけ/` は会社のフォルダの .gitignore にあり、版の履歴に入らない（lib/company_init.py）。
- 出したファイルは読み取り専用（0o444）にし、`見るだけ/` とその中のフォルダも書き込めない形（0o555）にする
  （社長が誤って直したり、作業のファイルをここに置いたりしないように。Word・Excel は読み取り専用で開く）。
- 出したものは `.hojokin/一時/見るだけ/出したもの.json` に控える（場所と中身の印 sha256。版の履歴に入れない）。
- 次に開いたとき（SessionStart の startup・resume・clear）に片付ける。compact では片付けない（同じセッションの
  途中で、社長が見ているものを消さないため）。
  消すのは、控えにあり、中身が控えと同じものだけ。ほかのもの（社長が置いたもの、書き換えられたもの、別名）は
  消さずに残し、Claude に伝える（`見るだけ/` は版の履歴に入らないので、消すと取り戻せないため）。
- 版の履歴は読まない。Git の形でも、同期されるフォルダの形（M0c）でも同じに動く。

片付けは hook の中で動くので、どんな失敗でも例外を外に出さない（hook が落ちると、run.sh が
「Python が動かない」とみなし、書き込みと Bash を拒んでしまうため）。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from lib import company
from lib.company_init import VIEW_DIR

STATE_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/見るだけ"
STATE_FILE = "出したもの.json"
FILE_MODE = 0o444
DIR_MODE = 0o555
OPEN_DIR_MODE = 0o755
# 片付ける場面（version_hooks.RECORDED_SOURCES と同じ。source のない入力も片付ける）
CLEANUP_SOURCES = ("startup", "resume", "clear")
NOTE_LIST_MAX = 5


class ViewError(Exception):
    """見るだけに出せなかった。"""


def root(folder: Path) -> Path:
    return Path(folder) / VIEW_DIR


def _state_path(folder: Path) -> Path:
    return Path(folder) / STATE_DIR / STATE_FILE


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as f:
        while True:
            chunk = f.read(1024 ** 2)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ---- 出したものの控え ----

def load_exports(folder: Path) -> Dict[str, str]:
    """出したものの控え（`見るだけ/` からの場所 → sha256）。読めなければ空。"""
    try:
        value = json.loads(_state_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = value.get("出したもの") if isinstance(value, dict) else None
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}


def _save_exports(folder: Path, exports: Dict[str, str]) -> None:
    path = _state_path(folder)
    if not exports:
        try:
            path.unlink()
        except OSError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"出したもの": exports}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(path))


# ---- 書き込めるようにする・閉じる ----

def _open_dirs(top: Path) -> None:
    """top とその中のフォルダを、書き込める形にする（別名はたどらない）。"""
    if not top.is_dir() or top.is_symlink():
        return
    try:
        os.chmod(str(top), OPEN_DIR_MODE)
    except OSError:
        pass
    for dirpath, dirnames, _filenames in os.walk(str(top)):
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            try:
                os.chmod(full, OPEN_DIR_MODE)
            except OSError:
                pass


def _seal_dirs(top: Path) -> None:
    """top とその中のフォルダを、書き込めない形にする（下から順に）。"""
    if not top.is_dir() or top.is_symlink():
        return
    dirs = []
    for dirpath, dirnames, _filenames in os.walk(str(top)):
        dirs += [os.path.join(dirpath, n) for n in dirnames if not os.path.islink(os.path.join(dirpath, n))]
    for d in sorted(dirs, key=len, reverse=True) + [str(top)]:
        try:
            os.chmod(d, DIR_MODE)
        except OSError:
            pass


def _write_readonly(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(str(path.parent), OPEN_DIR_MODE)
    with open(str(path), "wb") as f:
        f.write(data)
    os.chmod(str(path), FILE_MODE)


def _same_file(path: Path, sha: str) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and sha256_file(path) == sha
    except OSError:
        return False


def _check_root(top: Path) -> None:
    """`見るだけ/` が別名やファイルになっていれば断る（別名の先の、会社のフォルダの外に書かないため）。"""
    if top.is_symlink() or (os.path.lexists(str(top)) and not top.is_dir()):
        raise ViewError(f"{VIEW_DIR} がフォルダでない（別名かファイルになっている）ため、出せません。"
                        f"{VIEW_DIR} を別の場所に移してから、もう一度試してください")


def _numbered(name: str, n: int, is_dir: bool) -> str:
    if is_dir:
        return f"{name}・{n}"
    stem, ext = os.path.splitext(name)
    return f"{stem}・{n}{ext}"


# ---- 出す ----

def export_file(folder: Path, names: Sequence[str], data: bytes) -> str:
    """1つのファイルを `見るだけ/` の直下に読み取り専用で出す。会社のフォルダからの場所を返す。

    names は名前の候補（先のものから使う）。同じ名前で中身の違うものがあれば、次の候補か「・2」を付けた名前にする。
    同じ名前で中身も同じもの（同じセッションでもう出したもの）があれば、それをそのまま使う。
    """
    folder = Path(folder)
    top = root(folder)
    _check_root(top)
    sha = sha256_bytes(data)
    exports = load_exports(folder)
    candidates = list(names) + [_numbered(names[-1], n, False) for n in range(2, 100)]
    _open_dirs(top)
    try:
        top.mkdir(exist_ok=True)
        os.chmod(str(top), OPEN_DIR_MODE)
        for name in candidates:
            path = top / name
            if os.path.lexists(str(path)):
                if exports.get(name) == sha and _same_file(path, sha):
                    return f"{VIEW_DIR}/{name}"
                continue
            _write_readonly(path, data)
            exports[name] = sha
            _save_exports(folder, exports)
            return f"{VIEW_DIR}/{name}"
        raise ViewError("見るだけ/ に、同じ名前のファイルが多すぎます")
    finally:
        _seal_dirs(top)


def export_tree(folder: Path, dir_name: str, items: Sequence[Tuple[str, bytes]]) -> Tuple[str, List[str]]:
    """いくつかのファイルを `見るだけ/<dir_name>/` に読み取り専用で出す。(フォルダの場所, ファイルの場所の一覧) を返す。

    items は (フォルダの中の場所（「/」区切り）, 中身)。同じ名前のフォルダがあり、中身がすべて同じなら、それを使う。
    違えば「・2」を付けた名前のフォルダにする。場所はどれも会社のフォルダから。
    """
    folder = Path(folder)
    top = root(folder)
    _check_root(top)
    exports = load_exports(folder)
    wanted = {rel: sha256_bytes(data) for rel, data in items}
    for rel in wanted:
        parts = rel.split("/")
        if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
            raise ViewError(f"見るだけに出す場所が正しくありません（{rel}）")
    _open_dirs(top)
    try:
        top.mkdir(exist_ok=True)
        os.chmod(str(top), OPEN_DIR_MODE)
        for name in [dir_name] + [_numbered(dir_name, n, True) for n in range(2, 100)]:
            base = top / name
            if os.path.lexists(str(base)):
                if _tree_matches(base, name, wanted, exports):
                    return f"{VIEW_DIR}/{name}", [f"{VIEW_DIR}/{name}/{rel}" for rel in sorted(wanted)]
                continue
            for rel, data in items:
                _write_readonly(base / rel, data)
                exports[f"{name}/{rel}"] = wanted[rel]
            _save_exports(folder, exports)
            return f"{VIEW_DIR}/{name}", [f"{VIEW_DIR}/{name}/{rel}" for rel in sorted(wanted)]
        raise ViewError("見るだけ/ に、同じ名前のフォルダが多すぎます")
    finally:
        _seal_dirs(top)


def _tree_matches(base: Path, name: str, wanted: Dict[str, str], exports: Dict[str, str]) -> bool:
    if not base.is_dir() or base.is_symlink():
        return False
    found = set()
    for dirpath, _dirnames, filenames in os.walk(str(base)):
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), str(base)).replace(os.sep, "/")
            found.add(rel)
    if found != set(wanted):
        return False
    return all(exports.get(f"{name}/{rel}") == sha and _same_file(base / rel, sha) for rel, sha in wanted.items())


# ---- 片付ける（開いたとき） ----

def cleanup(folder: Path) -> List[str]:
    """`見るだけ/` を片付ける。消さずに残したもの（会社のフォルダからの場所）を返す。

    控えにあり中身が同じファイルだけを消し、空になったフォルダを消す。`見るだけ/` が空になれば、それも消す。
    残したものがあるフォルダは、社長が動かせるよう書き込める形のままにする。
    """
    folder = Path(folder)
    top = root(folder)
    exports = load_exports(folder)
    if top.is_symlink() or (os.path.lexists(str(top)) and not top.is_dir()):
        # 別名やファイルになっていたら、触らない
        _save_exports(folder, {})
        return [VIEW_DIR]
    if not top.is_dir():
        _save_exports(folder, {})
        return []
    _open_dirs(top)
    kept: List[str] = []
    for dirpath, dirnames, filenames in os.walk(str(top)):
        for name in list(dirnames):
            if os.path.islink(os.path.join(dirpath, name)):
                kept.append(_rel(top, os.path.join(dirpath, name)))
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = _rel(top, full)
            sha = exports.get(rel)
            if sha is not None and not os.path.islink(full) and _same_file(Path(full), sha):
                try:
                    os.unlink(full)
                    continue
                except OSError:
                    pass
            kept.append(rel)
    # 空になったフォルダを、下から消す
    dirs = []
    for dirpath, dirnames, _filenames in os.walk(str(top)):
        dirs += [os.path.join(dirpath, n) for n in dirnames if not os.path.islink(os.path.join(dirpath, n))]
    for d in sorted(dirs, key=len, reverse=True) + [str(top)]:
        try:
            os.rmdir(d)
        except OSError:
            pass
    _save_exports(folder, {})
    return [f"{VIEW_DIR}/{rel}" for rel in sorted(kept)]


def _rel(top: Path, full: str) -> str:
    return os.path.relpath(full, str(top)).replace(os.sep, "/")


def cleanup_note(kept: List[str]) -> str:
    names = "、".join(kept[:NOTE_LIST_MAX]) + (f"（ほか{len(kept) - NOTE_LIST_MAX}件）"
                                                if len(kept) > NOTE_LIST_MAX else "")
    return (
        f"【hojokin】{VIEW_DIR}/ に、ツールが出したものでないファイル（社長が置いたもの、書き換えられたものなど）が"
        f"あったので、消さずに残しました：{names}。{VIEW_DIR}/ は開くたびに片付ける場所で、版の履歴にも残りません。"
        "要るものなら、別の場所（書類なら入れ口/）に移すよう、社長の最初の発言に答えるときに伝えてください。"
    )


def session_start(data: dict, folder: Path, output: Optional[dict]) -> Optional[dict]:
    """SessionStart の入口。開いたとき（compact のほか）に `見るだけ/` を片付け、残したものがあれば
    output の additionalContext に足して返す（ほかの処理が渡す情報は消さない）。例外は外に出さない。"""
    source = data.get("source") if isinstance(data, dict) else None
    if source is not None and source not in CLEANUP_SOURCES:
        return output
    try:
        kept = cleanup(folder)
        note = cleanup_note(kept) if kept else ""
    except Exception as error:  # 片付けで落ちても、hook は落とさない
        note = (f"【hojokin】{VIEW_DIR}/ を片付けられませんでした（{type(error).__name__}: {error}）。"
                "次に開いたときに、また片付けます。")
    if not note:
        return output
    return add_context(output, note)


def add_context(output: Optional[dict], note: str) -> dict:
    """SessionStart の出力に、Claude に渡す一言を足す。"""
    result = dict(output or {})
    hso = dict(result.get("hookSpecificOutput") or {"hookEventName": "SessionStart"})
    current = hso.get("additionalContext")
    hso["additionalContext"] = f"{current}\n{note}" if isinstance(current, str) and current else note
    result["hookSpecificOutput"] = hso
    return result
