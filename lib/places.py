"""会社のフォルダの中の場所に解く、共通の道具（SPEC F5「会社のフォルダの外には触れない」、DESIGN 5章
「会社のフォルダの外に書かない・外を読まない」。TASKS M2d・M0b の直し）。

道具ごとに同じ確かめを書かず、場所の確かめはすべてここの関数で行う。別名（シンボリックリンク）と「..」を
たどった後に、名前の文字の形を NFC にそろえてから比べる（DESIGN 5章 (b)。Finder で作った名前は NFD のことがある。
実験 E5）。

使い方
- 読む・書く場所が、会社のフォルダの中かを確かめる（相対の場所は、会社のフォルダから解く。~ は解かないので、
  渡す前に expanduser する）。
      real = places.resolve_inside(folder, path)   # 中なら、別名をたどった後の本当の場所（NFC）。外なら PlaceError
      rel = places.relative_inside(folder, path)   # 中なら、会社のフォルダからの場所（「/」区切り、NFC。そのものなら「.」）
      if places.is_inside(folder, path): ...       # 断らずに、中かどうかだけ知りたいとき
  会社のフォルダそのものも「中」に数える。そのものを断る道具は、呼んだ側で断る。
- 書き戻す・取り込む・書き出す道具は、別名の先を書き換えないよう、途中のフォルダとそのもの自体に別名がないことも
  確かめる（別名の先が会社のフォルダの中でも断る。行き先が別の置き場に変わるため）。
      places.no_link_on_the_way(folder, "案件/…/申請書/その1.docx")   # 別名があれば PlaceError（e.link が別名の場所）
      link = places.first_link(folder, rel)                         # 断らずに、最初の別名の場所（なければ None）
  rel は会社のフォルダからの場所。まだない所から先は、別名もないものとして扱う（消した書類を戻すときなど）。
- 名前の文字の形（NFC・NFD）に左右されずに、作業のファイルの実際の場所を引く。
      path = places.actual(folder, rel)                    # なければ None
      path = places.actual(folder, rel, partial=True)      # ない所から先は rel の名前のまま足す（これから作る場所）
- hook のように、別名をたどった後の場所どうしで比べたいときは、real(path) と is_under(real_path, real_top)。

PlaceError の文は、そのまま社長への説明にも使えるが、道具はふつう e.link・e.path を使って、その道具の調子の文に
言い換える（断る文を、直す前と同じに保つため）。

hook（外を読む判定）でも読み込むので、標準のライブラリだけを使い、軽く保つ。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, os.PathLike]


class PlaceError(ValueError):
    """場所が会社のフォルダの外になる、または途中に別名がある。

    path：渡された場所（文字）。link：別名があった、会社のフォルダからの場所（別名のときだけ）。
    """

    def __init__(self, message: str, path: str = "", link: Optional[str] = None) -> None:
        super().__init__(message)
        self.path = path
        self.link = link


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def real(path: PathLike) -> Path:
    """別名と「..」をたどり、名前の文字の形を NFC にそろえた場所。"""
    return Path(nfc(os.path.realpath(str(path))))


def is_under(path: Path, top: Path) -> bool:
    """path が top か、その下か（どちらも real を通した場所で渡す）。"""
    try:
        Path(path).relative_to(Path(top))
        return True
    except ValueError:
        return False


def _joined(folder: PathLike, path: PathLike) -> Path:
    given = Path(path)
    return given if given.is_absolute() else Path(folder) / given


def is_inside(folder: PathLike, path: PathLike) -> bool:
    """path（相対なら会社のフォルダから）が、別名と「..」をたどった後も、会社のフォルダかその中にあるか。"""
    return is_under(real(_joined(folder, path)), real(folder))


def resolve_inside(folder: PathLike, path: PathLike) -> Path:
    """path を、別名と「..」をたどった後の本当の場所（NFC）にする。会社のフォルダの外なら PlaceError。"""
    target = real(_joined(folder, path))
    if not is_under(target, real(folder)):
        raise PlaceError(f"{path} は、会社のフォルダの外です", path=str(path))
    return target


def relative_inside(folder: PathLike, path: PathLike) -> str:
    """path の、会社のフォルダからの場所（「/」区切り、NFC）。そのものなら「.」。外なら PlaceError。"""
    target = resolve_inside(folder, path)
    return target.relative_to(real(folder)).as_posix()


def _parts(rel: PathLike) -> list:
    """会社のフォルダからの場所を、名前の並びにする。絶対の場所・「..」・空の名前は PlaceError。"""
    text = nfc(Path(rel).as_posix()) if not isinstance(rel, str) else nfc(rel)
    if text.startswith("/") or "\x00" in text:
        raise PlaceError(f"{rel} は、会社のフォルダからの場所ではありません", path=str(rel))
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PlaceError(f"{rel} は、会社のフォルダからの場所として正しくありません", path=str(rel))
    return parts


def _entry(current: str, part: str) -> Optional[str]:
    """フォルダ current の中の、名前が part（NFC）に当たるものの実際の場所（名前が NFD のこともある）。なければ None。"""
    try:
        names = os.listdir(current)
    except OSError:
        # 中の一覧を読めないフォルダでも、名前で開けるものはある
        direct = os.path.join(current, part)
        return direct if os.path.lexists(direct) else None
    match = next((n for n in names if nfc(n) == part), None)
    return None if match is None else os.path.join(current, match)


def actual(folder: PathLike, rel: PathLike, partial: bool = False) -> Optional[Path]:
    """会社のフォルダからの場所 rel の、実際の場所（名前が NFD のこともある）。なければ None。

    partial=True なら、ない所から先は rel の名前のまま足した場所を返す（これから作る場所）。
    別名はたどらずに名前で引く（別名かどうかは first_link で見る）。
    """
    parts = _parts(rel)
    current = str(folder)
    for i, part in enumerate(parts):
        found = _entry(current, part)
        if found is None:
            return Path(current).joinpath(*parts[i:]) if partial else None
        current = found
    return Path(current)


def first_link(folder: PathLike, rel: PathLike) -> Optional[str]:
    """会社のフォルダから rel までの途中のフォルダか、rel そのものが別名なら、いちばん手前の別名の場所
    （会社のフォルダからの場所、NFC）。なければ None。まだない所から先は見ない。"""
    parts = _parts(rel)
    current = str(folder)
    for i, part in enumerate(parts):
        found = _entry(current, part)
        if found is None:
            return None
        if os.path.islink(found):
            return "/".join(parts[: i + 1])
        current = found
    return None


def no_link_on_the_way(folder: PathLike, rel: PathLike) -> None:
    """会社のフォルダから rel までの途中のフォルダと、rel そのものに別名があれば PlaceError（e.link が別名の場所）。

    書き戻す・取り込む・書き出す道具が、別名の先（会社のフォルダの外や、別の置き場）を書き換えないために使う。
    """
    link = first_link(folder, rel)
    if link is not None:
        raise PlaceError(f"{link} が別名（シンボリックリンク）になっています", path=str(rel), link=link)
