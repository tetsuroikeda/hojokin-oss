"""場所の確かめ（lib/places.py）で断るときの文（SPEC F5、DESIGN 5章「会社のフォルダの外に書かない・外を読まない」）。

どの道具も、確かめは lib/places.py の関数で行い、断るときはここの文を、その道具の例外（とその道具の頭の文）に入れる。
文の調子は、波2a で直した道具（lib/gaiyou.py・lib/submission.py・lib/past_versions.py）にそろえる。

- 読む材料が、別名と「..」をたどった後に会社のフォルダの外になる（places.is_inside が偽）：outside(what)
- 書く先の途中のフォルダか、書く先そのものが別名（places.no_link_on_the_way が PlaceError）：linked(action, e.link)
  action は、しないことの文（「段階のフォルダを作りません」など）。
  別名の先が会社のフォルダの中でも断る（行き先が別の置き場に変わるため。lib/places.py）。

hook からも読み込まれるので、標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from lib import places

PathLike = Union[str, Path]

AGAIN = "別名を本物のフォルダやファイルに置き換えてから、もう一度試してください"


def outside(what: str) -> str:
    """読む材料が、別名などで会社のフォルダの外を指しているときの文。"""
    return f"{what}が、別名（シンボリックリンク）などで会社のフォルダの外を指しています。外のファイルは読まず、外にも書きません。{AGAIN}"


def linked(action: str, link: str) -> str:
    """書く先までの途中のフォルダか、書く先そのもの（link。会社のフォルダからの場所）が別名のときの文。

    action は、しないことの文（「段階のフォルダを作りません」など）。
    """
    return (f"{link} が別名（シンボリックリンク）になっているため、{action}"
            f"（別名の先の、会社のフォルダの外や別の場所に書かないため）。{AGAIN}")


def read_problem(folder: PathLike, path: PathLike, what: str) -> Optional[str]:
    """path（相対なら会社のフォルダから）が、別名と「..」をたどった後も会社のフォルダの中なら None。外なら断る文。"""
    return None if places.is_inside(folder, path) else outside(what)


def write_problem(folder: PathLike, rel: str, action: str) -> Optional[str]:
    """会社のフォルダから rel までの途中のフォルダと rel そのものに、別名がなければ None。あれば断る文。"""
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        if e.link is None:  # rel の形が違う（道具が組んだ場所なので、ふつうは起きない）
            return f"{rel} は、会社のフォルダからの場所として正しくありません。そのため、{action}"
        return linked(action, e.link)
    return None
