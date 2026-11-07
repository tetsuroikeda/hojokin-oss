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
   前提のセルに名前を付け、計画は名前を使った数式で書く。指定に「決算書の科目」（kijun --into が書く）があれば、
   計画のシートのいちばん下に損益の内訳（決算書の科目。計画の年は、区分の値を科目の割合で分けた見込み）を置く。
2. LibreOffice で計算し直し（計算し直しは「常に」）、数式のセルの値が、すべて Python の計算と一致するかを確かめる。
   食い違えば、財務モデル.xlsx を置かずに終了コード3で終える（道具の不具合なので、作者に知らせる）。
   LibreOffice がない・動かないときは、確かめずに置き、そのことを伝える（Excel で開くと計算される）。
3. 制度データの「数値の要件」の基準で、様式（別紙4）と同じ計算をして判定する。基準との差が0.01ポイント未満なら、
   境目として知らせる（社長に、計画の数字を少し上げることを勧める）。

4. 数量の前提（名前が「数量_」で始まるもの）を2割減らした場合も、要件を満たすかを判定する（DESIGN 8.3）。
   指定に「省力化」があれば、様式その3 の別紙1・別紙3 と同じ計算で、省力化指数と投資回収期間を出す。
5. 置いたら、数字の控え `記録/財務モデルの数字.json`（前提の値・計画の数字・指標・判定）を書く。計画書・様式・
   入力シートの数字と財務モデルを照らすとき（kakunin.py）は、この控えを読む（財務モデル.xlsx は数式だけで、
   計算済みの値を持たないため）。

  python3 -B <この場所>/zaimu_model.py kijun --input 記録/一時/決算の内訳.json [--into 記録/財務モデルの指定.json]
                                             [--as 基準年度|直近期] [--json]
      決算書の科目ごとの金額を、財務モデルの基準年度の区分（売上・原材料費・給与支給総額・その他の人件費・
      減価償却費・その他の経費）に足し上げる（Claude は足し算をしない。波3 の気づき #7）。組み立てた営業利益が
      決算書の営業利益と1円でも違えば、区分の割り当てか科目の抜けを疑い、何も書かずに断る。
      --into を付けると、その指定の「基準年度」を、足し上げた値と出典で置き換える（ほかに書くのは、下の「売上原価の
      割合」と「決算書の科目」だけ。前提や事業の式などは変えない）。
      --as 直近期 なら「基準年度」ではなく「直近期の実績」を置き換える（決算が出ているのが直近期だけで、基準年度は
      補助事業の完了日を含む先の期のとき。基準年度は、直近期の実績からの式で指定に書く）。
      行に「損益の区分」（売上原価 か 販管費）を付けると、区分ごとの売上原価の割合を出し、--into の指定の
      「売上原価の割合」に書く（様式の別紙4 の売上原価・販売費及び一般管理費に使う）。決算書の売上原価と販管費の
      合計（"売上原価"・"販売費及び一般管理費"）を渡すと、行の合計と1円でも違えば断る。
      --into では、科目ごとの金額も指定の「決算書の科目」に書く（期は --as のもの）。build はこれを使って、計画の
      シートのいちばん下に「損益の内訳」（決算書の科目。計画の年は、区分の値を決算書の科目の割合で分けた見込み）を置く。
      入力：{"決算書": "決算書 第18期", "行": [{"科目": "材料費", "区分": "原材料費", "金額": 82600000, "出典": "p.3",
             "損益の区分": "売上原価"}], "営業利益": {"金額": 4800000, "出典": "p.2"},
             "売上原価": {"金額": 148200000, "出典": "p.3"}, "販売費及び一般管理費": {"金額": 48600000, "出典": "p.3"},
             "人数": {"役員数": {"値": 2, "根拠": "…", "出典": "…"}, …}}

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

from lib import company, company_record, places  # noqa: E402

SEIDO_DIR = "記録/制度データ"
WORK_DIR = f"{company.MARKER_DIR}/{company.TEMP_DIR}/財務モデル"
NUMBERS_FILE = "記録/財務モデルの数字.json"
OK, BROKEN, REFUSED, MISMATCH = 0, 1, 2, 3
KIJUN_BLOCKS = ("基準年度", "直近期")  # kijun --as：置き換える所（直近期は、指定の「直近期の実績」）
SIDES = {"売上原価": "売上原価", "販管費": "販売費及び一般管理費", "販売費及び一般管理費": "販売費及び一般管理費"}


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
    kijun = sub.add_parser("kijun", help="決算書の科目を、基準年度の区分に足し上げる")
    kijun.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    kijun.add_argument("--input", required=True, help="決算の内訳（会社のフォルダの中の JSON）")
    kijun.add_argument("--into", help="基準年度を置き換える財務モデルの指定（会社のフォルダの中の JSON）")
    kijun.add_argument("--as", dest="as_block", choices=KIJUN_BLOCKS, default=KIJUN_BLOCKS[0],
                       help="置き換える所（基準年度か、直近期の実績か）")
    kijun.add_argument("--json", action="store_true", help="JSON で出す")
    compare = sub.add_parser("compare", help="実績を財務モデルに入れて、計画と比べる（採択後の実績報告・効果報告）")
    compare.add_argument("--folder", help="会社のフォルダ（${CLAUDE_PROJECT_DIR}）。なければ今いるフォルダ")
    compare.add_argument("--spec", required=True, help="応募のときの財務モデルの指定（会社のフォルダの中の JSON）")
    compare.add_argument("--actual", required=True, help="その年の実績（会社のフォルダの中の JSON。記録/一時/実績.json）")
    compare.add_argument("--seido", help="数値の要件を読む制度データ（省くと 記録/制度データ/ の直下の1つ）")
    compare.add_argument("--target", type=float, help="応募のときに自分で定めた目標値（1人当たり給与支給総額の伸び。%）")
    compare.add_argument("--grant", type=int, help="補助金の交付額（円。交付決定通知書か確定の通知から）")
    compare.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)
    if args.command not in ("build", "kijun", "compare"):
        raise Refused("build・kijun・compare のどれかを付けてください")
    return args


def run_compare(folder: Path, args) -> int:
    """実績を財務モデルに入れて計画と比べる（B31c。SPEC F12・T12-4）。満たさない要件があっても、比べられたら終了コード 0。"""
    from lib import jisseki, youken, zaimu
    try:
        raw_spec, _ = read_json_inside(folder, args.spec, "財務モデルの指定")
        actual, _ = read_json_inside(folder, args.actual, "実績")
        seido, _path = find_seido(folder, args.seido)
        if seido is None:
            raise Refused("制度データがありません（数値の要件と返還の条件を読むため。--seido で渡してください）")
        spec = zaimu.parse_spec({k: v for k, v in raw_spec.items() if k != "説明"} if isinstance(raw_spec, dict) else raw_spec)
        result = jisseki.compare(spec, seido, actual, target=args.target, grant=args.grant)
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except (youken.YoukenError, zaimu.SpecError, jisseki.JissekiError) as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(jisseki.report(result), end="")
    return OK


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


def yen_list(values, digits: int = 0) -> str:
    return "、".join("—" if v is None else (f"{v:,.{digits}f}" if isinstance(v, (int, float)) else str(v)) for v in values)


def low_case_lines(low: dict) -> list:
    """数量が2割少ない場合の読み方（今の数量まで減らしていないか、変わる行、動かない原材料費、最後の年の差）。"""
    lines = []
    if low.get("参考の判定（今の数量まで減らした場合）"):
        lines.append(f"  参考：今の数量まで減らした場合の判定は「{low['参考の判定（今の数量まで減らした場合）']}」（上の伸びはこの場合のもの）")
    last = low.get("最後の年")
    if last:
        moved = "、".join(f"{m['事業']}の{m['行']}" for m in low.get("数量を減らすと変わる行") or []) or "なし"
        lines.append(f"  {last['年']}年目：売上 {last['売上'][0]:,.0f}円 → {last['売上'][1]:,.0f}円、付加価値額 "
                     f"{last['付加価値額'][0]:,.0f}円 → {last['付加価値額'][1]:,.0f}円（数量を減らすと変わる行：{moved}）")
    lines += [f"  知らせ：{note}" for note in low.get("知らせ") or []]
    return lines


def timeline_lines(tl) -> list:
    if not tl:
        return []
    deadline = (f"{tl['応募の締切']}（{tl['応募の締切の出典']}）" if tl["応募の締切の出典"] else tl["応募の締切"]) if tl["応募の締切"] \
        else "分からない"
    lines = ["", "年度（様式の別紙4 の決算期。基準年度は補助事業の完了日を含む期、1年目はその翌年度）",
             f"- 直近期：{tl['直近期']}" + (f"（様式の直近期は {tl['様式の直近期']}）" if tl["様式の直近期"] != tl["直近期"] else "")
             + f"／締切期：{tl['締切期']}（応募の締切 {deadline} を含む期）",
             f"- 基準年度：{tl['基準年度']}（補助事業の完了予定 {tl['補助事業の完了予定']} を含む期）／経過年数 {tl['経過年数']}年"
             f"／計画：{tl['計画の年'][0]}〜{tl['計画の年'][-1]}"]
    lines += [f"  知らせ：{note}" for note in tl.get("知らせ") or []]
    return lines


BEPPYO_SHOWN = ("売上高", "売上原価", "販売費及び一般管理費", "営業利益", "人件費", "既存設備の減価償却費",
                "本補助金で導入する設備の減価償却費", "付加価値額", "役員数", "常勤従業員数", "労働生産性の伸び", "給与支給総額",
                "給与を受けた従業員数", "1人当たり給与支給総額の伸び")


def beppyo_lines(b) -> list:
    """様式（別紙4）に写す数字（円に丸めた値）。"""
    if not b:
        return []
    rows = b["年ごと"]
    lines = ["", "様式（別紙4）に写す数字（円に丸めた値。列は " + "、".join(b["列"]) + "）"]
    for key in BEPPYO_SHOWN:
        if key in rows:
            lines.append(f"- {key}：{yen_list(rows[key]) if '伸び' not in key else '、'.join(fmt_growth(v) if v is not None else '—' for v in rows[key])}")
    check = b.get("照らし")
    if check:
        lines.append(f"- 照らし：売上原価＋販売費及び一般管理費（丸める前）と 売上−営業利益 の差は、年ごとの最大で {check['差の最大']:.6f}円"
                     f" → {'合う' if check['合う'] else '合わない（道具の不具合なので、作者に知らせる）'}")
    a = b.get("足下の賃上げ")
    if a:
        lines.append(f"- 足下の賃上げ（{'、'.join(a['列'])}）：⑦ {yen_list(a['給与支給総額'])}／⑧ {yen_list(a['給与を受けた従業員数'])}"
                     f"／1人当たり {yen_list(a['1人当たり給与支給総額'], 2)} → 年平均成長率 {fmt_growth(a['伸び'])}（経過年数 {a['経過年数']}年。"
                     "要件ではなく審査で見る値。比べる目安は公募要領の審査項目で確かめる）")
    if not b.get("様式の値と財務モデルの伸びの違い"):
        lines.append("- 円に丸めた値から様式と同じ計算をしても、伸びは財務モデル（判定に使った値）と同じです")
    lines += [f"  知らせ：{note}" for note in b.get("知らせ") or []]
    return lines


def accounts_lines(acc) -> list:
    """損益の内訳（決算書の科目）を置いた場所と分け方。"""
    if not acc:
        return []
    shape = "売上高・売上原価・売上総利益・販売費及び一般管理費・営業利益の形" if acc["損益の区分"] else "区分ごと"
    period = "基準年度" if acc["期"] == "基準年度" else "直近期（決算書）"
    lines = ["", f"損益の内訳：計画のシートの {acc['行']} 行目から、{acc['決算書'] or '決算書'}の科目 {acc['科目の数']} 個を{shape}で"
             f"置きました。計画の年の科目の値は、区分の値を{period}の科目の割合で分けた見込みです（区分の計と営業利益は合算と同じ）。"]
    if any(v != 0 for v in acc["照らし"]):
        lines.append("  照らし：科目の和から出した営業利益が、合算の営業利益と合いません（道具の不具合なので、作者に知らせる）")
    lines += [f"  知らせ：{note}" for note in acc.get("知らせ") or []]
    return lines


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
    low = s.get("数量が2割少ない場合")
    lines.append("")
    if low is None:
        lines.append("数量が2割少ない場合：数量の前提（名前が「数量_」で始まるもの）がないので、判定していません。"
                     "売上を「単価 × 数量」に分け、数量の前提の名前を「数量_」で始めてください。")
    else:
        lines.append(f"数量が2割少ない場合（{'・'.join(low['数量の前提'])} を0.8倍）：数値の要件（特例を除く）を"
                     f"すべて満たすか → {low['判定'] if low['判定'] is not None else '判定できる要件がありません'}")
        for r in low["要件ごと"]:
            tag = "（特例を選ぶときだけ）" if r["特例"] else ""
            years = "、".join(f"{p['年']}年目 {fmt_growth(p['伸び'])}" for p in r["年ごと"])
            lines.append(f"- {r['名前']}{tag}：{r['判定']}（{years}）")
        if low.get("理由"):
            lines.append(f"- 計算できませんでした：{low['理由']}")
        if low["判定"] == "満たさない":
            lines.append("  数量が2割少ないと要件を満たせません。要件を満たせないと返還につながるので、社長に伝えてください。")
        lines += low_case_lines(low)
    lines += timeline_lines(s.get("年度")) + beppyo_lines(s.get("別紙4")) + accounts_lines(result.get("損益の内訳"))
    sh = s.get("省力化")
    if sh is not None:
        shown = sh["表示"]
        lines.append("")
        lines.append("省力化の指標（様式その3 の別紙1・別紙3 と同じ計算。数字は道具が出したものを使う）")
        lines.append(f"- 設備導入により削減される業務に要していた時間：{sh['削減される業務に要していた時間']:.2f} 時間/日")
        lines.append(f"- 設備導入後に発生する業務に要する時間：{sh['導入後に発生する業務に要する時間']:.2f} 時間/日")
        lines.append(f"- 省力化指数：{shown['省力化指数']:.2f}")
        lines.append(f"- 削減工数：{shown['削減工数']:.2f} 時間/日")
        lines.append(f"- 増加した付加価値額（1年あたり）：{sh['増加した付加価値額']:,.0f}円")
        payback = shown["投資回収期間"]
        lines.append("- 投資回収期間：" + (f"{payback:.2f} 年" if payback is not None else "計算できません（分母が0以下）"))
        if sh["根拠か出典のない数"]:
            lines.append("  根拠か出典のない数：" + "、".join(sh["根拠か出典のない数"]))
        if sh["仮の数"]:
            lines.append("  仮の数（後で確かめる）：" + "、".join(sh["仮の数"]))
    eff = s.get("投資の効果の見え方")
    if eff:
        lines.append("")
        lines.append("投資の効果の見え方（審査員が設備投資の効果をどう読むか。数字は計画の合算から道具が出したもの）")
        years = "、".join(("基準" if i == 0 else f"{i}年目") + f" {p:,.0f}円" + (f"（{m * 100:.1f}%）" if m is not None else "")
                          for i, (p, m) in enumerate(zip(eff["営業利益"], eff["営業利益率"])))
        lines.append(f"- 営業利益（営業利益率）：{years}")
        lines.append(f"- 営業利益の増加（基準年度から最終年）：{eff['営業利益の増加（基準年度から最終年）']:,.0f}円")
        lines.append(f"- 減価償却費の増加：{eff['減価償却費の増加（基準年度から最終年）']:,.0f}円")
        if eff.get("省力化で浮く時間の人件費相当額（1年あたり）"):
            lines.append(f"- 省力化で浮く時間の人件費相当額（1年あたり）：{eff['省力化で浮く時間の人件費相当額（1年あたり）']:,.0f}円")
        if eff["知らせ"]:
            lines.append("  効果の見え方の知らせ（財務モデルの式と、計画書の効果の筋を見直す。社長にも伝える）")
            lines += [f"  - {note}" for note in eff["知らせ"]]
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
    if s.get("根拠か出典のない基準年度の値"):
        lines.append("根拠か出典のない基準年度の値（決算書などの出典を付ける）：" + "、".join(s["根拠か出典のない基準年度の値"]))
    if s["仮の前提"]:
        lines.append("仮の前提（後で確かめる）：" + "、".join(s["仮の前提"]))
    if s.get("仮の基準年度の値"):
        lines.append("仮の基準年度の値（後で確かめる）：" + "、".join(s["仮の基準年度の値"]))
    if s.get("根拠か出典のない、そのほかの値"):
        lines.append("根拠か出典のない値（直近期の実績・売上原価の割合など。出典を付ける）：" + "、".join(s["根拠か出典のない、そのほかの値"]))
    if s.get("仮の、そのほかの値"):
        lines.append("仮の値（直近期の実績・売上原価の割合など。後で確かめる）：" + "、".join(s["仮の、そのほかの値"]))
    if result.get("数字の控え"):
        lines.append("")
        lines.append(f"数字の控えを {result['数字の控え']} に書きました（計画書と財務モデルの照合に使う）。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 数字の控え


def fact_marks(folder: Path) -> dict:
    """作ったときの会社の記録の事実の指紋（後で増えた・変わった事実を、確かめで知らせるため。B37）。読めなければ空。"""
    try:
        return company_record.fact_marks(company_record.load(folder))
    except company_record.RecordError:
        return {}


def write_numbers(folder: Path, data: dict) -> str:
    places.no_link_on_the_way(folder, NUMBERS_FILE)
    target = places.actual(folder, NUMBERS_FILE, partial=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(target))
    return NUMBERS_FILE


# ---------------------------------------------------------------- 決算書の科目を、基準年度の区分に足し上げる


def kijun_block(data, zaimu) -> dict:
    """決算の内訳から、財務モデルの指定の「基準年度」を組み立てる。合わなければ Refused。"""
    if not isinstance(data, dict):
        raise Refused("決算の内訳の形が違います（JSON の { } ではありません）")
    head = data.get("決算書") if isinstance(data.get("決算書"), str) else ""
    rows = data.get("行")
    if not isinstance(rows, list) or not rows:
        raise Refused("決算の内訳に「行」（科目ごとの金額）がありません")
    totals = {key: 0.0 for key in zaimu.ROW_KEYS}
    parts = {key: [] for key in zaimu.ROW_KEYS}
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise Refused(f"行の{i}つ目の形が違います")
        name, kind, amount = row.get("科目"), row.get("区分"), row.get("金額")
        if not isinstance(name, str) or not name.strip():
            raise Refused(f"行の{i}つ目に科目の名前がありません")
        if kind not in zaimu.ROW_KEYS:
            raise Refused(f"行の{i}つ目（{name}）の区分「{kind}」は使えません（使える区分：{'、'.join(zaimu.ROW_KEYS)}）")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise Refused(f"行の{i}つ目（{name}）の金額が数ではありません")
        totals[kind] += float(amount)
        source = row.get("出典") if isinstance(row.get("出典"), str) else ""
        parts[kind].append(f"{name.strip()} {float(amount):,.0f}円" + (f"（{source.strip()}）" if source.strip() else ""))
    profit = data.get("営業利益")
    if not isinstance(profit, dict) or isinstance(profit.get("金額"), bool) or not isinstance(profit.get("金額"), (int, float)):
        raise Refused("決算の内訳に、決算書の営業利益（{\"金額\": …, \"出典\": …}）がありません。足し上げの確かめに使います")
    built = totals["売上"] - sum(totals[k] for k in zaimu.ROW_KEYS if k != "売上")
    expected = float(profit["金額"])
    if abs(built - expected) >= 1:
        raise Refused(f"足し上げた営業利益 {built:,.0f}円が、決算書の営業利益 {expected:,.0f}円と合いません"
                      f"（差 {built - expected:+,.0f}円）。区分の割り当てか、抜けた科目・二重に入れた科目を確かめてください")
    block = {}
    for key in zaimu.ROW_KEYS:
        if not parts[key]:
            block[key] = {"値": 0, "根拠": "決算書", "出典": (head + "：" if head else "") + "該当する科目なし"}
            continue
        block[key] = {"値": totals[key], "根拠": "決算書", "出典": (head + "：" if head else "") + "＋".join(parts[key])}
    people = data.get("人数") or {}
    if not isinstance(people, dict):
        raise Refused("人数は { } の形にしてください")
    extra = sorted(set(people) - set(zaimu.PEOPLE_KEYS))
    if extra:
        raise Refused("人数に、知らない項目があります：" + "、".join(extra))
    for key in zaimu.PEOPLE_KEYS:
        if key in people:
            block[key] = people[key]
    shares = cost_share_block(data, rows, totals, head, zaimu)
    return {"基準年度": block, "営業利益": {"足し上げ": built, "決算書": expected},
            "人数のない項目": [k for k in zaimu.PEOPLE_KEYS if k not in people],
            "売上原価の割合": shares, "決算書の科目": accounts_block(rows, head, shares is not None)}


def accounts_block(rows: list, head: str, sided: bool) -> dict:
    """指定の「決算書の科目」（財務モデルの損益の内訳に使う）。科目・区分・金額と、損益の区分・出典（あれば）。"""
    out = []
    for row in rows:
        item = {"科目": row["科目"].strip(), "区分": row["区分"], "金額": row["金額"]}
        if sided and row["区分"] != "売上":
            item["損益の区分"] = SIDES[row["損益の区分"]]
        if isinstance(row.get("出典"), str) and row["出典"].strip():
            item["出典"] = row["出典"].strip()
        out.append(item)
    return {"決算書": head, "行": out}


def cost_share_block(data: dict, rows: list, totals: dict, head: str, zaimu) -> "dict | None":
    """行の「損益の区分」（売上原価か販管費）から、区分ごとの売上原価の割合（様式の別紙4 の売上原価・販管費に使う）。

    どの行にも付いていなければ None（今までどおり）。一部の行だけなら断る。決算書の売上原価・販管費の合計を渡されたら、
    行の合計と照らす。割合は、その区分の売上原価の科目の和 ÷ その区分の和（区分の和が0なら書かない）。"""
    cost_rows = [r for r in rows if r.get("区分") != "売上"]
    marked = [r for r in cost_rows if r.get("損益の区分") is not None]
    if not marked:
        return None
    unmarked = [r["科目"] for r in cost_rows if r.get("損益の区分") is None]
    if unmarked:
        raise Refused("損益の区分（売上原価か販管費）が付いていない行があります：" + "、".join(unmarked)
                      + "。付けるときは、売上のほかのすべての行に付けてください")
    sums = {"売上原価": 0.0, "販売費及び一般管理費": 0.0}
    cost_by_kind = {key: 0.0 for key in zaimu.COST_KEYS}
    parts = {key: [] for key in zaimu.COST_KEYS}
    for r in cost_rows:
        side = SIDES.get(r["損益の区分"]) if isinstance(r["損益の区分"], str) else None
        if side is None:
            raise Refused(f"{r['科目']}の損益の区分「{r['損益の区分']}」は使えません（売上原価 か 販管費）")
        sums[side] += float(r["金額"])
        if side == "売上原価":
            cost_by_kind[r["区分"]] += float(r["金額"])
            parts[r["区分"]].append(f"{r['科目'].strip()} {float(r['金額']):,.0f}円")
    for side, total in sums.items():
        given = data.get(side) if side in data else (data.get("販管費") if side == "販売費及び一般管理費" else None)
        if given is None:
            continue
        if not isinstance(given, dict) or isinstance(given.get("金額"), bool) or not isinstance(given.get("金額"), (int, float)):
            raise Refused(f"決算の内訳の「{side}」は {{\"金額\": …, \"出典\": …}} の形にしてください")
        if abs(total - float(given["金額"])) >= 1:
            raise Refused(f"損益の区分が{side}の行の合計 {total:,.0f}円が、決算書の{side} {float(given['金額']):,.0f}円と合いません"
                          f"（差 {total - float(given['金額']):+,.0f}円）。行の損益の区分を確かめてください")
    out = {}
    for key in zaimu.COST_KEYS:
        if totals[key] == 0:
            continue
        share = cost_by_kind[key] / totals[key]
        value = int(share) if share in (0.0, 1.0) else share
        listed = "＋".join(parts[key]) if parts[key] else "なし"
        out[key] = {"値": value, "根拠": "決算書",
                    "出典": (head + "：" if head else "") + f"売上原価の科目（{listed}）÷ {key}の計 {totals[key]:,.0f}円"}
    return {"割合": out, "売上原価": sums["売上原価"], "販売費及び一般管理費": sums["販売費及び一般管理費"]}


def cost_share_lines(shares) -> list:
    if shares is None:
        return []
    lines = [f"損益の区分：売上原価の科目の計 {shares['売上原価']:,.0f}円、販売費及び一般管理費の科目の計 "
             f"{shares['販売費及び一般管理費']:,.0f}円。区分ごとの売上原価の割合（残りは販管費）："]
    for key, item in shares["割合"].items():
        lines.append(f"- {key}：{item['値'] * 100:.2f}%（{item['出典']}）")
    return lines


def run_kijun(folder: Path, args) -> int:
    from lib import zaimu
    try:
        data, _ = read_json_inside(folder, args.input, "決算の内訳")
        result = kijun_block(data, zaimu)
        if args.into:
            spec_data, spec_real = read_json_inside(folder, args.into, "財務モデルの指定")
            if not isinstance(spec_data, dict):
                raise Refused("財務モデルの指定の形が違います")
            block = "基準年度" if args.as_block == "基準年度" else zaimu.RECENT_KEY
            old_base = spec_data.get(block) if isinstance(spec_data.get(block), dict) else {}
            spec_data[block] = dict(result["基準年度"])
            for key in zaimu.PEOPLE_KEYS:  # 人数を渡さなかったときは、指定にある人数を残す
                if key not in spec_data[block] and key in old_base:
                    spec_data[block][key] = old_base[key]
            if result["売上原価の割合"] is not None:
                spec_data[zaimu.COST_SHARE_KEY] = result["売上原価の割合"]["割合"]
            spec_data[zaimu.ACCOUNTS_KEY] = dict(result["決算書の科目"], 期=args.as_block)
            rel = places.relative_inside(folder, spec_real)
            places.no_link_on_the_way(folder, rel)
            tmp = spec_real.with_name(spec_real.name + ".tmp")
            tmp.write_text(json.dumps(spec_data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            os.replace(str(tmp), str(spec_real))
            result["書いた指定"] = rel
    except Refused as e:
        print(f"しませんでした：{e}。")
        return REFUSED
    except places.PlaceError as e:
        print(f"しませんでした：{e.link or e} が別名（シンボリックリンク）になっているので、書きません。")
        return REFUSED
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return OK
    lines = [f"決算書の科目を、{'基準年度' if args.as_block == '基準年度' else zaimu.RECENT_KEY}の区分に足し上げました（足し上げた営業利益 "
             f"{result['営業利益']['足し上げ']:,.0f}円 が決算書と一致）。"]
    for key in zaimu.ROW_KEYS:
        item = result["基準年度"][key]
        lines.append(f"- {key}：{item['値']:,.0f}円（{item['出典']}）")
    for key in zaimu.PEOPLE_KEYS:
        if key in result["基準年度"]:
            v = result["基準年度"][key]
            lines.append(f"- {key}：{v.get('値') if isinstance(v, dict) else v}人")
    if result["人数のない項目"]:
        lines.append("人数を渡していない項目（指定に書く）：" + "、".join(result["人数のない項目"]))
    lines += cost_share_lines(result["売上原価の割合"])
    if result.get("書いた指定"):
        block = "基準年度" if args.as_block == "基準年度" else zaimu.RECENT_KEY
        lines.append(f"{result['書いた指定']} の{block}を置き換えました"
                     + ("（売上原価の割合も書きました）。" if result["売上原価の割合"] is not None else "。"))
        lines.append(f"決算書の科目（{len(result['決算書の科目']['行'])}個）も、指定の「{zaimu.ACCOUNTS_KEY}」に書きました"
                     "（財務モデルの計画のシートの下に、損益の内訳として置きます）。")
        if args.as_block == "直近期":
            lines.append(f"基準年度は、{zaimu.RECENT_KEY}からの式（例：{{\"式\": \"直近_給与支給総額*(1+賃上げ率)^経過年数\", "
                         "\"根拠\": …, \"出典\": …}）で指定に書き、「年度」（直近期・補助事業の完了予定）を足してから build してください。")
    else:
        lines.append("指定に入れるときは --into 記録/財務モデルの指定.json を付けて動かし直してください（写し書きしない）。")
    print("\n".join(lines))
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
        from lib import dates, libreoffice, youken, zaimu
    except Exception as e:  # 同梱のファイルが欠けた・壊れた、Python が古いなど
        print(f"補助プログラムを読み込めませんでした（{type(e).__name__}: {e}）。"
              "プラグインを入れ直してから、もう一度試してください。")
        return BROKEN
    if args.command == "kijun":
        return run_kijun(folder, args)
    if args.command == "compare":
        return run_compare(folder, args)

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
        spec = zaimu.parse_spec(zaimu.with_seido_deadline(raw_spec, seido))  # 年度の応募の締切がなければ制度データから
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
        numbers_rel = None
        if not check["食い違い"]:
            places.no_link_on_the_way(folder, zaimu.MODEL_FILE)
            os.replace(str(built), str(target))
            placed = True
            seido_rel = relative(folder, seido_path) if seido_path is not None else None
            when = dates.format_datetime(dates.now(folder))
            record = zaimu.numbers_record(spec, book, seido_rel, when)
            record[company_record.FACT_MARKS_KEY] = fact_marks(folder)
            numbers_rel = write_numbers(folder, record)
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
        "数字の控え": numbers_rel,
        "中身": book.summary,
        "損益の内訳": book.accounts,  # 数字の控えには入れない（控えの形は変えない）
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(report_text(result))
    return MISMATCH if check["食い違い"] else OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
