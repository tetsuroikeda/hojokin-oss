"""LibreOffice で Excel の数式を計算し直す（DESIGN 6章「様式の数式の計算し直しは LibreOffice で行う」、実験 E2b・E5。
TASKS M5。M6 以降の様式の計算し直しと PDF への変換でも使う）。

- LibreOffice は PATH に頼らず、決まった場所と Spotlight で探す（PATH は最後に見る。開発用の Linux など）。
- 利用者の設定（プロフィール）は、そのたびに一時の場所に新しく作る。社長が開いている LibreOffice とぶつからず、
  社長の設定も変えない。一時の場所は、呼ぶ側が会社のフォルダの `.hojokin/一時/` の下に用意する。
- 計算し直しは「常に」にする（Calc の OOXMLRecalcMode を0）。既定（1）のままでは計算し直さず、古い値や、一部だけ
  計算し直した誤った値が残った（実験 E2b）。

標準のライブラリだけを使う。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

PLACES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "~/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
SPOTLIGHT_QUERY = "kMDItemCFBundleIdentifier == 'org.libreoffice.script'"
# ふだんは10秒ほどで終わる。パソコンが混んでいても待てるよう、長めにする
TIMEOUT = 300

XCU_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
)
RECALC_ALWAYS = (
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>'
)


class LibreOfficeError(RuntimeError):
    """LibreOffice が動かなかった、または計算し直したファイルができなかった。"""


def _runnable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _spotlight() -> Iterable[str]:
    mdfind = "/usr/bin/mdfind"
    if not _runnable(mdfind):
        return []
    try:
        r = subprocess.run([mdfind, SPOTLIGHT_QUERY], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    apps = r.stdout.decode("utf-8", "replace").splitlines()
    return [os.path.join(a, "Contents", "MacOS", "soffice") for a in apps if a.endswith(".app")]


def find_soffice(places: Optional[Iterable[str]] = None, spotlight: bool = True, path_fallback: bool = True
                 ) -> Optional[str]:
    """LibreOffice（soffice）の場所。見つからなければ None。"""
    for place in places if places is not None else PLACES:
        full = os.path.expanduser(place)
        if _runnable(full):
            return full
    if spotlight:
        for full in _spotlight():
            if _runnable(full):
                return full
    if path_fallback:
        found = shutil.which("soffice")
        if found:
            return found
    return None


def write_profile(profile: Path) -> None:
    """一時のプロフィールに、計算し直しを「常に」にする設定を書く（起動する前に書く）。"""
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(XCU_HEAD + RECALC_ALWAYS + "</oor:items>", encoding="utf-8")


def recalc_xlsx(src: Path, work: Path, soffice: str, timeout: int = TIMEOUT) -> Path:
    """src を、計算し直しを「常に」にした LibreOffice で開いて xlsx に保存し直し、その場所を返す。

    work は、呼ぶ側が用意した空の一時の場所（会社のフォルダの .hojokin/一時/ の下など）。
    中に、ファイルの写し（in/）、保存し直したもの（out/）、プロフィール（profile/）を作る。片付けは呼ぶ側が行う。
    """
    inbox, outbox, profile = work / "in", work / "out", work / "profile"
    for d in (inbox, outbox):
        d.mkdir(parents=True, exist_ok=True)
    write_profile(profile)
    copy = inbox / "model.xlsx"
    shutil.copyfile(str(src), str(copy))
    cmd = [
        soffice,
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless",
        "--norestore",
        "--nologo",
        "--nodefault",
        "--nolockcheck",
        "--convert-to",
        "xlsx:Calc Office Open XML",
        "--outdir",
        str(outbox),
        str(copy),
    ]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise LibreOfficeError(f"LibreOffice が {timeout} 秒たっても終わりませんでした")
    except OSError as e:
        raise LibreOfficeError(f"LibreOffice を動かせませんでした（{e}）")
    out = outbox / "model.xlsx"
    if r.returncode != 0 or not out.is_file():
        detail = (r.stdout + r.stderr).decode("utf-8", "replace").strip()[-500:]
        raise LibreOfficeError(f"LibreOffice で計算し直したファイルができませんでした（終了コード {r.returncode}）{detail}")
    return out
