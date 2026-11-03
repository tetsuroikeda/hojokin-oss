"""実験 E2 の共通の部品。出力先の確かめ、LibreOffice の呼び出し、zip の部品の読み書き。

公式の様式は downloads/ から毎回読み、書き込んだ写しや PDF はリポの外にだけ書く（DESIGN 11章、T0-4）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORMS_DIR = REPO_ROOT / "downloads" / "shoryokuka_ippan"
WORD_FORM = FORMS_DIR / "yoshiki_business_plan_part1_part2_ippan.docx"
EXCEL_FORM = FORMS_DIR / "yoshiki_business_plan_part3_ippan_08.xlsx"

SOFFICE_CANDIDATES = [
    "soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def prepare_out_dir(path: str) -> Path:
    """出力先を作る。リポの中なら止める（様式から作ったものをリポに入れないため）。"""
    out = Path(path).expanduser().resolve()
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        sys.exit(f"出力先がリポの中です。リポの外を指定してください：{out}")
    out.mkdir(parents=True, exist_ok=True)
    return out


def require_form(path: Path) -> Path:
    if not path.is_file():
        sys.exit(f"様式がありません：{path}（E0 の手順で downloads/ に取ってください）")
    return path


def soffice_path() -> str:
    for cand in SOFFICE_CANDIDATES:
        found = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if found:
            return found
    sys.exit("LibreOffice（soffice）が見つかりません")


def convert(src: Path, fmt: str, out_dir: Path, profile_dir: Path, timeout: int = 180) -> Path:
    """LibreOffice で変換する。手元の設定を変えないよう、プロフィールは出力先の下に別に作る。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice_path(),
        f"-env:UserInstallation={profile_dir.as_uri()}",
        "--headless",
        "--norestore",
        "--nologo",
        "--convert-to",
        fmt,
        "--outdir",
        str(out_dir),
        str(src),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    ext = fmt.split(":")[0]
    dst = out_dir / f"{src.stem}.{ext}"
    if result.returncode != 0 or not dst.is_file():
        raise RuntimeError(f"変換に失敗しました：{src.name} → {fmt}\n{result.stdout}\n{result.stderr}")
    return dst


XCU_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
)


def write_registry(profile_dir: Path, items: list[str]) -> None:
    """別に作ったプロフィールに、LibreOffice の設定を書く（起動する前に書く。手元のプロフィールは触らない）。"""
    user = profile_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    (user / "registrymodifications.xcu").write_text(XCU_HEAD + "".join(items) + "</oor:items>", encoding="utf-8")


def font_replacement_items(pairs: dict[str, str]) -> list[str]:
    """フォントの置き換え表（ツール → オプション → フォント と同じもの）を、常に使う形で書く。"""
    items = [
        '<item oor:path="/org.openoffice.Office.Common/Font/Substitution">'
        '<prop oor:name="Replacement" oor:op="fuse"><value>true</value></prop></item>'
    ]
    for i, (requested, substitute) in enumerate(pairs.items()):
        items.append(
            '<item oor:path="/org.openoffice.Office.Common/Font/Substitution/FontPairs">'
            f'<node oor:name="_{i}" oor:op="replace">'
            '<prop oor:name="Always" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="OnScreenOnly" oor:op="fuse"><value>false</value></prop>'
            f'<prop oor:name="ReplaceFont" oor:op="fuse"><value>{requested}</value></prop>'
            f'<prop oor:name="SubstituteFont" oor:op="fuse"><value>{substitute}</value></prop>'
            "</node></item>"
        )
    return items


def read_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def write_parts(src: Path, dst: Path, replace: dict[str, bytes | None]) -> None:
    """zip の部品を差し替えて書く。順番と圧縮の形は元のまま。None の部品は消す。"""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename in replace:
                data = replace[info.filename]
                if data is None:
                    continue
            else:
                data = zin.read(info.filename)
            zout.writestr(info, data)


def is_xml_part(name: str) -> bool:
    return name.endswith((".xml", ".rels", ".vml"))
