"""実験 E6 の試し。今のフォルダに、目印と .claude/settings.json を作る（S5 の会社のフォルダを作る道具に見立てる）。"""

import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    folder = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    template = Path(__file__).resolve().parent.parent / "templates" / "settings.json"
    (folder / ".hojokin").mkdir(exist_ok=True)
    claude_dir = folder / ".claude"
    claude_dir.mkdir(exist_ok=True)
    target = claude_dir / "settings.json"
    shutil.copyfile(template, target)
    settings = json.loads(target.read_text(encoding="utf-8"))
    print(f"会社のフォルダを用意しました：{folder}")
    print(f"目印：{folder / '.hojokin'}")
    print(f"設定：{target}")
    print("設定の中身：" + json.dumps(settings["permissions"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
