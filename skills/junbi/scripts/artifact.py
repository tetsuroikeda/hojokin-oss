"""claude.ai に上げる今の状態（Artifact）の道具（SPEC F6、共通の要件の②。DESIGN 4.6・5章の文案。中身は lib/status_artifact.py）。

使い方（どれも --folder "${CLAUDE_PROJECT_DIR}" を付ける）：
  1. 上げる画面を作る（会社名・金額・相手先を除いた写し）。上げるもの・上げないもの・だれが見られるか・同意の有無と、
     Artifact の道具に渡す値を出す
       python3 -B <この場所>/artifact.py --folder "${CLAUDE_PROJECT_DIR}" --make
  2. 社長の同意を残す（選択肢の画面で、社長が「上げる」を選んだときだけ）
       python3 -B <この場所>/artifact.py --folder "${CLAUDE_PROJECT_DIR}" --agree
  3. 上げた先の URL を残す（次から同じ URL を上げ直す）
       python3 -B <この場所>/artifact.py --folder "${CLAUDE_PROJECT_DIR}" --url "https://claude.ai/artifact/…"
  4. やめる（次から上げることを hook が拒む。上げたページは消さないので、消し方を出す）
       python3 -B <この場所>/artifact.py --folder "${CLAUDE_PROJECT_DIR}" --stop

- 画面は `.hojokin/一時/今の状態_claudeai.html` に置き、中身のハッシュを控える。PreToolUse の hook は、この画面が控えと
  同じ中身で、同意があるときだけ、Artifact の道具で上げることを通す（hooks/artifact_hooks.py）。
- 正本は、パソコンの 今の状態.html のまま。上げた画面は、上げた時点のまま古くなる。
- 終了コード：0 できた。2 動かさなかった（会社のフォルダでない、入れてはいけないものが入った、同意がない、URL の形が違う、
  書く先が別名など。何も書いていない）。3 補助プログラムが動かない、または途中で止まった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

NOT_DONE = "何も書いていません。\n\n"
BROKEN = 3


def parse(argv):
    parser = argparse.ArgumentParser(description="claude.ai に上げる今の状態")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--make", action="store_true", help="上げる画面を作る")
    group.add_argument("--agree", action="store_true", help="社長の同意を残す")
    group.add_argument("--url", metavar="URL", help="上げた先の URL を残す")
    group.add_argument("--stop", action="store_true", help="やめる")
    return parser.parse_args(argv)


def bullet(items):
    return "\n".join(f"- {x}" for x in items)


def made_text(folder, path) -> str:
    from lib import status_artifact as sa

    values = sa.call_values(folder)
    lines = [
        f"claude.ai に上げる画面を作りました：{path}",
        "",
        "## 上げるもの",
        bullet(sa.INCLUDED),
        "",
        "## 上げないもの",
        bullet(sa.EXCLUDED),
        "",
        "## だれが見られるか",
        sa.WHO_CAN_SEE,
        "",
    ]
    if sa.agreed(folder):
        lines += [f"社長の同意：あり（{sa.record(folder).get(sa.AGREED)}）。聞き直さずに、そのまま上げてかまいません。", ""]
    else:
        lines += ["社長の同意：まだありません。上の3つを社長に示し、選択肢の画面で上げるかを聞いてください。"
                  "「上げる」を選んだら --agree で残してから上げます。", ""]
    lines += ["## Artifact の道具に渡す値（このとおりに渡す。ほかの値を足さない。画面は直さずに、そのまま上げる）"]
    lines += [f"- {k}: {v}" for k, v in values.items()]
    if "url" in values:
        lines.append("- 前に上げた URL を更新します。この会話でまだ読んでいなければ、先に action: \"read\" でその URL を読みます。")
    else:
        lines.append("- 上げた後、結果の URL を --url で残してください（次から同じ URL を更新するため）。")
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    try:
        from lib import company, status_artifact as sa
    except Exception as error:  # noqa: BLE001
        print(f"補助プログラムを読み込めませんでした（{type(error).__name__}: {error}）。")
        return BROKEN
    folder = company.company_folder(args.folder) if args.folder else company.company_folder()
    if folder is None:
        print(NOT_DONE + "会社のフォルダ（目印の .hojokin/ があるフォルダ）で動かしてください。")
        return 2
    try:
        if args.make:
            path = sa.make(folder)
            print(made_text(folder, path))
        elif args.agree:
            day = sa.agree(folder)
            print(f"社長の同意を残しました（{day}。.hojokin/設定.json の「{sa.SETTINGS_KEY}」）。"
                  "まだ --make で画面を作っていなければ、作ってから上げてください。")
        elif args.url:
            sa.set_url(folder, args.url)
            print(f"上げた先の URL を残しました：{args.url.strip()}。次からは同じ URL を更新します。")
        else:
            url = sa.stop(folder)
            if url == "":
                print("やめました（同意の記録を外しました）。claude.ai には、まだ上げていません。")
            elif url:
                print(f"やめました。次からは claude.ai に上げません。上げたページ（{url}）は残っています。"
                      "消すときは、ターミナルの /artifacts で選んで d を押すか、Claude にこの URL のページを消すよう頼んでください"
                      "（消す前に、社長に確かめます）。")
            else:
                print("claude.ai には、まだ上げていません（同意の記録もありません）。")
    except sa.ArtifactPageError as error:
        print(NOT_DONE + str(error))
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"途中で止まりました（{type(error).__name__}: {error}）。")
        return BROKEN
    return 0


if __name__ == "__main__":
    sys.exit(main())
