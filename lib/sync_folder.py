"""会社のフォルダにしない場所と、同期されるフォルダの見分け（DESIGN 4.7・10章、TASKS S5b）。

会社のフォルダを作る道具（lib/company_init.py）が、書く前の確かめで使う。読むだけで、何も書かない。

- ホームのフォルダと、それを含むフォルダ、ディスクの根（「/」と、外付けのディスクなどのつなぎ目）は、
  会社のフォルダにしない。中のものがすべて版の履歴と照らしの対象になってしまうため。
- 同期されるフォルダ（Google ドライブ、OneDrive、Dropbox、iCloud Drive など）は、場所で見分ける。
  中身は版の履歴ごとクラウドに上がるので、SPEC では「同期されるフォルダの形」（版をファイルで残す）にする。
  - Mac の今の形：~/Library/CloudStorage/<サービス>-…（Google ドライブ、OneDrive、Dropbox、Box など）、
    ~/Library/Mobile Documents/（iCloud Drive）。
  - 前からの形：ホームの直下の Dropbox、Google Drive、OneDrive など。Dropbox は、根に .dropbox のファイルを置く。
    この目印は、ホームより下だけで探す。Dropbox のアプリは、自分の設定を ~/.dropbox/（フォルダ）に置くので、
    ホームまで遡ると、ホームの下のどのフォルダも同期されるとみなしてしまうため。
- Mac と Windows の標準のディスクは、大文字と小文字を区別しない（~/library/cloudstorage/… でも同じ場所に着く）。
  そのため、道筋を比べるときは、大文字と小文字をそろえて比べる（_key）。区別するディスクで別の場所を同じとみなしても、
  断る側に倒れるだけで、害はない。
  - Windows の OneDrive は、環境変数（OneDrive など）に場所がある（期間中は確かめない。SPEC 4章）。
  - iCloud の「デスクトップと書類」：Finder の設定（com.apple.finder の FXICloudDriveDesktop・
    FXICloudDriveDocuments）が 1 のときだけ、~/Desktop・~/Documents の下を同期されるとみなす。
    切ってある Mac で 0 と読めることは確かめた。入れた Mac で 1 になることは、まだ確かめていない。
    M0c（11/4）で、開発の Mac を読むだけで確かめた結果：Desktop・Documents は 0（切ってある）、FXICloudDriveEnabled
    は 1（iCloud Drive は入っている）。~/Desktop・~/Documents はふつうのフォルダ（別名でない）で、拡張属性に iCloud の
    印はない（com.apple.macl・com.apple.provenance だけ）。~/Library/Mobile Documents/com~apple~CloudDocs/ の中には
    Desktop・Documents のフォルダが残っている（切った後も残る）ので、そのフォルダがあることは見分けに使わない。
    入れた Mac は手元になく、1 になることは確かめられなかった（作者に確かめてもらう）。~/Desktop が iCloud Drive の
    中への別名になる形なら、別名をたどった場所（~/Library/Mobile Documents/）で iCloud Drive と見分ける。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set, Tuple

# ~/Library/CloudStorage/ の下のフォルダの名前の始まりと、社長に伝えるサービスの名前
CLOUD_STORAGE_PREFIXES = (
    ("GoogleDrive", "Google ドライブ"),
    ("OneDrive", "OneDrive"),
    ("Dropbox", "Dropbox"),
    ("iCloud", "iCloud Drive"),
    ("Box", "Box"),
)
# ホームの直下にある、前からの形の同期されるフォルダ（名前の始まり）
HOME_PREFIXES = (
    ("Google Drive", "Google ドライブ"),
    ("GoogleDrive", "Google ドライブ"),
    ("My Drive", "Google ドライブ"),
    ("OneDrive", "OneDrive"),
    ("Dropbox", "Dropbox"),
    ("iCloudDrive", "iCloud Drive"),
    ("Box", "Box"),
)
# 同期のアプリが、同期するフォルダの根に置く目印（名前、サービス、フォルダか）。
# .dropbox は小さなファイル、.dropbox.cache はフォルダ。ホームの ~/.dropbox/（アプリの設定のフォルダ）とは別のもの
ROOT_MARKERS = ((".dropbox", "Dropbox", False), (".dropbox.cache", "Dropbox", True))
# 道筋の大文字と小文字を区別しないとみなす OS（標準のディスクが区別しない）
CASE_INSENSITIVE = sys.platform in ("darwin", "win32")
# Windows の OneDrive の場所が入る環境変数
ONEDRIVE_ENV = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
# iCloud の「デスクトップと書類」の設定の名前と、ホームの下のフォルダ
ICLOUD_DESKTOP_KEYS = (("FXICloudDriveDesktop", "Desktop"), ("FXICloudDriveDocuments", "Documents"))
DEFAULTS = "/usr/bin/defaults"


@dataclass(frozen=True)
class Synced:
    """同期されるフォルダ。service は社長に伝えるサービスの名前、root は同期される一番上のフォルダ。"""

    service: str
    root: Path


def _resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(os.path.abspath(str(path.expanduser())))


def home_dirs() -> List[Path]:
    """ホームのフォルダ。環境変数 HOME と、利用者の登録（pwd）の両方を見る。"""
    found = [_resolve(Path.home())]
    try:
        import pwd

        found.append(_resolve(Path(pwd.getpwuid(os.getuid()).pw_dir)))
    except (ImportError, KeyError, OSError):
        pass
    return list(dict.fromkeys(found))


def _key(part: str) -> str:
    """道筋の1つの部分を、比べるための形にする（文字の合成の形と、大文字と小文字をそろえる）。"""
    text = unicodedata.normalize("NFC", part)
    return text.casefold() if CASE_INSENSITIVE else text


def _keys(path: Path) -> Tuple[str, ...]:
    return tuple(_key(p) for p in path.parts)


def _is_within(path: Path, parent: Path) -> bool:
    """path が parent そのものか、その下にある。"""
    k, p = _keys(path), _keys(parent)
    return k[: len(p)] == p


def _is_below(path: Path, parent: Path) -> bool:
    """path が parent の下にある（parent そのものは含まない）。"""
    return len(path.parts) > len(parent.parts) and _is_within(path, parent)


def not_allowed_reason(folder: Path) -> Optional[str]:
    """ホームのフォルダ・それを含むフォルダ・ディスクの根なら、その理由。会社のフォルダにしてよければ None。"""
    path = _resolve(folder)
    if path.parent == path or os.path.ismount(str(path)):
        return (
            f"このフォルダ（{path}）は、ディスクの一番上のフォルダです。"
            "中のものがすべて版の履歴と照らしの対象になってしまうため、会社のフォルダにはしません。"
        )
    for home in home_dirs():
        if _keys(path) == _keys(home):
            return (
                "このフォルダは、ホームのフォルダです。"
                "中のものがすべて版の履歴と照らしの対象になってしまうため、会社のフォルダにはしません。"
            )
        if _is_below(home, path):
            return (
                f"このフォルダ（{path}）は、ホームのフォルダ（{home}）を含んでいます。"
                "中のものがすべて版の履歴と照らしの対象になってしまうため、会社のフォルダにはしません。"
            )
    return None


def _match_prefix(name: str, table: Iterable, whole_word: bool = False) -> Optional[str]:
    """名前の始まりが表にあれば、そのサービスの名前。

    whole_word のときは、名前そのものか、後ろが空白・「-」・「_」・括弧で続くものだけに当てる
    （ホームの直下の「Boxes」のような、同期と関係のない名前に当てないため）。
    """
    lowered = name.lower()
    for prefix, service in table:
        p = prefix.lower()
        if not lowered.startswith(p):
            continue
        rest = lowered[len(p):]
        if not whole_word or rest == "" or rest[0] in " -_(（":
            return service
    return None


def icloud_desktop_synced() -> Set[str]:
    """iCloud の「デスクトップと書類」で同期されている、ホームの下のフォルダの名前（Desktop・Documents）。

    Finder の設定を /usr/bin/defaults で読む（設定のファイルは、書き戻される前の古い中身のことがあるため）。
    読めないときと、1 でないときは、同期されていないとみなす。Mac でなければ空。
    """
    if sys.platform != "darwin" or not Path(DEFAULTS).exists():
        return set()
    found = set()
    for key, name in ICLOUD_DESKTOP_KEYS:
        try:
            r = subprocess.run([DEFAULTS, "read", "com.apple.finder", key], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip() == b"1":
            found.add(name)
    return found


def synced(folder: Path, icloud_desktop: Optional[Callable[[], Set[str]]] = None) -> Optional[Synced]:
    """folder が同期されるフォルダの中なら、サービスと同期される一番上のフォルダ。そうでなければ None。

    icloud_desktop は、iCloud の「デスクトップと書類」で同期されているフォルダの名前を返す関数（テストで差し替える）。
    """
    path = _resolve(folder)
    homes = home_dirs()
    for home in homes:
        if not _is_below(path, home):
            continue
        # 比べるのは大文字と小文字をそろえた形（keys）、社長に伝える場所は渡された書き方のまま（parts）
        start = len(home.parts)
        parts = path.parts[start:]
        keys = [_key(p) for p in parts]

        def top(n: int) -> Path:
            return Path(*path.parts[: start + n])

        # ~/Library/CloudStorage/<サービス>-…
        if len(parts) >= 3 and keys[0] == _key("Library") and keys[1] == _key("CloudStorage"):
            service = _match_prefix(parts[2], CLOUD_STORAGE_PREFIXES) or f"クラウドの同期（{parts[2]}）"
            return Synced(service, top(3))
        # ~/Library/Mobile Documents/（iCloud Drive と、アプリごとの iCloud の置き場）
        if len(parts) >= 2 and keys[0] == _key("Library") and keys[1] == _key("Mobile Documents"):
            return Synced("iCloud Drive", top(2))
        # ホームの直下の、前からの形の同期されるフォルダ
        service = _match_prefix(unicodedata.normalize("NFC", parts[0]), HOME_PREFIXES, whole_word=True)
        if service:
            return Synced(service, top(1))
        # iCloud の「デスクトップと書類」
        for name in ("Desktop", "Documents"):
            if keys[0] == _key(name) and name in (icloud_desktop or icloud_desktop_synced)():
                return Synced("iCloud Drive（デスクトップと書類）", top(1))
    # 同期のアプリが根に置く目印（場所を変えた Dropbox など）。
    # ホームとそれを含むフォルダ、ディスクの根は見ない（~/.dropbox/ はアプリの設定のフォルダで、同期の根ではない）
    for candidate in [path] + list(path.parents):
        if candidate.parent == candidate or any(_is_within(home, candidate) for home in homes):
            break
        for marker, service, is_dir in ROOT_MARKERS:
            target = candidate / marker
            if (target.is_dir() if is_dir else target.is_file()):
                return Synced(service, candidate)
    # Windows の OneDrive
    for key in ONEDRIVE_ENV:
        value = os.environ.get(key)
        if value:
            root = _resolve(Path(value))
            if _is_within(path, root) and root.parent != root:
                return Synced("OneDrive", root)
    return None
