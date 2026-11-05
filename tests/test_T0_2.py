"""T0-2 地名を書き込まない（SPEC 共通の要件「所在地を固定しない」、TASKS B34、実験 E11）。

合格ライン：プログラムと同梱の知見を、全国の都道府県・市区町村名で検索して、該当0件。

- 調べるもの：プラグインに入れて配るもの（skills/、hooks/、agents/、knowledge/、schema/、lib/（同梱のライブラリ lib/vendor/ を除く）、
  .claude-plugin/）。テスト・テストの材料（tests/、testdata/、evals/、mock/）と開発の文書（docs/、SPEC.md、experiments/）は調べない
  （架空の会社の所在地や、制度の資料の地名を持つため）。
- 地名の一覧：都道府県47はこのファイルに書く。市区町村（市・町・村・特別区と、政令指定都市の区）は tests/data/市区町村.txt
  （1行に「都道府県<TAB>名前<TAB>種類<TAB>親の市（政令指定都市の区だけ）」。作り方と出典はそのファイルの頭の注記）。
- 普通の言葉を拾わない（実験 E11）：名前は「市・区・町・村・都・道・府・県」まで付けて探す（「中央」「北」「港」だけでは探さない）。
  そのうえで、次の2つを当たりにしない。
  1. 名前のすぐ後ろに、言葉を続ける字（区分の「分」、市場の「場」、区域の「域」など。FOLLOWERS）がある。
  2. 字の部分が1字の名前（北区・港区・津市など）の前に、漢字がある（集中区・空港区域などの言葉の一部。親の名前と続く
     「大阪市北区」は、親の名前の方で当たる）。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pytest

from conftest import REPO_ROOT

LIST_FILE = REPO_ROOT / "tests" / "data" / "市区町村.txt"
TARGET_DIRS = ["skills", "hooks", "agents", "knowledge", "schema", "lib", ".claude-plugin"]
EXCLUDE_DIRS = ["lib/vendor"]
TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".yaml", ".yml", ".sh", ".html", ".csv", ""}

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県",
    "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
    "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

# 名前のすぐ後ろに来ると、名前ではなく別の言葉の一部になる字（実験 E11 で決めた。中区分・中央市場・区域・区画）。
# 「内」「民」「長」「役」「立」などは入れない（「福井県内」「大田区民」「松江市長」「入善町役場」は地名として拾うため）
FOLLOWERS = set("分場域画")
# 一覧と別の書き方の名前（一覧は出典の字のまま）
ALIASES = ["飛騨市", "梼原町"]
_KANJI = re.compile(r"[㐀-鿿豈-﫿々〆ヶ]")


def is_kanji(ch: str) -> bool:
    return bool(_KANJI.match(ch))


def load_municipalities() -> List[Tuple[str, str, str]]:
    """（都道府県、名前、種類）の一覧。ファイルの「#」の行は注記。4つ目の欄（政令指定都市の区の親の市）は読まない。"""
    out = []
    for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pref, name, kind = line.split("\t")[:3]
        out.append((pref, name, kind))
    return out


def place_names() -> List[str]:
    names = set(PREFECTURES) | set(ALIASES)
    if LIST_FILE.is_file():
        names |= {name for _p, name, _k in load_municipalities()}
    return sorted(names, key=len, reverse=True)


def find_places(text: str, names: Iterable[str]) -> List[Tuple[int, str]]:
    """text の中の地名（位置、名前）。E11 の決まりで、普通の言葉の一部は当たりにしない。"""
    text = unicodedata.normalize("NFKC", text)
    hits = []
    for name in names:
        stem_one = len(name) == 2  # 字の部分が1字（北区・港区・津市など）
        start = 0
        while True:
            i = text.find(name, start)
            if i < 0:
                break
            start = i + 1
            after = text[i + len(name)] if i + len(name) < len(text) else ""
            before = text[i - 1] if i > 0 else ""
            if after in FOLLOWERS:
                continue
            if stem_one and before and is_kanji(before):
                continue
            hits.append((i, name))
    return sorted(hits)


def target_files() -> List[Path]:
    out = []
    for d in TARGET_DIRS:
        for p in sorted((REPO_ROOT / d).rglob("*")):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if not p.is_file() or any(rel.startswith(x + "/") for x in EXCLUDE_DIRS) or "__pycache__" in rel:
                continue
            if p.suffix.lower() in TEXT_SUFFIXES:
                out.append(p)
    return out


def scan(paths: Iterable[Path], names: List[str]) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="ignore")
        hits = find_places(text, names)
        if hits:
            norm = unicodedata.normalize("NFKC", text)
            found[p.relative_to(REPO_ROOT).as_posix()] = [f"{n}（…{norm[max(0, i - 8):i + len(n) + 8]}…）" for i, n in hits[:5]]
    return found


def test_municipality_list() -> None:
    """市区町村の一覧がそろっている（市町村1,718、特別区23、政令指定都市の区。都道府県は47すべてにある）。"""
    if not LIST_FILE.is_file():
        pytest.fail(f"市区町村の一覧（{LIST_FILE.relative_to(REPO_ROOT)}）がない。作り方は tests/test_T0_2.py の頭と報告を見る")
    rows = load_municipalities()
    kinds: Dict[str, int] = {}
    for _p, _n, k in rows:
        kinds[k] = kinds.get(k, 0) + 1
    assert kinds.get("市", 0) + kinds.get("町", 0) + kinds.get("村", 0) == 1718, kinds
    assert kinds.get("特別区") == 23, kinds
    assert kinds.get("政令指定都市の区", 0) >= 150, kinds
    assert {p for p, _n, _k in rows} == set(PREFECTURES)


def test_no_place_names_in_plugin() -> None:
    """プログラムと同梱の知見に、都道府県・市区町村名が0件（T0-2）。"""
    files = target_files()
    assert len(files) > 30  # 調べる場所を取り違えていない
    assert scan(files, place_names()) == {}


@pytest.mark.parametrize("text", [
    "区分", "中区分", "地区", "中央市場", "空港区域", "北側の工場", "中央の通路", "港の倉庫", "南向き", "緑色",
    "市町村", "市区町村", "町内会", "村長", "都道府県", "東西南北", "集中区画", "北区分",
])
def test_ordinary_words_are_not_places(text: str) -> None:
    """普通の言葉と、その一部に地名と同じ字を含む言葉を拾わない（実験 E11）。"""
    assert find_places(text, place_names()) == []


@pytest.mark.parametrize("text, name", [
    ("東京都大田区東糀谷", "東京都"), ("本社は大田区にある", "大田区"), ("島根県松江市", "松江市"),
    ("入善町の補助金", "入善町"), ("北区の会社", "北区"), ("「港区」", "港区"), ("中央区で", "中央区"),
    ("福井県内に", "福井県"), ("松江市長", "松江市"), ("大田区民", "大田区"), ("入善町役場", "入善町"), ("飛騨市", "飛騨市"),
])
def test_place_names_are_found(text: str, name: str) -> None:
    """地名は、言葉の中にあっても拾う（一覧にない名前は拾えないので、一覧がないときは都道府県だけ）。"""
    names = place_names()
    if name not in names:
        pytest.skip(f"「{name}」は市区町村の一覧がないと探せない")
    assert name in [n for _i, n in find_places(text, names)]
