"""T5-3 開いたときの確認の準備（TASKS B9。testdata/書類の変化/材料の一覧.md の案 B）。

1. 保存した状態「書類の前」を戻す（原本のない形。材料の書類が、保存した原本と同じ中身にならないように）。
2. 前の6件（testdata/書類の変化/開いたときの確認/前/）を写し、開いたときの控えを作る
   （前回開いたときに見つけたが、社長が別のことを先に頼んだので、整理はしていない形）。ここまでを「ツール」の版にする。
3. 後の形（1つ足し・1つ書き換え・1つ動かし・1つ名前を変え）に変えてから、eval が Claude を開く。
今日の日付は、書き換えた労働者名簿の「2026年11月15日現在」より後にする。
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

SOURCE = "書類の変化/開いたときの確認"

target = sc.restore("書類の前")
sc.set_today(target, "2026-11-16")
sc.put_folder(target, f"{SOURCE}/前")
before = sc.remember_opening(target)
sc.record(target, "T5-3 の準備：前回開いたときの書類")
# 後の形にする（社長が閉じている間にしたこと）
after = sc.TESTDATA / SOURCE / "後"
for rel in ("入れ口/役員名簿.docx", "社長の書類/カタログ_つばさ台フードシステム.pdf"):
    (target / rel).unlink()
for path in sorted(after.rglob("*")):
    if path.is_file():
        rel = path.relative_to(after).as_posix()
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(path), str(dest))
sc.done({"前の書類": len(before["変化"])})
