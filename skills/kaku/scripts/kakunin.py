"""申請書を確かめる道具（SPEC F9、DESIGN 6章・8章。TASKS M7）。中身は lib/kakunin.py。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/kakunin.py count [--case] [--stage] [--seido] [--json]
      コードによる確かめ：申請書の仮の印（【仮：…】、財務モデルなどの「状態」が仮の行）と空欄（【空欄：…】、
      まだ何も書いていない様式の項目、入力シートの空の値）、根拠対照表の出典のない行を数える。
  python3 -B <この場所>/kakunin.py konkyo [--case] [--stage] [--replace] [--input <JSON のファイル>] <<'EOF'
      {"行": [{"記述": "年商2億円", "種類": "数字", "書いた場所": "1-1 現状分析", "出典": "決算書 第18期 p.2"}]}
      EOF
      `案件/<案件>/<段階>/申請書/根拠対照表.xlsx` に行を足す（なければ作る）。--replace なら置き換える。
  python3 -B <この場所>/kakunin.py prepare [--case] [--stage] [--seido]
      コードの確かめが通ったら、審査役に渡すものを `記録/審査に渡すもの/` にまとめ、確かめの番号を出す。
      通らなければ何も書かない（審査役を呼ばない）。Excel の様式（その3 など）の数式のセルの値は、LibreOffice で
      計算し直した写し（`.hojokin/一時/計算し直した写し/`）から渡す。様式のファイルは変えない。
  python3 -B <この場所>/kakunin.py result [--number 確かめ-0001] [--json]
      hook が保存した審査役の結果（`記録/審査役の結果/<確かめの番号>.json`）を読み、指摘を重さごとに出す。
  python3 -B <この場所>/kakunin.py finish [--case] [--stage] [--seido]
      完成の条件（コードの確かめ・今の版の審査役の結果・要修正0件）を確かめ、満たせば `記録/完成の記録.json` に残す。

- --case：`案件/` の下の案件のフォルダの名前。1つなら省いてよい。--stage：段階のフォルダ（1_申請 など）。
  省くと、番号のいちばん小さい段階。--seido：制度データ（`記録/制度データ/` の中の JSON）。1つなら省いてよい。
- 会社のフォルダの外は読まない・書かない。場所の確かめは lib/places.py で行う。
- 終了コード：0 した（count は通った、result は届いていた）、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、引数・案件・制度データが正しくない、別名がある など）、
  3 通らない（count・prepare はコードの確かめが通らない、result はまだ届いていない、finish は完成の条件を満たさない）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

OK, BROKEN, REFUSED, NOT_PASSED = 0, 1, 2, 3


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="申請書を確かめる")
    sub = parser.add_subparsers(dest="command")

    def common(p, seido=True):
        p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
        p.add_argument("--case", help="案件のフォルダの名前（案件/ の下）。1つなら省いてよい")
        p.add_argument("--stage", help="段階のフォルダ（1_申請 など）。省くと番号のいちばん小さい段階")
        if seido:
            p.add_argument("--seido", help="制度データ（記録/制度データ/ の中の JSON）。1つなら省いてよい")

    p = sub.add_parser("count", help="仮の印・空欄・根拠のない記述を数える")
    common(p)
    p.add_argument("--json", action="store_true", help="JSON で出す")
    p = sub.add_parser("konkyo", help="根拠対照表に行を足す")
    common(p, seido=False)
    p.add_argument("--replace", action="store_true", help="前の行を消して置き換える")
    p.add_argument("--input", help="行の JSON（会社のフォルダの中のファイル）。省くか - なら標準入力")
    p = sub.add_parser("prepare", help="審査役に渡すものをまとめる")
    common(p)
    p = sub.add_parser("result", help="保存された審査役の結果を読む")
    p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    p.add_argument("--number", help="確かめの番号（確かめ-0001 の形）。省くと今の控えの番号")
    p.add_argument("--json", action="store_true", help="JSON で出す")
    p = sub.add_parser("finish", help="完成の条件を確かめ、満たせば完成の記録に残す")
    common(p)
    args = parser.parse_args(argv)
    if args.command is None:
        raise Refused("count・konkyo・prepare・result・finish のどれかを付けてください")
    return args


def _target(folder, args, kk, need_seido=True):
    case = kk.find_case(folder, args.case)
    stage = kk.find_stage(folder, case, args.stage)
    seido = None
    if need_seido:
        seido, _rel = kk.find_seido(folder, getattr(args, "seido", None))
    return case, stage, seido


def do_count(folder, args, kk) -> int:
    case, stage, seido = _target(folder, args, kk)
    report = kk.check(folder, case, stage, seido)
    state = kk.after_check(folder, report["通った"])
    reasons = kk.stop_reasons(state)
    if args.json:
        report = dict(report, 社長に返す理由=reasons)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(kk.report_text(report))
        if reasons:
            print(kk.returning_text(reasons))
    return OK if report["通った"] else NOT_PASSED


def do_konkyo(folder, args, kk) -> int:
    case, stage, _seido = _target(folder, args, kk, need_seido=False)
    if args.input and args.input != "-":
        data, _rel = kk._read_json_inside(folder, args.input, "行の JSON")
    else:
        try:
            data = json.loads(sys.stdin.read())
        except ValueError as e:
            raise Refused(f"標準入力の行が JSON として読めません（{e}）")
    done = kk.write_evidence(folder, case, stage, data, replace=args.replace)
    made = "作り、" if done["作った"] else ""
    how = "置き換えました" if args.replace else "足しました"
    print(f"{done['場所']} を{made}{done['足した行']}行を{how}（いまは{done['行']}行）。")
    if done["出典のない行"]:
        print(f"- 出典のない行が{done['出典のない行']}行あります。出典が分からないものは社長に聞き、分かったら出典を足してください。")
    return OK


def do_prepare(folder, args, kk) -> int:
    case, stage, seido = _target(folder, args, kk)
    reasons = kk.before_review(folder)
    if reasons:
        print("審査役に渡すものはまとめていません（審査役は呼ばないでください）。")
        print(kk.returning_text(reasons))
        return NOT_PASSED
    try:
        done = kk.prepare(folder, case, stage, seido, PLUGIN_ROOT)
    except kk.NotPassed as e:
        state = kk.after_check(folder, False)
        print("審査役に渡すものはまとめていません（コードの確かめが通らないため。審査役は呼ばないでください）。")
        print(kk.report_text(e.report))
        if kk.stop_reasons(state):
            print(kk.returning_text(kk.stop_reasons(state)))
        return NOT_PASSED
    kk.after_check(folder, True)
    number = done["確かめの番号"]
    kk.review_called(folder, number)
    print(f"審査役に渡すものを {done['フォルダ']}/ にまとめました。確かめの番号：{number}")
    print(f"- 渡したもの：{'、'.join(done['渡したもの'])}")
    for name, why in done["渡していないもの"].items():
        print(f"- 渡していないもの：{name}（{why}）")
    for rel, recalc in done.get("数式の計算し直し", {}).items():
        if recalc["計算し直した"]:
            print(f"- {rel} の数式のセルの値は、計算し直した写し（{recalc['写し']}）から渡しました（{rel} は変えていません）。")
        else:
            print(f"- {rel}：{kk.RECALC_FAILED}。数式のセルの値は前の計算の値のまま渡し、そのことを計画書の本文に書きました"
                  f"（{recalc['理由']}）。社長に伝えてください。")
    print("次に、審査役（subagent の hojokin:shinsa）を呼び、次の文をそのまま渡してください：")
    print(f"「{done['フォルダ']}/ にあるものをすべて読み、申請書を確かめてください。確かめの番号は {number} です。」")
    print(f"審査役が終わったら、result で結果がそろったかを確かめてください（保存先：{kk.RESULTS_DIR}/{number}.json）。")
    return OK


def do_result(folder, args, kk) -> int:
    status = kk.review(folder, args.number)
    state = kk.after_review(folder, status)
    reasons = kk.stop_reasons(state) if status["届いた"] and status.get("重さごとの数", {}).get("要修正", 0) + \
        len(status.get("社長の答えが要ること") or []) + sum(1 for i in status.get("指摘") or [] if i.get("社長に聞くこと")) else []
    if args.json:
        print(json.dumps(dict(status, 社長に返す理由=reasons), ensure_ascii=False, indent=1))
    else:
        print(kk.review_text(status))
        if reasons:
            print(kk.returning_text(reasons))
        elif status["届いた"] and not status.get("重さごとの数", {}).get("要修正", 0):
            print("要修正は0件です。finish で完成の記録を残してください。")
        elif status["届いた"]:
            print(f"要修正の指摘を直し、count からやり直してください（審査役は、社長に返すまでに{kk.MAX_REVIEWS}回まで）。")
    return OK if status["届いた"] else NOT_PASSED


def do_finish(folder, args, kk) -> int:
    case, stage, seido = _target(folder, args, kk)
    done = kk.complete(folder, case, stage, seido)
    if not done["完成"]:
        print("完成にしていません。次のことが残っています：")
        for reason in done["理由"]:
            print(f"- {reason}")
        return NOT_PASSED
    counts = done["審査役の結果"]["重さごとの数"]
    if done.get("もうある"):
        print(f"{done['審査役の結果']['確かめの番号']} の版は、もう完成の記録にあります。")
    else:
        print(f"完成にしました（{kk.COMPLETION_REL} に残しました。確かめの番号：{done['記録']['確かめの番号']}）。")
    print(f"- 仮の印 0件、空欄 0件、根拠のない記述 0件。審査役の要修正 0件（要確認 {counts['要確認']}件、助言 {counts['助言']}件）。")
    if counts["要確認"] or counts["助言"]:
        print("- 要確認と助言の指摘は、社長に示し、直すかを決めてもらってください（result で一覧を出せます）。")
    return OK


def main(argv) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        args = parse(argv)
    except Refused as e:
        print(f"しませんでした：引数が違います（{e}）。")
        return REFUSED
    folder = Path(args.folder).expanduser() if args.folder else company.project_dir()
    if company.company_folder(folder) is None:
        print(f"{folder} は会社のフォルダではありません（.hojokin/ がありません）。何もしていません。"
              "会社のフォルダで動かしてください。")
        return REFUSED
    try:
        from lib import kakunin as kk
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    handlers = {"count": do_count, "konkyo": do_konkyo, "prepare": do_prepare, "result": do_result,
                "finish": do_finish}
    # 質問の記録（回数の数え直し）と審査役の結果の保存は hooks が行う。hooks が動いていなければ、先に知らせる
    # （11/6 のリハーサルで、親のフォルダで開いたまま進め、審査役の結果が「まだ届いていない」・回数が数え直されない
    # まま、理由が分からず止まったため。止めはしない。lib/company.py の hookの合図）
    if args.command in ("count", "prepare", "result") and not getattr(args, "json", False):
        problem = company.hook_signal_problem(folder)
        if problem:
            print(f"【注意】{problem}")
    try:
        return handlers[args.command](folder, args, kk)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except ValueError as e:  # CheckError・EvidenceError、Word・Excel が読めないなど
        print(f"しませんでした：{e}。ファイルは前のままです。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを読めないか書けませんでした（{e.strerror or e}）。ファイルは前のままです。")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
