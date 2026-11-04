"""様式（Word のその1・2）と入力シート.xlsx に書く道具（SPEC F8「様式に書式を壊さずに書き込む」・F10、DESIGN 1.1・
5章・6章・9.1。TASKS M6）。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/yoshiki.py outline [--case <案件>] [--source <公式資料の様式>] [--json]
      様式の表・セル・文字のある段落の一覧を、場所の名前（t4.r2.c0.p0 など）付きで出す。読み取り役に渡す。
  python3 -B <この場所>/yoshiki.py map [--case <案件>] [--seido <制度データ>] [--source <公式資料の様式>] <<'EOF'
      {"様式": "<制度データの様式の名前>", "対応": [{"項目": "<項目の名前>", "書き込む位置": {"見出し": "…", "場所": "…", "範囲": "見出しの後"}}]}
      EOF
      読み取り役の対応づけを、様式の一覧と照らして確かめ、制度データの 様式[].項目[].書き込む位置 に書く。
  python3 -B <この場所>/yoshiki.py write --item "<項目の名前>" [--form "<様式の名前>"] [--case] [--stage] [--seido]
                                       [--source] [--text "<書く文>"]   （--text がなければ標準入力から読む）
      `案件/<案件>/<段階>/申請書/その1・2.docx` の、その項目の書いてよい範囲に書く（なければ公式資料の様式から写して作る）。
  python3 -B <この場所>/yoshiki.py sheet --field "<欄の名前>" [--screen "<画面の名前>"] [--case] [--stage] [--seido]
                                       [--value "<値>"]   （--value がなければ標準入力から読む）
      `案件/<案件>/<段階>/申請書/入力シート.xlsx` の、その欄の「値」に書く（なければ制度データの申請画面から作る）。
  python3 -B <この場所>/yoshiki.py sheet --values - [--case] [--stage] [--seido] <<'EOF'
      {"値": [{"画面": "<画面の名前>", "欄": "<欄の名前>", "値": "<値>"}]}
      EOF
      入力シートの欄に、まとめて書く（M12b。欄が数百あるため）。1件でも書けなければ、何も書かない。
      会社に当てはまらない欄には「該当なし」と書く（数字の欄にも書ける。画面入力の道具は、その欄を画面に入れない）。

- --case：`案件/` の下の案件のフォルダの名前。1つなら省いてよい。--stage：段階のフォルダ（1_申請 など）。省くと、
  番号のいちばん小さい段階。--seido：制度データ（`記録/制度データ/` の中の JSON）。1つなら省いてよい。
- --source：公式資料の様式（会社のフォルダの中の .docx）。省くと、案件の資料の一覧（`記録/資料の本文/<案件>/資料の一覧.json`）
  の置き場所から、様式の「元のファイル」の資料を使う。それもなければ、資料の一覧にある .docx が1つならそれを使う。
- 書いた後に直前の版と構造を比べ、書いてよい範囲の外が1か所でも変わっていたら保存しない（終了コード3）。
- 会社のフォルダの外は読まない・書かない。場所の確かめは lib/places.py で行う（書き出す先とその途中に別名があれば断る。
  案件のフォルダ・`記録/制度データ/` が別名のときも、中の一覧を読まずに断る）。
- 終了コード：0 書いた（outline は出した）、1 補助プログラムを読み込めない、2 しなかった（会社のフォルダでない、
  引数・制度データ・書き込む位置が正しくない など）、3 書くと書いてよい範囲の外が変わるので、保存しなかった。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company, places  # noqa: E402

CASES_DIR = "案件"
SEIDO_DIR = "記録/制度データ"
TEXT_DIR = "記録/資料の本文"
LIST_FILE = "資料の一覧.json"
APPLICATION_DIR = "申請書"
WORD_FILE = "その1・2.docx"
STAGE_NAME = re.compile(r"^([0-9]+)_[^/\\]+$")
OK, BROKEN, REFUSED, OUTSIDE = 0, 1, 2, 3


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="様式と入力シートに書く")
    sub = parser.add_subparsers(dest="command")

    def common(p, stage=False, seido=True, source=True):
        p.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
        p.add_argument("--case", help="案件のフォルダの名前（案件/ の下）。1つなら省いてよい")
        if stage:
            p.add_argument("--stage", help="段階のフォルダ（1_申請 など）。省くと番号のいちばん小さい段階")
        if seido:
            p.add_argument("--seido", help="制度データ（記録/制度データ/ の中の JSON）。1つなら省いてよい")
        if source:
            p.add_argument("--source", help="公式資料の様式（会社のフォルダの中の .docx）")

    p = sub.add_parser("outline", help="様式の見出し・表・セルの一覧")
    common(p, seido=False)
    p.add_argument("--json", action="store_true", help="JSON で出す")
    p = sub.add_parser("map", help="読み取り役の対応づけを確かめて、制度データに書く")
    common(p)
    p.add_argument("--input", help="対応づけの JSON（会社のフォルダの中のファイル）。省くか - なら標準入力")
    p = sub.add_parser("write", help="様式の項目に書く")
    common(p, stage=True)
    p.add_argument("--item", required=True, help="制度データの様式の項目の名前")
    p.add_argument("--form", help="制度データの様式の名前（項目の名前が2つの様式にあるとき）")
    p.add_argument("--text", help="書く文（省くか - なら標準入力）。改行で段落を分ける")
    p = sub.add_parser("sheet", help="入力シートの欄に書く")
    common(p, stage=True, source=False)
    p.add_argument("--field", help="入力シートの欄の名前（制度データの申請画面の欄の名前）")
    p.add_argument("--screen", help="画面の名前（同じ名前の欄が2つの画面にあるとき）")
    p.add_argument("--value", help="書く値（省くか - なら標準入力）")
    p.add_argument("--values", help="まとめて書く欄と値の JSON（- なら標準入力）。"
                                    "{\"値\": [{\"画面\": \"…\", \"欄\": \"…\", \"値\": …}]} の形")
    args = parser.parse_args(argv)
    if args.command is None:
        raise Refused("outline・map・write・sheet のどれかを付けてください")
    if args.command == "sheet":
        if args.values is not None and (args.field or args.value is not None or args.screen):
            raise Refused("--values と、--field・--value・--screen は一緒に使えません")
        if args.values is None and not args.field:
            raise Refused("--field（1つの欄）か --values（まとめて）を付けてください")
    return args


# ---------------------------------------------------------------- 場所と材料


def inside(folder: Path, given, what: str) -> Path:
    try:
        return places.resolve_inside(folder, Path(given).expanduser())
    except places.PlaceError:
        raise Refused(f"{what}（{given}）が会社のフォルダの外です。会社のフォルダの中のものだけを使います")


def read_json(folder: Path, given, what: str):
    real = inside(folder, given, what)
    try:
        return json.loads(real.read_text(encoding="utf-8")), real
    except OSError as e:
        raise Refused(f"{what}（{given}）を読めませんでした（{e.strerror or e}）")
    except ValueError as e:
        raise Refused(f"{what}（{given}）が JSON として読めません（{e}）")


def find_case(folder: Path, given) -> str:
    top = places.actual(folder, CASES_DIR)
    if top is None or not top.is_dir() or not places.is_inside(folder, top):
        raise Refused(f"{CASES_DIR}/ がありません（または会社のフォルダの外を指しています）。先に junbi で案件を作ってください")
    names = sorted(places.nfc(p.name) for p in top.iterdir() if p.is_dir() and not p.name.startswith("."))
    if given:
        if places.nfc(given) not in names:
            raise Refused(f"案件「{given}」が {CASES_DIR}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if len(names) != 1:
        raise Refused(f"{CASES_DIR}/ に案件が{len(names)}つあります。--case で、どれかを渡してください"
                      f"（{'、'.join(names) or 'なし'}）")
    return names[0]


def no_link_before_looking(folder: Path, rel: str) -> None:
    """中の一覧を読む前に、rel（とその途中のフォルダ）が別名でないかを確かめる（lib/places.py）。別名なら Refused。

    別名の先（会社のフォルダの外かもしれない）の中の名前を読まず、出さないため。first_link は、最初の別名で止まり、
    その中の一覧は読まない。
    """
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、中を見ません。別名を外してください")


def find_stage(folder: Path, case: str, given) -> str:
    # 案件のフォルダが別名なら、その先の段階のフォルダの一覧を読まずに断る（書き出す先も別名を断る。application_file）
    no_link_before_looking(folder, f"{CASES_DIR}/{case}")
    case_dir = places.actual(folder, f"{CASES_DIR}/{case}")
    stages = sorted((p for p in case_dir.iterdir() if p.is_dir() and STAGE_NAME.match(places.nfc(p.name))),
                    key=lambda p: int(STAGE_NAME.match(places.nfc(p.name)).group(1)))
    names = [places.nfc(p.name) for p in stages]
    if given:
        if places.nfc(given) not in names:
            raise Refused(f"段階のフォルダ「{given}」が {CASES_DIR}/{case}/ にありません（あるもの：{'、'.join(names) or 'なし'}）")
        return places.nfc(given)
    if not names:
        raise Refused(f"{CASES_DIR}/{case}/ に段階のフォルダ（1_申請 など）がありません。先に junbi で作ってください")
    return names[0]


def find_seido(folder: Path, given):
    if given:
        return read_json(folder, given, "制度データ")
    # 記録/ か 記録/制度データ/ が別名なら、その先の一覧を読まずに断る（places.actual も途中の一覧を読むので、その前に）。
    # map はここで見つけた制度データに書き戻すので、中を指す別名も断る
    no_link_before_looking(folder, SEIDO_DIR)
    top = places.actual(folder, SEIDO_DIR)
    if top is None or not top.is_dir():
        raise Refused(f"{SEIDO_DIR}/ に制度データがありません。先に junbi で制度データを作ってください")
    found = sorted(p for p in top.iterdir() if p.suffix == ".json" and not p.name.startswith("."))
    if len(found) != 1:
        raise Refused(f"{SEIDO_DIR}/ に制度データが{len(found)}つあります。--seido で、どれを使うかを渡してください")
    return read_json(folder, str(found[0]), "制度データ")


def find_source(folder: Path, case: str, given, form=None) -> Path:
    """公式資料の Word の様式。"""
    if given:
        real = inside(folder, given, "公式資料の様式")
    else:
        listed_rel = f"{TEXT_DIR}/{case}/{LIST_FILE}"
        # places.actual は途中のフォルダの一覧を読むので、その前に、別名をたどった後も中かを確かめる（一覧は読まない）
        if not places.is_inside(folder, f"{TEXT_DIR}/{case}"):
            raise Refused(f"{TEXT_DIR}/{case}/ が会社のフォルダの外を指しています（別名）。中を見ません。別名を外してください")
        listed_path = places.actual(folder, listed_rel)
        placed = {}
        if listed_path is not None and listed_path.is_file():
            listed, _ = read_json(folder, str(listed_path), "案件の資料の一覧")
            placed = listed.get("置き場所") or {} if isinstance(listed, dict) else {}
        wanted = None
        if isinstance(form, dict):
            dest = (form.get("入力先") or {}).get("値") or {}
            wanted = dest.get("元のファイル") if isinstance(dest, dict) else None
        if wanted and isinstance(placed.get(wanted), dict) and placed[wanted].get("ファイル"):
            rel = placed[wanted]["ファイル"]
        else:
            docx = sorted({v.get("ファイル") for v in placed.values()
                           if isinstance(v, dict) and str(v.get("ファイル", "")).lower().endswith(".docx")})
            if len(docx) != 1:
                raise Refused(f"公式資料の Word の様式を決められません（資料の一覧の .docx が{len(docx)}つ）。"
                              "--source で、公式資料/ の様式を渡してください")
            rel = docx[0]
        real = inside(folder, rel, "公式資料の様式")
    if real.suffix.lower() != ".docx" or not real.is_file():
        raise Refused(f"公式資料の様式（{given or real.name}）が Word のファイル（.docx）ではないか、ありません")
    return real


def application_file(folder: Path, case: str, stage: str, name: str) -> Path:
    """`案件/<案件>/<段階>/申請書/<name>` の場所（書き出す先）。別名があれば断る。"""
    rel = f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}/{name}"
    try:
        places.no_link_on_the_way(folder, rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、書きません。別名を外してください")
    target = places.actual(folder, rel, partial=True)
    if not target.parent.is_dir():
        raise Refused(f"{CASES_DIR}/{case}/{stage}/{APPLICATION_DIR}/ がありません。先に junbi で段階のフォルダを作ってください")
    if not places.is_inside(folder, target):
        raise Refused(f"{rel} が会社のフォルダの外を指しています。書きません")
    return target


def read_text_arg(value) -> str:
    if value is None or value == "-":
        return sys.stdin.read()
    return value


# ---------------------------------------------------------------- 制度データの様式


def forms_with_item(seido, item: str, form_name=None):
    forms = seido.get("様式") if isinstance(seido, dict) else None
    if not isinstance(forms, list):
        raise Refused("制度データに「様式」の並びがありません")
    hits = []
    for form in forms:
        if not isinstance(form, dict):
            continue
        if form_name and form.get("名前") != form_name:
            continue
        for entry in form.get("項目") or []:
            if isinstance(entry, dict) and entry.get("名前") == item:
                hits.append((form, entry))
    if not hits:
        where = f"様式「{form_name}」" if form_name else "制度データの様式"
        raise Refused(f"{where}に、項目「{item}」がありません")
    if len(hits) > 1:
        raise Refused(f"項目「{item}」が{len(hits)}つの様式にあります。--form で様式の名前を渡してください")
    return hits[0]


def mapped_positions(form):
    out = []
    for entry in form.get("項目") or []:
        pos = entry.get("書き込む位置") if isinstance(entry, dict) else None
        if isinstance(pos, dict) and pos.get("範囲"):
            out.append((str(entry.get("名前")), pos))
    return out


# ---------------------------------------------------------------- 各コマンド


def do_outline(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    source = find_source(folder, case, args.source)
    _infos, parts = yw.read_parts(source.read_bytes())
    if yw.DOC not in parts:
        raise Refused(f"{source.name} に Word の本文がありません")
    from lib import xml_spans

    entries = yw.outline(xml_spans.parse(parts[yw.DOC]))
    rel = places.relative_inside(folder, source)
    if args.json:
        print(json.dumps({"様式": rel, "一覧": entries}, ensure_ascii=False, indent=1))
    else:
        print(f"様式：{rel}（場所の名前は、t＝表、r＝行、c＝セル、p＝段落。数は0から）")
        print(yw.outline_text(entries), end="")
    return OK


def do_map(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    seido, seido_path = find_seido(folder, args.seido)
    if args.input and args.input != "-":
        data, _ = read_json(folder, args.input, "対応づけの JSON")
    else:
        try:
            data = json.loads(sys.stdin.read())
        except ValueError as e:
            raise Refused(f"標準入力の対応づけが JSON として読めません（{e}）")
    if not isinstance(data, dict) or not isinstance(data.get("対応"), list) or not data["対応"]:
        raise Refused("対応づけは {\"様式\": \"…\", \"対応\": [{\"項目\": \"…\", \"書き込む位置\": {…}}]} の形で渡してください")
    form_name = data.get("様式")
    from lib import xml_spans

    checked = []
    problems = []
    source = None
    root = None
    for k, pair in enumerate(data["対応"], 1):
        if not isinstance(pair, dict) or not isinstance(pair.get("項目"), str):
            problems.append(f"{k}件目：「項目」がありません")
            continue
        try:
            form, entry = forms_with_item(seido, pair["項目"], form_name)
        except Refused as e:
            problems.append(f"{k}件目：{e}")
            continue
        if root is None:
            source = find_source(folder, case, args.source, form)
            root = xml_spans.parse(yw.read_parts(source.read_bytes())[1][yw.DOC])
        try:
            fixed = yw.check_position(root, pair.get("書き込む位置"), pair["項目"])
        except yw.FormError as e:
            problems.append(f"{k}件目（{pair['項目']}）：{e}")
            continue
        checked.append((entry, fixed))
    if problems:
        print("しませんでした（制度データは変えていません）。直す所：")
        for p in problems:
            print(f"- {p}")
        return REFUSED
    seido_rel = places.relative_inside(folder, seido_path)
    try:
        places.no_link_on_the_way(folder, seido_rel)
    except places.PlaceError as e:
        raise Refused(f"{e.link} が別名（シンボリックリンク）になっているので、制度データに書きません")
    for entry, fixed in checked:
        entry["書き込む位置"] = fixed
    from lib.docx_min import write_replacing

    write_replacing(seido_path, (json.dumps(seido, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"制度データ（{seido_rel}）に、書き込む位置を{len(checked)}件書きました（様式：{places.relative_inside(folder, source)}）。")
    for entry, fixed in checked:
        print(f"- {entry['名前']}：{fixed['範囲']}（見出し「{fixed['見出し']}」、場所 {fixed['場所']}）")
    return OK


def do_write(folder: Path, args, yw) -> int:
    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    seido, _seido_path = find_seido(folder, args.seido)
    form, entry = forms_with_item(seido, args.item, args.form)
    position = entry.get("書き込む位置")
    if not isinstance(position, dict) or not position.get("範囲"):
        raise Refused(f"項目「{args.item}」の書き込む位置が、まだ様式と対応づけられていません。outline の一覧を読み取り役に"
                      "渡して対応づけ、map で制度データに書いてから、もう一度試してください")
    text = read_text_arg(args.text)
    target = application_file(folder, case, stage, WORD_FILE)
    first = not os.path.lexists(str(target))
    if first:
        before = find_source(folder, case, args.source, form).read_bytes()
    else:
        before = target.read_bytes()
    try:
        new_blob, summary = yw.write_item(before, position, text, args.item, mapped_positions(form))
    except yw.OutsideChange as e:
        print(f"保存しませんでした：{WORD_FILE} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
              "前のファイルのままです。道具か様式の想定が違うので、作者に知らせてください。")
        for d in e.differences:
            print(f"- {d}")
        return OUTSIDE
    # 書く直前にもう一度、書き出す先に別名がないかを確かめる
    target = application_file(folder, case, stage, WORD_FILE)
    from lib.docx_min import write_replacing

    write_replacing(target, new_blob)
    rel = places.relative_inside(folder, target)
    made = "公式資料の様式から写して作り、" if first else ""
    print(f"{rel} に、{made}「{summary['項目']}」を書きました（段落 {summary['段落']}、{summary['文字数']}字）。")
    if summary["消した説明の青字の段落"]:
        print(f"- 様式の説明の青字（{summary['消した説明の青字の段落']}段落）は、様式の求めに合わせて消しました。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
    return OK


def sheet_field(seido, name, screen_name):
    """制度データの申請画面の（画面、欄）。見つからない・2つ以上なら Refused。"""
    from lib import input_sheet

    hits = [(s, f) for s, f in input_sheet.fields_of(seido)
            if f.get("名前") == name and (not screen_name or s.get("名前") == screen_name)]
    if not hits:
        where = f"画面「{screen_name}」に" if screen_name else ""
        raise Refused(f"制度データの申請画面の{where}、欄「{name}」がありません")
    if len(hits) > 1:
        raise Refused(f"制度データの申請画面に、欄「{name}」が{len(hits)}つあります。画面の名前を渡してください")
    return hits[0]


def sheet_value(field, value):
    """欄の種類に合わせた値（数字の欄は数。「該当なし」は文字のまま）。"""
    from lib import input_sheet

    if isinstance(value, bool):
        value = "はい" if value else "いいえ"
    if field.get("種類") == "数字":
        if input_sheet.is_not_applicable(value):
            return input_sheet.NOT_APPLICABLE
        if isinstance(value, (int, float)):
            return value
        return input_sheet.parse_number(str(value))
    if value is None:
        return ""
    return str(value)


def do_sheet(folder: Path, args, yw) -> int:
    from lib import input_sheet

    case = find_case(folder, args.case)
    stage = find_stage(folder, case, args.stage)
    seido, _seido_path = find_seido(folder, args.seido)
    if args.values is not None:
        return do_sheet_many(folder, args, yw, case, stage, seido)
    screen, field = sheet_field(seido, args.field, args.screen)
    value = read_text_arg(args.value)
    if value.endswith("\n") and args.value in (None, "-"):
        value = value[:-1]
    value = sheet_value(field, value)
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    first = not os.path.lexists(str(target))
    before = input_sheet.build(seido) if first else target.read_bytes()
    try:
        new_blob, summary = input_sheet.write_value(before, args.field, value, screen.get("名前"),
                                                    input_sheet.limit_of(field))
    except yw.OutsideChange as e:
        print(f"保存しませんでした：{input_sheet.FILE_NAME} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
              "前のファイルのままです。作者に知らせてください。")
        for d in e.differences:
            print(f"- {d}")
        return OUTSIDE
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    from lib.docx_min import write_replacing

    write_replacing(target, new_blob)
    rel = places.relative_inside(folder, target)
    made = "制度データの申請画面から作り、" if first else ""
    print(f"{rel} に、{made}欄「{summary['欄']}」（{screen.get('名前')}）の値を書きました（セル {summary['セル']}）。")
    if summary.get("注意"):
        print(f"- 注意：{summary['注意']}。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
    return OK


def read_values(folder: Path, given) -> list:
    """--values の JSON（{"値": [...]} か、並びそのもの）。"""
    if given in (None, "-"):
        try:
            data = json.loads(sys.stdin.read())
        except ValueError as e:
            raise Refused(f"標準入力の欄と値が JSON として読めません（{e}）")
    else:
        data, _ = read_json(folder, given, "欄と値の JSON")
    entries = data.get("値") if isinstance(data, dict) else data
    if not isinstance(entries, list) or not entries:
        raise Refused("欄と値は {\"値\": [{\"画面\": \"…\", \"欄\": \"…\", \"値\": …}]} の形で渡してください")
    return entries


def do_sheet_many(folder: Path, args, yw, case: str, stage: str, seido) -> int:
    """入力シートの欄に、まとめて書く。1件でも書けなければ、何も書かない（入力シートは前のまま）。"""
    from lib import input_sheet

    entries = read_values(folder, args.values)
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    first = not os.path.lexists(str(target))
    original = input_sheet.build(seido) if first else target.read_bytes()
    blob = original
    problems, written, notes = [], [], []
    for k, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("欄"), str) or "値" not in entry:
            problems.append(f"{k}件目：「欄」と「値」がありません")
            continue
        name, screen_name = entry["欄"], entry.get("画面")
        try:
            screen, field = sheet_field(seido, name, screen_name)
            value = sheet_value(field, entry["値"])
            blob, summary = input_sheet.write_value(blob, name, value, screen.get("名前"), input_sheet.limit_of(field))
        except yw.OutsideChange as e:
            print(f"保存しませんでした：{input_sheet.FILE_NAME} に書くと、書いてよい範囲の外が変わります（{len(e.differences)}か所）。"
                  "前のファイルのままです。作者に知らせてください。")
            for d in e.differences:
                print(f"- {d}")
            return OUTSIDE
        except (Refused, ValueError) as e:
            problems.append(f"{k}件目（{screen_name + '・' if screen_name else ''}{name}）：{e}")
            continue
        written.append((screen.get("名前"), summary))
        if summary.get("注意"):
            notes.append(f"{screen.get('名前')}・{summary['欄']}：{summary['注意']}")
    if problems:
        print(f"しませんでした（{input_sheet.FILE_NAME} は前のままです）。直す所：")
        for p in problems:
            print(f"- {p}")
        return REFUSED
    # 書く前に、はじめの版と最後の版も比べる（1件ずつの比べに加えて）
    differences = input_sheet.compare_xlsx(original, blob)
    if differences:
        print(f"保存しませんでした：{input_sheet.FILE_NAME} の書いてよい範囲の外が変わります（{len(differences)}か所）。"
              "前のファイルのままです。作者に知らせてください。")
        for d in differences:
            print(f"- {d}")
        return OUTSIDE
    target = application_file(folder, case, stage, input_sheet.FILE_NAME)
    from lib.docx_min import write_replacing

    write_replacing(target, blob)
    rel = places.relative_inside(folder, target)
    made = "制度データの申請画面から作り、" if first else ""
    print(f"{rel} に、{made}{len(written)}件の欄の値を書きました。")
    for screen_name, summary in written:
        print(f"- {screen_name}・{summary['欄']}（セル {summary['セル']}）")
    for n in notes:
        print(f"- 注意：{n}。")
    print("- 直前の版と比べ、書いてよい範囲の外は変わっていません。")
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
        from lib import input_sheet  # noqa: F401
        from lib import yoshiki_word as yw
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    handlers = {"outline": do_outline, "map": do_map, "write": do_write, "sheet": do_sheet}
    try:
        return handlers[args.command](folder, args, yw)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except ValueError as e:  # 書き込む位置が見つからない、様式や入力シートが読めない（FormError・SpanError）など
        print(f"しませんでした：{e}。ファイルは前のままです。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを読めないか書けませんでした（{e.strerror or e}）。ファイルは前のままです。")
        return REFUSED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
