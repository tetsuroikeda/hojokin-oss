"""同梱したライブラリ（lib/vendor/。置き方の決まりは lib/vendor/README.md）。

- wheel の中身を1バイトも変えずに置いている（RECORD のハッシュと照らす）。ほかのファイルを足していない
- Python だけの wheel で、C の拡張がない
- ライセンスの全文がある
- 社長の Mac と同じ /usr/bin/python3 で、通信のための urllib3 なしに、同梱の dulwich を読み込める
- 同じく /usr/bin/python3 で、同梱の pypdf（公式資料をページごとの文字にする。TASKS M2a）を読み込める
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import subprocess

import hook_runner as hr
import pytest

VENDOR = hr.REPO_ROOT / "lib" / "vendor"
PACKAGES = {"dulwich": "0.24.10", "typing_extensions": "4.16.0", "pypdf": "6.21.4"}
# dist-info のうち置くもの（コマンドの入口・entry_points.txt・top_level.txt は置かない）
KEPT_INFO = ("METADATA", "RECORD", "WHEEL", "licenses/")
README = "README.md"


def dist_info(name: str):
    return VENDOR / f"{name}-{PACKAGES[name]}.dist-info"


def record(name: str) -> list:
    """RECORD の行（場所、ハッシュ、大きさ）。"""
    with open(dist_info(name) / "RECORD", encoding="utf-8", newline="") as f:
        return [row for row in csv.reader(f) if row]


def kept(path: str) -> bool:
    """RECORD に載ったファイルのうち、同梱するもの。"""
    if ".dist-info/" in path:
        return path.split(".dist-info/", 1)[1].startswith(KEPT_INFO)
    return ".data/" not in path


def sha256_of(path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize("name", list(PACKAGES))
def test_files_match_wheel_record(name) -> None:
    """RECORD に載った同梱のファイルは、wheel のときと同じ中身。載っていても置かないものは、ない。"""
    rows = record(name)
    assert rows
    for path, digest, _size in rows:
        target = VENDOR / path
        if path.endswith("/RECORD"):
            assert target.is_file()
        elif kept(path):
            assert target.is_file(), path
            assert sha256_of(target) == digest, path
        else:
            assert not target.exists(), path


def test_nothing_else_is_added() -> None:
    """RECORD にないファイル（__pycache__、C の拡張、手で足したものなど）を置いていない。README は除く。"""
    listed = {path for name in PACKAGES for path, _d, _s in record(name) if kept(path)}
    present = {str(p.relative_to(VENDOR)) for p in VENDOR.rglob("*") if p.is_file()}
    assert present - listed == {README}
    for suffix in (".so", ".pyd", ".dylib", ".dll", ".c", ".pyc"):
        assert not list(VENDOR.rglob(f"*{suffix}")), suffix
    # 通信の機能にだけ使う urllib3 は入れない
    assert not (VENDOR / "urllib3").exists()


@pytest.mark.parametrize("name", list(PACKAGES))
def test_pure_python_wheel(name) -> None:
    info = dist_info(name)
    wheel = (info / "WHEEL").read_text(encoding="utf-8")
    assert "Root-Is-Purelib: true" in wheel
    assert "Tag: py3-none-any" in wheel
    metadata = (info / "METADATA").read_text(encoding="utf-8")
    assert f"Version: {PACKAGES[name]}" in metadata
    # Python 3.9 で動く版
    assert "Requires-Python: >=3.9" in metadata


def test_license_texts_are_bundled() -> None:
    """dulwich は Apache-2.0 か GPL-2.0-or-later を選べる（このリポジトリでは Apache-2.0）。typing_extensions は PSF-2.0。"""
    copying = (dist_info("dulwich") / "licenses" / "COPYING").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0 OR GPL-2.0-or-later" in copying
    assert "Apache License" in copying and "Version 2.0" in copying
    assert "License-Expression: Apache-2.0 OR GPL-2.0-or-later" in (dist_info("dulwich") / "METADATA").read_text(
        encoding="utf-8")
    te = dist_info("typing_extensions")
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in (te / "licenses" / "LICENSE").read_text(encoding="utf-8")
    assert "License-Expression: PSF-2.0" in (te / "METADATA").read_text(encoding="utf-8")
    pdf = dist_info("pypdf")
    assert "Redistribution and use in source and binary forms" in (pdf / "licenses" / "LICENSE").read_text(
        encoding="utf-8")
    assert "License-Expression: BSD-3-Clause" in (pdf / "METADATA").read_text(encoding="utf-8")
    readme = (VENDOR / README).read_text(encoding="utf-8")
    for name, version in PACKAGES.items():
        assert name in readme and version in readme


LOAD_CODE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from lib import history
import dulwich
print(json.dumps({
    "dulwich": dulwich.__file__,
    "version": list(dulwich.__version__),
    "typing_extensions": sys.modules["typing_extensions"].__file__ if "typing_extensions" in sys.modules else None,
    "urllib3": "urllib3" in sys.modules,
    "compiled": sorted(m for m in sys.modules if m.startswith("dulwich._")),
}))
"""


def test_history_loads_bundled_dulwich_on_system_python(tmp_path) -> None:
    """lib/history.py は、利用者の site-packages を読まない（-I）/usr/bin/python3 でも、同梱の dulwich で動く。"""
    plugin = tmp_path / "plugin"
    hr.copy_plugin(plugin)
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", LOAD_CODE, str(plugin)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    seen = json.loads(r.stdout.decode("utf-8"))
    vendor = plugin / "lib" / "vendor"
    assert seen["dulwich"] == str(vendor / "dulwich" / "__init__.py")
    assert seen["version"] == [0, 24, 10]
    if seen["typing_extensions"] is not None:
        assert seen["typing_extensions"] == str(vendor / "typing_extensions.py")
    assert seen["urllib3"] is False
    assert seen["compiled"] == []
    # プラグインの場所に __pycache__ を書かない
    assert not list(plugin.rglob("__pycache__"))


PYPDF_LOAD_CODE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from lib import doc_text
import pypdf
print(json.dumps({
    "pypdf": pypdf.__file__,
    "version": pypdf.__version__,
    "typing_extensions": sys.modules["typing_extensions"].__file__ if "typing_extensions" in sys.modules else None,
}))
"""


def test_doc_text_loads_bundled_pypdf_on_system_python(tmp_path) -> None:
    """lib/doc_text.py は、利用者の site-packages を読まない /usr/bin/python3 でも、同梱の pypdf で動く。"""
    plugin = tmp_path / "plugin"
    hr.copy_plugin(plugin)
    r = subprocess.run(
        [hr.real_python(), "-I", "-B", "-c", PYPDF_LOAD_CODE, str(plugin)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8")
    seen = json.loads(r.stdout.decode("utf-8"))
    vendor = plugin / "lib" / "vendor"
    assert seen["pypdf"] == str(vendor / "pypdf" / "__init__.py")
    assert seen["version"] == PACKAGES["pypdf"]
    if seen["typing_extensions"] is not None:
        assert seen["typing_extensions"] == str(vendor / "typing_extensions.py")
    assert not list(plugin.rglob("__pycache__"))
