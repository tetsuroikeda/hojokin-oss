"""T8-2 ファイルが開ける（SPEC F8。自動の部分。TASKS B14b）。

合格ライン：LibreOffice で変換し、Word と Excel でも開く → 変換エラーなし。修復のメッセージが出ない。
Word と Excel で開いて修復のメッセージが出ないことは、作者が人の確かめ（A10）で見る。ここでは自動の部分を確かめる。

- 書き終えた その1・2.docx（すべての項目と欄）、その3.xlsx（その3・別紙1・別紙3・別紙4 の入力）、入力シート.xlsx
  （ツールが入れる欄すべて）を、LibreOffice で PDF に変換できる（変換エラーなし）。
- 修復を求められる主な原因がないこと：すべての XML の部品が読める、[Content_Types].xml がすべての部品の種類を
  持つ、Word の段落の番号（w14:paraId）の重なりを足していない（公式の様式にもとから1つ重なりがある）、
  Excel は同梱の openpyxl でも読める。

LibreOffice がなければ飛ばす。様式は downloads/ から読み、作ったファイルは tmp_path にだけ置く。
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import hook_runner as hr
import pytest
import test_T8_1 as t81
import test_write_min as twm
import test_write_word as tww
import zaimu_tool as zt

from lib import input_sheet


def _well_formed(blob: bytes) -> None:
    parts = twm.parts_of(blob)
    types = ET.fromstring(parts["[Content_Types].xml"])
    defaults = {e.get("Extension").lower() for e in types if e.tag.endswith("Default")}
    overrides = {e.get("PartName").lstrip("/") for e in types if e.tag.endswith("Override")}
    for name, data in parts.items():
        if name.endswith((".xml", ".rels", ".vml")):
            ET.fromstring(data)  # 読めないと例外
        if name != "[Content_Types].xml" and not name.endswith("/"):
            ext = name.rsplit(".", 1)[-1].lower()
            assert name in overrides or ext in defaults, name


def _duplicate_para_ids(blob: bytes) -> set:
    doc = twm.parts_of(blob)["word/document.xml"]
    ids = re.findall(rb'w14:paraId="([0-9A-Fa-f]+)"', doc)
    return {i for i in ids if ids.count(i) > 1}


def _no_new_duplicate_para_ids(blob: bytes, official: bytes) -> None:
    """書いた段落に、重なる段落の番号を足していない（公式の様式にもとからある重なりは除く）。"""
    assert _duplicate_para_ids(blob) <= _duplicate_para_ids(official)


def _convert(soffice: str, src: Path, work: Path) -> Path:
    profile, out = work / "profile", work / "out"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text(zt.RECALC_XCU, encoding="utf-8")
    out.mkdir()
    r = subprocess.run([soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                        "--nologo", "--convert-to", "pdf", "--outdir", str(out), str(src)],
                       capture_output=True, timeout=900, stdin=subprocess.DEVNULL)
    pdf = out / (src.stem + ".pdf")
    assert r.returncode == 0 and pdf.is_file(), (r.stdout + r.stderr).decode("utf-8", "replace")
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 5_000
    return pdf


OPENPYXL_LOAD = r"""
import sys, warnings
sys.path.insert(0, sys.argv[1])
import openpyxl
warnings.simplefilter("ignore")
wb = openpyxl.load_workbook(sys.argv[2])
print(len(wb.sheetnames))
"""


@pytest.mark.slow
def test_written_files_convert_without_errors(tmp_path: Path, form3: bytes) -> None:
    soffice = zt.soffice_or_skip()
    if not twm.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません")
    env = t81.Env(tmp_path, twm.FORM.read_bytes(), form3)
    seido = json.loads(tww.SEIKAI.read_text(encoding="utf-8"))
    (env.folder / twm.SEIDO_IN_FOLDER).write_text(json.dumps(seido, ensure_ascii=False), encoding="utf-8")
    tww.write_all(env)
    twm.ok(env.run("cells", "--input", env.put("記録/一時/その3の値.json", {"値": t81.VALUES})))
    values = [{"画面": s["名前"], "欄": f["名前"], "値": 1 if f.get("種類") == "数字" else "試し"}
              for s, f in input_sheet.fields_of(seido) if not f.get("担当者が入れる")
              and f.get("種類") not in ("チェック", "選択", "ファイル")]
    twm.ok(env.run("sheet", "--values", env.put("記録/一時/入力シートの値.json", {"値": values})))

    word = env.folder / twm.APP
    excel = env.folder / t81.APP3
    sheet = env.folder / twm.SHEET
    for path in (word, excel, sheet):
        _well_formed(path.read_bytes())
    _no_new_duplicate_para_ids(word.read_bytes(), twm.FORM.read_bytes())
    for path in (excel, sheet):
        r = subprocess.run([hr.real_python(), "-I", "-B", "-c", OPENPYXL_LOAD, str(zt.REPO_ROOT / "lib" / "vendor"),
                            str(path)], capture_output=True, timeout=300, env={"PATH": "/usr/bin:/bin"})
        assert r.returncode == 0, r.stderr.decode("utf-8")
    for n, path in enumerate((word, excel, sheet)):
        _convert(soffice, path, tmp_path / f"lo{n}")


@pytest.fixture(scope="module")
def form3() -> bytes:
    if not t81.FORM3.is_file():
        pytest.skip("downloads/ に省力化の様式（その3）がありません")
    return t81.FORM3.read_bytes()
