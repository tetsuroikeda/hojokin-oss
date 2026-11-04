"""財務モデルの道具（skills/kaku/scripts/zaimu_model.py）のテストに共通の部品（TASKS M5。test_T8_4.py・test_zaimu_min.py）。

- 道具は、社長の Mac と同じ /usr/bin/python3 で、Claude が Bash で動かすのと同じく引数で場所を渡して動かす。
- 同梱の openpyxl は、テストの Python の中では読み込まない（lib/vendor/ に __pycache__ ができるため）。
  Excel のファイルを読むときも /usr/bin/python3 -I -B で読む。
- LibreOffice で計算し直すテストは、LibreOffice がなければ飛ばす。計算し直しは、道具（lib/libreoffice.py）とは別に、
  ここで soffice を直接動かす（道具の確かめに頼らずに、テストの側でも確かめるため）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import hook_runner as hr
import pytest

REPO_ROOT = hr.REPO_ROOT
SCRIPT = Path("skills") / "kaku" / "scripts" / "zaimu_model.py"
DATA = REPO_ROOT / "tests" / "data" / "zaimu"
SEIDO = DATA / "省力化_第8回_数値の要件.json"
SPEC3 = DATA / "指定_前提3つ.json"
MODEL = "財務モデル.xlsx"
SEIDO_IN_FOLDER = "記録/制度データ/省力化_第8回.json"
SPEC_IN_FOLDER = "記録/財務モデルの指定.json"


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def copy_plugin(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("lib", "skills"):
        shutil.copytree(REPO_ROOT / name, dest / name, ignore=ignore)
    return dest


def boundary_spec(years: int = 3, pay_at_end: float = 8_869_743) -> dict:
    """ちょうど 3.5% の給与の伸びの計画（実験 E2：800万円 → 3年後 8,869,743円 は、別紙4 では 3.49%）。

    給与を受けた従業員は1人。前提は3つ（給与の最後の年の値・新しい売上の単価と数量）。
    """
    spec = load(SPEC3)
    spec["計画の年数"] = years
    spec["前提"] = [
        {"名前": "給与_最後の年", "値": pay_at_end, "単位": "円", "説明": "最後の年の給与支給総額", "根拠": "聞き取り",
         "出典": "社長の答え（架空）"},
        {"名前": "単価_新商品", "値": 1000, "単位": "円/個", "説明": "新しい商品1個の値段", "根拠": "見積書", "出典": "見積書（架空）"},
        {"名前": "数量_新商品", "値": 12000, "単位": "個/年", "説明": "1年に売る数", "根拠": "聞き取り", "出典": "社長の答え（架空）"},
    ]
    spec["基準年度"]["給与支給総額"] = 8_000_000
    spec["基準年度"]["給与を受けた従業員数"] = 1
    # 最後の年に「給与_最後の年」になるよう、年平均で伸ばす（途中の年も同じ伸び）
    spec["既存事業"] = {"給与支給総額": f"基準_給与支給総額*(給与_最後の年/基準_給与支給総額)^(年/{years})"}
    return spec


class Env:
    """1つのテストで使う、プラグインの写し・HOME・PATH など。"""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.plugin = copy_plugin(tmp_path / "plugin")
        self.home = tmp_path / "home"
        self.tmp = tmp_path / "tmp"
        self.cwd = tmp_path / "どこか"
        for d in (self.home, self.tmp, self.cwd):
            d.mkdir()
        self.path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "python-ran")
        self.no_soffice = str(tmp_path / "LibreOffice はない" / "soffice")

    def company(self, name: str = "山田 製作所", spec=None, seido=True) -> Path:
        """会社のフォルダ（目印と、制度データと、財務モデルの指定）。"""
        folder = self.root / name
        (folder / ".hojokin").mkdir(parents=True)
        if seido:
            target = folder / SEIDO_IN_FOLDER
            target.parent.mkdir(parents=True)
            seido_data = load(SEIDO) if seido is True else seido
            target.write_text(json.dumps(seido_data, ensure_ascii=False), encoding="utf-8")
        target = folder / SPEC_IN_FOLDER
        target.parent.mkdir(parents=True, exist_ok=True)
        data = load(SPEC3) if spec is None else spec
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return folder

    def run(self, folder: Optional[Path], *args: str, soffice: Optional[str] = "なし", stdin: bytes = b"",
            timeout: int = 900) -> subprocess.CompletedProcess:
        """道具を動かす。soffice="なし" なら LibreOffice がない場合、None なら道具が探す、それ以外はその場所。"""
        argv = ["build"]
        if folder is not None:
            argv += ["--folder", str(folder)]
        if not any(a == "--spec" for a in args):
            argv += ["--spec", SPEC_IN_FOLDER]
        argv += list(args)
        if soffice == "なし":
            argv += ["--soffice", self.no_soffice]
        elif soffice is not None:
            argv += ["--soffice", soffice]
        env = {"PATH": self.path, "HOME": str(self.home), "TMPDIR": str(self.tmp)}
        return subprocess.run(
            [hr.real_python(), "-B", str(self.plugin / SCRIPT), *argv],
            env=env,
            cwd=self.cwd,
            input=stdin,
            capture_output=True,
            timeout=timeout,
        )

    def outside(self) -> dict:
        return hr.snapshot(self.plugin, self.home, self.tmp, self.cwd)


def out(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode("utf-8")


def ok(r: subprocess.CompletedProcess) -> str:
    text = out(r)
    assert r.returncode == 0, (r.returncode, text, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return text


def ok_json(r: subprocess.CompletedProcess) -> dict:
    return json.loads(ok(r))


# ---------------------------------------------------------------- Excel のファイルを読む（/usr/bin/python3 と同梱の openpyxl）

DUMP_CODE = r"""
import json, sys, warnings
sys.path.insert(0, sys.argv[1])
import openpyxl
warnings.simplefilter("ignore")
path, data_only = sys.argv[2], sys.argv[3] == "1"
wb = openpyxl.load_workbook(path, data_only=data_only)
out = {"sheets": wb.sheetnames, "names": {n: d.attr_text for n, d in wb.defined_names.items()}, "cells": {}, "fills": {},
       "formats": {}}
for ws in wb.worksheets:
    cells, fills, formats = {}, {}, {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                cells[c.coordinate] = c.value
            if c.fill is not None and c.fill.fill_type == "solid":
                fills[c.coordinate] = str(c.fill.start_color.rgb)[-6:]
            if c.value is not None:
                formats[c.coordinate] = c.number_format
    out["cells"][ws.title] = cells
    out["fills"][ws.title] = fills
    out["formats"][ws.title] = formats
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def dump_xlsx(path: Path, data_only: bool = False) -> dict:
    """Excel のファイルの中身（シート、名前、セルの値か数式、塗り、表示形式）。"""
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", DUMP_CODE, str(REPO_ROOT / "lib" / "vendor"), str(path),
         "1" if data_only else "0"],
        env={"PATH": "/usr/bin:/bin", "HOME": str(path.parent)},
        capture_output=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    return json.loads(r.stdout.decode("utf-8"))


def row_of(cells: dict, label: str) -> int:
    """A 列が label の行の番号。"""
    rows = [int(ref[1:]) for ref, v in cells.items() if ref.startswith("A") and ref[1:].isdigit() and v == label]
    assert len(rows) == 1, (label, rows)
    return rows[0]


# ---------------------------------------------------------------- LibreOffice（テストの側で、道具とは別に動かす）

def soffice_or_skip() -> str:
    for place in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                  os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice")):
        if os.access(place, os.X_OK):
            return place
    found = shutil.which("soffice")
    if found:
        return found
    pytest.skip("LibreOffice がありません（計算し直しのテストは、LibreOffice のある所で流す）")


RECALC_XCU = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item></oor:items>'
)


def recalc(src: Path, work: Path) -> Path:
    """計算し直しを「常に」にした、テスト用のプロフィールの LibreOffice で開いて保存し直す。"""
    soffice = soffice_or_skip()
    profile, inbox, outbox = work / "profile", work / "in", work / "out"
    (profile / "user").mkdir(parents=True)
    (profile / "user" / "registrymodifications.xcu").write_text(RECALC_XCU, encoding="utf-8")
    inbox.mkdir()
    outbox.mkdir()
    copy = inbox / "book.xlsx"
    shutil.copyfile(src, copy)
    r = subprocess.run(
        [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nologo",
         "--convert-to", "xlsx:Calc Office Open XML", "--outdir", str(outbox), str(copy)],
        capture_output=True,
        timeout=900,
        stdin=subprocess.DEVNULL,
    )
    result = outbox / "book.xlsx"
    assert r.returncode == 0 and result.is_file(), (r.stdout + r.stderr).decode("utf-8", "replace")
    return result
