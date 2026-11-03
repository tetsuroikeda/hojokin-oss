"""会社のフォルダを作る道具（DESIGN 4.7、TASKS S5）。社長の了承を得てから動かす。

使い方：
  python3 -B <この場所>/init_company.py --data-dir "${CLAUDE_PLUGIN_DATA}" [--folder "${CLAUDE_PROJECT_DIR}"]

- -B：Python の控え（__pycache__ や、Mac の ~/Library/Caches/com.apple.python）を書かない。

- Claude が Bash で動かすコマンドには、CLAUDE_PLUGIN_DATA・CLAUDE_PROJECT_DIR の環境変数が入らない（公式文書）。
  そのため、skill の本文に書いた `${…}` の置き換えで、引数として渡す。
  環境変数があればそれも使う。--folder がなければ、今いるフォルダを会社のフォルダにする。
- 最初に、補助プログラム（dulwich など）をデータの置き場の venv に用意し、その python で動かし直す（実験 E5）。
- 結果として、作ったものと、どの段階にも共通の決まりの短い文を出す
  （初めて使うセッションでは、SessionStart がもう動いた後のため。DESIGN 4.7）。
- 終了コード：0 用意した（すでに会社のフォルダだったときも）、1 補助プログラムを用意できない、2 会社のフォルダにできない。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import runtime  # noqa: E402


def parse(argv):
    parser = argparse.ArgumentParser(description="会社のフォルダを作る（社長の了承を得てから動かす）")
    parser.add_argument("--data-dir", help="プラグインのデータの置き場（${CLAUDE_PLUGIN_DATA}）")
    parser.add_argument("--folder", help="会社のフォルダにするフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    return parser.parse_args(argv)


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        data = runtime.data_dir(args.data_dir)
        if not runtime.running_in_venv(data):
            python = runtime.ensure(data)
            return runtime.reexec(python, os.path.abspath(__file__), list(argv))
    except runtime.SetupError as e:
        print(f"会社のフォルダを用意できませんでした。何も変えていません。\n\n{e}")
        return 1

    from lib import company, company_init

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    try:
        result = company_init.init(folder)
    except company_init.Refused as e:
        print(company_init.refusal(folder, e.reasons), end="")
        return 2
    print(company_init.report(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
