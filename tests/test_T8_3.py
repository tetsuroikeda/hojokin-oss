"""T8-3 図表と写真（SPEC F8「図表（作業の前後比較、工程表、グラフなど）と、社長が用意した写真を入れられる」、
DESIGN 8.2「図表は道具が数字から作る（数字は根拠対照表と同じもの）」。TASKS B33）。

合格ライン：ファイル内にあり、余白からはみ出さない（自動の部分）。見た目は人が見る（A10）。

確かめ方
- 図を作る部品（lib/zuhyo.py）：図を置く行の読み方、PNG・JPEG の大きさ、前後比較・数値計画・工程表の SVG に
  財務モデルの数字の控えと指定の値が出ること、数字が足りないときと指定が正しくないときに作らないこと。
- 様式に書く道具（skills/kaku/scripts/yoshiki.py write --figures）：省力化の様式（downloads/）の1項目に、文と
  【図：前後比較】【図：数値計画】【図：工程表】【写真：…】を書く。
  - ファイル内にある：画像の部品が word/media/ にあり、関係と種類の登録があり、本文の図の段落がその関係を指す。
  - 余白からはみ出さない：図の幅（wp:extent）が、そのセルの幅から左右の余白を引いたものと、ページの本文の幅の
    どちらにも収まる。縦横の比は元の画像のまま。
  - 範囲の外は変わらない（図の画像・関係・種類の登録のほか）。書き直して図を外すと、画像と関係も片付く。
  - 審査役に渡す本文（item_text）に「［図：題］」が出る。財務モデルの数字の控えがなければ、何も書かない。
- 様式は downloads/ から読み、写しは tmp_path にだけ作る。図を PNG にするのに LibreOffice が要る。どちらもなければ飛ばす。
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path

import pytest
import test_write_min as twm

from lib import libreoffice, zuhyo
from lib import yoshiki_word as yw
from lib import xml_spans

W = yw.W
ITEM = "1-2 経営課題"
POSITION = twm.KEIEI

# 架空の財務モデルの数字の控え（テストのためだけの値）
NUMBERS = {
    "説明": "テストのための架空の控え",
    "省力化の作業": [
        {"側": "導入前", "No": 1, "工程": "盛り付け（手作業）", "分": 900.0},
        {"側": "導入前", "No": 2, "工程": "包装（手作業）", "分": 480.0},
        {"側": "導入後", "No": 1, "工程": "ラインの見守り", "分": 420.0},
    ],
    "中身": {"指標": {
        "付加価値額": [69300000.0, 73135000.0, 77161750.0], "付加価値額の伸び": [None, 5.53, 5.51],
        "労働生産性": [4076470.0, 4302058.0, 4538926.0], "労働生産性の伸び": [None, 5.53, 5.51],
        "1人当たり給与": [2999637.0, 3119622.0, 3244407.0], "1人当たり給与の伸び": [None, 3.99, 3.99],
    }},
}
GANTT = {"題": "補助事業のスケジュール（試し）", "行": [
    {"作業": "発注", "始め": "2027-07", "終わり": "2027-07"},
    {"作業": "製作と納品", "始め": "2027-07", "終わり": "2027-12"},
    {"作業": "据付と試運転", "始め": "2028-01", "終わり": "2028-01"},
]}
TEXT = ("受注が増えても、盛り付けと包装の人手が足りない（試しの文）。\n【図：前後比較】\n数値の計画（試しの文）。\n"
        "【図：数値計画】\n【図：工程表】\n【写真：原本/写真・カタログ/工場.png｜今の盛り付けの作業（試し）】\n終わりの文（試し）。")


def tiny_png(width: int, height: int) -> bytes:
    """幅 width・高さ height の白い PNG（写真の代わり）。"""
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- 図を作る部品


def test_figure_lines_and_image_sizes() -> None:
    lines = zuhyo.figure_lines("文\n  【図：前後比較】 \n【写真：a.png｜題】\n【図：前後比較】\n【仮：まだ】")
    assert lines == [("【図：前後比較】", "図", "前後比較"), ("【写真：a.png｜題】", "写真", "a.png｜題")]
    assert zuhyo.image_size(tiny_png(30, 20)) == ("png", 30, 20)
    # JPEG は SOF の印から大きさを読む（中身は読まない）
    jpeg = b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + \
        b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 480, 640) + b"\x00" * 10
    assert zuhyo.image_size(jpeg) == ("jpeg", 640, 480)
    with pytest.raises(zuhyo.FigureError):
        zuhyo.image_size(b"%PDF-1.7")


def test_svgs_show_the_numbers_from_the_model_and_the_spec() -> None:
    svg, title = zuhyo.before_after_svg(NUMBERS["省力化の作業"])
    assert title == "工程ごとの1日の作業時間（導入前 合計1,380分 → 導入後 合計420分）"
    for text in ("盛り付け（手作業）", "900分", "480分", "ラインの見守り", "420分", "960分 減る見込み"):
        assert text in svg
    svg, title = zuhyo.plan_svg(NUMBERS["中身"]["指標"])
    assert title == "数値計画（基準年度と事業計画の2年間）"
    for text in ("6,930万円", "7,716万円", "408万円", "324万円", "年平均 +5.51%", "年平均 +3.99%", "基準", "2年目"):
        assert text in svg
    svg, title = zuhyo.gantt_svg(GANTT)
    assert title == "補助事業のスケジュール（試し）"
    for text in ("2027年", "2028年", "7月", "12月", "1月", "製作と納品"):
        assert text in svg
    # 1つの軸だけ（2つの物差しを重ねない）：どの図も、0の線から伸びる棒と、文字だけ
    assert "<polyline" not in svg


@pytest.mark.parametrize("call, message", [
    (lambda: zuhyo.before_after_svg([{"側": "導入前", "工程": "a", "分": 10}]), "導入前と導入後の作業がそろっていません"),
    (lambda: zuhyo.plan_svg({"付加価値額": [1.0]}), "「付加価値額」の年ごとの数字がありません"),
    (lambda: zuhyo.gantt_svg({"行": []}), "「工程表」の「行」がありません"),
    (lambda: zuhyo.gantt_svg({"行": [{"作業": "a", "始め": "2027/07", "終わり": "2027-08"}]}), "「2027-07」の形"),
    (lambda: zuhyo.gantt_svg({"行": [{"作業": "a", "始め": "2027-09", "終わり": "2027-08"}]}), "「終わり」が「始め」より前"),
])
def test_figures_are_not_made_from_missing_or_wrong_input(call, message: str) -> None:
    with pytest.raises(zuhyo.FigureError) as e:
        call()
    assert message in str(e.value)


# ---------------------------------------------------------------- 様式に書く


SOFFICE = libreoffice.find_soffice()


@pytest.fixture
def env(tmp_path: Path, form_bytes: bytes) -> twm.Env:
    if SOFFICE is None:
        pytest.skip("LibreOffice がないので、図を PNG にできない")
    e = twm.Env(tmp_path, form_bytes)
    e.set_positions({ITEM: POSITION})
    (e.folder / "記録" / "財務モデルの数字.json").write_text(json.dumps(NUMBERS, ensure_ascii=False), encoding="utf-8")
    photo = e.folder / "原本" / "写真・カタログ" / "工場.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(tiny_png(300, 400))  # 縦長の写真
    spec = e.folder / "記録" / "一時" / "図表.json"
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({"工程表": GANTT}, ensure_ascii=False), encoding="utf-8")
    (e.folder / "記録" / "一時" / "書く文.txt").write_text(TEXT, encoding="utf-8")
    return e


@pytest.fixture
def form_bytes() -> bytes:
    if not twm.FORM.is_file():
        pytest.skip("downloads/ に省力化の様式（その1・2）がありません（公式資料を取ってから流す）")
    return twm.FORM.read_bytes()


def write(env: twm.Env, *extra: str) -> str:
    return twm.ok(env.run("write", "--item", ITEM, "--input", "記録/一時/書く文.txt", "--figures", "記録/一時/図表.json",
                          *extra))


def test_figures_are_inside_the_file_and_within_the_margins(env: twm.Env, form_bytes: bytes) -> None:
    out = write(env)
    for title in ("工程ごとの1日の作業時間", "数値計画", "補助事業のスケジュール（試し）", "今の盛り付けの作業（試し）"):
        assert title in out
    written = (env.folder / twm.APP).read_bytes()
    parts = twm.parts_of(written)
    data, root = twm.doc_root(written)
    rels = parts[yw.RELS].decode("utf-8")
    # ファイル内にある：4つの画像の部品、関係、種類の登録。本文の図の段落が関係を指す
    media = sorted(n for n in parts if n.startswith(yw.FIGURE_MEDIA_PREFIX))
    assert len(media) == 4
    embeds = re.findall(r'embed="([^"]+)"', data.decode("utf-8"))
    for rid in embeds:
        target = re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', rels) or re.search(rf'Target="([^"]+)"[^>]*Id="{rid}"', rels)
        assert target and f"word/{target.group(1)}" in media
    assert re.search(r'<Default\b[^>]*Extension="png"', parts["[Content_Types].xml"].decode("utf-8"))
    # 余白からはみ出さない：セルの幅から左右の余白を引いた幅と、ページの本文の幅に収まる。縦横の比は元のまま
    rng = yw.resolve(root, POSITION)
    limit = yw.available_width(root, rng) * yw.EMU_PER_TWIP
    sect = next(n for n in root.iter() if n.is_(W, "sectPr"))
    page = (int(sect.find(W, "pgSz").attr(W, "w")) - int(sect.find(W, "pgMar").attr(W, "left"))
            - int(sect.find(W, "pgMar").attr(W, "right"))) * yw.EMU_PER_TWIP
    extents = [n for n in rng.container.iter() if n.local == "extent" and n.uri == yw.NS_WP]
    assert len(extents) == 4
    for ext in extents:
        cx, cy = int(ext.attrs["cx"]), int(ext.attrs["cy"])
        assert 0 < cx <= limit <= page or 0 < cx <= page, (cx, limit, page)
        assert cx <= limit
    photo_ext = extents[3]
    assert int(photo_ext.attrs["cy"]) <= yw.MAX_PHOTO_EMU  # 縦長の写真は高さで収める
    assert abs(int(photo_ext.attrs["cx"]) / int(photo_ext.attrs["cy"]) - 300 / 400) < 0.01
    for name in media:
        kind, w, h = zuhyo.image_size(parts[name])
        assert kind == "png" and w > 0 and h > 0
    # 範囲の外は変わらない（図の画像・関係・種類の登録のほか）
    assert yw.compare_docx(form_bytes, written, [(ITEM, POSITION)]) == []
    # 審査役に渡す本文に、図があることと題が出る
    text = yw.item_text(written, POSITION)
    assert "［図：工程ごとの1日の作業時間（導入前 合計1,380分 → 導入後 合計420分）］" in text
    assert "［図：今の盛り付けの作業（試し）］" in text
    assert "【図：" not in text and "【写真：" not in text


def test_rewriting_without_figures_cleans_up(env: twm.Env) -> None:
    write(env)
    with_figures = (env.folder / twm.APP).read_bytes()
    twm.ok(env.run("write", "--item", ITEM, "--text", "図のない文（試し）"))
    written = (env.folder / twm.APP).read_bytes()
    parts = twm.parts_of(written)
    assert not [n for n in parts if n.startswith(yw.FIGURE_MEDIA_PREFIX)]
    assert yw.FIGURE_REL_PREFIX not in parts[yw.RELS].decode("utf-8")
    assert yw.compare_docx(with_figures, written, [(ITEM, POSITION)]) == []
    assert yw.item_text(written, POSITION) == "図のない文（試し）"


def test_no_model_numbers_writes_nothing(env: twm.Env) -> None:
    (env.folder / "記録" / "財務モデルの数字.json").unlink()
    out = twm.refused(env.run("write", "--item", ITEM, "--input", "記録/一時/書く文.txt", "--figures", "記録/一時/図表.json"))
    assert "図を作れなかったので、何も書いていません" in out and "財務モデルの数字の控え" in out
    assert not (env.folder / twm.APP).exists()


def test_photo_outside_the_company_folder_is_not_read(env: twm.Env, tmp_path: Path) -> None:
    outside = tmp_path / "外の写真.png"
    outside.write_bytes(tiny_png(10, 10))
    out = twm.refused(env.run("write", "--item", ITEM, "--text", f"文\n【写真：{outside}｜外】"))
    assert "会社のフォルダの外" in out
    assert not (env.folder / twm.APP).exists()


def test_figure_line_without_figure_is_refused(form_bytes: bytes) -> None:
    with pytest.raises(yw.FormError) as e:
        yw.write_item(form_bytes, POSITION, "文\n【図：前後比較】", ITEM)
    assert "図がありません" in str(e.value)


def test_figure_paragraph_is_well_formed(env: twm.Env) -> None:
    """図の段落は XML として読め、行の高さを固定しない段落の書式で、中央に置く（絵が切れないように）。"""
    write(env)
    data, root = twm.doc_root((env.folder / twm.APP).read_bytes())
    # 様式にもともとある絵は数えない（この道具の関係を指す段落だけ）
    drawings = [p for p in yw._paragraphs(root) if yw.FIGURE_REL_PREFIX.encode() in p.raw(data)]
    assert len(drawings) == 4
    for p in drawings:
        spacing = p.find(W, "pPr").find(W, "spacing")
        assert spacing.attr(W, "lineRule") == "auto"
        assert p.find(W, "pPr").find(W, "jc").attr(W, "val") == "center"
    xml_spans.parse(data)  # 本文全体が XML として読める
