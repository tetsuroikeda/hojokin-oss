"""説明の練習（想定問答）の材料を出す道具（SPEC F11、DESIGN 4.2・6章。TASKS M9）。

使い方（--folder "${CLAUDE_PROJECT_DIR}" を付ける。なければ今いるフォルダ）：
  python3 -B <この場所>/renshu.py [--case <案件>] [--stage <段階>] [--seido <制度データ>] [--count <数>]

出すもの（何も書かない。読むだけ）：
1. 進め方：この skill の別ファイル `説明の練習.md` の中身。ファイルの道具はプラグインの中を読めないので、
   道具が出して渡す（DESIGN 4.2・4.7）。
2. 練習で問う審査項目：制度データの「審査項目」のすべて（SPEC T11-2「質問がすべての審査項目にわたる」。TASKS B30）。
   並べ方は pick_items のとおり。答えてもらうのは3問ずつなので、問1〜3、問4〜6…の組に分けて示す。
   --count を付けたときだけ、その数に絞り、残りは「そのほかの審査項目」として並べる。
3. 計画書の本文：申請書（`案件/<案件>/<段階>/申請書/`）から道具が取り出した文字（lib/kakunin.py の plan_text。
   様式の説明の青字は除く）と、財務モデル.xlsx の前提。答えと照らすのは Claude が行う（DESIGN 6章「想定問答」）。
4. 申請書の状態：今の申請書が、完成の記録（記録/完成の記録.json）にある版と同じか。違っても練習はできる。

- --case・--stage・--seido の扱いは kakunin.py と同じ（1つなら省いてよい。段階は番号のいちばん小さいもの）。
- 会社のフォルダの外は読まない。場所の確かめは lib/places.py で行う（lib/kakunin.py を通す）。
- 終了コード：0 出した、1 補助プログラムを読み込めない、
  2 しなかった（会社のフォルダでない、引数・案件・制度データが正しくない、申請書がまだない、審査項目がない、
  別名がある など）。
"""

import sys

# 会社のフォルダやプラグインの場所に __pycache__ を書かない
sys.dont_write_bytecode = True

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT))

from lib import company  # noqa: E402

GUIDE = Path(__file__).resolve().parents[1] / "説明の練習.md"
ORAL = "口頭審査"
PER_ROUND = 3  # 1回に答えてもらう問いの数（共通の要件「一度に答えてもらう質問は3つまで」）

OK, BROKEN, REFUSED = 0, 1, 2


class Refused(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def parse(argv):
    parser = Parser(description="説明の練習の材料を出す")
    parser.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    parser.add_argument("--case", help="案件のフォルダの名前（案件/ の下）。1つなら省いてよい")
    parser.add_argument("--stage", help="段階のフォルダ（1_申請 など）。省くと番号のいちばん小さい段階")
    parser.add_argument("--seido", help="制度データ（記録/制度データ/ の中の JSON）。1つなら省いてよい")
    parser.add_argument("--count", type=int, help="練習で問う審査項目の数（省くと、すべての審査項目）")
    args = parser.parse_args(argv)
    if args.count is not None and args.count < 1:
        raise Refused("--count は1以上にしてください")
    return args


# ---------------------------------------------------------------- 審査項目


def _items(seido: dict) -> list:
    items = seido.get("審査項目")
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict) and str(it.get("名前") or "").strip()]


def _viewpoints(item: dict) -> list:
    view = item.get("観点")
    value = view.get("値") if isinstance(view, dict) else None
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def pick_items(items: list, count=None):
    """練習で問う審査項目と、そのほかの審査項目に分ける（count が None なら、すべてを問う）。

    - 区分が「口頭審査」の項目の観点に、ほかの審査項目の名前が挙がっていれば、それを先に選ぶ（口頭審査で問われる
      項目のため。省力化 第8回では、適格性・技術面・計画面）。
    - 残りは、制度データの並び順に選ぶ。口頭審査の項目そのもの（口頭審査で何を見るかの説明）は、ほかに問える
      項目がないときだけ選ぶ。
    """
    oral = [it for it in items if str(it.get("区分") or "") == ORAL]
    written = [it for it in items if it not in oral] or oral
    named = set()
    for it in oral:
        named.update(v.strip() for v in _viewpoints(it))
    first = [it for it in written if str(it["名前"]).strip() in named]
    order = first + [it for it in written if it not in first]
    if count is None:  # すべての審査項目を問う（口頭審査の説明の項目は、ほかに問える項目があれば問わずに残す）
        return order, [it for it in items if it not in order]
    chosen = order[:count]
    rest = [it for it in items if it not in chosen]
    return chosen, rest


def _source_names(seido: dict) -> dict:
    names = {}
    for doc in seido.get("資料") or []:
        if isinstance(doc, dict) and doc.get("id"):
            label = str(doc.get("名前") or doc["id"])
            if doc.get("公募回"):
                label += f"（{doc['公募回']}）"
            names[str(doc["id"])] = label
    return names


def _sources(item: dict, names: dict) -> str:
    view = item.get("観点")
    found = view.get("出典") if isinstance(view, dict) else None
    out = []
    for src in found if isinstance(found, list) else []:
        if not isinstance(src, dict):
            continue
        doc = names.get(str(src.get("資料")), str(src.get("資料") or "資料"))
        page = src.get("ページ")
        if page is None:
            out.append(doc)
            continue
        end = src.get("終わりのページ")
        out.append(f"{doc} p.{page}" + (f"〜{end}" if end and end != page else ""))
    return "、".join(out)


def _item_lines(item: dict, label: str, names: dict) -> list:
    kind = str(item.get("区分") or "").strip()
    head = f"{label}{item['名前']}" + (f"（{kind}）" if kind else "")
    where = _sources(item, names)
    lines = [head + (f"　出典：{where}" if where else "")]
    views = _viewpoints(item)
    if views:
        lines += [f"   - {v}" for v in views]
    else:
        view = item.get("観点")
        state = view.get("状態") if isinstance(view, dict) else None
        lines.append(f"   - （観点が制度データにありません{f'。状態：{state}' if state else ''}）")
    return lines


# ---------------------------------------------------------------- 計画書と申請書の状態


def _demote(lines: list) -> list:
    """見出しを1段下げる（この出力の節の下に入れるため）。"""
    return ["#" + line if line.startswith("#") else line for line in lines]


def _plan_body(folder: Path, files: dict, seido: dict, case: str, stage: str, kk) -> list:
    """計画書の本文（ファイルごとの節だけ。見出しは1段下げる）。申請書のファイルがなければ空。"""
    text = kk.plan_text(folder, files, seido, "説明の練習", case, stage)
    lines = text.splitlines()
    for n, line in enumerate(lines):
        if line.startswith("## "):
            return _demote(lines[n:])
    return []


def _guide_lines() -> list:
    """進め方（説明の練習.md）。表題の行を除き、見出しを1段下げる。"""
    try:
        lines = GUIDE.read_text(encoding="utf-8").rstrip().splitlines()
    except OSError as e:
        raise OSError(f"進め方のファイル（{GUIDE.name}）を読めませんでした（{e.strerror or e}）")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return _demote(lines)


def _model_lines(files: dict, kk) -> list:
    from lib.shinsa_result import MODEL_FILE

    if MODEL_FILE not in files:
        return ["（財務モデル.xlsx がまだありません）"]
    rows = kk._sheet_rows_text(kk._read_bytes(files[MODEL_FILE], MODEL_FILE), MODEL_FILE, only="前提")
    return rows or ["（財務モデル.xlsx に「前提」のシートがありません）"]


def _state_line(folder: Path, case: str, stage: str, kk) -> str:
    from lib import shinsa_result

    current = shinsa_result.application_hash(folder, case, stage)
    entries = [e for e in kk._completion_entries(folder) if (e.get("案件"), e.get("段階")) == (case, stage)]
    same = [e for e in entries if e.get("申請書のハッシュ") == current]
    if same:
        return f"完成の記録にある版です（確かめの番号：{same[-1].get('確かめの番号')}）。"
    if entries:
        return "完成の記録の後に、申請書が変わっています（練習はできます。終わりに社長へ一言添えてください）。"
    return "まだ完成の記録がありません（kaku の「確かめる」を通っていません。練習はできます。終わりに社長へ一言添えてください）。"


# ---------------------------------------------------------------- 出す


def materials(folder: Path, args, kk) -> str:
    case = kk.find_case(folder, args.case)
    stage = kk.find_stage(folder, case, args.stage)
    seido, seido_rel = kk.find_seido(folder, args.seido)
    if seido is None:
        raise Refused(f"{kk.SEIDO_DIR}/ に制度データがありません。審査項目が分からないので、先に junbi で制度データを作ってください")
    items = _items(seido)
    if not items:
        raise Refused(f"制度データ（{seido_rel}）に審査項目がありません。先に junbi で制度データの審査項目を埋めてください")
    files = kk.application_files(folder, case, stage)
    body = _plan_body(folder, files, seido, case, stage, kk)
    if not body:
        raise Refused(f"{case}／{stage} の申請書（申請書/ の中の計画書・入力シート）がまだありません。"
                      "先に計画書を書いてから練習してください")
    guide = _guide_lines()
    chosen, rest = pick_items(items, args.count)
    names = _source_names(seido)
    out = [f"# 説明の練習の材料（案件：{case}　段階：{stage}）", "",
           f"申請書の状態：{_state_line(folder, case, stage, kk)}", "",
           "下の「進め方」に従って、「練習で問う審査項目」の問1・問2…の項目から1問ずつ作り（どの項目も飛ばさない）、"
           "社長の答えを「計画書の本文」と照らしてください。",
           f"始めに問いの全体の一覧（問1〜問{len(chosen)}）を示し、答えてもらうのは{PER_ROUND}問ずつにしてください。",
           "この出力は社長にそのまま見せず、問いと結果だけを普段の言葉で伝えてください。", "",
           "## 進め方（kaku の別ファイル「説明の練習」）", ""] + guide + [
           "", f"## 練習で問う審査項目（{len(chosen)}つ。制度データ：{seido_rel}）", ""]
    for n, item in enumerate(chosen, 1):
        if (n - 1) % PER_ROUND == 0:
            last = min(n + PER_ROUND - 1, len(chosen))
            out.append(f"（{(n - 1) // PER_ROUND + 1}回目に答えてもらう問い：問{n}〜問{last}）")
        out += _item_lines(item, f"問{n}：", names)
    out.append("")
    if rest:
        out += ["## そのほかの審査項目（今回は問わない。続けて練習するときに使う）", ""]
        for item in rest:
            out += _item_lines(item, "- ", names)
        out.append("")
    out += ["## 計画書の本文", "",
            "申請書のファイルから、道具が文字を取り出したものです。様式の説明の青字は除いています。", ""]
    out += body
    out += ["", "### 財務モデルの前提（財務モデル.xlsx の「前提」シート）", ""]
    out += _demote(_model_lines(files, kk))
    return "\n".join(out).rstrip() + "\n"


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
    try:
        text = materials(folder, args, kk)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except ValueError as e:  # CheckError（案件・段階・制度データ・別名）、Word・Excel が読めないなど
        print(f"しませんでした：{e}。")
        return REFUSED
    except OSError as e:
        print(f"しませんでした：ファイルを読めませんでした（{e.strerror or e}）。")
        return REFUSED
    print(text, end="")
    return OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
