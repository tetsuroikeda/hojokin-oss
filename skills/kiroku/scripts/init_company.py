"""会社のフォルダを作る道具（DESIGN 4.7、TASKS S5）。社長の了承を得てから動かす。

使い方：
  python3 -B <この場所>/init_company.py [--folder "${CLAUDE_PROJECT_DIR}"]

- -B：Python の控え（__pycache__ や、Mac の ~/Library/Caches/com.apple.python）を書かない。

- Claude が Bash で動かすコマンドには、CLAUDE_PROJECT_DIR の環境変数が入らない（公式文書）。
  そのため、skill の本文に書いた `${…}` の置き換えで、引数として渡す。
  環境変数があればそれも使う。--folder がなければ、今いるフォルダを会社のフォルダにする。
- 版の履歴に使う dulwich はプラグインに同梱している（lib/vendor/）。通信も venv の準備もなしに、
  /usr/bin/python3（3.9）のまま動く。--data-dir（${CLAUDE_PLUGIN_DATA}）は、前の呼び方のために受け付けるが使わない。
- 結果として、作ったものと、どの段階にも共通の決まりの短い文を出す
  （初めて使うセッションでは、SessionStart がもう動いた後のため。DESIGN 4.7）。
- 終了コード：0 用意した（すでに会社のフォルダだったときも）、
  1 補助プログラムが動かない（読み込めない。途中で止まったときは、書きかけたものを戻す）、
  2 会社のフォルダにできない（ホームのフォルダ、ディスクの根、前からある設定、同期されるフォルダなど。何も書いていない）。
  2 のときの出力には、社長への案内（新しいフォルダで始め、書類は取り込む）と、
  同期されるフォルダなら版の持ち方を選んでもらう問いが入る（DESIGN 4.7、TASKS S5b）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))


def parse(argv):
    parser = argparse.ArgumentParser(description="会社のフォルダを作る（社長の了承を得てから動かす）")
    parser.add_argument("--folder", help="会社のフォルダにするフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--data-dir", help="使わない（前の呼び方のために受け付ける）")
    return parser.parse_args(argv)


def main(argv) -> int:
    # 環境の文字コードによらず、日本語の結果を UTF-8 で返す
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse(argv)
    try:
        from lib import company, company_init, history  # noqa: F401（同梱の dulwich を、何か書く前に読み込む）
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(
            "会社のフォルダを用意できませんでした。何も変えていません。\n\n"
            f"補助プログラム（版の履歴に使う dulwich）を読み込めませんでした（{type(e).__name__}: {e}）。"
            "プラグインを入れ直してから、もう一度試してください。"
        )
        return 1

    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    try:
        result = company_init.init(folder)
    except company_init.Refused as e:
        print(company_init.refusal(folder, e.reasons, e.synced), end="")
        return 2
    except Exception as e:  # dulwich が使うときだけ読み込むモジュールが欠けていた、など。init() が書いたものを戻した後
        print(
            "会社のフォルダを用意できませんでした。途中で止まったため、書きかけたものを元に戻しました。\n\n"
            f"補助プログラムが途中で止まりました（{type(e).__name__}: {e}）。"
            "続けて起きるときは、プラグインを入れ直してから、もう一度試してください。"
        )
        return 1
    print(company_init.report(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
