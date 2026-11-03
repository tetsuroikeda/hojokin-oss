"""実験 E6 の試し。社長が伝えた外の場所のファイルを、会社のフォルダの「取り込み/」に写す。元のファイルは動かさない。"""

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("使い方：torikomi.py <場所>")
        return 1
    source = Path(sys.argv[1]).expanduser()
    if not source.is_file():
        print(f"ファイルが見つかりません：{source}")
        return 1
    folder = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    dest_dir = folder / "取り込み"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    print(f"写しました：{source} → {dest}")
    print("中身の1行目：" + dest.read_text(encoding="utf-8").splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
