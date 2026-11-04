"""書類の整理（最小限。SPEC F5、DESIGN 4.5・4.7・5章・6章。TASKS M4）。

社長から受け取った書類（原本）を、原本の置き場へ移して決まった形の名前にし、書類の台帳に残す。
答えが1つに決まる処理（ハッシュ、移す、名前を付ける、台帳に書く）だけをここで行う。
何の書類か（種類・日付・相手先・区分）を読み取るのは Claude で、道具には引数で渡す（DESIGN 6章）。

- 見つける：`入れ口/`（下のフォルダも）と、`原本/` のうち台帳にない書類を、中身のハッシュ（sha256）で見る。
  台帳の原本と同じ中身のもの、見つけた書類どうしで同じ中身のものは「同じ中身」として分ける（動かさない）。
  前に「確かめ済み」と残したものと同じ中身なら、場所や名前が変わっていても出さない
  （動かしただけ・名前を変えただけは、変わったとしない。SPEC F5）。
- 移す：`原本/<区分>/<日付>_<種類>[_<相手先>][_<補足>]<拡張子>` にする（例：「2026-10-20_見積書_〇〇機械.pdf」）。
  名前の文字は1文字の形（NFC）にそろえる（DESIGN 10章）。中身は1バイトも変えない（名前と場所だけ）。
  移した原本は読み取り専用にする（DESIGN 4.5）。同じ名前の原本があるときと、同じ中身の原本があるときは、移さない。
- 台帳（`記録/書類の台帳.json`）：原本ごとに、場所・区分・種類・日付・相手先・元の名前と場所・ハッシュ・
  版の印（Git の中身の印）・大きさ・整理した日時を残す。照らしと戻し（lib/originals_guard.py）が、このハッシュを使う。
- 版の履歴があれば、移す前に中身を版の履歴の置き場（.git）に入れておく。同じ応答の中で原本が書き換えられても、
  応答の終わりの照らしで戻せるようにするため（版としての記録は、応答の終わりの hook が「ツール」で残す）。
  移した後は、原本の控え（lib/protected_store.py）にも足す。台帳が消えたり項目が消えたりしても、照らしと戻しを続けるため。
- 控えにある原本は、台帳から項目が消えていても整理した原本として扱う（新しい書類として出さない、もう一度移さない）。
  控えに原本があるのに台帳がないときは、台帳を前の版に戻すまで整理しない（台帳にない原本を残さないため）。

ここは標準のライブラリだけで動く。版の履歴の置き場に入れるときだけ、同梱の dulwich（lib/history.py）を読み込む。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_mode
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib import case_folder, company, dates, places, protected_store
from lib.company_init import CASES_DIR, INBOX_DIR, ORIGINAL_KINDS, ORIGINALS_DIR, RECORDS_DIR, VIEW_DIR

LEDGER_FILE = "書類の台帳.json"
LEDGER_PATH = f"{RECORDS_DIR}/{LEDGER_FILE}"
ORIGINALS_KEY = "原本"
KEPT_KEY = "確かめ済み"
LEDGER_NOTE = ("書類の台帳。原本ごとの場所・種類・日付・相手先・元の名前と場所・中身のハッシュと、"
               "動かさずに確かめた書類を残す。書類を整理する道具（skills/shorui/scripts/seiri.py）が書く")
READ_ONLY = 0o444
CHUNK = 1024 * 1024
# 見つける場所（会社のフォルダからの場所の始まり）
SCAN_TOPS = (INBOX_DIR, ORIGINALS_DIR)
# 書類を持ってこない場所（ツールの置き場、案件の書類、見るだけ）
FORBIDDEN_TOPS = (".git", company.MARKER_DIR, ".claude", RECORDS_DIR, CASES_DIR, VIEW_DIR)
# 書類として扱わないもの（パソコンや Word・Excel が自動で作るファイル）
IGNORED_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
IGNORED_PREFIXES = (".", "~$")
_DATE = re.compile(r"^([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?$")
_SUFFIX = re.compile(r"^\.[0-9A-Za-z]{1,10}$")
# 名前の部分をつなぐ記号。部分の中の同じ記号は「・」にする（名前から部分を読み返せるように）
JOIN = "_"


class SeiriError(ValueError):
    """整理しなかった（台帳の形が違う、引数が足りない、同じ名前・同じ中身の原本がある など）。何も変えていない。"""


# ---- 中身の印 ----


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


git_blob_id = protected_store.blob_id  # Git が中身を置くときの印


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# ---- 台帳 ----


def ledger_path(folder: Path) -> Path:
    return Path(folder) / RECORDS_DIR / LEDGER_FILE


def empty_ledger() -> dict:
    return {"説明": LEDGER_NOTE, ORIGINALS_KEY: [], KEPT_KEY: []}


def anchored_originals(folder: Path) -> Dict[str, dict]:
    """原本の控え（lib/protected_store.py）にある原本。場所 → {ハッシュ, 版の印, 種類}。"""
    anchors, _problem = protected_store.load_anchors(folder)
    return {rel: a for rel, a in anchors.items() if a["種類"] == protected_store.ORIGINAL}


def load_ledger(folder: Path) -> dict:
    """台帳を読む。なければ空の台帳。

    読めないとき（JSON として読めない、UTF-8 でない、権限がない など）と形が違うときは SeiriError（黙って空にしない）。
    台帳がないのに原本の控えに原本があるときも SeiriError（台帳が消えた。前の版に戻すまで整理しない）。
    """
    path = ledger_path(folder)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        known = anchored_originals(folder)
        if known:
            raise SeiriError(
                f"{LEDGER_PATH} がありません（前に整理した原本が {len(known)} 件あります）。"
                "台帳を前の版に戻してから整理します（kiroku の版の道具の revert で、"
                f"{LEDGER_PATH} を消える前の版に戻す）。分からなければ社長に確かめてください")
        return empty_ledger()
    except UnicodeDecodeError as e:
        raise SeiriError(f"{LEDGER_PATH} が読めません（文字の形が UTF-8 ではありません）") from e
    except OSError as e:
        raise SeiriError(f"{LEDGER_PATH} が読めません（{type(e).__name__}）") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SeiriError(f"{LEDGER_PATH} が JSON として読めません（{e}）") from e
    if not isinstance(data, dict):
        raise SeiriError(f"{LEDGER_PATH} の形が違います（{{ }} で囲んだ形にしてください）")
    for key in (ORIGINALS_KEY, KEPT_KEY):
        value = data.setdefault(key, [])
        if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
            raise SeiriError(f"{LEDGER_PATH} の「{key}」の形が違います（一覧の形にしてください）")
    return data


def save_ledger(folder: Path, data: dict) -> None:
    """台帳を書く。書きかけのファイルが残らないよう、隣に書いてから置き換える。"""
    path = ledger_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".書類の台帳_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def originals(ledger: dict) -> List[dict]:
    return [e for e in ledger.get(ORIGINALS_KEY, []) if isinstance(e.get("場所"), str)]


# ---- 場所 ----


def _ignored(name: str) -> bool:
    return name in IGNORED_NAMES or name.startswith(IGNORED_PREFIXES) or (name.startswith(".~lock.") and name.endswith("#"))


def _rel(folder: Path, path: Path) -> str:
    return nfc(Path(os.path.relpath(str(path), str(folder))).as_posix())


def _walk_documents(folder: Path, top: str) -> List[Path]:
    """top の下の書類（ふつうのファイル。別名と、自動で作られるファイルは除く）。"""
    base = Path(folder) / top
    found: List[Path] = []
    if not base.is_dir() or base.is_symlink():
        return found
    for dirpath, dirnames, filenames in os.walk(str(base)):
        dirnames[:] = sorted(d for d in dirnames if not _ignored(d) and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            if _ignored(name):
                continue
            path = Path(dirpath) / name
            try:
                st = os.lstat(str(path))
            except OSError:
                continue
            if stat_mode.S_ISREG(st.st_mode):
                found.append(path)
    return found


def _forbidden_top(real_folder: str, top: str) -> bool:
    """会社のフォルダの直下の名前 top が、書類を持ってこない場所（FORBIDDEN_TOPS）か。

    大文字・小文字と文字の形（NFC）をそろえて比べ、さらに実際に同じフォルダを指していないかも確かめる
    （大文字・小文字や濁点の形を区別しないディスクでは、違う名前で同じフォルダを指せるため）。
    """
    key = nfc(top).casefold()
    if key in {nfc(name).casefold() for name in FORBIDDEN_TOPS}:
        return True
    given = os.path.join(real_folder, top)
    if not os.path.isdir(given):
        return False
    for name in FORBIDDEN_TOPS:
        candidate = os.path.join(real_folder, name)
        try:
            if os.path.isdir(candidate) and os.path.samefile(given, candidate):
                return True
        except OSError:
            continue
    return False


def resolve_document(folder: Path, given: str) -> Tuple[Path, str]:
    """渡された場所（会社のフォルダからの場所か、中の絶対の場所）を、(実際のファイル, 会社のフォルダからの場所) にする。

    会社のフォルダの外、ツールの置き場・案件・見るだけの中、別名、ふつうのファイルでないものは断る。
    「.」で始まる名前（`.git/`・`.hojokin/`・`.claude/` や隠しファイル）が場所のどこかにあるものも断る。
    Mac の既定のディスクは大文字と小文字を区別しないため、`.Claude/settings.json` も `.claude/settings.json` を
    指してしまう。名前の文字を比べるだけでは足りないので、「.」で始まる名前をすべて断り、始まりのフォルダも
    大文字・小文字をそろえて比べ、同じフォルダを指していないかも確かめる（DESIGN 5章）。
    """
    folder = Path(folder)
    raw = Path(given)
    path = raw if raw.is_absolute() else folder / raw
    if os.path.islink(str(path)):
        raise SeiriError(f"{given} は別名（エイリアス）です。元のファイルを指してください")
    # 別名と「..」をたどった後に、会社のフォルダの中かを確かめる（lib/places.py。会社のフォルダそのものも断る）
    try:
        rel = places.relative_inside(folder, path)
    except places.PlaceError:
        rel = "."
    if rel == ".":
        raise SeiriError(f"{given} は会社のフォルダの外です。外の書類は、社長に場所を聞いて取り込んでから整理します")
    real_folder = str(places.real(folder))
    real = os.path.join(real_folder, *rel.split("/"))
    parts = rel.split("/")
    top = parts[0]
    hidden = next((p for p in parts if p.startswith(".")), None)
    if hidden is not None:
        raise SeiriError(f"{rel} は書類を整理する場所の外です（「.」で始まる名前の {hidden} の中のもの・隠しファイルは原本にしません）")
    if _forbidden_top(real_folder, top):
        raise SeiriError(f"{rel} は書類を整理する場所の外です（{top}/ の中のものは原本にしません）")
    if not os.path.isfile(real):
        raise SeiriError(f"{rel} が見つからないか、ファイルではありません")
    return Path(real), rel


# ---- 名前 ----


def check_date(text: str) -> str:
    """名前に使う日付。「2026-10-20」「2026-10」「2026」の形だけ受け付ける（年だけの書類はカタログなど）。"""
    value = nfc(text or "").strip()
    m = _DATE.match(value)
    if not m:
        raise SeiriError(f"日付（{text}）は「2026-10-20」の形で渡してください（月まで・年までなら「2026-10」「2026」）")
    year, month, day = int(m.group(1)), m.group(2), m.group(3)
    try:
        date(year, int(month or 1), int(day or 1))
    except ValueError as e:
        raise SeiriError(f"日付（{text}）が、ない日付です") from e
    return value


def _part(text: Optional[str], what: str, required: bool = False) -> str:
    value = nfc(text or "").strip()
    if not value:
        if required:
            raise SeiriError(f"{what}を渡してください")
        return ""
    try:
        value = case_folder.safe_name(value)
    except case_folder.CaseError as e:
        raise SeiriError(f"{what}（{text}）が名前に使えません（{e}）") from e
    return value.replace(JOIN, "・")


def standard_name(kind: str, day: str, suffix: str, partner: str = "", note: str = "") -> str:
    """決まった形の名前（例：「2026-10-20_見積書_〇〇機械.pdf」）。拡張子は小文字にする。"""
    parts = [check_date(day), _part(kind, "種類", required=True)]
    for value, what in ((partner, "相手先"), (note, "補足")):
        p = _part(value, what)
        if p:
            parts.append(p)
    ext = nfc(suffix or "").lower()
    if ext and not _SUFFIX.match(ext):
        ext = ""
    name = JOIN.join(parts) + ext
    if len(name.encode("utf-8")) > 240:
        raise SeiriError(f"名前が長すぎます（{name}）。種類・相手先・補足を短くしてください")
    return name


def check_category(category: str) -> str:
    value = nfc(category or "").strip()
    if value.startswith(ORIGINALS_DIR + "/"):
        value = value[len(ORIGINALS_DIR) + 1:]
    if value not in ORIGINAL_KINDS:
        raise SeiriError(f"区分（{category}）は、次のどれかにしてください：{'・'.join(ORIGINAL_KINDS)}")
    return value


# ---- 見つける ----


@dataclass
class ScanResult:
    new: List[dict] = field(default_factory=list)  # 新しい書類（整理するもの）
    same: List[dict] = field(default_factory=list)  # 同じ中身（動かさずに知らせて聞く）
    kept: int = 0  # 前に確かめ済みとしたもの（出さない）

    def as_dict(self) -> dict:
        return {"新しい書類": self.new, "同じ中身": self.same, "確かめ済みで出さなかった数": self.kept}


def scan(folder: Path) -> ScanResult:
    """入れ口と、原本の置き場のうち台帳にない書類を、中身のハッシュで見つける。何も変えない。"""
    folder = Path(folder)
    ledger = load_ledger(folder)
    registered = {nfc(e["場所"]) for e in originals(ledger)}
    by_hash = {e.get("ハッシュ"): e for e in originals(ledger)}
    # 控えにある原本は、台帳から項目が消えていても整理した原本として扱う
    for rel, anchor in anchored_originals(folder).items():
        registered.add(rel)
        by_hash.setdefault(anchor["ハッシュ"], {"場所": rel})
    kept_hashes = {e.get("ハッシュ") for e in ledger.get(KEPT_KEY, [])}
    result = ScanResult()
    first: Dict[str, str] = {}
    for top in SCAN_TOPS:
        for path in _walk_documents(folder, top):
            rel = _rel(folder, path)
            if rel in registered:
                continue  # 整理した原本（照らすのは lib/originals_guard.py）
            try:
                digest = sha256_of(path)
                size = path.stat().st_size
            except OSError:
                continue
            if digest in kept_hashes:
                result.kept += 1
                continue
            original = by_hash.get(digest)
            if original is not None:
                result.same.append({"場所": rel, "同じ中身の書類": original["場所"], "同じ中身の書類は": "台帳の原本"})
                continue
            if digest in first:
                result.same.append({"場所": rel, "同じ中身の書類": first[digest], "同じ中身の書類は": "新しい書類"})
                continue
            first[digest] = rel
            result.new.append({"場所": rel, "大きさ": size, "形式": path.suffix.lower() or "（拡張子なし）"})
    return result


# ---- 移す ----


def _store_blob(folder: Path, path: Path) -> bool:
    """版の履歴があれば、中身を版の履歴の置き場（.git）に入れる。入れたら True。"""
    try:
        return bool(protected_store.store(folder, path))
    except protected_store.Busy as e:
        raise SeiriError("ほかの処理が版の履歴を使っているところです。移していません。少し待ってから、もう一度動かしてください") from e


def _move_without_overwrite(src: Path, dest: Path) -> None:
    """dest がなければ、src を dest に移す。あれば FileExistsError（上書きしない）。"""
    try:
        os.link(str(src), str(dest))
    except FileExistsError:
        raise
    except OSError:
        # 硬いリンクを作れないディスク（外付けの一部など）。直前に確かめてから移す
        if os.path.lexists(str(dest)):
            raise FileExistsError(str(dest))
        os.rename(str(src), str(dest))
        return
    try:
        os.unlink(str(src))
    except OSError:
        # 元の場所から消せない（フォルダが書き込めない など）。原本の置き場に作った分を消して、移さなかったことにする
        os.unlink(str(dest))
        raise


def _next_id(ledger: dict) -> str:
    numbers = []
    for e in originals(ledger):
        m = re.match(r"^原本-([0-9]+)$", str(e.get("id", "")))
        if m:
            numbers.append(int(m.group(1)))
    return f"原本-{max(numbers, default=0) + 1:04d}"


def organize(folder: Path, given: str, category: str, kind: str, day: str,
             partner: str = "", note: str = "") -> dict:
    """1つの書類を原本の置き場へ移し、決まった形の名前にして、台帳に残す。台帳の1件を返す。

    移さないとき（同じ名前・同じ中身の原本がある、引数が違う など）は SeiriError で、何も変えていない。
    """
    folder = Path(folder)
    ledger = load_ledger(folder)
    src, rel = resolve_document(folder, given)
    registered = {nfc(e["場所"]): e for e in originals(ledger)}
    anchored = anchored_originals(folder)
    if rel in registered or rel in anchored:
        raise SeiriError(f"{rel} は、もう整理した原本です")
    category = check_category(category)
    name = standard_name(kind, day, src.suffix, partner, note)
    dest_rel = f"{ORIGINALS_DIR}/{category}/{name}"
    digest = sha256_of(src)
    known = [(e["場所"], e.get("ハッシュ")) for e in originals(ledger)] + [(p, a["ハッシュ"]) for p, a in anchored.items()]
    for place, known_digest in known:
        if known_digest == digest:
            raise SeiriError(
                f"{rel} は、原本の {place} と同じ中身です。移していません。1つにまとめるかを社長に確かめてください")
    dest = folder / ORIGINALS_DIR / category / name
    if os.path.lexists(str(dest)) or dest_rel in anchored:
        raise SeiriError(
            f"同じ名前の原本（{dest_rel}）がもうあります（中身は違います）。移していません。"
            "見分ける言葉（機械の名前、何通目か など）を補足（--note）に入れて、もう一度動かしてください")
    size = src.stat().st_size
    blob = git_blob_id(src)
    _store_blob(folder, src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _move_without_overwrite(src, dest)
    except FileExistsError as e:
        raise SeiriError(f"{dest_rel} という名前の原本がもうあります。移していません") from e
    os.chmod(str(dest), READ_ONLY)
    entry = {
        "id": _next_id(ledger),
        "場所": dest_rel,
        "区分": category,
        "種類": _part(kind, "種類", required=True),
        "日付": check_date(day),
        "相手先": _part(partner, "相手先"),
        "補足": _part(note, "補足"),
        "元の名前": nfc(src.name),
        "元の場所": rel,
        "ハッシュ": digest,
        "版の印": blob,
        "大きさ": size,
        "整理した日時": dates.now(folder).isoformat(timespec="seconds"),
    }
    ledger[ORIGINALS_KEY] = originals(ledger) + [entry]
    # 確かめ済みにしていた同じ中身のものは、整理したので外す
    ledger[KEPT_KEY] = [e for e in ledger.get(KEPT_KEY, []) if e.get("ハッシュ") != digest]
    try:
        save_ledger(folder, ledger)
    except OSError:
        # 台帳に書けなければ、元に戻す（台帳にない原本を残さない）
        os.chmod(str(dest), stat_mode.S_IMODE(os.lstat(str(dest)).st_mode) | 0o200)
        os.rename(str(dest), str(src))
        raise
    # 原本の控えにも足す（台帳が消えたり項目が消えたりしても、照らしと戻しを続けるため）
    protected_store.remember(folder, dest_rel, digest, blob, protected_store.ORIGINAL)
    return entry


def keep(folder: Path, given: str, reason: str) -> dict:
    """動かさずに確かめた書類（何の書類か分からない、社長が動かさないと答えた など）として台帳に残す。"""
    folder = Path(folder)
    ledger = load_ledger(folder)
    src, rel = resolve_document(folder, given)
    if rel in {nfc(e["場所"]) for e in originals(ledger)} or rel in anchored_originals(folder):
        raise SeiriError(f"{rel} は、もう整理した原本です")
    digest = sha256_of(src)
    entry = {
        "場所": rel,
        "ハッシュ": digest,
        "理由": nfc(reason or "").strip() or "社長に確かめて、動かさないことにした",
        "確かめた日時": dates.now(folder).isoformat(timespec="seconds"),
    }
    others = [e for e in ledger.get(KEPT_KEY, []) if e.get("場所") != rel and e.get("ハッシュ") != digest]
    ledger[KEPT_KEY] = others + [entry]
    save_ledger(folder, ledger)
    return entry


# ---- 中身を読む（Claude が種類・日付・相手先を読み取るため） ----

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".heic", ".gif", ".tif", ".tiff", ".bmp", ".webp")


def text_of(folder: Path, given: str, limit: int = 4000) -> str:
    """書類の文字（PDF はページごと、Word は本文、Excel はシートごと）。写真と、文字のない PDF は案内を返す。"""
    from lib import doc_text  # 同梱の pypdf を使う（PDF のときだけ読み込まれる）

    path, rel = resolve_document(folder, given)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return f"{rel} は写真・画像です。Read で開いて、写っている書類を見てください。"
    try:
        if suffix in doc_text.PDF_SUFFIXES:
            pages = doc_text.pdf_pages(path)
            if not any(p.strip() for p in pages):
                return f"{rel} は文字のない PDF（スキャンしたものなど）です。Read で開いて、ページの画像を見てください。"
            text = "\n".join(f"--- {i} ページ ---\n{p.strip()}" for i, p in enumerate(pages, 1))
        elif suffix in doc_text.WORD_SUFFIXES:
            text = doc_text.word_text(path)
        elif suffix in doc_text.EXCEL_SUFFIXES:
            text = "\n".join(f"--- シート {name} ---\n{body.strip()}" for name, body in doc_text.excel_sheets(path))
        else:
            return f"{rel} は、この道具で文字にできない形です。Read で開けるか試し、分からなければ社長に聞いてください。"
    except doc_text.TextError as e:
        return f"{rel} を文字にできませんでした（{e}）。Read で開いて見てください。"
    text = text.strip()
    if len(text) > limit:
        text = text[:limit] + f"\n…（ここまで。全体は {len(text)} 字）"
    return text or f"{rel} には文字がありません。Read で開いて見てください。"
