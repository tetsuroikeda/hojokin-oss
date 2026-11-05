"""社長が会社の記録を手で直した形を作る（eval の scaffold から。TASKS B4 の T13-11、台本「記録の手直し」）。

会社の記録（記録/会社の記録.json）の、名前に「強み」を含む事実の値の終わりに、台本の「足す文」を足す。
ほかの欄（id・出典・覚えた日・最後に確かめた日・状態）は変えない。版の履歴には入れない（閉じている間に社長が直した形。
開いたとき・送ったときに、版の記録が「社長」で残す）。直した後も、会社の記録の形（schema）に合うことを確かめる。

使い方（今いるフォルダ＝会社のフォルダ）：/usr/bin/python3 -B evals/_lib/kiroku_tenaoshi.py
- 終了コード：0 直した、1 直せなかった（強みの事実がない、形が合わないなど）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
LIB_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = LIB_DIR.parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

ADD = "2026年10月から、のみこむ力が弱い方向けに、おかずをゼリーで固めたゼリー食も始めた。"


def tenaoshi(folder: Path) -> str:
    from lib import company_record as cr

    path = folder / cr.RECORD_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    found = [it for it in data["項目"] if it["種類"] == cr.FACT and "強み" in it["名前"]]
    if not found:
        raise RuntimeError("会社の記録に、名前に「強み」を含む事実がありません")
    item = found[0]
    value = item["値"]
    if isinstance(value, list):
        item["値"] = value + [ADD]
    else:
        text = str(value).rstrip()
        item["値"] = text + ("" if text.endswith("。") else "。") + ADD
    errors = cr.validate(data)
    if errors:
        raise RuntimeError("直した後の記録が、形に合いません：" + "／".join(errors[:3]))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return item["id"]


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        fact_id = tenaoshi(folder)
    except Exception as e:
        print(f"kiroku_tenaoshi: できませんでした（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    print(f"kiroku_tenaoshi: ok {fact_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
