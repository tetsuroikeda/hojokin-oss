"""T5-6 原本の差し替えの準備（TASKS B10。testdata/書類の変化/材料の一覧.md の3章）。

保存した状態「書く前」（原本に、発行日 2026-10-23 の納税証明書（その2）がある）を戻し、その原本から、
省力化の案件の 1_申請/添付する書類/ に写しを作る（写しを作る道具 lib/utsushi.py）。ここまでを「ツール」の版にする。
今日の日付を 2026-11-16 にし、取り直した納税証明書（発行日 2026-11-16）を入れ口に入れてから、eval が Claude を開く。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
import shorui_case as sc  # noqa: E402

OLD = "原本/決算・税/2026-10-23_納税証明書（その2）.pdf"

target = sc.restore("書く前")
sc.set_today(target, "2026-11-16")
from lib import utsushi  # noqa: E402

copy = utsushi.make(target, [OLD], sc.CASE, "1_申請", "納税証明書（その2）")
sc.record(target, "T5-6 の準備：納税証明書の写し")
sc.remember_opening(target)
sc.put(target, {"入れ口/納税証明書_その2_11月.pdf": "書類の変化/取り直した納税証明書/納税証明書_その2_11月.pdf"})
sc.done({"写し": copy["場所"]})
