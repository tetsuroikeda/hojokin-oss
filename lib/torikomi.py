"""社長が伝えた外の場所から、書類を会社のフォルダに写して取り込む（SPEC F5「外のものは、社長が場所を伝えたら取り込む」、
DESIGN 4.7・5章。TASKS B10。T5-9）。

- 社長が送ったとき（UserPromptSubmit）に、発言にある会社のフォルダの外の場所を控える（remember）。控えは
  `.hojokin/一時/外の場所.json` に1つだけ持ち、発言のたびに作り直す（社長の直前の発言にあった場所だけを受け付けるため）。
  - 場所の見つけ方：「/」か「~/」で始まる場所（引用符・かぎかっこで囲んだもの、「\\ 」で空白を逃がしたものも）、
    「デスクトップ」「ダウンロード」の言葉（ホームの Desktop・Downloads）。あるものだけを控える。
  - ホームのフォルダそのものと、それを含むフォルダ（/Users、/ など）は控えない（広すぎるため。DESIGN 4.7）。
- 取り込みの道具（skills/shorui/scripts/torikomi.py）は、控えた場所だけを読む。Bash のコマンドに外の場所を書かずに済むよう、
  場所は控えの番号で指す（ファイルの道具と Claude Code の設定は、外を読まないため。DESIGN 4.7）。
- 写す先は `入れ口/取り込み/<今日の日付>/<元の名前>`。元のファイルは動かさず、変えない。写した後は、ほかの書類と同じく
  shorui の整理（seiri.py）で原本の置き場へ移す。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import List, Optional

from lib import company, dates, place_text, places
from lib.company_init import INBOX_DIR

CONTROL = f"{company.MARKER_DIR}/{company.TEMP_DIR}/外の場所.json"
IMPORT_DIR = f"{INBOX_DIR}/取り込み"
WORDS = (("デスクトップ", "Desktop"), ("ダウンロード", "Downloads"))
MAX_FILES = 100  # 1つのフォルダから取り込む数の上限（多すぎるときは、ファイルの名前で指してもらう）
_QUOTED = re.compile(r'"([^"\n]+)"|\'([^\'\n]+)\'|「([^」\n]+)」|『([^』\n]+)』')
_BARE = re.compile(r'(?<![\w/~])(~?/(?:\\ |[^\s"\'「」『』、。，,（）()])+)')
_TRAIL = "。、，,.)）」』"


class TorikomiError(ValueError):
    """取り込まなかった（伝えられていない場所、番号が違う など）。何も写していない。"""


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


# ---- 社長の発言から、外の場所を控える ----


def candidates(prompt: str, home: Path) -> List[Path]:
    """発言にある場所の候補（あるかどうかは見ていない）。"""
    text = nfc(prompt)
    found: List[str] = []
    for m in _QUOTED.finditer(text):
        value = next(g for g in m.groups() if g)
        if value.startswith(("/", "~/")):
            found.append(value)
    for m in _BARE.finditer(_QUOTED.sub(" ", text)):
        found.append(m.group(1).replace("\\ ", " ").rstrip(_TRAIL))
    paths = [Path(os.path.expanduser(v)) if v.startswith("~") else Path(v) for v in found]
    for word, name in WORDS:
        if word in text:
            paths.append(Path(home) / name)
    out: List[Path] = []
    for p in paths:
        if p not in out:
            out.append(p)
    return out


def _too_wide(path: Path, home: Path) -> bool:
    real, real_home = places.real(path), places.real(home)
    return real == real_home or places.is_under(real_home, real)


def told_places(prompt: str, folder: Path, home: Optional[Path] = None) -> List[str]:
    """発言にある、会社のフォルダの外の、ある場所（別名と「..」をたどった場所）。"""
    home = Path(home or Path.home())
    out: List[str] = []
    for p in candidates(prompt, home):
        if not os.path.exists(str(p)):
            continue
        if places.is_inside(folder, p) or _too_wide(p, home):
            continue
        real = str(places.real(p))
        if real not in out:
            out.append(real)
    return out


def remember(data: dict, folder: Path) -> None:
    """社長が送ったときに、発言にある外の場所を控える（前の控えは捨てる。直前の発言の場所だけを受け付けるため）。"""
    folder = Path(folder)
    prompt = (data or {}).get("prompt")
    if not isinstance(prompt, str):
        return
    found = told_places(prompt, folder)
    path = folder / CONTROL
    if place_text.write_problem(folder, CONTROL, "外の場所を控えていません"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "説明": "社長の直前の発言にあった、会社のフォルダの外の場所（lib/torikomi.py が書く。取り込みの道具はここだけを読む）",
        "セッション": (data or {}).get("session_id"),
        "発言の日時": dates.now(folder).isoformat(timespec="seconds"),
        "場所": found,
    }
    fd, tmp = tempfile.mkstemp(prefix=".外の場所_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def told(folder: Path) -> List[str]:
    """控えた場所（なければ空）。"""
    try:
        data = json.loads((Path(folder) / CONTROL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get("場所") if isinstance(data, dict) else None
    return [p for p in found if isinstance(p, str)] if isinstance(found, list) else []


# ---- 取り込む ----


def _files_in(place: Path) -> List[Path]:
    """フォルダの中の書類（すぐ下だけ。隠しファイルと別名は除く）。"""
    out = []
    for p in sorted(place.iterdir()):
        if p.name.startswith((".", "~$")) or p.is_symlink() or not p.is_file():
            continue
        out.append(p)
    return out


def listing(folder: Path) -> List[dict]:
    """控えた場所の一覧（番号、場所、ファイルかフォルダか、フォルダの中のファイルの名前）。中身は読まない。"""
    out = []
    for number, raw in enumerate(told(folder), 1):
        p = Path(raw)
        item = {"番号": number, "場所": raw, "種類": "フォルダ" if p.is_dir() else "ファイル"}
        if p.is_dir():
            files = _files_in(p)
            item["中のファイル"] = [nfc(f.name) for f in files[:MAX_FILES]]
            if len(files) > MAX_FILES:
                item["中のファイル"].append(f"…ほか {len(files) - MAX_FILES}件")
        out.append(item)
    return out


def _pick(folder: Path, number: int, name: str) -> List[Path]:
    places_told = told(folder)
    if not places_told:
        raise TorikomiError("社長の直前の発言に、取り込む場所がありません。社長に、取り込む書類の場所を伝えてもらってください"
                            "（ファイルをこの画面に引いて入れるか、場所を書いてもらう）")
    if not 1 <= number <= len(places_told):
        raise TorikomiError(f"番号（{number}）が違います。list で控えた場所の番号を確かめてください（1〜{len(places_told)}）")
    place = Path(places_told[number - 1])
    if not os.path.exists(str(place)):
        raise TorikomiError(f"{place} が見つかりません（動かされたか、消されたかもしれません）")
    if place.is_file():
        if name and nfc(name) != nfc(place.name):
            raise TorikomiError(f"番号 {number} はファイル（{place.name}）です。名前（--name）は付けずに取り込んでください")
        return [place]
    files = _files_in(place)
    if name:
        chosen = [f for f in files if nfc(f.name) == nfc(name)]
        if not chosen:
            raise TorikomiError(f"{place} のすぐ下に {name} がありません。list でファイルの名前を確かめてください")
        return chosen
    if len(files) > MAX_FILES:
        raise TorikomiError(f"{place} には書類が{len(files)}件あります。多いので、取り込むファイルの名前（--name）で指してください")
    return files


def import_from(folder: Path, number: int, name: str = "") -> List[dict]:
    """控えた場所（番号）から、書類を `入れ口/取り込み/<今日>/` に写す。元のファイルは変えない。写したものの一覧を返す。"""
    folder = Path(folder)
    sources = _pick(folder, number, name)
    day = dates.today(folder).isoformat()
    dest_dir = f"{IMPORT_DIR}/{day}"
    problem = place_text.write_problem(folder, f"{dest_dir}/x", "取り込んでいません")
    if problem:
        raise TorikomiError(problem)
    plan = []
    for src in sources:
        rel = f"{dest_dir}/{nfc(src.name)}"
        dest = folder / rel
        if os.path.lexists(str(dest)):
            if dest.is_file() and dest.read_bytes() == src.read_bytes():
                plan.append((src, rel, False))
                continue
            raise TorikomiError(f"{rel} に、同じ名前の別の書類がもうあります。先にそちらを整理してから取り込んでください。"
                                "何も取り込んでいません")
        plan.append((src, rel, True))
    done = []
    for src, rel, copy in plan:
        if copy:
            dest = folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(src), str(dest))  # 中身だけを写す（元の権限や日時は持ち込まない）
        done.append({"元の場所": nfc(str(src)), "取り込んだ場所": rel,
                     "結果": "写しました" if copy else "同じ中身がもうあるので、写しませんでした"})
    return done
