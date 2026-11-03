"""案件のフォルダ（書類フォルダ）を作る（DESIGN 4.5、TASKS M2a）。

会社のフォルダの `案件/<案件の名前>/` に、案件ごとのフォルダを作る。
- 名前は「2026_省力化（一般型）第9回」の形（年_制度の略称（枠）公募回）。
- 中に `公式資料/`（公募要領・様式・手引き。中のファイルは読み取り専用）を作る。
- 段階のフォルダ（1_申請 など）は、制度データの「手続きの段階」から作る（DESIGN 4.5）。
  制度データは公式資料を読んでから作るので（M2c）、ここでは作る道具（ensure_stage_folders）だけを用意する。
  どの段階のフォルダも、中は「申請書」と「添付する書類」の2つにそろえる。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional

CASES_DIR = "案件"  # lib/company_init.py の CASES_DIR と同じ
OFFICIAL_DIR = "公式資料"
STAGE_SUBDIRS = ("申請書", "添付する書類")
STAGE_NAME = re.compile(r"^[0-9]+_[^/\\]+$")
# ファイルやフォルダの名前に使えない文字と、置き換える文字
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


class CaseError(ValueError):
    """案件の名前や段階の名前が、フォルダの名前として使えない。"""


def safe_name(text: str) -> str:
    """フォルダやファイルの名前に使えるようにする。使えない文字は「・」に置き換える。"""
    name = _UNSAFE.sub("・", unicodedata.normalize("NFC", text)).strip().strip(".")
    if not name:
        raise CaseError(f"名前に使える文字がありません（{text!r}）")
    if len(name.encode("utf-8")) > 200:
        raise CaseError(f"名前が長すぎます（{name}）")
    return name


def _case_label(seido: Dict) -> str:
    """案件の名前の、年の後ろの部分（略称（枠）公募回）。"""
    short = seido.get("略称") or seido.get("名前") or ""
    frame = seido.get("枠") or ""
    round_ = seido.get("公募回") or ""
    label = f"{short}（{frame}）" if frame else short
    return f"{label}{round_}"


def case_name(seido: Dict, year: int) -> str:
    """案件のフォルダの名前（DESIGN 4.5 の形）。

    seido は「略称」（なければ「名前」）・「枠」・「公募回」を持つ辞書。例：2026_省力化（一般型）第9回
    """
    return safe_name(f"{year}_{_case_label(seido)}")


def existing_cases(company: Path, seido: Dict) -> List[str]:
    """`案件/` の中で、同じ略称・枠・公募回の案件のフォルダ（年だけが違ってよい）の名前。

    年は、案件を始めた年。年が変わってから取り直しても（採択後の手引きを取る、改訂を確かめる など）、
    前のフォルダを使うために探す。
    """
    base = company / CASES_DIR
    if not base.is_dir():
        return []
    pattern = re.compile(r"^[0-9]{4}_" + re.escape(safe_name(f"0000_{_case_label(seido)}")[5:]) + r"$")
    names = (unicodedata.normalize("NFC", p.name) for p in base.iterdir() if p.is_dir())
    return sorted(n for n in names if pattern.match(n))


def find_or_name_case(company: Path, seido: Dict, year: int) -> str:
    """案件のフォルダの名前を決める。同じ略称・枠・公募回のフォルダが1つあれば、それを使う。

    なければ、今日の年で新しい名前を作る。2つ以上あれば、どれか分からないので CaseError
    （呼ぶ側は「案件の名前」を渡し直す）。
    """
    found = existing_cases(company, seido)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise CaseError(
            "同じ制度・枠・回の案件のフォルダが2つ以上あります（" + "、".join(found) + "）。"
            "どの案件のものか、案件の名前で指定してください")
    return case_name(seido, year)


def case_dir(company: Path, name: str) -> Path:
    return company / CASES_DIR / safe_name(name)


def official_dir(company: Path, name: str) -> Path:
    return case_dir(company, name) / OFFICIAL_DIR


def ensure_case(company: Path, name: str) -> List[str]:
    """案件のフォルダと `公式資料/` を作る。新しく作ったフォルダ（会社のフォルダからの場所）を返す。"""
    made = []
    for path in (company / CASES_DIR, case_dir(company, name), official_dir(company, name)):
        if not path.is_dir():
            path.mkdir()
            made.append(str(path.relative_to(company)))
    return made


def stage_folders(stages: Iterable[Dict]) -> List[str]:
    """制度データの「手続きの段階」から、段階のフォルダの名前を順番どおりに並べる（「フォルダ」のある段階だけ）。"""
    named = [s for s in stages if s.get("フォルダ")]
    return [s["フォルダ"] for s in sorted(named, key=lambda s: s.get("順番", 0))]


def ensure_stage_folders(company: Path, name: str, folders: Iterable[str],
                         only: Optional[Iterable[str]] = None) -> List[str]:
    """段階のフォルダ（と、中の「申請書」「添付する書類」）を作る。新しく作ったフォルダを返す。

    only を渡すと、その名前の段階だけを作る（採択後に次の段階へ進むとき。M10）。
    """
    wanted = set(only) if only is not None else None
    base = case_dir(company, name)
    if not base.is_dir():
        raise CaseError(f"案件のフォルダがありません（{base.relative_to(company)}）")
    made = []
    for folder in folders:
        if not STAGE_NAME.match(folder) or safe_name(folder) != folder:
            raise CaseError(f"段階のフォルダの名前は「1_申請」の形にしてください（{folder}）")
        if wanted is not None and folder not in wanted:
            continue
        for path in [base / folder] + [base / folder / sub for sub in STAGE_SUBDIRS]:
            if not path.is_dir():
                path.mkdir()
                made.append(str(path.relative_to(company)))
    return made
