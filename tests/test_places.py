"""会社のフォルダの中の場所に解く共通の道具（lib/places.py。SPEC F5「会社のフォルダの外には触れない」、
DESIGN 5章「会社のフォルダの外に書かない・外を読まない」(b)。TASKS M2d・M0b の直し）。

- resolve_inside：相対・絶対の場所を、別名と「..」をたどった後の本当の場所（NFC）にし、外なら PlaceError。
- no_link_on_the_way：会社のフォルダから場所までの途中のフォルダと、そのもの自体に別名があれば PlaceError
  （別名の先が会社のフォルダの中でも断る）。
- 名前が NFD（Finder で作った名前など。実験 E5）でも、NFC で渡した場所と同じものとして扱う。
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from lib import places

CASE = "2026_テスト補助金（一般型）第4回"  # 濁点（ポ・ジ）を含む名前


@pytest.fixture
def folder(tmp_path) -> Path:
    company = tmp_path / "架空 惣菜工房"
    (company / ".hojokin").mkdir(parents=True)
    (company / "案件" / CASE / "1_申請" / "申請書").mkdir(parents=True)
    (company / "案件" / CASE / "1_申請" / "申請書" / "その1.docx").write_bytes(b"PK")
    (company / "記録").mkdir()
    (company / "記録" / "会社の記録.json").write_text("{}", encoding="utf-8")
    return company


@pytest.fixture
def outside(tmp_path) -> Path:
    path = tmp_path / "外のフォルダ"
    path.mkdir()
    (path / "秘密.json").write_text("{}", encoding="utf-8")
    return path


# ---- resolve_inside ----


def test_relative_and_absolute_places_inside(folder) -> None:
    real_folder = places.real(folder)
    for given in ("記録/会社の記録.json", folder / "記録" / "会社の記録.json", "./記録/../記録/会社の記録.json"):
        assert places.resolve_inside(folder, given) == real_folder / "記録" / "会社の記録.json", given
        assert places.relative_inside(folder, given) == "記録/会社の記録.json", given
        assert places.is_inside(folder, given), given
    # まだないファイルも、場所が中なら中（これから書く場所）
    assert places.relative_inside(folder, "案件/新しい.docx") == "案件/新しい.docx"
    # 会社のフォルダそのものも中に数える（そのものを断る道具は、呼んだ側で断る）
    assert places.relative_inside(folder, ".") == "."
    assert places.relative_inside(folder, folder) == "."


def test_dot_dot_that_leaves_the_folder_is_outside(folder, outside) -> None:
    for given in ("../外のフォルダ/秘密.json", "記録/../../外のフォルダ/秘密.json", folder / ".." / "外のフォルダ",
                  "案件/" + CASE + "/../../../外のフォルダ"):
        with pytest.raises(places.PlaceError) as e:
            places.resolve_inside(folder, given)
        assert "外" in str(e.value), given
        assert not places.is_inside(folder, given), given


def test_absolute_place_outside(folder, outside) -> None:
    for given in (outside / "秘密.json", outside, Path("/etc/hosts"), Path.home(), folder.parent):
        with pytest.raises(places.PlaceError):
            places.resolve_inside(folder, given)
        assert not places.is_inside(folder, given), given
    # 名前の始まりが同じだけの隣のフォルダも外（文字の前方一致で比べない）
    sibling = folder.parent / (folder.name + "2")
    sibling.mkdir()
    with pytest.raises(places.PlaceError):
        places.resolve_inside(folder, sibling)


def test_links_are_followed_before_comparing(folder, outside) -> None:
    # 外を指す別名（ファイル・フォルダ）は外
    (folder / "記録" / "外へのリンク.json").symlink_to(outside / "秘密.json")
    (folder / "案件" / "外のフォルダへ").symlink_to(outside, target_is_directory=True)
    for given in ("記録/外へのリンク.json", "案件/外のフォルダへ", "案件/外のフォルダへ/秘密.json",
                  "案件/外のフォルダへ/まだない.docx", folder / "記録" / "外へのリンク.json"):
        with pytest.raises(places.PlaceError):
            places.resolve_inside(folder, given)
        assert not places.is_inside(folder, given), given
    # 中を指す別名は、たどった先の場所になる
    (folder / "記録" / "中へのリンク.json").symlink_to(folder / "記録" / "会社の記録.json")
    assert places.relative_inside(folder, "記録/中へのリンク.json") == "記録/会社の記録.json"


def test_company_folder_reached_through_a_link(tmp_path, folder) -> None:
    """会社のフォルダそのものが別名を通して渡されても（/tmp → /private/tmp など）、中の場所は中。"""
    alias = tmp_path / "会社への別名"
    alias.symlink_to(folder, target_is_directory=True)
    assert places.relative_inside(alias, "記録/会社の記録.json") == "記録/会社の記録.json"
    assert places.relative_inside(alias, folder / "記録" / "会社の記録.json") == "記録/会社の記録.json"
    places.no_link_on_the_way(alias, "記録/会社の記録.json")


def test_nfd_names_are_the_same_as_nfc(tmp_path) -> None:
    """Finder で作った名前（NFD）の会社のフォルダと書類を、NFC の場所で渡しても中。返す場所は NFC。"""
    nfd_folder = tmp_path / unicodedata.normalize("NFD", "ポンプ製作所")
    nfd_case = unicodedata.normalize("NFD", CASE)
    (nfd_folder / ".hojokin").mkdir(parents=True)
    (nfd_folder / "案件" / nfd_case).mkdir(parents=True)
    (nfd_folder / "案件" / nfd_case / unicodedata.normalize("NFD", "概要と流れ.docx")).write_bytes(b"PK")
    nfc_folder = tmp_path / "ポンプ製作所"
    rel = f"案件/{CASE}/概要と流れ.docx"
    for base in (nfd_folder, nfc_folder):
        for given in (rel, unicodedata.normalize("NFD", rel)):
            got = places.resolve_inside(base, given)
            assert str(got) == unicodedata.normalize("NFC", str(got))
            assert places.relative_inside(base, given) == rel
            places.no_link_on_the_way(base, given)
    # 実際の場所は、ディスクの上の名前（NFD）で引ける
    found = places.actual(nfc_folder, rel)
    assert found is not None and found.name == unicodedata.normalize("NFD", "概要と流れ.docx")
    assert places.actual(nfc_folder, f"案件/{CASE}/ない.docx") is None
    assert places.actual(nfc_folder, f"案件/{CASE}/ない/もの.docx", partial=True).parts[-2:] == ("ない", "もの.docx")


# ---- no_link_on_the_way ----


def test_no_link_passes_real_folders_and_missing_places(folder) -> None:
    places.no_link_on_the_way(folder, f"案件/{CASE}/1_申請/申請書/その1.docx")
    places.no_link_on_the_way(folder, "記録/会社の記録.json")
    # まだない所から先は、別名もない（消した書類を戻すときなど）
    places.no_link_on_the_way(folder, f"案件/{CASE}/1_申請/申請書/消した.docx")
    places.no_link_on_the_way(folder, "まだない/フォルダ/の中.docx")
    assert places.first_link(folder, "記録/会社の記録.json") is None


@pytest.mark.parametrize("where", ["案件", f"案件/{CASE}", f"案件/{CASE}/1_申請/申請書"])
def test_link_on_the_way_to_outside(folder, outside, where) -> None:
    """途中のフォルダが外を指す別名なら、その先の場所はどれも断り、別名の場所を返す。"""
    target = folder / where
    moved = outside / "元の中身"
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=True)
    rel = f"案件/{CASE}/1_申請/申請書/その1.docx"
    with pytest.raises(places.PlaceError) as e:
        places.no_link_on_the_way(folder, rel)
    assert e.value.link == where
    assert "別名" in str(e.value)
    assert places.first_link(folder, rel) == where
    # その別名そのものも断る
    with pytest.raises(places.PlaceError):
        places.no_link_on_the_way(folder, where)


def test_the_place_itself_as_a_link(folder, outside) -> None:
    record = folder / "記録" / "会社の記録.json"
    record.unlink()
    record.symlink_to(outside / "秘密.json")
    with pytest.raises(places.PlaceError) as e:
        places.no_link_on_the_way(folder, "記録/会社の記録.json")
    assert e.value.link == "記録/会社の記録.json"


def test_link_inside_the_folder_is_also_refused(folder) -> None:
    """別名の先が会社のフォルダの中でも、no_link_on_the_way は断る（書く先が別の置き場に変わるため）。
    resolve_inside は、たどった先が中なので通す。"""
    (folder / "原本").mkdir()
    (folder / "案件" / "原本への別名").symlink_to(folder / "原本", target_is_directory=True)
    rel = "案件/原本への別名/写し.pdf"
    assert places.relative_inside(folder, rel) == "原本/写し.pdf"
    with pytest.raises(places.PlaceError) as e:
        places.no_link_on_the_way(folder, rel)
    assert e.value.link == "案件/原本への別名"


def test_nfd_link_on_the_way_is_found(folder, outside) -> None:
    """ディスクの上の名前が NFD の別名も、NFC の場所で渡して見つける。"""
    nfd_name = unicodedata.normalize("NFD", "ポンプの資料")
    (folder / "案件" / nfd_name).symlink_to(outside, target_is_directory=True)
    with pytest.raises(places.PlaceError) as e:
        places.no_link_on_the_way(folder, "案件/ポンプの資料/秘密.json")
    assert e.value.link == "案件/ポンプの資料"


def test_bad_relative_places_are_refused(folder) -> None:
    for rel in ("../外のフォルダ/秘密.json", "記録/../../外", "/etc/hosts", "", "."):
        with pytest.raises(places.PlaceError):
            places.no_link_on_the_way(folder, rel)
        with pytest.raises(places.PlaceError):
            places.actual(folder, rel)


def test_unreadable_folder_on_the_way(folder, outside) -> None:
    """中の一覧を読めないフォルダの下の別名も、名前で開いて見つける。"""
    locked = folder / "案件" / CASE
    (locked / "外へ").symlink_to(outside, target_is_directory=True)
    os.chmod(str(locked), 0o311)  # 一覧は読めないが、名前で開ける
    try:
        with pytest.raises(places.PlaceError) as e:
            places.no_link_on_the_way(folder, f"案件/{CASE}/外へ/秘密.json")
        assert e.value.link == f"案件/{CASE}/外へ"
    finally:
        os.chmod(str(locked), 0o755)
