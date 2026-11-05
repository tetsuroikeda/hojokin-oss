"""T5-8 スキャンした書類の金額の準備（TASKS B11。testdata/スキャン/材料の一覧.md）。

保存した状態「書類の前」（原本のない形）を戻し、スキャンした PDF と写真の見積書3通・納品書・請求書（経費のメモは除く）を、
材料のとおりの名前で入れ口に入れる。今日の日付は「書く前」と同じ 2026-11-05。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

FILES = ("scan_20261104_0001.pdf", "IMG_2741.jpg", "FAX_20261006_1642.pdf", "scan_20261104_0003.pdf", "IMG_2742.jpg")

target = sc.restore("書類の前")
sc.put(target, {f"入れ口/{name}": f"スキャン/材料/{name}" for name in FILES})
sc.done({"書類": len(FILES)})
