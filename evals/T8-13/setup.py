"""T8-13 経費明細の準備（TASKS B20。testdata/スキャン/材料の一覧.md の「T8-13 の正解」）。

保存した状態「書類の前」（原本のない形。省力化 第9回の案件と、第8回の制度データの正解がある）を戻し、
スキャンした見積書3通（つばさ台 10/20、ほしみ機工 10/20、つばさ台 10/6 の概算）と経費のメモの写真を入れ口に入れる。
今日の日付は 2026-11-05（概算の有効期限 2026-10-31 は切れている）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

FILES = ("scan_20261104_0001.pdf", "IMG_2741.jpg", "FAX_20261006_1642.pdf", "IMG_2745.jpg")

target = sc.restore("書類の前")
sc.put(target, {f"入れ口/{name}": f"スキャン/材料/{name}" for name in FILES})
sc.done({"書類": len(FILES)})
