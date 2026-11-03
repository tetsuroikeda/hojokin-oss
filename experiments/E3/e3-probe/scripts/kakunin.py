"""実験 E3 のスクリプト。eval の中で、Bash（sandbox の中）から動くかを見る。

今のフォルダ（eval の作業フォルダ）で、scaffold が戻した会社のフォルダと、
downloads/ から写した公式資料がそろっているかを確かめ、結果を 記録/確かめ.json に書く。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_WORD = "ひまわり5"
OFFICIAL = Path("案件") / "2026_省力化（一般型）第8回" / "公式資料"
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK"}


def main() -> int:
    here = Path.cwd()
    result: dict = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": str(here),
        "HOME": os.environ.get("HOME"),
        "目印": (here / ".hojokin").is_dir(),
        "版の履歴": (here / ".git").is_dir(),
    }
    try:
        record = json.loads((here / "記録" / "会社の記録.json").read_text(encoding="utf-8"))
        result["社名"] = record.get("社名")
    except (OSError, ValueError) as e:
        result["社名"] = f"読めない：{e}"

    files = []
    folder = here / OFFICIAL
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            head = p.read_bytes()[:4]
            files.append({
                "名前": p.name,
                "大きさ": p.stat().st_size,
                "中身の形が合う": head.startswith(MAGIC.get(p.suffix.lower(), b"")),
            })
    result["公式資料"] = files

    # プラグインの中のほかのファイルが、sandbox の中から読めるか
    skill = Path(__file__).resolve().parent.parent / "skills" / "kakunin" / "SKILL.md"
    try:
        result["プラグインの中を読めた"] = len(skill.read_text(encoding="utf-8")) > 0
    except OSError as e:
        result["プラグインの中を読めた"] = f"読めない：{e}"

    ok = bool(result["目印"]) and bool(files) and all(f["中身の形が合う"] for f in files)
    result["そろった"] = ok
    out = here / "記録" / "確かめ.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if ok:
        print(f"スクリプトの合言葉：{SCRIPT_WORD}（公式資料 {len(files)} 件）")
    else:
        print("スクリプトの合言葉：出せない（目印か公式資料が足りない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
