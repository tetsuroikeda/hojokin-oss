"""T1-6 候補の Word。

SPEC：候補の一覧から Word を作る。
合格ライン：候補・区分・合う理由・対象外になりそうな点・次の公募の見込み・予算の状況・出典URLが、すべて Word に入る。
探し直すと同じファイルが直り、別のファイルは増えない。

- 道具（skills/sagasu/scripts/kouho_word.py）を、社長の Mac と同じ /usr/bin/python3（3.9）で動かす。
- Word は zip と XML を標準のライブラリで読み、候補ごとの表の「項目 → 中身」を、渡した一覧と1つずつ突き合わせる。
- 探し直す前後で、会社のフォルダのファイルの一覧（隠しファイルを含む）が同じで、中身だけが変わることを見る。
- XML で使えない文字（PDF から写した改ページなど）が入っても、どの部品も XML として読める Word になり、
  前の正常な版を壊れたもので置き換えないことを見る。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib import kouho

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "sagasu" / "scripts" / "kouho_word.py"
SYSTEM_PYTHON = "/usr/bin/python3"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

FIELDS = ("合う理由", "対象外になりそうな点", "次の公募の見込み", "予算の状況")

SAMPLE = {
    "会社名": "架空 惣菜工房",
    "聞き取りの要点": ["惣菜の製造", "盛り付けと包装を機械にしたい"],
    "候補": [
        {
            "名前": "中小企業省力化投資補助金（一般型）",
            "区分": "例年公募がある",
            "合う理由": ["盛り付けと包装の機械は、省力化の設備に当たる", "人手不足が続いている"],
            "対象外になりそうな点": "賃上げの計画が立たないと、補助上限が下がる",
            "次の公募の見込み": "第9回は2026年12月ごろ（第7回・第8回の公募の時期から）",
            "予算の状況": "令和7年度補正予算で継続（中小企業庁の予算資料）",
            "出典URL": ["https://shoryokuka.smrj.go.jp/ippan/", "https://www.chusho.meti.go.jp/koukai/yosan/"],
        },
        {
            "名前": "小規模事業者持続化補助金（一般型・通常枠）",
            "区分": "公募予定（発表済み）",
            "合う理由": "販路開拓の取り組みに使える",
            "対象外になりそうな点": "従業員が20人を超えると対象外",
            "次の公募の見込み": "第20回の受付開始は2026年12月（公募要領で発表済み）",
            "予算の状況": "見つからなかった",
            "出典URL": "https://r6.jizokukahojokin.info/",
            "対象外の可能性が高い": True,
        },
        {
            "名前": "業務改善助成金",
            "区分": "公募中",
            "合う理由": "設備投資と事業場内最低賃金の引き上げをあわせて行う",
            "対象外になりそうな点": "賃金を引き上げる前に交付申請が要る",
            "次の公募の見込み": "今の受付は2027年1月31日まで",
            "予算の状況": "令和8年度当初予算に計上（厚生労働省の予算資料）",
            "出典URL": ["https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/shienjigyou/03.html?a=1&b=2"],
            "締切": "2027年1月31日（日）23:59",
        },
    ],
}


def make_company(tmp_path: Path, name: str = "架空の会社") -> Path:
    folder = tmp_path / name
    (folder / ".hojokin").mkdir(parents=True)
    (folder / "メモ.txt").write_text("会社のメモ", encoding="utf-8")
    return folder


def listing(folder: Path) -> list:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def run_tool(folder: Path, data, *extra: str) -> subprocess.CompletedProcess:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return subprocess.run(
        [SYSTEM_PYTHON, "-I", "-B", str(SCRIPT), "--folder", str(folder), *extra],
        input=text, capture_output=True, text=True, encoding="utf-8",
        env={"PATH": "/usr/bin:/bin", "HOME": str(folder.parent)}, cwd=folder.parent, timeout=60,
    )


def text_of(element) -> str:
    """段落やセルの文字（改行 w:br は \\n にする）。"""
    out = []
    for node in element.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "br":
            out.append("\n")
    return "".join(out)


class Docx:
    """Word の中身を読む。見出し2（候補の名前）の直後の表を、その候補の表として持つ。"""

    def __init__(self, path: Path) -> None:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names
            assert zf.testzip() is None
            root_rels = ET.fromstring(zf.read("_rels/.rels"))
            targets = [r.get("Target") for r in root_rels.iter(PKG_REL)]
            assert "word/document.xml" in targets
            self.document = ET.fromstring(zf.read("word/document.xml"))
            rels = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
            self.rels = {r.get("Id"): r for r in rels.iter(PKG_REL)}
            for part in names:
                if part.endswith(".xml") or part.endswith(".rels"):
                    ET.fromstring(zf.read(part))  # どの部品も XML として読める
        body = self.document.find(W + "body")
        self.headings = {1: [], 2: []}
        self.tables = {}
        self.paragraphs = []
        current = None
        for child in body:
            if child.tag == W + "p":
                style = child.find(f"{W}pPr/{W}pStyle")
                level = {"Heading1": 1, "Heading2": 2}.get(style.get(W + "val") if style is not None else "")
                text = text_of(child)
                self.paragraphs.append(text)
                if level:
                    self.headings[level].append(text)
                    current = text if level == 2 else None
            elif child.tag == W + "tbl":
                rows = [[cell for cell in row.findall(W + "tc")] for row in child.findall(W + "tr")]
                if current is not None and current not in self.tables:
                    self.tables[current] = rows
                elif current is None:
                    self.tables.setdefault("一覧", rows)

    def detail(self, heading: str) -> dict:
        rows = self.tables[heading]
        assert [text_of(c) for c in rows[0]] == ["項目", "中身"]
        return {text_of(r[0]): r[1] for r in rows[1:]}

    def links_in(self, cell) -> list:
        out = []
        for link in cell.iter(W + "hyperlink"):
            rel = self.rels[link.get(R_ID)]
            assert rel.get("TargetMode") == "External"
            out.append((text_of(link), rel.get("Target")))
        return out

    @property
    def all_text(self) -> str:
        return text_of(self.document)


def heading_for(item: dict) -> str:
    return item["名前"] + (" 【対象外の可能性が高い】" if item.get("対象外の可能性が高い") else "")


def as_text(value) -> str:
    return "\n".join(f"・{v}" for v in value) if isinstance(value, list) else value


def as_urls(value) -> list:
    return value if isinstance(value, list) else [value]


def assert_word_matches(path: Path, data: dict) -> Docx:
    doc = Docx(path)
    for item in data["候補"]:
        title = heading_for(item)
        assert title in doc.headings[2]
        rows = doc.detail(title)
        assert text_of(rows["区分"]) == item["区分"]  # 区分
        for field in FIELDS:  # 合う理由・対象外になりそうな点・次の公募の見込み・予算の状況
            assert text_of(rows[field]) == as_text(item[field]), field
        urls = as_urls(item["出典URL"])  # 出典URL（文字とリンク先の両方）
        assert text_of(rows["出典URL"]) == "\n".join(urls)
        assert doc.links_in(rows["出典URL"]) == [(u, u) for u in urls]
        if "締切" in item:
            assert text_of(rows["締切（日本時間）"]) == item["締切"]
        else:
            assert "締切（日本時間）" not in rows
    # 一覧の表にも、すべての候補が区分つきで入る
    summary = [[text_of(c) for c in row] for row in doc.tables["一覧"]]
    assert summary[0] == ["区分", "候補", "締切・次の公募の見込み"]
    assert sorted((r[0], r[1]) for r in summary[1:]) == sorted((i["区分"], heading_for(i)) for i in data["候補"])
    # 区分ごとの見出しに件数が付く
    for category in kouho.CATEGORIES:
        n = sum(1 for i in data["候補"] if i["区分"] == category)
        assert (f"{category}（{n}件）" in doc.headings[1]) == (n > 0)
    return doc


# --- すべての項目が Word に入る ---

def test_all_items_go_into_word(tmp_path) -> None:
    folder = make_company(tmp_path)
    r = run_tool(folder, SAMPLE)
    assert r.returncode == 0, r.stdout + r.stderr
    path = folder / "補助金の候補.docx"
    doc = assert_word_matches(path, SAMPLE)
    assert "会社：架空 惣菜工房" in doc.all_text
    assert "・盛り付けと包装を機械にしたい" in doc.all_text
    assert "公募中 1件、公募予定（発表済み） 1件、例年公募がある 1件" in r.stdout
    assert listing(folder) == sorted([".hojokin", "メモ.txt", "補助金の候補.docx"])


def test_searched_date_follows_substituted_today(tmp_path) -> None:
    folder = make_company(tmp_path)
    (folder / ".hojokin" / "設定.json").write_text('{"今日の日付": "2027-03-01"}', encoding="utf-8")
    assert run_tool(folder, SAMPLE).returncode == 0
    assert "探した日：2027年3月1日（月）" in Docx(folder / "補助金の候補.docx").all_text


def test_no_candidates_is_written_as_such(tmp_path) -> None:
    folder = make_company(tmp_path)
    assert run_tool(folder, {"候補": []}).returncode == 0
    assert "条件に合う候補は見つかりませんでした。" in Docx(folder / "補助金の候補.docx").all_text


# --- 探し直すと同じファイルが直り、別のファイルは増えない ---

def test_search_again_updates_same_file_without_new_files(tmp_path) -> None:
    folder = make_company(tmp_path)
    assert run_tool(folder, SAMPLE).returncode == 0
    before = listing(folder)
    first = (folder / "補助金の候補.docx").read_bytes()

    again = copy.deepcopy(SAMPLE)
    removed = again["候補"].pop(2)
    again["候補"][0]["予算の状況"] = "令和8年度の概算要求に計上（中小企業庁の資料）"
    again["候補"].append({
        "名前": "ものづくり・商業・サービス生産性向上促進補助金",
        "区分": "公募中",
        "合う理由": "新しい惣菜の製造ラインに使える",
        "対象外になりそうな点": "前の採択から日が浅いと減点",
        "次の公募の見込み": "今の受付は2027年2月まで",
        "予算の状況": "見つからなかった",
        "出典URL": "https://portal.monodukuri-hojo.jp/",
    })
    r = run_tool(folder, again)
    assert r.returncode == 0, r.stdout + r.stderr

    assert listing(folder) == before  # ファイルは増えない（一時ファイルも残らない）
    path = folder / "補助金の候補.docx"
    assert path.read_bytes() != first  # 同じファイルが直った
    doc = assert_word_matches(path, again)
    assert removed["名前"] not in doc.all_text
    assert "令和7年度補正予算で継続" not in doc.all_text

    # 同じ一覧でもう一度作ると、中身は1バイトも変わらない（版の履歴に無駄な版を残さない）
    second = path.read_bytes()
    assert run_tool(folder, again).returncode == 0
    assert path.read_bytes() == second
    assert listing(folder) == before


def test_failed_write_keeps_old_file_and_leaves_nothing(tmp_path, monkeypatch) -> None:
    folder = make_company(tmp_path)
    kouho.write(folder, SAMPLE)
    before = listing(folder)
    old = (folder / "補助金の候補.docx").read_bytes()

    def broken_replace(src, dst):
        raise OSError("ディスクがいっぱい")

    monkeypatch.setattr(os, "replace", broken_replace)
    changed = copy.deepcopy(SAMPLE)
    changed["候補"][0]["合う理由"] = "書き換えた理由"
    with pytest.raises(OSError):
        kouho.write(folder, changed)
    assert listing(folder) == before
    assert (folder / "補助金の候補.docx").read_bytes() == old


# --- XML で使えない文字（PDF から写した改ページなど）が入っても、読める Word にする ---

@pytest.mark.parametrize(
    "raw, shown",
    [
        ("A\u000bB", "A\nB"),  # 垂直タブ → 改行
        ("A\u000cB", "A\nB"),  # 改ページ → 改行
        ("A\r\nB", "A\nB"),
        ("A\x00B", "AB"),
        ("A\x1fB", "AB"),
        ("A￾B", "AB"),
        ("A\ud800B", "AB"),  # 対になっていないサロゲート
    ],
)
def test_characters_not_allowed_in_xml_still_make_readable_word(tmp_path, raw, shown) -> None:
    folder = make_company(tmp_path)
    assert run_tool(folder, SAMPLE).returncode == 0  # 前の正常な版
    data = copy.deepcopy(SAMPLE)
    item = data["候補"][0]
    item["名前"] = "省力化" + raw
    item["合う理由"] = ["一つめ" + raw, "二つめ"]
    item["予算の状況"] = "予算" + raw
    data["聞き取りの要点"] = "要点" + raw
    # サロゲートは UTF-8 で送れないので、JSON の \\uXXXX の形で渡す
    r = run_tool(folder, json.dumps(data, ensure_ascii=True))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    doc = Docx(folder / "補助金の候補.docx")  # どの部品も XML として読める（読めなければここで落ちる）
    title = "省力化" + shown
    assert title in doc.headings[2]
    rows = doc.detail(title)
    assert text_of(rows["合う理由"]) == f"・一つめ{shown}\n・二つめ"
    assert text_of(rows["予算の状況"]) == "予算" + shown
    assert "要点" + shown in doc.all_text
    summary = [[text_of(c) for c in row] for row in doc.tables["一覧"]]
    assert ["例年公募がある", title] in [row[:2] for row in summary]
    assert listing(folder) == sorted([".hojokin", "メモ.txt", "補助金の候補.docx"])


@pytest.mark.parametrize("url", ["https://ok.go.jp/a\u000cb", "https://ok.go.jp/a b", "https://ok.go.jp/\x00"])
def test_url_with_space_or_control_character_is_refused_and_old_file_stays(tmp_path, url) -> None:
    folder = make_company(tmp_path)
    assert run_tool(folder, SAMPLE).returncode == 0
    old = (folder / "補助金の候補.docx").read_bytes()
    broken = copy.deepcopy(SAMPLE)
    broken["候補"][2]["出典URL"] = ["https://ok.go.jp/", url]
    r = run_tool(folder, json.dumps(broken, ensure_ascii=True))
    assert r.returncode == 2, r.stdout
    assert "空白か使えない文字" in r.stdout
    assert (folder / "補助金の候補.docx").read_bytes() == old


def test_name_of_only_unusable_characters_is_empty(tmp_path) -> None:
    folder = make_company(tmp_path)
    broken = copy.deepcopy(SAMPLE)
    broken["候補"][0]["名前"] = "\x00\ud800"
    r = run_tool(folder, json.dumps(broken, ensure_ascii=True))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "「名前」が空" in r.stdout
    assert "Traceback" not in r.stderr
    assert not (folder / "補助金の候補.docx").exists()


def test_broken_xml_part_is_not_written_and_old_file_stays(tmp_path, monkeypatch) -> None:
    """文字を直しても読めない部品ができたとき（道具の誤り）は、書く前に止まり、前の版が残る。"""
    from lib import docx_min

    broken_doc = docx_min.Document()
    broken_doc._body.append("<w:p>")  # 閉じていない
    with pytest.raises(docx_min.DocxError):
        broken_doc.to_bytes()

    folder = make_company(tmp_path)
    kouho.write(folder, SAMPLE)
    before = listing(folder)
    old = (folder / "補助金の候補.docx").read_bytes()
    monkeypatch.setattr(kouho, "build", lambda data, day: broken_doc)
    with pytest.raises(kouho.KouhoError):
        kouho.write(folder, SAMPLE)
    assert listing(folder) == before
    assert (folder / "補助金の候補.docx").read_bytes() == old


# --- 欠けた一覧では作らない ---

@pytest.mark.parametrize("field", kouho.REQUIRED_FIELDS)
def test_missing_field_is_refused_and_nothing_changes(tmp_path, field) -> None:
    folder = make_company(tmp_path)
    assert run_tool(folder, SAMPLE).returncode == 0
    before = listing(folder)
    old = (folder / "補助金の候補.docx").read_bytes()
    broken = copy.deepcopy(SAMPLE)
    del broken["候補"][1][field]
    r = run_tool(folder, broken)
    assert r.returncode == 2
    assert f"「{field}」がありません" in r.stdout
    assert listing(folder) == before
    assert (folder / "補助金の候補.docx").read_bytes() == old


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("区分", "公募中です", "「区分」は"),
        ("出典URL", [], "出典URL"),
        ("出典URL", "どこかのサイト", "出典URL"),
        ("出典URL", ["https://ok.go.jp/", "ftp://x"], "出典URL"),
        ("予算の状況", "", "見つからなかった"),
        ("合う理由", [], "「合う理由」が空"),
        ("名前", " ", "「名前」が空"),
        ("対象外の可能性が高い", "はい", "true か false"),
        ("理由メモ", "x", "使わない欄"),
    ],
)
def test_wrong_values_are_refused(tmp_path, field, value, message) -> None:
    folder = make_company(tmp_path)
    broken = copy.deepcopy(SAMPLE)
    broken["候補"][0][field] = value
    r = run_tool(folder, broken)
    assert r.returncode == 2
    assert message in r.stdout
    assert not (folder / "補助金の候補.docx").exists()


def test_not_json_is_refused(tmp_path) -> None:
    folder = make_company(tmp_path)
    r = run_tool(folder, "候補は3つです")
    assert r.returncode == 2
    assert not (folder / "補助金の候補.docx").exists()


def test_outside_company_folder_writes_nothing(tmp_path) -> None:
    folder = tmp_path / "ふつうのフォルダ"
    folder.mkdir()
    r = run_tool(folder, SAMPLE)
    assert r.returncode == 2
    assert "会社のフォルダではありません" in r.stdout
    assert list(folder.iterdir()) == []


def test_input_file_option(tmp_path) -> None:
    """--input のファイルは、会社のフォルダの中のものを読む（相対の場所は会社のフォルダから解く）。"""
    folder = make_company(tmp_path)
    source = folder / "候補.json"
    source.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    for where in (str(source), "候補.json"):
        (folder / "補助金の候補.docx").unlink(missing_ok=True)
        r = run_tool(folder, "", "--input", where)
        assert r.returncode == 0, r.stdout
        assert_word_matches(folder / "補助金の候補.docx", SAMPLE)


def test_input_file_outside_company_folder_is_not_read(tmp_path) -> None:
    """--input のファイルが会社のフォルダの外（外の絶対の場所、../、外を指す別名）なら、読まずに断る
    （DESIGN 5章「会社のフォルダの外に書かない・外を読まない」。lib/places.py）。"""
    folder = make_company(tmp_path)
    secret = tmp_path / "候補.json"
    secret.write_text(json.dumps(dict(SAMPLE, 会社名="外のファイルの会社名"), ensure_ascii=False), encoding="utf-8")
    (folder / "外へのリンク.json").symlink_to(secret)
    for where in (str(secret), "../候補.json", "外へのリンク.json", str(folder / "外へのリンク.json")):
        # 標準入力には正しい一覧を流す（--input を無視して標準入力を読めば、書いてしまうので分かる）
        r = run_tool(folder, SAMPLE, "--input", where)
        assert r.returncode == 2, (where, r.stdout)
        assert "外のファイルは読みません" in r.stdout, (where, r.stdout)
        assert "外のファイルの会社名" not in r.stdout
        assert not (folder / "補助金の候補.docx").exists(), where
    # 会社のフォルダでない所では、ファイルを読まずに断る
    other = tmp_path / "ふつうのフォルダ"
    other.mkdir()
    r = run_tool(other, SAMPLE, "--input", str(secret))
    assert r.returncode == 2 and "会社のフォルダではありません" in r.stdout and "読んでいません" in r.stdout
    assert list(other.iterdir()) == []
