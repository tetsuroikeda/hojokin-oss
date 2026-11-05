"""原本から写しを作る（SPEC F5「案件で使う書類は、原本から写しを作り、提出するファイルの決まりに合わせて整える」、
DESIGN 4.5・6章・14章。TASKS B10。T5-5・T5-6）。

- 写しは `案件/<案件>/<段階>/添付する書類/` に置く（効果報告は `<段階>/1年目/` の下も）。原本は読むだけで、1バイトも変えない。
- 整える範囲は、制度データの「提出するファイルの決まり」と、その書類の「形式」が求める所まで（DESIGN 14章）。
  - 形式：原本の形が決まりの形にないときは PDF にする（JPEG は道具が PDF に包む。Word・Excel・PNG などは LibreOffice）。
  - 結合：2つ以上の原本を1つの写しにするときは、PDF にしてからつなぐ（同梱の pypdf）。
  - 容量：決まりに上限があれば照らし、超えるときは知らせる（画像を縮める道具はないので、縮めない）。
  - 名前：決まりに名前の決まりがあれば、写しの名前（--name）でそろえるよう知らせる。なければ、原本の名前に、写しの形の拡張子。
- 書類の台帳（`記録/書類の台帳.json`）の「写し」に、写しの場所・案件・段階・書類の名前・元の原本（id・場所・ハッシュ・日付）・
  中身のハッシュ・整え方・作った日時を残す。写しの中身は、作り直すたびにその場で直す（前の版は版の履歴に残る）。
- 原本が新しくなったとき（同じ区分・種類・相手先で、日付の新しい原本が入ったとき）は、古い原本から作った写しがある
  案件を見つけ（stale）、作り直す（remake）。古い原本は消さない（提出版と照らし合わせるため）。

標準のライブラリと、同梱の pypdf（結合のときだけ）を使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib import case_folder, company, dates, place_text, places, seiri
from lib.company_init import CASES_DIR

COPIES_KEY = "写し"
ATTACH_DIR = "添付する書類"
PDF = ".pdf"
JPEG_SUFFIXES = (".jpg", ".jpeg")
# 決まりの文に出る形の言葉 → 拡張子
FORMAT_WORDS = (
    (r"PDF|ＰＤＦ|pdf", (".pdf",)),
    (r"Excel|エクセル|xlsx?|ｘｌｓ", (".xlsx", ".xls")),
    (r"Word|ワード|docx?", (".docx", ".doc")),
    (r"JPE?G|jpe?g|ＪＰＥＧ", (".jpg", ".jpeg")),
    (r"PNG|png|ＰＮＧ", (".png",)),
    (r"zip|ZIP", (".zip",)),
    (r"画像", (".jpg", ".jpeg", ".png")),
)
_SIZE = re.compile(r"([0-9０-９]+(?:\.[0-9]+)?)\s*(MB|ＭＢ|メガ|KB|ＫＢ|キロ)")
LO_TIMEOUT = 180


class UtsushiError(ValueError):
    """写しを作らなかった（原本でない、案件や段階がない、形にできない など）。何も変えていない。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


# ---- 制度データの決まり ----


def _value(node) -> object:
    if isinstance(node, dict):
        return node.get("値")
    return node


def file_rules(seido: Optional[dict]) -> Dict[str, object]:
    """制度データの「提出するファイルの決まり」（形式・容量・名前）。読み取れない値は None。"""
    rules = (seido or {}).get("提出するファイルの決まり") or {}
    out = {}
    for key in ("形式", "容量", "名前"):
        value = _value(rules.get(key))
        out[key] = value if value not in ("", None) else None
    return out


def suffixes_in(text: object) -> List[str]:
    """決まりの文（「PDF・JPEG・PNG」など）に出る形を、拡張子の一覧にする。"""
    found: List[str] = []
    for pattern, suffixes in FORMAT_WORDS:
        if re.search(pattern, str(text or "")):
            found += [s for s in suffixes if s not in found]
    return found


def size_limit(text: object) -> Optional[int]:
    """容量の決まりの文から、上限のバイト数（読めなければ None）。"""
    m = _SIZE.search(nfc(str(text or "")).replace("，", ","))
    if not m:
        return None
    number = float(unicodedata.normalize("NFKC", m.group(1)))
    unit = unicodedata.normalize("NFKC", m.group(2)).upper()
    return int(number * (1024 * 1024 if unit in ("MB", "メガ") else 1024))


def document_entry(seido: Optional[dict], name: str) -> Optional[dict]:
    """制度データの「書類」から、名前の合う1件（同じ名前を先に、なければ名前を含むもの）。"""
    name = nfc(name).strip()
    if not name:
        return None
    docs = [d for d in (seido or {}).get("書類") or [] if isinstance(d, dict) and d.get("名前")]
    for d in docs:
        if nfc(d["名前"]) == name:
            return d
    for d in docs:
        if name in nfc(d["名前"]) or nfc(d["名前"]) in name:
            return d
    return None


def copy_suffix(original_suffixes: List[str], doc: Optional[dict], rules: Dict[str, object]) -> str:
    """写しの形の拡張子。書類の形式（なければ決まりの形式）に、原本の形が入っていればそのまま、なければ PDF。
    結合するとき（原本が2つ以上）は PDF。決まりがなければ、原本の形のまま。"""
    if len(original_suffixes) > 1:
        return PDF
    suffix = original_suffixes[0].lower()
    wanted = suffixes_in((doc or {}).get("形式")) or suffixes_in(rules.get("形式"))
    if not wanted or suffix in wanted:
        return suffix
    return PDF


# ---- PDF にする ----


def _jpeg_size(data: bytes) -> Tuple[int, int, int]:
    """JPEG の幅・高さ・色の数（SOF の区切りから読む）。"""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height, data[i + 9]
        i += 2 + length
    raise UtsushiError("JPEG の大きさを読めませんでした（壊れているか、JPEG ではありません）")


def jpeg_to_pdf(data: bytes) -> bytes:
    """JPEG を、A4 に収まる1ページの PDF に包む（画像は変えない。中身は JPEG のバイトのまま）。"""
    width, height, comps = _jpeg_size(data)
    color = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(comps, "/DeviceRGB")
    page_w, page_h = 595.28, 841.89  # A4（ポイント）
    if width > height:
        page_w, page_h = page_h, page_w
    scale = min(page_w / width, page_h / height)
    draw_w, draw_h = width * scale, height * scale
    x, y = (page_w - draw_w) / 2, (page_h - draw_h) / 2
    content = f"q {draw_w:.2f} 0 0 {draw_h:.2f} {x:.2f} {y:.2f} cm /Im0 Do Q".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.2f} {page_h:.2f}] "
         "/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>").encode("ascii"),
        (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace {color} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n").encode("ascii") + data
        + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return out.getvalue()


def _libreoffice_pdf(src: Path, work: Path) -> bytes:
    """Word・Excel・PNG などを、LibreOffice で PDF にする（利用者の設定は一時の場所に作る。lib/libreoffice.py）。"""
    from lib import libreoffice

    soffice = libreoffice.find_soffice()
    if not soffice:
        raise UtsushiError(f"{src.name} を PDF にするための LibreOffice が見つかりません。"
                           "LibreOffice を入れるか、社長に PDF に保存してもらってください")
    inbox, outbox, profile = work / "in", work / "out", work / "profile"
    for d in (inbox, outbox):
        d.mkdir(parents=True, exist_ok=True)
    libreoffice.write_profile(profile)
    copy = inbox / f"doc{src.suffix.lower()}"
    shutil.copyfile(str(src), str(copy))
    cmd = [soffice, f"-env:UserInstallation={profile.resolve().as_uri()}", "--headless", "--norestore", "--nologo",
           "--nodefault", "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outbox), str(copy)]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=LO_TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise UtsushiError(f"LibreOffice が {LO_TIMEOUT} 秒たっても終わりませんでした（{src.name}）") from e
    except OSError as e:
        raise UtsushiError(f"LibreOffice を動かせませんでした（{e}）") from e
    out = outbox / "doc.pdf"
    if r.returncode != 0 or not out.is_file():
        raise UtsushiError(f"{src.name} を PDF にできませんでした（LibreOffice の終了コード {r.returncode}）")
    return out.read_bytes()


def to_pdf(src: Path, work: Path) -> bytes:
    suffix = src.suffix.lower()
    if suffix == PDF:
        return src.read_bytes()
    if suffix in JPEG_SUFFIXES:
        return jpeg_to_pdf(src.read_bytes())
    return _libreoffice_pdf(src, work)


def merge_pdfs(parts: List[bytes]) -> bytes:
    from lib import doc_text  # noqa: F401  同梱の pypdf を読めるようにする（lib/vendor/）
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for data in parts:
        for page in PdfReader(io.BytesIO(data)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---- 場所 ----


def attach_dir(folder: Path, case: str, stage: str) -> str:
    """写しの置き場（会社のフォルダからの場所）。案件と段階のフォルダがなければ UtsushiError。"""
    case = nfc(case).strip()
    stage = nfc(stage).strip().strip("/")
    if not case or not stage or ".." in case.split("/") + stage.split("/"):
        raise UtsushiError("案件と段階（例：1_申請）を渡してください")
    try:
        case_folder.safe_name(case)
    except case_folder.CaseError as e:
        raise UtsushiError(f"案件の名前（{case}）が使えません（{e}）") from e
    stage_rel = f"{CASES_DIR}/{case}/{stage}"
    if not (Path(folder) / stage_rel).is_dir():
        raise UtsushiError(f"段階のフォルダ（{stage_rel}）がありません。案件と段階の名前を確かめてください")
    return f"{stage_rel}/{ATTACH_DIR}"


def _seido_for(folder: Path, case: str) -> Optional[dict]:
    try:
        from lib import seido_data
        _path, data = seido_data.load_data(Path(folder), case)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ---- 写しを作る ----


def _original(ledger: dict, given: str) -> dict:
    given = nfc(given).strip()
    for e in seiri.originals(ledger):
        if given in (e.get("id"), nfc(e["場所"])):
            return e
    raise UtsushiError(f"{given} は、書類の台帳の原本ではありません。先に shorui の organize で原本の置き場へ移してください")


def copies(ledger: dict) -> List[dict]:
    return [e for e in ledger.get(COPIES_KEY, []) if isinstance(e, dict) and isinstance(e.get("場所"), str)]


def _next_id(ledger: dict) -> str:
    numbers = [int(m.group(1)) for m in (re.match(r"^写し-([0-9]+)$", str(e.get("id", ""))) for e in copies(ledger)) if m]
    return f"写し-{max(numbers, default=0) + 1:04d}"


def _build(folder: Path, sources: List[dict], suffix: str) -> Tuple[bytes, List[str]]:
    """原本から写しの中身を作る。（中身、整え方）。原本は読むだけ。"""
    paths = [Path(folder) / e["場所"] for e in sources]
    for p, e in zip(paths, sources):
        if seiri.sha256_of(p) != e.get("ハッシュ"):
            raise UtsushiError(f"原本（{e['場所']}）の中身が、台帳のハッシュと合いません。写しを作っていません")
    done: List[str] = []
    if suffix != PDF:
        return paths[0].read_bytes(), ["原本の形のまま写した"]
    work = Path(tempfile.mkdtemp(prefix="写し_", dir=str(_temp_dir(folder))))
    try:
        parts = []
        for p in paths:
            parts.append(to_pdf(p, work / str(len(parts))))
            if p.suffix.lower() != PDF:
                done.append(f"{p.name} を PDF にした")
        if len(parts) > 1:
            data = merge_pdfs(parts)
            done.append(f"{len(parts)}つの原本を1つの PDF にした")
        else:
            data = parts[0]
            if not done:
                done.append("原本の形のまま写した")
        return data, done
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def _temp_dir(folder: Path) -> Path:
    path = Path(folder) / company.MARKER_DIR / company.TEMP_DIR / "写し"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(folder: Path, rel: str, data: bytes) -> None:
    problem = place_text.write_problem(folder, rel, f"写し（{rel}）を書いていません")
    if problem:
        raise UtsushiError(problem)
    path = Path(folder) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(path))


def make(folder: Path, given: List[str], case: str, stage: str, document: str = "", name: str = "") -> dict:
    """原本（1つか、つなぐときは2つ以上）から写しを作り、台帳に残す。台帳の1件（と知らせ）を返す。"""
    folder = Path(folder)
    if not given:
        raise UtsushiError("写しの元にする原本を、--original で渡してください")
    ledger = seiri.load_ledger(folder)
    sources = [_original(ledger, g) for g in given]
    attach = attach_dir(folder, case, stage)
    seido = _seido_for(folder, case)
    rules = file_rules(seido)
    doc = document_entry(seido, document or sources[0].get("種類", ""))
    suffix = copy_suffix([Path(e["場所"]).suffix for e in sources], doc, rules)
    base = nfc(name).strip() or Path(sources[0]["場所"]).stem
    try:
        base = case_folder.safe_name(Path(base).stem if Path(base).suffix.lower() == suffix else base)
    except case_folder.CaseError as e:
        raise UtsushiError(f"写しの名前（{name}）が使えません（{e}）") from e
    rel = f"{attach}/{base}{suffix}"
    existing = next((e for e in copies(ledger) if nfc(e["場所"]) == rel), None)
    if existing is None and os.path.lexists(str(folder / rel)):
        raise UtsushiError(f"{rel} に、台帳にないファイルがもうあります。写しの名前（--name）を変えてください")
    data, done = _build(folder, sources, suffix)
    notes = _notes(data, rules, name)
    _write(folder, rel, data)
    entry = {
        "id": existing["id"] if existing else _next_id(ledger),
        "場所": rel,
        "案件": nfc(case).strip(),
        "段階": nfc(stage).strip().strip("/"),
        "書類": (doc or {}).get("名前") or nfc(document).strip() or sources[0].get("種類", ""),
        "元の原本": [{"id": e.get("id"), "場所": e["場所"], "ハッシュ": e.get("ハッシュ"), "日付": e.get("日付")}
                  for e in sources],
        "ハッシュ": hashlib.sha256(data).hexdigest(),
        "大きさ": len(data),
        "整え方": done,
        "作った日時": dates.now(folder).isoformat(timespec="seconds"),
    }
    if notes:
        entry["注意"] = notes
    others = [e for e in copies(ledger) if nfc(e["場所"]) != rel]
    ledger[COPIES_KEY] = others + [entry]
    seiri.save_ledger(folder, ledger)
    return entry


def _notes(data: bytes, rules: Dict[str, object], name: str) -> List[str]:
    notes = []
    limit = size_limit(rules.get("容量"))
    if limit is not None and len(data) > limit:
        notes.append(f"写しの大きさ（{len(data):,}バイト）が、提出するファイルの決まりの容量（{rules['容量']}）を超えています。"
                     "スキャンの解像度を下げて取り直すなど、社長に相談してください")
    if rules.get("名前") and not nfc(name).strip():
        notes.append(f"提出するファイルの決まりに名前の決まりがあります（{rules['名前']}）。写しの名前（--name）をそろえてください")
    return notes


# ---- 原本が新しくなったとき ----


def _key(e: dict) -> Tuple[str, str, str]:
    return (nfc(e.get("区分", "")), nfc(e.get("種類", "")), nfc(e.get("相手先", "")))


def newer_original(ledger: dict, original: dict) -> Optional[dict]:
    """同じ区分・種類・相手先で、日付のいちばん新しい原本（original より新しいときだけ）。"""
    candidates = [e for e in seiri.originals(ledger) if _key(e) == _key(original) and e.get("id") != original.get("id")
                  and str(e.get("日付", "")) > str(original.get("日付", ""))]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (str(e.get("日付", "")), str(e.get("id", ""))))


def stale(folder: Path) -> List[dict]:
    """古い原本から作った写し（元の原本より新しい原本が台帳にあるもの）。案件ごとに知らせ、作り直すため。"""
    ledger = seiri.load_ledger(Path(folder))
    by_id = {e.get("id"): e for e in seiri.originals(ledger)}
    found = []
    for c in copies(ledger):
        for src in c.get("元の原本") or []:
            original = by_id.get(src.get("id")) or {**src, "区分": "", "種類": ""}
            newer = newer_original(ledger, original)
            if newer is not None:
                found.append({"写し": c["場所"], "案件": c.get("案件"), "段階": c.get("段階"),
                              "古い原本": src.get("場所"), "新しい原本": newer["場所"]})
    return found


def remake(folder: Path, copy_place: str) -> dict:
    """写しを、新しくなった原本で作り直す（同じ場所・同じ名前。古い原本は消さない）。台帳の1件を返す。"""
    folder = Path(folder)
    ledger = seiri.load_ledger(folder)
    copy_place = nfc(copy_place).strip()
    entry = next((e for e in copies(ledger) if nfc(e["場所"]) == copy_place or e.get("id") == copy_place), None)
    if entry is None:
        raise UtsushiError(f"{copy_place} は、書類の台帳の写しではありません")
    by_id = {e.get("id"): e for e in seiri.originals(ledger)}
    sources = []
    replaced = []
    for src in entry.get("元の原本") or []:
        original = by_id.get(src.get("id"))
        if original is None:
            raise UtsushiError(f"写しの元の原本（{src.get('場所')}）が、書類の台帳にありません")
        newer = newer_original(ledger, original)
        if newer is not None:
            replaced.append(f"{original['場所']} → {newer['場所']}")
            original = newer
        sources.append(original["場所"])
    rel = entry["場所"]
    attach, filename = rel.rsplit("/", 1)
    stage = attach[len(f"{CASES_DIR}/{entry['案件']}/"):-len(f"/{ATTACH_DIR}")]
    result = make(folder, sources, entry["案件"], stage, entry.get("書類", ""), Path(filename).stem)
    result["作り直した原本"] = replaced
    return result
