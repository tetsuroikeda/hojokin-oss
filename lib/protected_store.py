"""原本と公式資料を守るための、置き場所の決まり・中身の預け先・控え（TASKS M4。DESIGN 4.5・5章・10章）。

書類を整理する道具（lib/seiri.py）、公式資料を取る道具（lib/official_docs.py）、照らしと戻し（lib/originals_guard.py）が
共通に使う。

- 置き場所の決まり（allowed_place）：照らして戻してよいのは、`原本/<区分>/…` と `案件/<案件>/公式資料/…` の下だけ。
  「..」・絶対の場所・隠しファイルの名前は除く。台帳や資料の一覧は Claude も社長も直せるので（DESIGN 4.5）、
  そこに書かれた場所を信じて `.claude/`・`.hojokin/`・`.git/` や申請書に書き戻さないため（DESIGN 5章）。
- 中身の預け先（store）：置く前に、中身を版の履歴の置き場（.git）に入れる。同じ応答の中でその場のコードに
  書き換えられても、応答の終わりの照らしで戻せるようにするため（版としての記録は、応答の終わりの hook が残す）。
- 控え（`.hojokin/一時/原本の印.json`）：道具が置いた原本と公式資料ごとに、場所・入れたときのハッシュ・版の印・種類を残す。
  台帳や資料の一覧が消えたり、項目が消えたり、ハッシュが書き換えられたりしても、照らしと戻しは控えの値で続ける。
  控えは足すだけで、同じ場所の値は書き換えない（入れたときの値を残す）。
  控えにない台帳・資料の一覧の項目は、道具が置いた記録がないものとして、今の中身で確かめられたときだけ控えに採る
  （lib/originals_guard.py）。控えのファイルが消えたときは、そのことを知らせる（anchors_missing）。

ここは標準のライブラリだけで動く。版の履歴の置き場に入れるときだけ、同梱の dulwich（lib/history.py）を読み込む。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple

from lib import company
from lib.case_folder import OFFICIAL_DIR
from lib.company_init import CASES_DIR, ORIGINAL_KINDS, ORIGINALS_DIR

ORIGINAL = "原本"
OFFICIAL = "公式資料"
KINDS = (ORIGINAL, OFFICIAL)
ANCHOR_FILE = "原本の印.json"
ANCHORS_KEY = "守るもの"
ANCHOR_NOTE = ("道具が置いた原本と公式資料の、場所・入れたときのハッシュ・版の印・種類。"
               "照らしと戻し（lib/originals_guard.py）が、台帳や資料の一覧と合わせて使う。足すだけで書き換えない")
CHUNK = 1024 * 1024


class Busy(Exception):
    """ほかの処理が版の履歴を使っているところで、中身を預けられなかった。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# ---- 置き場所の決まり ----


def allowed_place(rel: object, kind: Optional[str] = None) -> bool:
    """rel が、照らして戻してよい場所か（会社のフォルダからの場所）。kind を渡すと、その種類の置き場かも確かめる。"""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return False
    parts = nfc(rel).split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return False
    is_original = len(parts) >= 3 and parts[0] == ORIGINALS_DIR and parts[1] in ORIGINAL_KINDS
    is_official = len(parts) >= 4 and parts[0] == CASES_DIR and parts[2] == OFFICIAL_DIR
    if kind == ORIGINAL:
        return is_original
    if kind == OFFICIAL:
        return is_official
    return is_original or is_official


def kind_of_place(rel: str) -> str:
    """場所から種類（原本・公式資料）を決める。決まりの外なら空。"""
    if allowed_place(rel, ORIGINAL):
        return ORIGINAL
    if allowed_place(rel, OFFICIAL):
        return OFFICIAL
    return ""


def real_place_problem(folder: Path, rel: str) -> str:
    """rel までのフォルダに別名（エイリアス）がないかを確かめる。問題がなければ空、あれば理由。

    フォルダが別名だと、書き戻しや読み取り専用にする操作が、会社のフォルダの別の場所や外に及ぶため。
    ファイルそのものが別名のときは、書き戻しで別名を置き換えるだけなので、ここでは問わない。
    """
    folder = Path(folder)
    parts = nfc(rel).split("/")
    current = folder
    for part in parts[:-1]:
        current = current / part
        if os.path.islink(str(current)):
            return f"{current.relative_to(folder).as_posix()} が別名（エイリアス）になっています"
    real_folder = os.path.realpath(str(folder))
    expected = os.path.join(real_folder, *parts[:-1])
    if nfc(os.path.realpath(str(folder.joinpath(*parts[:-1])))) != nfc(expected):
        return f"{'/'.join(parts[:-1])} が会社のフォルダの別の場所を指しています"
    return ""


# ---- 中身の預け先 ----


def blob_id(path: Path) -> str:
    """Git が中身を置くときの印（版の履歴から同じ中身を探すときに使う）。"""
    digest = hashlib.sha1(b"blob %d\x00" % os.path.getsize(str(path)))
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store(folder: Path, path: Path) -> str:
    """版の履歴があれば、path の中身を版の履歴の置き場（.git）に入れ、版の印を返す。版の履歴がなければ空。

    ほかの処理が版の履歴を使っているときは Busy（何も入れていない）。
    """
    from lib import history  # 同梱の dulwich を読み込む（使うときだけ）

    if not history.enabled(folder):
        return ""
    from dulwich.objects import Blob
    from dulwich.repo import Repo

    data = Path(path).read_bytes()
    obj = Blob.from_string(data)
    try:
        with history.locked(folder):
            repo = Repo(str(folder))
            try:
                repo.object_store.add_object(obj)
            finally:
                repo.close()
    except history.HistoryBusy as e:
        raise Busy(str(e)) from e
    return obj.id.decode("ascii")


# ---- 控え ----


def anchor_path(folder: Path) -> Path:
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / ANCHOR_FILE


ANCHOR_REL = f"{company.MARKER_DIR}/{company.TEMP_DIR}/{ANCHOR_FILE}"


def anchors_missing(folder: Path) -> bool:
    """控えのファイルがないか（先のない別名も、ないとみなす。読めないものは load_anchors の理由で知らせる）。"""
    return not os.path.exists(str(anchor_path(folder)))


def _clean_anchor(rel: object, value: object) -> Optional[dict]:
    if not isinstance(rel, str) or not isinstance(value, dict):
        return None
    kind = value.get("種類")
    digest = value.get("ハッシュ")
    blob = value.get("版の印") or ""
    if kind not in KINDS or not allowed_place(rel, kind):
        return None
    if not isinstance(digest, str) or len(digest) != 64 or not isinstance(blob, str):
        return None
    return {"ハッシュ": digest, "版の印": blob, "種類": kind}


def load_anchors(folder: Path) -> Tuple[Dict[str, dict], str]:
    """控えを読む。(場所 → {ハッシュ, 版の印, 種類}, 読めなかったときの理由)。なければ空で、理由も空。

    置き場所の決まりに合わない項目は捨てる（控えが書き換えられても、決まりの外には書き戻さない）。
    """
    path = anchor_path(folder)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as e:
        return {}, f"{ANCHOR_REL} が読めません（{type(e).__name__}）"
    raw = data.get(ANCHORS_KEY) if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}, f"{ANCHOR_REL} の形が違います"
    anchors: Dict[str, dict] = {}
    for rel, value in raw.items():
        clean = _clean_anchor(rel, value)
        if clean is not None:
            anchors[nfc(rel)] = clean
    return anchors, ""


def save_anchors(folder: Path, anchors: Dict[str, dict]) -> None:
    """控えを書く。書きかけのファイルが残らないよう、隣に書いてから置き換える。"""
    path = anchor_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".原本の印_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"説明": ANCHOR_NOTE, ANCHORS_KEY: anchors}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def remember(folder: Path, rel: str, digest: str, blob: str, kind: str) -> bool:
    """道具が置いた原本・公式資料を控えに足す。足したら True。

    同じ場所がもう控えにあれば、書き換えない（入れたときの値を残す）。版の印だけがなければ、同じハッシュのときに足す。
    控えに書けなくても、道具の処理は止めない（台帳と資料の一覧でも照らすため）。
    """
    rel = nfc(rel)
    if kind not in KINDS or not allowed_place(rel, kind):
        return False
    try:
        anchors, problem = load_anchors(folder)
        if problem and anchor_path(folder).exists():
            return False  # 読めない控えは上書きしない（照らしと戻しが知らせる）
        old = anchors.get(rel)
        if old is not None:
            if old["ハッシュ"] != digest or old["版の印"] or not blob:
                return False
            anchors[rel] = dict(old, 版の印=blob)
        else:
            anchors[rel] = {"ハッシュ": digest, "版の印": blob or "", "種類": kind}
        save_anchors(folder, anchors)
        return True
    except OSError:
        return False
