"""T3-1 資料の取得とフォルダ（SPEC F3、DESIGN 4.5・9.2、TASKS M2a）。

合格ライン：資料がそろい、書類フォルダができる。未公表なら「直近回の資料に基づく」と示す。

確かめること
- 資料がそろう
  - 取る資料の一覧（skills/junbi/取る資料/）の資料が、すべて `案件/<案件>/公式資料/` に置かれる。中身は公式サイトのものと同じ
    （手元の写しでは、downloads/ と制度データの正解のハッシュと1バイトも違わない）。置いたファイルは読み取り専用
  - 公式サイトから実際に取る（通信あり）。省力化 第8回と持続化 第20回の資料が、すべてそろう
  - 資料ごとに、ページごとの文字（`記録/資料の本文/`）と、印刷されたページ番号との対応ができる。ずれは DESIGN 9章の注と正解のとおり。
    印刷された番号で引いたページに、そのページの中身がある
  - 資料の一覧が、制度データの「資料」の形（スキーマ）で残る
  - 取れない資料（ない場所、PDF のはずがウェブページ）は置かずに、そろっていないと示す。前と中身が違う資料は上書きしない
- 書類フォルダができる：`案件/2026_省力化（一般型）第9回/公式資料/`。段階のフォルダは、制度データの手続きの段階から作れる
- 未公表なら「直近回の資料に基づく」と示す：申請する回（第9回）の資料がなく、第8回の資料で作ったときは、結果と資料の一覧に示す。
  回が同じなら示さない
- 会社のフォルダでなければ、何も書かずに断る。会社のフォルダの外（プラグインの場所など）には何も書かない

道具は、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす。
同梱の pypdf を読み込む lib のモジュールは、テストの Python の中では読み込まない（開発用の環境と混ざらないように。tests/company_tool.py）。
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import company_tool as ct
import hook_runner as hr
import jsonschema
import pytest

from lib import case_folder

REPO_ROOT = hr.REPO_ROOT
DOWNLOADS = REPO_ROOT / "downloads"
SCRIPT = Path("skills") / "junbi" / "scripts" / "fetch_documents.py"
LISTS = REPO_ROOT / "skills" / "junbi" / "取る資料"
SHORYOKUKA_LIST = LISTS / "省力化_一般型_第8回.json"
JIZOKUKA_LIST = LISTS / "持続化_通常枠_第20回.json"
ANSWER = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
SCHEMA = REPO_ROOT / "schema" / "制度データ.schema.json"
TODAY = "2026-11-04"
SHORYOKUKA_CASE = "2026_省力化（一般型）第9回"
JIZOKUKA_CASE = "2026_持続化（一般型・通常枠）第20回"
LATEST_NOTICE = "第9回の資料はまだ公表されていないため、直近回である第8回の資料に基づいています"

# DESIGN 9章の注：持続化の公募要領・操作手引き・補助事業の手引きは、印刷された番号が PDF のページより1つ小さく、Q&A は5つ小さい
JIZOKUKA_OFFSETS = {"要領20": 1, "操作手引き19": 1, "補助事業の手引き19": 1, "Q&A20": 5}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- 手元の写しを出すウェブの場所（公式サイトの代わり） ----


def downloads_by_hash() -> dict:
    found = {}
    for p in DOWNLOADS.rglob("*"):
        if p.is_file() and p.name != ".DS_Store":
            found[sha256(p)] = p
    return found


class Site:
    """127.0.0.1 で、公式サイトと同じ場所（パス）に手元の写しを出す。中身を差し替えたり、ないことにしたりできる。"""

    def __init__(self) -> None:
        self.routes = {}  # パス → (中身, Content-Type)
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                route = site.routes.get(urlsplit(self.path).path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<html><body>not found</body></html>")
                    return
                body, ctype = route
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def put(self, path: str, body: bytes, ctype: str = "") -> None:
        if not ctype:
            ctype = mimetypes.guess_type(path)[0] or ("text/html" if path.endswith("/") else "application/octet-stream")
        self.routes[path] = (body, ctype)

    def local(self, url: str) -> str:
        return self.base + urlsplit(url).path

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site(downloads_files):
    s = Site()
    by_hash = downloads_by_hash()
    # 省力化：正解のハッシュと同じ手元の写しを、正解の URL の場所に出す
    for doc in load(ANSWER)["資料"]:
        s.put(urlsplit(doc["URL"]).path, by_hash[doc["ハッシュ"]].read_bytes())
    # 持続化：手元の写しを、同じファイルの名前の場所に出す
    for doc in load(JIZOKUKA_LIST)["資料"]:
        path = urlsplit(doc["URL"]).path
        s.put(path, (DOWNLOADS / "jizokuka_20" / Path(path).name).read_bytes())
    yield s
    s.close()


def local_list(site: Site, source: Path) -> dict:
    data = load(source)
    for doc in data["資料"]:
        doc["URL"] = site.local(doc["URL"])
    return data


# ---- 道具を動かす ----


class Company:
    def __init__(self, tmp_path: Path) -> None:
        self.env = ct.Env(tmp_path)
        self.folder = self.env.folder("山田 製作所")
        ct.ok(self.env.run(self.folder))
        settings = self.folder / ".hojokin" / "設定.json"
        data = load(settings) if settings.exists() else {}
        data["今日の日付"] = TODAY  # 案件の名前の年と、取得日を決まった値にする
        settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.lists = tmp_path / "一覧"
        self.lists.mkdir()

    def fetch(self, data: dict, *extra: str, folder: Path = None, name: str = "一覧.json") -> subprocess.CompletedProcess:
        path = self.lists / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        env = {"PATH": self.env.path, "HOME": str(self.env.home), "TMPDIR": str(self.env.tmp)}
        return subprocess.run(
            [hr.real_python(), "-B", str(self.env.plugin / SCRIPT),
             "--folder", str(folder or self.folder), "--list", str(path), *extra],
            env=env, cwd=self.env.cwd, capture_output=True, timeout=600,
        )

    def case(self, name: str) -> Path:
        return self.folder / "案件" / name

    def texts(self, name: str) -> Path:
        return self.folder / "記録" / "資料の本文" / name

    def doc_list(self, name: str) -> dict:
        return load(self.texts(name) / "資料の一覧.json")


def out(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode("utf-8")


def file_stem(doc: dict) -> str:
    return f"{doc['名前']}_{doc['公募回']}"


def official_files(company: Company, case: str) -> dict:
    return {p.stem: p for p in (company.case(case) / "公式資料").iterdir() if p.is_file()}


def page_file(company: Company, case: str, doc_id: str, printed: int) -> str:
    """印刷された番号で引いたページの文字（見出しの行を含む）。"""
    doc_dir = company.texts(case) / doc_id
    index = load(doc_dir / "ページの対応.json")
    pages = [p for p in index["ページ"] if p.get("印刷されたページ") == printed]
    assert len(pages) == 1, (doc_id, printed)
    return (doc_dir / pages[0]["ファイル"]).read_text(encoding="utf-8")


def validate_doc_list(entries: list) -> None:
    """資料の一覧が、制度データの「資料」の形（スキーマ）に合う。"""
    full = load(SCHEMA)
    schema = dict(full["properties"]["資料"])
    schema["$defs"] = full["$defs"]
    schema["$schema"] = full.get("$schema", "https://json-schema.org/draft/2020-12/schema")
    jsonschema.validate(entries, schema)


def check_text_dirs(company: Company, case: str, docs: list) -> None:
    """資料ごとに、ページごとの文字とページの対応ができている。"""
    for doc in docs:
        doc_dir = company.texts(case) / doc["id"]
        index = load(doc_dir / "ページの対応.json")
        assert index["資料"] == doc["id"]
        assert len(index["ページ"]) == index["ページ数"] >= 1
        for page in index["ページ"]:
            text = (doc_dir / page["ファイル"]).read_text(encoding="utf-8")
            assert text.startswith(f"【{doc['名前']}（{doc['公募回']}）／資料 {doc['id']}／")
        if index["種類"] == "PDF":
            # PDF のページを1から順に、すべて文字にした
            assert [p["PDFのページ"] for p in index["ページ"]] == list(range(1, index["ページ数"] + 1))
            assert sum(p["文字数"] for p in index["ページ"]) > 1000


# ---- 手元の写しで確かめる（決まった中身） ----


def test_lists_match_design(downloads_files) -> None:
    """同梱の一覧は、DESIGN 15.3 の資料（省力化は制度データの正解の資料と同じ）。"""
    answer = {d["id"]: d for d in load(ANSWER)["資料"]}
    listed = {d["id"]: d for d in load(SHORYOKUKA_LIST)["資料"]}
    assert listed.keys() == answer.keys()
    for doc_id, doc in listed.items():
        for key in ("名前", "公募回", "URL"):
            assert doc[key] == answer[doc_id][key], (doc_id, key)
    design = (REPO_ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    for doc in load(JIZOKUKA_LIST)["資料"]:
        assert doc["URL"] in design, doc["URL"]


def test_documents_and_case_folder_latest_round(tmp_path, site) -> None:
    """第9回の案件を、第8回の資料で作る。資料がそろい、書類フォルダができ、直近回の資料に基づくと示す。"""
    company = Company(tmp_path)
    data = local_list(site, SHORYOKUKA_LIST)
    before_outside = company.env.outside()
    r = company.fetch(data, "--case-round", "第9回")
    text = out(r)
    assert r.returncode == 0, (text, r.stderr.decode("utf-8"))
    assert r.stderr == b""
    assert "資料はすべてそろいました" in text

    # 書類フォルダ
    case = company.case(SHORYOKUKA_CASE)
    assert (case / "公式資料").is_dir()
    assert f"案件/{SHORYOKUKA_CASE}/" in text

    # 資料がそろう：中身は正解（公式サイトから取ったもの）と1バイトも違わず、読み取り専用
    answer = {d["id"]: d for d in load(ANSWER)["資料"]}
    files = official_files(company, SHORYOKUKA_CASE)
    assert set(files) == {file_stem(d) for d in data["資料"]}
    for doc in data["資料"]:
        path = files[file_stem(doc)]
        assert sha256(path) == answer[doc["id"]]["ハッシュ"], doc["id"]
        assert path.stat().st_mode & 0o222 == 0, doc["id"]
    assert files["公募要領_第8回"].suffix == ".pdf"
    assert files["スケジュール（一般型）のページ_第8回"].suffix == ".html"
    assert not [p for p in (case / "公式資料").iterdir() if p.name.startswith(".")]

    # 未公表なら「直近回の資料に基づく」と示す（結果の文と、資料の一覧の両方）
    assert LATEST_NOTICE in text
    assert "「交付申請の手引き」は、第6回の資料に基づいています" in text
    listed = company.doc_list(SHORYOKUKA_CASE)
    assert listed["案件の回"] == "第9回"
    assert listed["直近回の資料に基づく"] is True
    assert any(LATEST_NOTICE in n for n in listed["案内"])

    # 資料の一覧は、制度データの「資料」の形。ずれ・ハッシュは正解と同じ。取得日は今日
    validate_doc_list(listed["資料"])
    assert [e["id"] for e in listed["資料"]] == [d["id"] for d in data["資料"]]
    for entry in listed["資料"]:
        expected = answer[entry["id"]]
        assert entry["ハッシュ"] == expected["ハッシュ"]
        assert entry["取得日"] == TODAY
        assert entry["公募回"] == expected["公募回"]
        assert entry.get("ページのずれ") == expected.get("ページのずれ"), entry["id"]

    # ページごとの文字と、印刷されたページ番号との対応
    check_text_dirs(company, SHORYOKUKA_CASE, data["資料"])
    page9 = page_file(company, SHORYOKUKA_CASE, "要領8", 9)
    assert "印刷されたページ 9／PDF の 9 ページ目" in page9.splitlines()[0]
    assert "補助上限額" in page9 and "1,500 万円" in page9  # 要領8 p.9（SPEC 5.1）
    excel = load(company.texts(SHORYOKUKA_CASE) / "Excelその3" / "ページの対応.json")
    assert excel["種類"] == "Excel" and excel["ページ数"] >= 4  # 別紙1〜4 を含むシートごと
    schedule = (company.texts(SHORYOKUKA_CASE) / "スケジュール" / "本文.txt").read_text(encoding="utf-8")
    assert "第8回" in schedule and "2026年10月16日" in schedule

    # 会社のフォルダの外（プラグインの写し・HOME・一時の場所・今いるフォルダ）には何も書かない
    assert company.env.outside() == before_outside


def test_same_round_and_printed_page_offsets(tmp_path, site) -> None:
    """持続化 第20回は、回が同じなので直近回とは示さない。印刷された番号のずれは DESIGN 9章の注のとおり。"""
    company = Company(tmp_path)
    data = local_list(site, JIZOKUKA_LIST)
    r = company.fetch(data)
    text = out(r)
    assert r.returncode == 0, text
    assert "直近回" not in text
    assert "「申請システム操作手引き」は、第19回の資料に基づいています" in text
    listed = company.doc_list(JIZOKUKA_CASE)
    assert listed["直近回の資料に基づく"] is False
    validate_doc_list(listed["資料"])
    files = official_files(company, JIZOKUKA_CASE)
    assert len(files) == len(data["資料"])
    for doc in data["資料"]:
        name = Path(urlsplit(doc["URL"]).path).name
        assert sha256(files[file_stem(doc)]) == sha256(DOWNLOADS / "jizokuka_20" / name)
    offsets = {e["id"]: e.get("ページのずれ") for e in listed["資料"]}
    for doc_id, offset in JIZOKUKA_OFFSETS.items():
        assert offsets[doc_id] == offset, doc_id
    check_text_dirs(company, JIZOKUKA_CASE, data["資料"])
    # 印刷された番号で引くと、そのページの中身がある
    assert "事業概要" in page_file(company, JIZOKUKA_CASE, "要領20", 3)  # PDF の4ページ目
    assert "Q3-16" in page_file(company, JIZOKUKA_CASE, "Q&A20", 6)  # PDF の11ページ目
    assert "印刷されたページ 6／PDF の 11 ページ目" in page_file(company, JIZOKUKA_CASE, "Q&A20", 6)


def test_rerun_keeps_documents(tmp_path, site) -> None:
    """もう一度動かすと、同じ中身の資料はそのまま。取得日も変えない。"""
    company = Company(tmp_path)
    data = local_list(site, SHORYOKUKA_LIST)
    assert company.fetch(data, "--case-round", "第9回").returncode == 0
    first = hr.snapshot(company.case(SHORYOKUKA_CASE))
    settings = company.folder / ".hojokin" / "設定.json"
    settings.write_text(json.dumps({"今日の日付": "2026-11-05"}), encoding="utf-8")
    r = company.fetch(data, "--case-round", "第9回")
    assert r.returncode == 0, out(r)
    assert "前と同じ" in out(r)
    assert hr.snapshot(company.case(SHORYOKUKA_CASE)) == first
    assert {e["取得日"] for e in company.doc_list(SHORYOKUKA_CASE)["資料"]} == {TODAY}


def test_changed_document_is_not_overwritten(tmp_path, site) -> None:
    """前に取ったものと中身が違えば、上書きせずに知らせる（改訂の扱いは F7）。"""
    company = Company(tmp_path)
    data = local_list(site, SHORYOKUKA_LIST)
    assert company.fetch(data, "--case-round", "第9回").returncode == 0
    path = official_files(company, SHORYOKUKA_CASE)["公募要領_第8回"]
    before = sha256(path)
    guideline = urlsplit(data["資料"][0]["URL"]).path
    site.put(guideline, site.routes[guideline][0] + b"\n% revised\n", "application/pdf")
    r = company.fetch(data, "--case-round", "第9回")
    text = out(r)
    assert r.returncode == 1, text
    assert "前と中身が違う" in text and "改訂" in text
    assert "まだそろっていない" in text
    assert sha256(path) == before
    assert company.doc_list(SHORYOKUKA_CASE)["資料"][0]["ハッシュ"] == before


def test_missing_documents_are_reported(tmp_path, site) -> None:
    """ない場所と、PDF のはずがウェブページだった資料は置かずに、そろっていないと示す。取れたものは置く。"""
    company = Company(tmp_path)
    site.put("/doc/moved.pdf", b"<!DOCTYPE html><html><body>moved</body></html>", "text/html")
    data = {
        "制度": {"名前": "試しの補助金", "略称": "試し", "公募回": "第3回"},
        "資料": [
            {"id": "要領3", "名前": "公募要領", "公募回": "第3回", "URL": site.base + "/doc/missing.pdf"},
            {"id": "手引き3", "名前": "手引き", "公募回": "第3回", "URL": site.base + "/doc/moved.pdf"},
            {"id": "状況報告", "名前": "状況報告の手引き", "公募回": "記載なし",
             "URL": site.local("https://shoryokuka.smrj.go.jp/assets/pdf/status_report_manual_ippan.pdf")},
        ],
    }
    r = company.fetch(data)
    text = out(r)
    assert r.returncode == 1, text
    assert "まだそろっていない" in text
    assert "HTTP 404" in text
    assert "ウェブページが返ってきました" in text
    files = official_files(company, "2026_試し第3回")
    assert set(files) == {"状況報告の手引き_記載なし"}
    listed = company.doc_list("2026_試し第3回")
    assert [e["id"] for e in listed["資料"]] == ["状況報告"]


def test_refuses_outside_company_folder(tmp_path, site) -> None:
    """会社のフォルダでなければ、何も書かずに断る。"""
    company = Company(tmp_path)
    plain = tmp_path / "ただのフォルダ"
    plain.mkdir()
    r = company.fetch(local_list(site, SHORYOKUKA_LIST), folder=plain)
    assert r.returncode == 2
    assert "会社のフォルダではありません" in out(r)
    assert list(plain.iterdir()) == []


@pytest.mark.parametrize("data", [
    {"資料": []},
    {"制度": {"名前": "x", "公募回": "第1回"}, "資料": [{"id": "a/b", "名前": "x", "公募回": "第1回", "URL": "https://a.jp/x.pdf"}]},
    {"制度": {"名前": "x", "公募回": "第1回"}, "資料": [{"id": "a", "名前": "x", "公募回": "第1回", "URL": "file:///etc/passwd"}]},
])
def test_refuses_bad_list(tmp_path, data) -> None:
    """一覧の形が違えば、何も書かずに断る。"""
    company = Company(tmp_path)
    before = hr.snapshot(company.folder)
    r = company.fetch(data)
    assert r.returncode == 2, out(r)
    assert "取る資料の一覧を読めませんでした" in out(r)
    assert hr.snapshot(company.folder) == before


def test_stage_folders_from_seido_data(tmp_path) -> None:
    """段階のフォルダは、制度データの手続きの段階から作れる。中は「申請書」と「添付する書類」。"""
    company = tmp_path / "会社"
    company.mkdir()
    case_folder.ensure_case(company, SHORYOKUKA_CASE)
    folders = case_folder.stage_folders(load(ANSWER)["手続きの段階"])
    assert folders[0] == "1_申請"
    made = case_folder.ensure_stage_folders(company, SHORYOKUKA_CASE, folders, only=["1_申請"])
    base = company / "案件" / SHORYOKUKA_CASE
    assert (base / "1_申請" / "申請書").is_dir() and (base / "1_申請" / "添付する書類").is_dir()
    assert f"案件/{SHORYOKUKA_CASE}/1_申請/申請書" in made
    assert sorted(p.name for p in base.iterdir()) == ["1_申請", "公式資料"]
    with pytest.raises(case_folder.CaseError):
        case_folder.ensure_stage_folders(company, SHORYOKUKA_CASE, ["../外"])


# ---- 公式サイトから実際に取る（通信あり） ----


@pytest.mark.slow
@pytest.mark.parametrize("source,round_arg,case", [
    (SHORYOKUKA_LIST, ["--case-round", "第9回"], SHORYOKUKA_CASE),
    (JIZOKUKA_LIST, [], JIZOKUKA_CASE),
])
def test_fetch_from_official_site(tmp_path, source, round_arg, case) -> None:
    """公式サイトから資料を取り、書類フォルダを作る。資料がすべてそろう。"""
    company = Company(tmp_path)
    data = load(source)
    r = company.fetch(data, *round_arg)
    text = out(r)
    assert r.returncode == 0, f"公式サイトから取れませんでした（通信できる所で流してください）\n{text}"
    assert "資料はすべてそろいました" in text
    files = official_files(company, case)
    assert set(files) == {file_stem(d) for d in data["資料"]}
    magic = {".pdf": b"%PDF-", ".docx": b"PK\x03\x04", ".xlsx": b"PK\x03\x04"}
    for path in files.values():
        if path.suffix in magic:
            assert path.read_bytes()[:5].startswith(magic[path.suffix]), path.name
        assert path.stat().st_mode & 0o222 == 0
    listed = company.doc_list(case)
    validate_doc_list(listed["資料"])
    check_text_dirs(company, case, data["資料"])
    if round_arg:
        assert LATEST_NOTICE in text and listed["直近回の資料に基づく"] is True
    # 公式サイトの資料が、制度データの正解を作った日（2026-11-03）から改訂されていたら知らせる（落とさない）
    known = {d["id"]: d["ハッシュ"] for d in load(ANSWER)["資料"]} if source == SHORYOKUKA_LIST else {}
    changed = [e["id"] for e in listed["資料"] if e["id"] in known and e["ハッシュ"] != known[e["id"]]]
    if changed:
        warnings.warn(f"公式サイトの資料が改訂されています（{', '.join(changed)}）。制度データの正解を見直してください")
