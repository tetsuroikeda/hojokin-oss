"""スキャンした PDF と写真を、読み取り役に渡すページの画像にする（DESIGN 8.4「文字がない PDF や写真は、ページを画像にし、
向きを直してから読み取り役に渡す」「合わなければ、その部分を拡大した画像で読み直させる」。TASKS B11）。

- 文字のない PDF（スキャンしたもの）は、ページに埋め込まれた JPEG を、そのまま取り出す（同梱の pypdf。画像は変えない）。
  JPEG でない画像のページは、取り出せないので Read で PDF を開くよう案内する。
- 写真（JPEG・PNG）は、そのまま写す。
- 向きを直す（--rotate）と、帯を切り出して大きくする（--band。上からの割合）は、1ページずつの PDF にして、ページの
  回転と枠で行う（写真は JPEG を PDF に包む）。画像の画素は変えない。Read で開くと、直した形で読める。
  はじめは Mac の sips で画像を直す形にしたが、eval の中（Bash の sandbox）では sips が終了コード13で止まったため（TASKS B11）。
- 画像は `記録/一時/画像/` に置く（版の履歴に入れない一時の置き場。会社のフォルダの .gitignore にある）。原本は読むだけ。

標準のライブラリと、同梱の pypdf だけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from lib import place_text
from lib.company_init import RECORDS_DIR

IMAGE_DIR = f"{RECORDS_DIR}/一時/画像"
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")


class ImageError(ValueError):
    """画像にしなかった。"""


def _pdf_jpegs(path: Path) -> List[bytes]:
    """PDF のページごとの、埋め込まれた JPEG（ページに画像が1つだけのとき）。文字のある PDF・JPEG でない画像は ImageError。"""
    from lib import doc_text  # noqa: F401  同梱の pypdf を読めるようにする
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    texts = [(p.extract_text() or "").strip() for p in reader.pages]
    if any(texts):
        raise ImageError(f"{path.name} は文字の入った PDF です。seiri.py の text で文字を出して読んでください")
    out = []
    for number, page in enumerate(reader.pages, 1):
        xobjects = (page.get("/Resources") or {}).get("/XObject") or {}
        images = [o.get_object() for o in xobjects.values() if o.get_object().get("/Subtype") == "/Image"]
        if len(images) != 1:
            raise ImageError(f"{path.name} の {number} ページは、画像が1つのページではありません。Read で PDF を開いて読んでください")
        image = images[0]
        filters = image.get("/Filter")
        names = [str(f) for f in filters] if isinstance(filters, list) else [str(filters)]
        if names != ["/DCTDecode"]:
            raise ImageError(f"{path.name} の {number} ページの画像は JPEG ではありません。Read で PDF を開いて読んでください")
        out.append(image.get_data())  # DCTDecode は解かずに、JPEG のバイトのまま返る
    return out


def _pdf_pages(folder: Path, source: Path, stem: str, rotate: int, band: Optional[Tuple[float, float]]) -> List[dict]:
    """向きを直す・帯を切り出すを、PDF のページの枠と回転で行う（sips が使えないとき。同梱の pypdf だけで動く）。

    帯は、ページの枠をその帯に狭め、読みやすいよう大きく（帯の高さがページの高さになるまで、4倍まで）してから出す。
    出すのは1ページずつの PDF（Read で開くと、そのページの画像として読める）。写真は、JPEG を PDF に包んでから直す。
    """
    import io

    from lib import doc_text  # noqa: F401  同梱の pypdf を読めるようにする
    from lib import utsushi
    from pypdf import PdfReader, PdfWriter

    data = source.read_bytes() if source.suffix.lower() == ".pdf" else utsushi.jpeg_to_pdf(source.read_bytes())
    reader = PdfReader(io.BytesIO(data))
    tag = (f"_回転{rotate}" if rotate else "") + (f"_帯{int(band[0] * 100)}-{int(band[1] * 100)}" if band else "")
    made = []
    for number, page in enumerate(reader.pages, 1):
        done = []
        if band:
            box = page.mediabox
            left, bottom, right, top = float(box.left), float(box.bottom), float(box.right), float(box.top)
            height = top - bottom
            if rotate == 180:  # まわす前の画像では、帯は下から数えた位置にある
                a, b = 1 - band[1], 1 - band[0]
            else:
                a, b = band
            new_top, new_bottom = top - height * a, top - height * b
            page.mediabox.lower_left = (left, new_bottom)
            page.mediabox.upper_right = (right, new_top)
            page.cropbox.lower_left = (left, new_bottom)
            page.cropbox.upper_right = (right, new_top)
            factor = min(4.0, 1 / max(band[1] - band[0], 0.25))
            page.scale_by(factor)
            done.append(f"上から {int(band[0] * 100)}%〜{int(band[1] * 100)}% の帯を切り出し、{factor:.1f}倍にした")
        if rotate:
            page.rotate(rotate)
            done.append(f"{rotate}度まわした")
        writer = PdfWriter()
        writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        rel = f"{IMAGE_DIR}/{stem}_p{number}{tag}.pdf"
        (Path(folder) / rel).write_bytes(out.getvalue())
        made.append({"ページ": number, "画像": rel, "直したこと": done})
    return made


def make_images(folder: Path, source: Path, stem: str, rotate: int = 0,
                band: Optional[Tuple[float, float]] = None) -> List[dict]:
    """原本（source）のページの画像を作り、[{"ページ", "画像"（会社のフォルダからの場所）, "直したこと"}] を返す。

    向きを直す・帯を切り出すときは、1ページずつの PDF にして出す（ページの枠と回転で直す。sips が使えない
    eval の中でも動くように。TASKS B11 の試しで、eval の中では sips が終了コード13で止まった）。
    """
    folder = Path(folder)
    if rotate not in (0, 90, 180, 270):
        raise ImageError("向き（--rotate）は 0・90・180・270 のどれかにしてください")
    if band is not None and not (0 <= band[0] < band[1] <= 1):
        raise ImageError("帯（--band）は、上からの割合で「0.55,0.75」の形にしてください")
    problem = place_text.write_problem(folder, f"{IMAGE_DIR}/x.jpg", "画像を作っていません")
    if problem:
        raise ImageError(problem)
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        pages = [(i, data, ".jpg") for i, data in enumerate(_pdf_jpegs(source), 1)]
    elif suffix in PHOTO_SUFFIXES:
        pages = [(1, source.read_bytes(), suffix)]
    else:
        raise ImageError(f"{source.name} は、画像にできる形（文字のない PDF・JPEG・PNG）ではありません")
    out_dir = folder / IMAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if rotate or band:
        if suffix == ".png":
            raise ImageError(f"{source.name}（PNG）は、向きを直す・切り出すことができません。Read でそのまま開いて読んでください")
        return _pdf_pages(folder, source, stem, rotate, band)
    made = []
    for number, data, ext in pages:
        rel = f"{IMAGE_DIR}/{stem}_p{number}{ext}"
        (folder / rel).write_bytes(data)
        made.append({"ページ": number, "画像": rel, "直したこと": ["そのまま取り出した"]})
    return made


def clear(folder: Path) -> None:
    """一時の画像を片付ける（呼ぶ側が要るときだけ）。"""
    shutil.rmtree(str(Path(folder) / IMAGE_DIR), ignore_errors=True)
