"""T0-4 公式ファイルを含めない（SPEC 共通の要件、5.4）。

合格ライン：プラグインのリポジトリに公募要領・様式のファイルが0件。
公式資料そのものに加え、公式の様式から作ったテストの材料（手で直した計画書の Word など）も入れない（DESIGN 11章）。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from conftest import REPO_ROOT

# 公式資料らしい名前の語。文書のファイルの名前にあれば、公式資料とみなす
OFFICIAL_NAME_WORDS = re.compile(
    r"公募要領|様式|手引き|交付規程|事務局マニュアル|koubo|yoshiki|tebiki|guideline|manual",
    re.IGNORECASE,
)
DOCUMENT_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".zip"}
OFFICE_SUFFIXES = {".docx", ".xlsx", ".xlsm"}

# 公式の様式の文がこの割合より多く入っている Word・Excel は、様式から作ったものとみなす
DERIVED_RATIO = 0.5
MIN_TEXT_LEN = 8


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _office_texts(path: Path) -> set[str]:
    """Word・Excel の中の文（段落とセルの文字）を集める。"""
    texts: set[str] = set()
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if not name.endswith(".xml"):
                    continue
                if not (name.startswith("word/") or name == "xl/sharedStrings.xml" or name.startswith("xl/worksheets/")):
                    continue
                xml = zf.read(name).decode("utf-8", errors="ignore")
                # Word は段落ごと、Excel は文字列ごとにまとめる
                for block in re.findall(r"<w:p[ >].*?</w:p>|<si>.*?</si>|<is>.*?</is>", xml, flags=re.S):
                    text = "".join(re.findall(r"<(?:w:)?t(?: [^>]*)?>([^<]*)</(?:w:)?t>", block)).strip()
                    if len(text) >= MIN_TEXT_LEN:
                        texts.add(text)
    except zipfile.BadZipFile:
        pass
    return texts


def test_downloads_is_ignored() -> None:
    """downloads/ が Git の外にある。"""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "downloads/x.pdf"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, "downloads/ が .gitignore に入っていません"


def test_no_file_under_downloads(repo_files: list[Path]) -> None:
    """downloads/ の下のファイルがリポジトリに入っていない。"""
    found = [str(p.relative_to(REPO_ROOT)) for p in repo_files if p.relative_to(REPO_ROOT).parts[0] == "downloads"]
    assert found == [], f"downloads/ のファイルがリポジトリにあります：{found}"


def test_no_copy_of_official_files(repo_files: list[Path], downloads_files: list[Path]) -> None:
    """公式資料と同じ中身のファイルがリポジトリにない（名前を変えた写しも含む）。"""
    official = {_sha256(p): p for p in downloads_files}
    found = []
    for p in repo_files:
        h = _sha256(p)
        if h in official:
            found.append(f"{p.relative_to(REPO_ROOT)}（{official[h].relative_to(REPO_ROOT)} と同じ）")
    assert found == [], f"公式資料の写しがリポジトリにあります：{found}"


def test_no_official_file_names(repo_files: list[Path], downloads_files: list[Path]) -> None:
    """公式資料と同じ名前の文書や、公式資料らしい名前の文書がリポジトリにない。"""
    official_names = {p.name for p in downloads_files if p.suffix.lower() in DOCUMENT_SUFFIXES}
    found = []
    for p in repo_files:
        if p.suffix.lower() not in DOCUMENT_SUFFIXES:
            continue
        if p.name in official_names or OFFICIAL_NAME_WORDS.search(p.name):
            found.append(str(p.relative_to(REPO_ROOT)))
    assert found == [], f"公式資料らしい名前の文書がリポジトリにあります：{found}"


def test_no_file_made_from_official_forms(repo_files: list[Path], downloads_files: list[Path]) -> None:
    """公式の様式（Word・Excel）から作ったファイルがリポジトリにない。"""
    forms = [(p, _office_texts(p)) for p in downloads_files if p.suffix.lower() in OFFICE_SUFFIXES]
    forms = [(p, t) for p, t in forms if t]
    if not forms:
        pytest.skip("downloads/ に Word・Excel の様式がありません")
    found = []
    for p in repo_files:
        if p.suffix.lower() not in OFFICE_SUFFIXES:
            continue
        texts = _office_texts(p)
        for form, form_texts in forms:
            ratio = len(form_texts & texts) / len(form_texts)
            if ratio > DERIVED_RATIO:
                found.append(f"{p.relative_to(REPO_ROOT)}（{form.name} の文の {ratio:.0%} を含む）")
    assert found == [], f"公式の様式から作ったファイルがリポジトリにあります：{found}"


def test_detector_finds_forms(downloads_files: list[Path]) -> None:
    """様式から文を取り出せている（取り出せないと、上のテストが何も見ずに通ってしまう）。"""
    forms = [p for p in downloads_files if p.suffix.lower() in OFFICE_SUFFIXES]
    if not forms:
        pytest.skip("downloads/ に Word・Excel の様式がありません")
    for form in forms:
        assert len(_office_texts(form)) >= 5, f"{form.name} から文を取り出せません"
