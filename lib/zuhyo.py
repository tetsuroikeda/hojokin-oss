"""計画書の図表と写真（SPEC F8「図表（作業の前後比較、工程表、グラフなど）と、社長が用意した写真を入れられる」T8-3、
DESIGN 8.2「図表は道具が数字から作る（数字は根拠対照表と同じもの）」。TASKS B33）。

役割の分け方（DESIGN 6章）
- どの図をどこに置くかは Claude が決める。書く文の中に、図を置く行を1行で書く（下の「図を置く行」）。
- 図の数字は、この道具が取る。前後比較と数値計画は財務モデルの数字の控え（記録/財務モデルの数字.json）から取るので、
  根拠対照表と財務モデルの照合を通った数字と同じになる。工程表の月は、Claude が図表の指定（JSON）で渡す。
- 写真は、会社のフォルダの中の PNG・JPEG を、そのまま入れる。

図を置く行（書く文の中で、1行まるごと。前後の空白は見ない）
- 【図：前後比較】 工程ごとの1日の作業時間を、導入前と導入後で比べる横棒（財務モデルの「省力化の作業」）
- 【図：数値計画】 付加価値額・労働生産性・1人当たり給与支給総額の、基準年度と計画の年ごとの棒（財務モデルの「指標」）
- 【図：工程表】   図表の指定の「工程表」の行を、月ごとの横棒にする
- 【写真：<会社のフォルダの中の PNG か JPEG>｜<題>】 写真をそのまま入れる（題は代わりの文になる）

図表の指定（--figures で渡す JSON。工程表のときだけ要る）
{"工程表": {"題": "補助事業のスケジュール", "行": [{"作業": "発注", "始め": "2027-07", "終わり": "2027-07"}, …]}}

描き方（作図の手引きに沿う）：グラフは1つの軸だけ（2つの物差しを重ねない。数値計画は指標ごとに小さな図を並べる）、
棒は0から、細い棒に値を直接書く、目盛りの線は薄く、文字は墨の色（系列の色を文字に使わない）。色は2つだけで、
灰色が「今・導入前・実績」、青が「導入後・計画」。どの図も、題と値の文字で読めるので、色だけに頼らない。
SVG を作り、LibreOffice で PNG にする（日本語の文字を、Mac の字形で描くため。LibreOffice は PDF への変換でも使う）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

FIGURE_LINE = re.compile(r"^\s*【(図|写真)：(.+?)】\s*$")
KINDS = ("前後比較", "数値計画", "工程表", "推移")
# 推移の図（【図：推移｜売上・営業利益】）で並べられる財務モデルの行と、その在りか（数字の控えの「中身」の中）。
# 制度によって見せたい数字が違う（持続化は売上と客数、省力化は付加価値額と労働生産性など）ので、書き手が選ぶ（11/7）
TREND_SOURCES = ("合算", "指標", "投資の効果の見え方", "人数")
TREND_MAX = 3  # 4つ並べると、棒の上の数が隣と重なった
NUMBERS_FILE = "記録/財務モデルの数字.json"  # lib/zaimu.py の NUMBERS_FILE と同じ
PHOTO_TYPES = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg"}

# 色と文字（作図の手引きの既定の色から。灰色は「今」を控えめに見せる）
SURFACE = "#ffffff"
INK = "#1f1f1e"
INK_2 = "#52514e"
GRID = "#e3e2de"
NOW = "#8c8a85"   # 今・導入前・実績
PLAN = "#2a78d6"  # 導入後・計画
FONT = "Hiragino Sans, Hiragino Kaku Gothic ProN, Yu Gothic, Meiryo, sans-serif"
WIDTH = 1600  # 図の幅（px）。Word では本文の幅（16cm ほど）に縮めるので、250dpi ほどになる


class FigureError(ValueError):
    """図を作らなかった（数字の控えがない、指定が正しくない、LibreOffice がない など）。"""


@dataclass
class Figure:
    """Word に入れる絵。data は PNG か JPEG のバイト列。"""

    key: str          # 書く文の中の、図を置く行（前後の空白を除いたもの）
    title: str        # 代わりの文（審査役に渡す本文にも「［図：題］」で出る）
    data: bytes
    kind: str         # png / jpeg
    width_px: int
    height_px: int
    photo: bool = False


# ---------------------------------------------------------------- 図を置く行


def figure_lines(text: str) -> List[Tuple[str, str, str]]:
    """書く文の中の図を置く行（行、種類〈図・写真〉、中身）。同じ行が2回あっても1つにする。"""
    out: List[Tuple[str, str, str]] = []
    for line in text.split("\n"):
        m = FIGURE_LINE.match(line)
        if m and line.strip() not in [x[0] for x in out]:
            out.append((line.strip(), m.group(1), m.group(2).strip()))
    return out


# ---------------------------------------------------------------- 画像の大きさ


def image_size(data: bytes) -> Tuple[str, int, int]:
    """PNG・JPEG の（種類、幅、高さ）。どちらでもなければ FigureError。"""
    if data[:4] == b"\x89PNG" and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", w, h
            i += 2 + length
    raise FigureError("PNG か JPEG の画像ではありません")


# ---------------------------------------------------------------- SVG の部品


def _text(x: float, y: float, s: str, size: int = 26, color: str = INK, anchor: str = "start", bold: bool = False) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-family="{FONT}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}"{weight}>{escape(s)}</text>')


def _rect(x: float, y: float, w: float, h: float, color: str) -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{h:.1f}" rx="4" fill="{color}"/>'


def _line(x1: float, y1: float, x2: float, y2: float, color: str = GRID, width: int = 2) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"/>'


def _svg(height: int, body: Sequence[str]) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">'
            f'<rect width="{WIDTH}" height="{height}" fill="{SURFACE}"/>' + "".join(body) + "</svg>")


def _swatch(x: float, y: float, color: str, label: str) -> Tuple[str, float]:
    """凡例の1つ（色の四角と文字）と、次の凡例を置く x。"""
    return _rect(x, y - 22, 26, 26, color) + _text(x + 36, y, label, 26, INK_2), x + 36 + 27 * len(label) + 40


def _minutes(v: float) -> str:
    return f"{v:,.0f}分"


def _man(v: float) -> str:
    return f"{round(v / 10000):,}万円"


# ---------------------------------------------------------------- 前後比較


def _fit_label(text: str, width: float, size: int) -> str:
    """右揃えの作業名が、図の左の端からはみ出さない長さ（はみ出すなら、後ろを「…」にする。11/7：長い名前の頭が切れた）。"""
    def units(s: str) -> float:
        return sum(1.0 if ord(ch) > 0x2000 else 0.55 for ch in s) * size
    if units(text) <= width:
        return text
    while text and units(text + "…") > width:
        text = text[:-1]
    return text + "…"


def before_after_svg(tasks: Sequence[Dict]) -> Tuple[str, str]:
    """工程ごとの1日の作業時間を、導入前と導入後で比べる横棒（同じ物差し）。（SVG、題）"""
    before = [t for t in tasks if t.get("側") == "導入前" and isinstance(t.get("分"), (int, float))]
    after = [t for t in tasks if t.get("側") == "導入後" and isinstance(t.get("分"), (int, float))]
    if not before or not after:
        raise FigureError("財務モデルの「省力化の作業」に、導入前と導入後の作業がそろっていません。"
                          "財務モデルの指定に省力化の作業を書き、zaimu_model.py で作り直してください")
    total_b = sum(t["分"] for t in before)
    total_a = sum(t["分"] for t in after)
    top = max(t["分"] for t in before + after) or 1
    title = f"工程ごとの1日の作業時間（導入前 合計{_minutes(total_b)} → 導入後 合計{_minutes(total_a)}）"
    label_w, bar_x, bar_w, row_h = 600, 620, 820, 50
    body = [_text(40, 60, title, 32, INK, bold=True)]
    y = 110
    for name, rows, color in (("導入前", before, NOW), ("導入後", after, PLAN)):
        y += 30
        total = sum(t["分"] for t in rows)
        body.append(_rect(40, y - 24, 26, 26, color))
        body.append(_text(78, y, f"{name}（合計 {_minutes(total)}）", 28, INK, bold=True))
        y += 20
        for t in rows:
            y += row_h
            w = bar_w * t["分"] / top
            body.append(_text(label_w, y - 12, _fit_label(str(t.get("工程") or ""), label_w - 40, 26), 26, INK, "end"))
            body.append(_rect(bar_x, y - 38, w, 30, color))
            body.append(_text(bar_x + w + 12, y - 13, _minutes(t["分"]), 26, INK_2))
        y += 20
    body.append(_line(bar_x, 150, bar_x, y - 20, INK_2, 2))  # 0 の線
    reduced = total_b - total_a
    note = f"1日の作業時間は {_minutes(reduced)} 減る見込み（財務モデルの省力化の作業から）" if reduced > 0 else \
        "財務モデルの省力化の作業から"
    body.append(_text(40, y + 30, note, 24, INK_2))
    return _svg(int(y + 60), body), title


# ---------------------------------------------------------------- 数値計画


PLAN_PANELS = (("付加価値額", "付加価値額の伸び"), ("労働生産性", "労働生産性の伸び"),
               ("1人当たり給与", "1人当たり給与の伸び"))
PANEL_TITLES = {"付加価値額": "付加価値額", "労働生産性": "労働生産性", "1人当たり給与": "1人当たり給与支給総額"}


def trend_svg(contents: Dict, param: str) -> Tuple[str, str]:
    """財務モデルの好きな行（売上・営業利益・人数など）の、基準年度と計画の年ごとの棒（行ごとに小さな図を並べる）。"""
    names = [n.strip() for n in re.split(r"[・、,，/／]", param or "") if n.strip()]
    if not 1 <= len(names) <= TREND_MAX:
        raise FigureError(f"推移の図は、財務モデルの行を1〜{TREND_MAX}つ「・」で区切って選んでください（例：【図：推移｜売上・営業利益】）")
    found: Dict[str, List] = {}
    for src in TREND_SOURCES:
        for key, values in (contents.get(src) or {}).items():
            if isinstance(values, list) and len(values) >= 2 and all(isinstance(v, (int, float)) for v in values):
                found.setdefault(key, values)
    panels = []
    for name in names:
        if name not in found:
            raise FigureError(f"財務モデルの数字の控えに「{name}」の年ごとの数字がありません（選べるもの：{'・'.join(found)}）")
        panels.append((name, found[name], []))
    title = f"{'・'.join(names)}の推移（基準年度と事業計画の{len(panels[0][1]) - 1}年間）"
    units = {n: ("人" if n in (contents.get("人数") or {}) else
                 "率" if n.endswith("率") and max(abs(v) for v in found[n]) < 1.5 else "円") for n in names}
    return _panels_svg(panels, title, {n: n for n in names}, units, note="財務モデルの数字から")


def plan_svg(indicators: Dict) -> Tuple[str, str]:
    """付加価値額・労働生産性・1人当たり給与支給総額の、基準年度と計画の年ごとの棒（指標ごとに小さな図を並べる）。"""
    panels = []
    for key, growth in PLAN_PANELS:
        values = indicators.get(key)
        if not isinstance(values, list) or len(values) < 2 or not all(isinstance(v, (int, float)) for v in values):
            raise FigureError(f"財務モデルの「指標」に「{key}」の年ごとの数字がありません。zaimu_model.py で作り直してください")
        panels.append((key, values, indicators.get(growth) or []))
    years = len(panels[0][1]) - 1
    title = f"数値計画（基準年度と事業計画の{years}年間）"
    return _panels_svg(panels, title, PANEL_TITLES, {k: "円" for k, _v, _g in panels},
                       note="年平均は、基準年度から各年までの年平均成長率（様式と同じ切り捨て）。財務モデルの数字から")


def _value_label(v: float, unit: str) -> str:
    if unit == "人":
        return f"{v:,.0f}人"
    if unit == "率":
        return f"{v * 100:.1f}%"
    return _man(v)


def _panels_svg(panels: Sequence[Tuple[str, List, List]], title: str, titles: Dict[str, str], units: Dict[str, str],
                note: str) -> Tuple[str, str]:
    """行ごとの小さな棒の図を横に並べる（基準年度は灰色、計画の年は青）。"""
    body = [_text(40, 60, title, 32, INK, bold=True)]
    x = 40
    item, x = _swatch(x, 112, NOW, "基準年度（実績）")
    body.append(item)
    item, x = _swatch(x, 112, PLAN, "計画")
    body.append(item)
    gap, top_y, base_y = 60, 270, 600
    panel_w = (WIDTH - 80 - gap * (len(panels) - 1)) / max(1, len(panels))
    for i, (key, values, growth) in enumerate(panels):
        px = 40 + i * (panel_w + gap)
        last = next((g for g in reversed(growth) if isinstance(g, (int, float))), None)
        body.append(_text(px, 170, titles[key], 28, INK, bold=True))
        if last is not None:  # 題の下の行に（長い題と重ならないように）
            body.append(_text(px, 208, f"年平均 {last:+.2f}%（{len(values) - 1}年目）", 24, INK_2))
        top = max(max(values), 0) or 1
        n = len(values)
        slot = panel_w / n
        bw = slot * 0.56
        body.append(_line(px, base_y, px + panel_w, base_y, INK_2, 2))
        for j, v in enumerate(values):
            h = max(0.0, (base_y - top_y) * v / top)  # 負の値は棒を描かず、数だけ示す
            bx = px + j * slot + (slot - bw) / 2
            body.append(_rect(bx, base_y - h, bw, h, NOW if j == 0 else PLAN))
            body.append(_text(bx + bw / 2, base_y - h - 12, _value_label(v, units.get(key, "円")),
                              22 if len(panels) <= 2 else 19, INK, "middle"))
            body.append(_text(bx + bw / 2, base_y + 34, "基準" if j == 0 else f"{j}年目", 24, INK_2, "middle"))
    body.append(_text(40, base_y + 84, note, 22, INK_2))
    return _svg(base_y + 110, body), title


# ---------------------------------------------------------------- 工程表


MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def _month(value, where: str) -> date:
    m = MONTH.match(str(value or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise FigureError(f"{where}は「2027-07」の形（年-月）で書いてください（いまは {value!r}）")
    return date(int(m.group(1)), int(m.group(2)), 1)


def _index(d: date) -> int:
    return d.year * 12 + d.month - 1


def gantt_svg(spec: Dict) -> Tuple[str, str]:
    """図表の指定の工程表を、月ごとの横棒にする。"""
    if not isinstance(spec, dict) or not isinstance(spec.get("行"), list) or not spec["行"]:
        raise FigureError("図表の指定に「工程表」の「行」がありません（--figures の JSON に "
                          '{"工程表": {"題": "…", "行": [{"作業": "…", "始め": "2027-07", "終わり": "2027-12"}]}} を書く）')
    rows = []
    for n, row in enumerate(spec["行"], 1):
        where = f"工程表の{n}行目"
        if not isinstance(row, dict) or not str(row.get("作業") or "").strip():
            raise FigureError(f"{where}に「作業」がありません")
        start, end = _month(row.get("始め"), f"{where}の「始め」"), _month(row.get("終わり"), f"{where}の「終わり」")
        if end < start:
            raise FigureError(f"{where}は、「終わり」が「始め」より前です")
        rows.append((str(row["作業"]).strip(), start, end))
    if len(rows) > 15:
        raise FigureError("工程表の行は15行までにしてください（多いと読めないため。まとめられる作業はまとめる）")
    first = min(_index(s) for _n, s, _e in rows)
    last = max(_index(e) for _n, _s, e in rows)
    months = last - first + 1
    if months > 60:
        raise FigureError("工程表は60か月までにしてください")
    title = str(spec.get("題") or "補助事業のスケジュール").strip()
    label_w, area_x, area_w, row_h = 560, 580, 980, 54
    col = area_w / months
    head_y = 160
    body = [_text(40, 60, title, 32, INK, bold=True)]
    # 年は上の行に（最初の月と1月だけ）、月は下の行に。欄が狭いときは、月を何か月かおきに書く
    step = 1 if col >= 48 else (3 if col >= 18 else 6)
    for k in range(months):
        idx = first + k
        year, month = divmod(idx, 12)
        x = area_x + k * col
        if k == 0 or month == 0:
            body.append(_text(x + 4, head_y - 50, f"{year}年", 22, INK_2))
        if k % step == 0:
            body.append(_text(x + col / 2 if step == 1 else x + 4, head_y - 14, f"{month + 1}月", 22, INK_2,
                              "middle" if step == 1 else "start"))
        body.append(_line(x, head_y, x, head_y + row_h * len(rows), GRID, 1))
    body.append(_line(area_x + area_w, head_y, area_x + area_w, head_y + row_h * len(rows), GRID, 1))
    for i, (name, start, end) in enumerate(rows):
        y = head_y + i * row_h
        body.append(_line(40, y + row_h, area_x + area_w, y + row_h, GRID, 1))
        body.append(_text(label_w, y + 36, name, 26, INK, "end"))
        x = area_x + (_index(start) - first) * col
        w = (_index(end) - _index(start) + 1) * col
        body.append(_rect(x + 2, y + 12, w - 4, 30, PLAN))
    return _svg(head_y + row_h * len(rows) + 40, body), title


# ---------------------------------------------------------------- PNG にする


def svgs_to_png(svgs: Dict[str, str], work: Path, soffice: str) -> Dict[str, bytes]:
    """SVG を LibreOffice で PNG にする（1回の起動でまとめて）。work は、呼ぶ側が用意した空の一時の場所。"""
    from lib import libreoffice

    names = {}
    srcs = []
    work.mkdir(parents=True, exist_ok=True)
    for i, (key, svg) in enumerate(svgs.items()):
        src = work / f"zu_{i}.svg"
        src.write_text(svg, encoding="utf-8")
        names[key] = src
        srcs.append(src)
    try:
        outs = libreoffice.convert_files(srcs, work / "out", work / "profile", soffice, "png")
    except libreoffice.LibreOfficeError as e:
        raise FigureError(f"図を PNG にできませんでした（{e}）") from e
    return {key: outs[src].read_bytes() for key, src in names.items()}


# ---------------------------------------------------------------- まとめ


def load_numbers(folder: Path) -> Optional[Dict]:
    """財務モデルの数字の控え。なければ None。会社のフォルダの外を指すものは読まない。"""
    from lib import places

    path = places.actual(folder, NUMBERS_FILE)
    if path is None or not path.is_file() or not places.is_inside(folder, path):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def build(folder: Path, text: str, spec: Optional[Dict], soffice_finder=None) -> Dict[str, Figure]:
    """書く文の図を置く行ごとの絵。図を置く行がなければ空。作れなければ FigureError（何も書かない）。"""
    from lib import libreoffice, places

    lines = figure_lines(text)
    if not lines:
        return {}
    spec = spec or {}
    numbers = None
    svgs: Dict[str, Tuple[str, str]] = {}
    out: Dict[str, Figure] = {}
    for line, kind, arg in lines:
        if kind == "写真":
            path_text, _sep, title = arg.partition("｜")
            path_text, title = path_text.strip(), title.strip()
            if not path_text:
                raise FigureError(f"{line}：写真のファイルの場所がありません（【写真：原本/写真・カタログ/工場.jpg｜題】の形）")
            try:
                real = places.resolve_inside(folder, Path(path_text))
            except places.PlaceError:
                raise FigureError(f"{line}：写真（{path_text}）が会社のフォルダの外です。会社のフォルダの中のものだけを使います")
            if not real.is_file():
                raise FigureError(f"{line}：写真（{path_text}）が見つかりません")
            data = real.read_bytes()
            try:
                fmt, w, h = image_size(data)
            except FigureError:
                raise FigureError(f"{line}：写真（{path_text}）は PNG か JPEG にしてください（PDF のカタログは、ページを画像にしてから）")
            out[line] = Figure(line, title or Path(path_text).stem, data, fmt, w, h, photo=True)
            continue
        arg, _sep, param = arg.partition("｜")
        arg = arg.strip()
        if arg not in KINDS:
            raise FigureError(f"{line}：図の種類は {'・'.join(KINDS)} のどれかにしてください")
        if arg in ("前後比較", "数値計画", "推移"):
            if numbers is None:
                numbers = load_numbers(folder)
            if numbers is None:
                raise FigureError(f"{line}：財務モデルの数字の控え（{NUMBERS_FILE}）がありません。"
                                  "先に財務モデルを作ってください（zaimu_model.py）")
            if arg == "前後比較":
                svgs[line] = before_after_svg(numbers.get("省力化の作業") or [])
            elif arg == "推移":
                try:
                    svgs[line] = trend_svg(numbers.get("中身") or {}, param)
                except FigureError as e:
                    raise FigureError(f"{line}：{e}")
            else:
                svgs[line] = plan_svg((numbers.get("中身") or {}).get("指標") or {})
        else:
            svgs[line] = gantt_svg(spec.get("工程表"))
    if svgs:
        find = soffice_finder or libreoffice.find_soffice
        soffice = find()
        if not soffice:
            raise FigureError("LibreOffice が見つからないので、図を作れませんでした。LibreOffice を入れるか、"
                              "図を置く行を外して書いてください")
        work = Path(tempfile.mkdtemp(prefix="図表_", dir=str(_tmp_dir(folder))))
        try:
            pngs = svgs_to_png({k: s for k, (s, _t) in svgs.items()}, work, soffice)
        finally:
            shutil.rmtree(str(work), ignore_errors=True)
        for line, (_svg_text, title) in svgs.items():
            fmt, w, h = image_size(pngs[line])
            out[line] = Figure(line, title, pngs[line], fmt, w, h)
    return out


def _tmp_dir(folder: Path) -> Path:
    """会社のフォルダの `.hojokin/一時/`（版の履歴に入れない一時の置き場）。"""
    d = folder / ".hojokin" / "一時"
    d.mkdir(parents=True, exist_ok=True)
    return d
