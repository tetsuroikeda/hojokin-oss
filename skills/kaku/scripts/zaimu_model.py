"""財務モデル.xlsx を作り、計算を確かめ、数値の要件を判定する道具（SPEC F8「財務モデル」「数値の要件」T8-4、
DESIGN 6章・8.3。TASKS M5）。

kaku が、聞き取りと書類から前提を集めた後に動かす。数字の組み立ては、すべてこの道具が行う（Claude は計算しない）。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/zaimu_model.py build --spec 記録/財務モデルの指定.json [--seido 記録/制度データ/<制度>_<回>.json]
                                             [--replace] [--soffice <LibreOffice の soffice の場所>] [--json]
      --spec：財務モデルの指定（前提・基準年度の実績・事業ごとの式。形は lib/zaimu.py の冒頭）。会社のフォルダの中の
              JSON。「-」なら標準入力から読む。
      --seido：数値の要件を読む制度データ。省くと `記録/制度データ/` の直下の JSON を使う（1つだけのとき）。
      --replace：財務モデル.xlsx がもうあるときに作り直す（前の版は版の履歴に残る）。ないときは断る。
      --soffice：LibreOffice の場所。省くと決まった場所と Spotlight で探す。

すること
1. 指定を確かめ、会社のフォルダの直下に「財務モデル.xlsx」を作る（シートは3つ：前提・計画（N年）・月次（1年目））。
   前提のセルに名前を付け、計画は名前を使った数式で書く。
2. LibreOffice で計算し直し（計算し直しは「常に」）、数式のセルの値が、すべて Python の計算と一致するかを確かめる。
   食い違えば、財務モデル.xlsx を置かずに終了コード3で終える（道具の不具合なので、作者に知らせる）。
   LibreOffice がない・動かないときは、確かめずに置き、そのことを伝える（Excel で開くと計算される）。
3. 制度データの「数値の要件」の基準で、様式（別紙4）と同じ計算をして判定する。基準との差が0.01ポイント未満なら、
   境目として知らせる（社長に、計画の数字を少し上げることを勧める）。

- 作業の途中のファイルは `.hojokin/一時/財務モデル/` の下に作り、終わったら消す（版の履歴に入れない）。
- 会社のフォルダの外は読まない・書かない。場所の確かめは lib/places.py で行う（別名をたどった先が外なら断る。
  財務モデル.xlsx とその途中に別名があれば断る）。
- 終了コード：0 作った、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、指定や制度データが
  正しくない、財務モデル.xlsx がもうある など）、3 計算し直した結果が Python の計算と食い違った（置いていない）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, places  # noqa: E402

SEIDO_DIR = "記録/制度データ"
WORK_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/財務モデル"
OK, BROKEN, REFUSED, MISMATCH = 0, 1, 2, 3


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="財務モデル.xlsx を作り、計算を確かめ、数値の要件を判定する")
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser("build", help="財務モデル.xlsx を作る")
    build.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    build.add_argument("--spec", required=True, help="財務モデルの指定（会社のフォルダの中の JSON。「-」なら標準入力）")
    build.add_argument("--seido", help="数値の要件を読む制度データ（省くと 記録/制度データ/ の直下の1つ）")
    build.add_argument("--replace", action="store_true", help="財務モデル.xlsx がもうあるときに作り直す")
    build.add_argument("--soffice", help="LibreOffice（soffice）の場所")
    build.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)
    if args.command != "build":
        raise Refused("build を付けてください")
    return args


def read_json_inside(folder: Path, given: str, what: str):
    """会社のフォルダの中の JSON を読む。外なら断る。"""
    try:
        real = places.resolve_inside(folder, Path(given).expanduser())
    except places.PlaceError:
        raise Refused(f"{what}（{given}）が会社のフォルダの外です。会社のフォルダの中に置いてください")
    try:
        text = real.read_text(encoding="utf-8")
    except OSError as e:
        raise Refused(f"{what}（{given}）を読めませんでした（{e.strerror or e}）")
    try:
        return json.loads(text), real
    except ValueError as e:
        raise Refused(f"{what}（{given}）が JSON として読めません（{e}）")


def find_seido(folder: Path, given):
    """制度データの場所と中身。指定がなく、記録/制度データ/ の直下に JSON がなければ (None, None)。"""
    if given:
        data, real = read_json_inside(folder, given, "制度データ")
        return data, real
    top = places.actual(folder, SEIDO_DIR)
    if top is None or not top.is_dir():
        return None, None
    found = sorted(p for p in top.iterdir() if p.suffix == ".json" and not p.name.startswith("."))
    if not found:
        return None, None
    if len(found) > 1:
        names = "、".join(p.name for p in found)
        raise Refused(f"{SEIDO_DIR}/ に制度データが2つ以上あります（{names}）。--seido で、どれを使うかを渡してください")
    return read_json_inside(folder, str(found[0]), "制度データ")


def relative(folder: Path, path) -> str:
    try:
        return places.relative_inside(folder, path)
    except places.PlaceError:
        return str(path)


def fmt_growth(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}%"
    return str(value)


def report_text(result: dict) -> str:
    lines = []
    s = result["中身"]
    if result["置いた"]:
        lines.append(f"{result['財務モデル']} を作りました（シート：{'・'.join(s['シート'])}。前提 {s['前提の数']} 個、"
                     f"計画 {s['計画の年数']} 年）。")
    else:
        lines.append(f"{result['財務モデル']} は置いていません。")
    check = result["計算し直し"]
    if check["した"]:
        if check["食い違い"]:
            lines.append(f"計算の確かめ：LibreOffice で計算し直すと、{len(check['食い違い'])} 個のセルが Python の計算と"
                         "食い違いました。道具の不具合なので、この数字は使わず、作者に知らせてください。")
            lines += ["  " + w for w in check["食い違い"][:20]]
        else:
            lines.append(f"計算の確かめ：LibreOffice で計算し直した数式のセル {check['数式のセル']} 個が、"
                         "すべて Python の計算と一致しました。")
    else:
        lines.append(f"計算の確かめ：{check['理由']}。Excel で開くと計算されます。")
    lines.append("")
    seido = result["制度データ"]
    if seido is None:
        lines.append("制度データがないので、数値の要件は判定していません。junbi で制度データを作ってから、もう一度作ってください。")
    else:
        lines.append(f"数値の要件（基準は制度データ「{seido}」から。様式の別紙4 と同じ計算で判定）")
        if not s["判定した要件"]:
            lines.append("- 判定できる要件がありませんでした（下の「判定しなかった要件」を見てください）。")
        for r in s["判定した要件"]:
            tag = "（特例を選ぶときだけ）" if r["特例"] else ""
            lines.append(f"- {r['名前']}{tag}：{r['判定']}（基準 {r['基準']}・{r['いつ']}。{r['出典']}）")
            years = "、".join(f"{p['年']}年目 {fmt_growth(p['伸び'])}" + ("（境目）" if p["境目"] else "")
                              for p in r["年ごと"])
            lines.append(f"    {years}")
        near = [(r, p) for r in s["判定した要件"] for p in r["年ごと"] if p["境目"]]
        if near:
            lines.append("")
            lines.append("境目の知らせ（社長に伝えること）")
            for r, p in near:
                lines.append(
                    f"- 「{r['名前']}」の{p['年']}年目は {fmt_growth(p['伸び'])}（判定：{p['判定']}）で、基準の {r['基準']}"
                    "との差が0.01ポイント未満です。様式（別紙4）の計算は小数第3位以下を切り捨てるので、ちょうど基準の計画でも"
                    "基準を下回ることがあります。計画の数字を少し上げることを勧めてください。")
        if s["判定しなかった要件"]:
            lines.append("")
            lines.append("判定しなかった要件（財務モデルの数字では判定しないもの・基準が読めないもの）")
            for r in s["判定しなかった要件"]:
                lines.append(f"- {r['名前']}：{r['理由']}")
    lines.append("")
    lines.append("まとめ")
    for label, value in s["まとめ"].items():
        unit = "円" if "売上" in label or label.endswith("付加価値額") else ""
        shown = fmt_growth(value) if "成長率" in label else (f"{value:,.0f}{unit}" if isinstance(value, float) else str(value))
        lines.append(f"- {label}：{shown}")
    if s["数値の要件（特例を除く）をすべて満たすか"] is not None:
        lines.append(f"- 数値の要件（特例を除く）をすべて満たすか：{s['数値の要件（特例を除く）をすべて満たすか']}")
    if s["根拠か出典のない前提"]:
        lines.append("")
        lines.append("根拠か出典のない前提（根拠を聞くか、決まっていなければ「仮」にする）：" + "、".join(s["根拠か出典のない前提"]))
    if s["仮の前提"]:
        lines.append("仮の前提（後で確かめる）：" + "、".join(s["仮の前提"]))
    return "\n".join(lines)


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
        from lib import libreoffice, youken, zaimu
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN

    try:
        if args.spec == "-":
            try:
                raw_spec = json.loads(sys.stdin.read())
            except ValueError as e:
                raise Refused(f"標準入力の指定が JSON として読めません（{e}）")
        else:
            raw_spec, _ = read_json_inside(folder, args.spec, "財務モデルの指定")
        seido, seido_path = find_seido(folder, args.seido)
        requirements = youken.read_requirements(seido) if seido is not None else []
        spec = zaimu.parse_spec(raw_spec)
        book = zaimu.build(spec, requirements)
        try:
            places.no_link_on_the_way(folder, zaimu.MODEL_FILE)
            places.no_link_on_the_way(folder, WORK_DIR)
        except places.PlaceError as e:
            raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、書きません。別名を外してください")
        target = places.actual(folder, zaimu.MODEL_FILE, partial=True)
        if os.path.lexists(str(target)) and not args.replace:
            raise Refused(f"{zaimu.MODEL_FILE} はもうあります。作り直すときは --replace を付けてください"
                          "（社長が前提のセルを書き換えていたら、その値を指定に入れてから作り直す。前の版は版の履歴に残ります）")
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except (youken.YoukenError, zaimu.SpecError) as e:
        print(f"しませんでした：{e}。財務モデル.xlsx は作っていません。")
        return REFUSED

    work = places.actual(folder, WORK_DIR, partial=True) / uuid.uuid4().hex
    try:
        work.mkdir(parents=True)
        try:
            from lib import zaimu_xlsx
        except Exception as e:
            print(f"補助プログラム（Excel を書く部分）を読み込めませんでした（{type(e).__name__}: {e}）。"
                  "プラグインを入れ直してから、もう一度試してください。")
            return BROKEN
        built = work / "model.xlsx"
        zaimu_xlsx.write(book, built)
        expected = book.formulas()
        check = {"した": False, "数式のセル": len(expected), "食い違い": [], "理由": ""}
        soffice = args.soffice if args.soffice else libreoffice.find_soffice()
        if soffice and not (os.path.isfile(soffice) and os.access(soffice, os.X_OK)):
            soffice = None
        if not soffice:
            check["理由"] = "LibreOffice が見つからないので、計算し直しの確かめはしていません"
        else:
            try:
                recalced = libreoffice.recalc_xlsx(built, work / "recalc", soffice)
                got = zaimu_xlsx.read_values(recalced)
                check["した"] = True
                check["食い違い"] = zaimu.compare(expected, got)
            except libreoffice.LibreOfficeError as e:
                check["理由"] = f"LibreOffice で計算し直せませんでした（{e}）ので、確かめはしていません"
        placed = False
        if not check["食い違い"]:
            places.no_link_on_the_way(folder, zaimu.MODEL_FILE)
            os.replace(str(built), str(target))
            placed = True
    except places.PlaceError as e:
        print(f"しませんでした：{e.link or e} が別名（シンボリックリンク）になっているので、書きません。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを書けませんでした（{e.strerror or e}）。")
        return REFUSED
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
        try:
            work.parent.rmdir()
        except OSError:
            pass

    result = {
        "財務モデル": zaimu.MODEL_FILE,
        "置いた": placed,
        "計算し直し": check,
        "制度データ": relative(folder, seido_path) if seido_path is not None else None,
        "中身": book.summary,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(report_text(result))
    return MISMATCH if check["食い違い"] else OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
