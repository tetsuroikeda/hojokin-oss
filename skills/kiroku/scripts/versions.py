"""書類の版の道具（SPEC 共通の要件「書類の版の管理」・T0-6、DESIGN 10章。TASKS M0b）。

社長が Git の操作を覚えなくても、前の版を見る・戻す、「提出した」ときの提出版を残す・見る、ができるようにする。
版は hook が自動で残す（lib/history.py）。この道具は、その履歴を読み、見るだけに出し、提出版を記録する。

使い方（する事の後に、--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/versions.py log [--document <書類>] [--limit 20]
      版の履歴を新しい順に出す（日時・だれ・変更・理由・版の印）。--document を省くと、会社のフォルダ全体。
  python3 -B <この場所>/versions.py show --document <書類> [--version <版の印> | --back 1]
      前の版を 見るだけ/ に読み取り専用で出す。--back は新しい方から数えた番号（0 が今の版、1 が1つ前）。
  python3 -B <この場所>/versions.py revert --document <書類> [--version <版の印> | --back 1] --reason "<社長の発言>"
      前の版に戻し、戻したことを新しい版として残す。
  python3 -B <この場所>/versions.py submit --case <案件> --stage <段階> --reason "<社長の発言>"
      「提出した」と言われたときに、その時点の申請書（添付の写しと財務モデル.xlsx を含む）を提出版として記録する。
  python3 -B <この場所>/versions.py submissions
      記録した提出版の一覧を出す。
  python3 -B <この場所>/versions.py show-submitted [--case <案件>] [--stage <段階>] [--number <番号>]
      提出版を 見るだけ/ に読み取り専用で出す（中身が提出したときと同じことを、印で確かめる）。番号を省けば最新。

- 書類は、会社のフォルダからの場所（例：案件/2026_省力化（一般型）第9回/1_申請/申請書/その1.docx）で指す。
  名前（その1.docx）だけでも、履歴の中で1つに決まればよい。
- 見るだけ/ は、次に Claude を開いたときに片付く。作業のファイルは増えない。
- 終了コード：0 できた、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、書類・版・案件が見つからない、提出版を記録できないなど）。
  2 のとき、作業のファイル・提出版の記録・見るだけ/ は変えていない（submit と revert は、それまでに変わった分を
  先に版に残すことがある）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

LOG_LIMIT = 20


def parse(argv):
    parser = argparse.ArgumentParser(description="書類の版を見る・戻す、提出版を残す・見る")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("log", parents=[common], help="版の履歴を新しい順に出す")
    p.add_argument("--document", help="書類（省くと会社のフォルダ全体）")
    p.add_argument("--limit", type=int, default=LOG_LIMIT, help="出す件数")

    for name, text in (("show", "前の版を 見るだけ/ に出す"), ("revert", "前の版に戻す")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("--document", required=True, help="書類")
        group = p.add_mutually_exclusive_group()
        group.add_argument("--version", help="版の印（log に出た7桁以上）")
        group.add_argument("--back", type=int, help="新しい方から数えた番号（0 が今の版、1 が1つ前）")
        if name == "revert":
            p.add_argument("--reason", help="社長の発言（版の理由に残す）")

    p = sub.add_parser("submit", parents=[common], help="提出版を記録する")
    p.add_argument("--case", help="案件のフォルダの名前（1つしかなければ省ける）")
    p.add_argument("--stage", help="段階のフォルダの名前（1_申請 など。1つしかなければ省ける）")
    p.add_argument("--reason", help="社長の発言（「申請を出しました」など。版の理由に残す）")

    sub.add_parser("submissions", parents=[common], help="記録した提出版の一覧を出す")

    p = sub.add_parser("show-submitted", parents=[common], help="提出版を 見るだけ/ に出す")
    p.add_argument("--case", help="案件")
    p.add_argument("--stage", help="段階")
    p.add_argument("--number", type=int, help="何回目の提出版か（省けば最新）")
    return parser.parse_args(argv)


def _log(folder: Path, args, history, past_versions) -> int:
    document = past_versions.resolve_document(folder, args.document) if args.document else None
    found = history.log(folder, document, limit=max(args.limit, 1))
    if not found:
        print("版の履歴はまだありません。")
        return 0
    title = document or "会社のフォルダ"
    print(f"{title} の版の履歴（新しい順、{len(found)}件）：")
    for i, r in enumerate(found):
        line = f"{i}. {past_versions.shown(r)}　{r.who}　{r.change}　理由：{r.reason}　［版 {r.version[:10]}］"
        if document is None:
            line += f"　書類：{r.document}"
        print(line)
    print("（番号は新しい方から。0 が今の版。前の版を見るときは show、戻すときは revert に --version で版を渡す）")
    return 0


def _show(folder: Path, args, past_versions) -> int:
    record, where = past_versions.show(folder, args.document, version=args.version, back=args.back)
    print(f"{record.document} の {past_versions.shown(record)} の版（{record.who}。理由：{record.reason}）を、"
          f"読み取り専用で出しました：{where}")
    print("見るだけ/ は、次に Claude を開いたときに片付きます。作業のファイルは変えていません。")
    return 0


def _revert(folder: Path, args, past_versions) -> int:
    record, changed = past_versions.revert(folder, args.document, version=args.version, back=args.back,
                                           reason=args.reason)
    if not changed:
        print(f"{record.document} は、もう {past_versions.shown(record)} の版と同じ中身です。何も変えていません。")
        return 0
    print(f"{record.document} を、{past_versions.shown(record)} の版（{record.who}。理由：{record.reason}）に戻しました。"
          "戻したことも版の履歴に残しました（戻す前の版も、履歴から取り出せます）。")
    return 0


def _submit(folder: Path, args, submission) -> int:
    entry = submission.record(folder, args.case, args.stage, reason=args.reason)
    print(f"提出版を記録しました：{submission.label(entry)}。")
    print(f"入れたファイル（{len(entry['ファイル'])}件。中身の印 sha256 も {submission.RECORD_FILE} に残しました）：")
    for f in entry["ファイル"]:
        print(f"- {f['書類']}")
    print("後で見るときは show-submitted で、見るだけ/ に読み取り専用で出せます。")
    return 0


def _submissions(folder: Path, submission) -> int:
    entries = submission.load(folder)
    if not entries:
        print("記録した提出版はまだありません。")
        return 0
    print(f"記録した提出版（古い順、{len(entries)}件）：")
    for e in entries:
        print(f"- {submission.label(e)}　ファイル {len(e['ファイル'])}件　［版 {e['版'][:10]}］")
    return 0


def _show_submitted(folder: Path, args, submission) -> int:
    entry = submission.find(folder, args.case, args.stage, args.number)
    where, files = submission.export(folder, entry)
    print(f"提出版（{submission.label(entry)}）を、{where}/ に読み取り専用で出しました"
          f"（{len(files)}件。提出したときと同じ中身であることを、印で確かめました）：")
    for path in files:
        print(f"- {path}")
    print("見るだけ/ は、次に Claude を開いたときに片付きます。作業のファイルは変えていません。")
    return 0


def main(argv) -> int:
    # 書類の名前に対になっていないサロゲートがあっても、出せるようにする
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse(argv)
    if args.command is None:
        print("する事（log・show・revert・submit・submissions・show-submitted）を指してください。")
        return 2
    folder = Path(args.folder).expanduser() if getattr(args, "folder", None) else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。"
              "会社のフォルダで動かしてください。")
        return 2
    try:
        from lib import history, past_versions, submission, view_only
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラム（版の履歴に使う dulwich）を読み込めませんでした（{type(e).__name__}: {e}）。"
              "何もしていません。プラグインを入れ直してから、もう一度試してください。")
        return 1
    known = (past_versions.VersionError, submission.SubmissionError, view_only.ViewError, history.HistoryBusy)
    try:
        if args.command == "log":
            return _log(folder, args, history, past_versions)
        if args.command == "show":
            return _show(folder, args, past_versions)
        if args.command == "revert":
            return _revert(folder, args, past_versions)
        if args.command == "submit":
            return _submit(folder, args, submission)
        if args.command == "submissions":
            return _submissions(folder, submission)
        return _show_submitted(folder, args, submission)
    except known as e:
        print(f"しませんでした：{e}")
        return 2
    except OSError as e:  # ファイルを読み書きできない（権限がない、ディスクがいっぱいなど）
        print(f"しませんでした：ファイルを読み書きできませんでした（{e}）。")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
