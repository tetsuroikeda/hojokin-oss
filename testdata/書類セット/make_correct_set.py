# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdfium2==5.14.0", "pillow==13.0.0"]
# ///
"""正しい書類セット（TASKS D5a）を作る。

T5-2（不備のない書類セットを入れて、「重大」の誤指摘が0件か）で、会社のフォルダに入れる書類の一式。
省力化（一般型）第8回 公募要領 4-4 の ①全事業者共通 と ②法人 のうち、社長が集めて持っている書類をそろえる。
【指定様式】の書類（事業計画書、役員名簿、株主・出資者名簿など）は、ツールが様式に書き込んで作るので入れない。

書類は testdata/デモの会社/書類/（D2a・D2b）から作る。元のファイルは読むだけで、変えない。

- 9つは、元のファイルをそのまま写す（同じバイト列）。
- 納税証明書（その2）は、紙をスマホで撮った写真（JPEG）にする。
- 履歴事項全部証明書は、紙をスキャンした PDF（文字の入っていない、画像だけの PDF）にする。

写真とスキャンも、同じ元のファイルと同じ版のライブラリからなら、何度作っても同じバイト列になる。
日本語の字形は、PDF に埋め込まれていないので、PDFium が手元の字形で描く（Mac ならヒラギノ）。
そのため、別の機械で作り直すと、写真とスキャンのバイト列は変わることがある。

セットのフォルダ（正しいセット/）には書類だけを置く。テストで会社のフォルダに写すのは、このフォルダの中だけ。
答え（どれも不備がないこと、申請の日の範囲）は、このスクリプトと セットの一覧.md に書く。

動かし方：uv run --script testdata/書類セット/make_correct_set.py
"""

from __future__ import annotations

import datetime as dt
import random
import shutil
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

HERE = Path(__file__).resolve().parent
SOURCE_DIR = HERE.parent / "デモの会社" / "書類"
SET_DIR = HERE / "正しいセット"

# そのまま写す書類（セットでの名前 ＝ 元の名前）
COPIED = [
    "決算書_第17期.pdf",
    "決算書_第18期.pdf",
    "法人事業概況説明書_第18期.pdf",
    "見積書_つばさ台フードシステム.pdf",
    "見積書_ほしみ機工.pdf",
    "カタログ_つばさ台フードシステム.pdf",
    "役員名簿.docx",
    "株主名簿.docx",
    "労働者名簿.xlsx",
]
# 形を変える書類（セットでの名前 → 元の名前）
PHOTO = ("納税証明書_その2.jpg", "納税証明書_その2.pdf")
SCAN = ("履歴事項全部証明書.pdf", "履歴事項全部証明書.pdf")

# セットでの名前 → 元の名前
SOURCES = {name: name for name in COPIED}
SOURCES[PHOTO[0]] = PHOTO[1]
SOURCES[SCAN[0]] = SCAN[1]

# スキャンした PDF の作成日時（同じバイト列にするため、決めておく）
FIXED_TIME = dt.datetime(2026, 11, 3, 0, 0, 0)

BICUBIC = Image.Resampling.BICUBIC
BILINEAR = Image.Resampling.BILINEAR
LANCZOS = Image.Resampling.LANCZOS


def render_page(pdf: Path, dpi: int) -> Image.Image:
    """1ページの PDF を画像にする。"""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        if len(doc) != 1:
            raise SystemExit(f"{pdf.name} は1ページの書類ではありません（{len(doc)}ページ）")
        return doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def noise_layer(size: tuple[int, int], seed: int, cell: int) -> Image.Image:
    """決まった種から作る、ざらつきの層（灰色）。"""
    rng = random.Random(seed)
    w, h = max(1, size[0] // cell), max(1, size[1] // cell)
    small = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    return small.resize(size, BILINEAR)


def make_photo(src: Path, dst: Path) -> None:
    """紙を机に置いて、スマホで真上から撮った写真にする。少し傾き、影と明るさのむらがある。読める程度にとどめる。"""
    page = render_page(src, 200)
    pw, ph = page.size
    size = (int(pw * 1.18), int(ph * 1.12))

    # 机（上から下へ、少し明るくなる木の色）
    gradient = Image.linear_gradient("L").resize(size, BILINEAR)
    desk = ImageOps.colorize(gradient, black=(96, 80, 64), white=(138, 118, 96))

    # 紙を少し傾ける
    paper = page.convert("RGBA").rotate(-1.3, resample=BICUBIC, expand=True)
    x = (size[0] - paper.size[0]) // 2
    y = (size[1] - paper.size[1]) // 2

    # 紙の影（右下にずらして、ぼかす）
    shadow = Image.new("L", size, 0)
    ImageDraw.Draw(shadow).rectangle([x + 18, y + 24, x + paper.size[0] + 18, y + paper.size[1] + 24], fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    desk = Image.composite(Image.new("RGB", size, (30, 24, 18)), desk, shadow)
    desk.paste(paper, (x, y), paper)

    # 明るさのむら（左上が明るく、右下が暗い）と、少し暖かい色
    light = Image.radial_gradient("L").resize((size[0] * 2, size[1] * 2), BILINEAR)
    light = light.crop((size[0] // 2, size[1] // 2, size[0] // 2 + size[0], size[1] // 2 + size[1]))
    light = ImageOps.invert(light).point(lambda v: 205 + v * 50 // 255)
    tint = Image.merge("RGB", (light, light.point(lambda v: v * 250 // 255), light.point(lambda v: v * 236 // 255)))
    photo = ImageChops.multiply(desk, tint)

    # 手ぶれのような少しのぼけと、ざらつき
    photo = photo.filter(ImageFilter.GaussianBlur(0.7))
    grain = noise_layer(size, seed=2611, cell=2).convert("RGB")
    photo = Image.blend(photo, grain, 0.05)

    # 3:4 に切って、スマホの写真の大きさにする
    h = min(size[1], size[0] * 4 // 3)
    w = h * 3 // 4
    left = (size[0] - w) // 2
    top = (size[1] - h) // 2
    photo = photo.crop((left, top, left + w, top + h)).resize((1536, 2048), LANCZOS)
    photo.save(dst, "JPEG", quality=87)


def make_scan(src: Path, dst: Path) -> None:
    """紙をスキャナで読んだ、画像だけの PDF にする。白黒（グレー）、わずかに傾き、地が真っ白でない。"""
    page = render_page(src, 200).convert("L")
    page = page.rotate(0.4, resample=BICUBIC, expand=False, fillcolor=255)
    page = page.point(lambda v: v * 93 // 100 + 12)
    page = Image.blend(page, noise_layer(page.size, seed=2610, cell=2), 0.035)
    page.save(
        dst,
        "PDF",
        resolution=200,
        title="スキャン",
        author="",
        creator="架空のスキャナ（テスト用）",
        producer="架空のスキャナ（テスト用）",
        creationDate=FIXED_TIME.timetuple(),
        modDate=FIXED_TIME.timetuple(),
    )


def build(out_dir: Path) -> list[Path]:
    """out_dir に正しい書類セットを作る。中にあったものは消してから作る。"""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for name in COPIED:
        shutil.copyfile(SOURCE_DIR / name, out_dir / name)
    make_photo(SOURCE_DIR / PHOTO[1], out_dir / PHOTO[0])
    make_scan(SOURCE_DIR / SCAN[1], out_dir / SCAN[0])
    return sorted(out_dir.iterdir())


def main() -> None:
    missing = [name for name in SOURCES.values() if not (SOURCE_DIR / name).is_file()]
    if missing:
        sys.exit(f"元の書類がありません（D2a・D2b を先に作る）：{missing}")
    for path in build(SET_DIR):
        print(f"{path.relative_to(HERE)}  {path.stat().st_size:,} バイト")


if __name__ == "__main__":
    main()
