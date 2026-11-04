"""改訂・新しい公募回の資料で、変わったページだけを読み直し、制度データの差を出す道具（SPEC F7、DESIGN 9.2、TASKS M14）。

確かめること
- 変わったページ：頁の番号のずれ（同じ文が次のページに送られた）と、目次の頁の番号だけの違いは、変わっていないにする。
  文が変わったページと、足した文のページだけを出す
- 引き継ぎ：章の読み取りの出典を、前の回の資料から今の資料に付け替える（頁がずれたら新しい頁）。
  今の資料の文のとおりの値は確認済みのまま、文が変わった値だけを要確認にして、読み直す値の一覧に出す
- 読み直した件の差し替え：件の名前で同じ件だけを差し替え、ほかの件は残す。名前が変わった件は、消す件で前の件を消す
- 制度データの差：値が変わった・足した・消えた項目を、前と後の値と出典の頁で出す。出典の頁のない変わった項目があれば
  終了コード 1。変わらなければ「変更なし」。自社の申請で影響するところ（期限の台帳の出来事、会社の作った申請書の前の値）を出す
- 実物：downloads/ の公募要領の第8回と第9回で、頁のずれを除いて、変わったページだけが出る（なければ飛ばす。公式資料の文はリポに入れない）

テストの公募要領は、テストのためだけに作った架空の文（言い回し・数は、公式の公募要領と別のもの）。
道具は、Claude が Bash で動かすのと同じく /usr/bin/python3 で、プラグインの写しから動かす（tests/company_tool.py）。
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest

REPO_ROOT = hr.REPO_ROOT
TOOL = Path("skills") / "junbi" / "scripts" / "kaitei.py"
CASE = "2026_テスト補助金（一般型）第2回"
CHAPTER = "1 事業の期間と経費"
READING = Path("記録") / "制度データ" / "読み取り" / CASE / f"{CHAPTER}_1回目.json"
YORYO8 = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "application_guidelines_ippan_08.pdf"
YORYO9 = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "application_guidelines_ippan_09.pdf"

# ---- 架空の公募要領の2つの回（テストのためだけに作った文） ----

OLD_PAGES = [
    "テスト用 作業改善設備補助金\n第１回 公募要領\n",
    "目次\n１．事業の期間 ・・・・・・・・ 2\n２．対象にならない経費 ・・・・・・ 3\n- 1 -\n",
    "１．事業の期間\n事業を行う期間は、交付決定の日から 12 か月までとする。\n申請の受付は、電子申請だけで行う。\n"
    "郵送の申請は受け付けない。\n- 2 -\n",
    "２．対象にならない経費\n◼ 中古の品の購入費\n◼ 事務机などの汎用の品\n- 3 -\n",
]
NEW_PAGES = [
    "テスト用 作業改善設備補助金\n第２回 公募要領\n",
    "目次\n１．事業の期間 ・・・・・・・・ 2\n２．対象にならない経費 ・・・・・・ 4\n- 1 -\n",
    # 事業の期間を 10 か月に変え、注意書きを1行足した。最後の行は次のページに送られた（中身は同じ）
    "１．事業の期間\n事業を行う期間は、交付決定の日から 10 か月までとする。\n申請の受付は、電子申請だけで行う。\n"
    "※ 申請の前に、事業者の登録を済ませること。\n- 2 -\n",
    "郵送の申請は受け付けない。\n- 3 -\n",
    "２．対象にならない経費\n◼ 中古の品の購入費\n◼ 事務机などの汎用の品\n- 4 -\n",
]

BUILD_CODE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib import doc_text
spec = json.loads(sys.stdin.read())
pages = spec["pages"]
doc_text.pdf_pages = lambda path: pages
index = doc_text.write_text(Path(spec["source"]), Path(spec["out"]), spec["doc"], spec["source"])
print(json.dumps({"ずれ": index["ページのずれ"], "ページ数": index["ページ数"]}, ensure_ascii=False))
"""


def sv(value, doc, page, sentence, state="確認済み"):
    source = {"資料": doc}
    if page is not None:
        source["ページ"] = page
    return {"値": value, "出典": [source], "根拠の文": sentence, "状態": state}


def chapter() -> dict:
    """前の回（要領1）で読んだ章。期間の値は p.2、同じページの文の値と、p.3 の経費の値。"""
    return {
        "読み取り": {"章": CHAPTER, "読んだページ": [{"資料": "要領1", "ページ": 2, "終わりのページ": 3}], "回目": 1},
        "制度データ": {
            "数値でない要件": [
                {"名前": "電子申請で申請する", "種類": "満たすこと", "区分": "申請の要件",
                 "内容": sv("申請の受付は電子申請だけ", "要領1", 2, "申請の受付は、電子申請だけで行う。")},
                {"名前": "郵送の申請はできない", "種類": "満たすこと", "区分": "申請の要件",
                 "内容": sv("郵送の申請は受け付けない", "要領1", 2, "郵送の申請は受け付けない。")},
                {"名前": "事業の期間", "種類": "満たすこと", "区分": "事業の要件",
                 "内容": sv("交付決定の日から12か月まで", "要領1", 2, "事業を行う期間は、交付決定の日から 12 か月までとする。")},
            ],
        },
    }


class Company:
    def __init__(self, tmp_path: Path) -> None:
        self.env = ct.Env(tmp_path)
        shutil.copytree(REPO_ROOT / "schema", self.env.plugin / "schema")
        self.folder = self.env.folder("架空 製作所")
        (self.folder / ".hojokin").mkdir()
        self.work = tmp_path / "作業"
        self.work.mkdir()
        self.texts = self.folder / "記録" / "資料の本文" / CASE

    def add_doc(self, doc_id: str, rnd: str, pages: list) -> None:
        pdf = self.work / f"{doc_id}.pdf"
        pdf.write_bytes(b"")
        spec = {"source": str(pdf), "out": str(self.texts / doc_id), "pages": pages,
                "doc": {"id": doc_id, "名前": "テスト用の公募要領", "公募回": rnd, "ハッシュ": ""}}
        r = subprocess.run([hr.real_python(), "-I", "-B", "-c", BUILD_CODE, str(self.env.plugin)],
                           input=json.dumps(spec, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=120)
        assert r.returncode == 0, r.stderr.decode("utf-8")

    def setup_rounds(self) -> None:
        self.add_doc("要領1", "第1回", OLD_PAGES)
        self.add_doc("要領2", "第2回", NEW_PAGES)
        listed = {
            "案件": CASE,
            "制度": {"名前": "テスト用 作業改善設備補助金", "略称": "テスト", "枠": "一般型", "種類": "補助金", "公募回": "第2回"},
            "案件の回": "第2回",
            "資料": [{"id": "要領2", "名前": "テスト用の公募要領", "公募回": "第2回"}],
            "前の回の資料": [{"id": "要領1", "名前": "テスト用の公募要領", "公募回": "第1回"}],
        }
        (self.texts / "資料の一覧.json").write_text(json.dumps(listed, ensure_ascii=False), encoding="utf-8")
        path = self.folder / READING
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(chapter(), ensure_ascii=False), encoding="utf-8")

    def run(self, *args: str, data=None) -> subprocess.CompletedProcess:
        env = {"PATH": self.env.path, "HOME": str(self.env.home), "TMPDIR": str(self.env.tmp)}
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        return subprocess.run([hr.real_python(), "-B", str(self.env.plugin / TOOL), "--folder", str(self.folder), *args],
                              input=payload, env=env, cwd=self.env.cwd, capture_output=True, timeout=120)

    def reading(self) -> dict:
        return json.loads((self.folder / READING).read_text(encoding="utf-8"))


def out(r: subprocess.CompletedProcess, code: int) -> str:
    text = r.stdout.decode("utf-8")
    assert r.returncode == code, (r.returncode, text, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return text


def items(data: dict) -> dict:
    return {x["名前"]: x for x in data["制度データ"]["数値でない要件"]}


@pytest.fixture
def company(tmp_path) -> Company:
    c = Company(tmp_path)
    c.setup_rounds()
    return c


def test_page_shift_and_toc_are_not_changes(company) -> None:
    text = out(company.run("--pages"), 0)
    line = next(x for x in text.splitlines() if x.startswith("- 要領1 → 要領2"))
    # 変わったのは p.2（期間の数と、足した注意書き）だけ。目次の頁の番号（3 → 4）と、p.3 に送られた行は変わっていない
    assert "今の資料の p.2" in line and "p.3" not in line and "p.4" not in line, line
    assert "目次" not in text.split("変わったページに当たる章")[0].split(line)[1].split("\n- ")[0]
    assert f"- {CHAPTER}：p.2" in text


def test_carry_repoints_and_lists_only_changed_values(company) -> None:
    before = (company.folder / READING).read_bytes()
    text = out(company.run("--carry"), 1)
    data = company.reading()
    got = items(data)
    # 送られた行の値は、新しい頁（p.3）に付け替えて確認済みのまま
    assert got["郵送の申請はできない"]["内容"]["出典"] == [{"資料": "要領2", "ページ": 3}]
    assert got["郵送の申請はできない"]["内容"]["状態"] == "確認済み"
    assert got["電子申請で申請する"]["内容"]["出典"] == [{"資料": "要領2", "ページ": 2}]
    assert got["電子申請で申請する"]["内容"]["状態"] == "確認済み"
    # 文が変わった値だけが要確認になり、読み直す値に出る
    assert got["事業の期間"]["内容"]["状態"] == "要確認"
    assert "数値でない要件「事業の期間」の内容" in text
    assert "郵送の申請はできない" not in text.split("読み直すもの")[1]
    assert all(s["資料"] == "要領2" for s in data["読み取り"]["読んだページ"])
    assert before != (company.folder / READING).read_bytes()


def test_apply_replaces_only_named_items(company) -> None:
    out(company.run("--carry"), 1)
    fixed = {
        "読み取り": {"章": CHAPTER, "読んだページ": [{"資料": "要領2", "ページ": 2}], "回目": 1},
        "制度データ": {"数値でない要件": [
            {"名前": "事業の期間", "種類": "満たすこと", "区分": "事業の要件",
             "内容": sv("交付決定の日から10か月まで", "要領2", 2, "事業を行う期間は、交付決定の日から 10 か月までとする。")},
            {"名前": "事業者の登録", "種類": "満たすこと", "区分": "申請の要件",
             "内容": sv("申請の前に事業者の登録を済ませる", "要領2", 2, "申請の前に、事業者の登録を済ませること。")},
        ]},
        "消す件": {"数値でない要件": ["郵送の申請はできない"]},
        "メモ": ["事業の期間が 12か月 → 10か月"],
    }
    text = out(company.run("--apply", "-", data=fixed), 0)
    got = items(company.reading())
    assert set(got) == {"電子申請で申請する", "事業の期間", "事業者の登録"}
    assert got["事業の期間"]["内容"]["状態"] == "確認済み"
    assert got["電子申請で申請する"]["内容"]["状態"] == "確認済み"  # 渡さなかった件は残る
    assert "足した件：数値でない要件「事業者の登録」" in text
    assert "消した件：数値でない要件「郵送の申請はできない」" in text


def test_apply_needs_the_previous_chapter(company) -> None:
    bad = {"読み取り": {"章": "9 ない章", "読んだページ": [], "回目": 1}, "制度データ": {"数値でない要件": []}}
    before = (company.folder / READING).read_bytes()
    text = out(company.run("--apply", "-", data=bad), 2)
    assert "前の結果がありません" in text
    assert before == (company.folder / READING).read_bytes()


# ---- 制度データの差 ----


def full(rnd: str, doc: str, months: int, page: int, extra: list = None) -> dict:
    steps = [{"id": "実施", "名前": "補助事業の実施", "期限": sv(
        {"種類": "出来事からの期間", "出来事": "交付決定日", "期間": {"数": months, "単位": "か月"}}, doc, page,
        f"交付決定の日から {months} か月までとする。")}]
    reqs = [{"名前": "電子申請で申請する", "種類": "満たすこと", "区分": "申請の要件",
             "内容": sv("申請の受付は電子申請だけ", doc, page, "申請の受付は、電子申請だけで行う。")}] + (extra or [])
    return {"スキーマの版": 1,
            "制度": {"名前": "テスト用 作業改善設備補助金", "枠": "一般型", "種類": "補助金", "公募回": rnd},
            "資料": [{"id": doc, "名前": "テスト用の公募要領", "公募回": rnd}],
            "手続きの段階": steps, "数値でない要件": reqs}


def put(company: Company, name: str, data: dict) -> str:
    rel = f"記録/制度データ/{name}"
    path = company.folder / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return rel


def test_diff_lists_changes_with_pages_and_impact(company) -> None:
    put(company, "テスト_第1回.json", full("第1回", "要領1", 12, 2))
    added = {"名前": "事業者の登録", "種類": "満たすこと", "区分": "申請の要件",
             "内容": sv("申請の前に事業者の登録を済ませる", "要領2", 2, "申請の前に、事業者の登録を済ませること。")}
    put(company, "テスト_第2回.json", full("第2回", "要領2", 10, 2, [added]))
    ledger = {"出来事": [{"案件": CASE, "名前": "交付決定日", "日付": "2027-05-10", "状態": "確定", "出典": "社長の答え"}]}
    (company.folder / "記録" / "期限の台帳.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    text = out(company.run("--diff"), 0)
    assert "変わった項目：2件" in text and "出典のページのない変わった項目：0件" in text
    assert "値が変わった：手続きの段階「補助事業の実施」の期限" in text
    assert "前：交付決定日から12か月　〔出典：テスト用の公募要領（第1回） p.2〕" in text
    assert "後：交付決定日から10か月　〔出典：テスト用の公募要領（第2回） p.2〕" in text
    assert "足した：数値でない要件「事業者の登録」の内容" in text
    assert "電子申請で申請する" not in text  # 値が同じ項目は、出典が付け替わっても差に出さない
    assert "出来事「交付決定日」（2027-05-10）から決まる期限" in text
    data = json.loads(out(company.run("--diff", "--json"), 0))
    assert [c["種類"] for c in data["変わった項目"]] == ["値が変わった", "足した"]
    assert data["変わった項目"][0]["後"]["出典"] == [{"資料": "要領2", "ページ": 2}]


def test_diff_without_page_is_exit_1(company) -> None:
    put(company, "テスト_第1回.json", full("第1回", "要領1", 12, 2))
    new = full("第2回", "要領2", 10, 2)
    del new["手続きの段階"][0]["期限"]["出典"][0]["ページ"]  # PDF の出典に頁がない
    put(company, "テスト_第2回.json", new)
    text = out(company.run("--diff"), 1)
    assert "出典のページのない変わった項目：1件" in text and "← 出典のページがありません" in text


def test_diff_no_change(company) -> None:
    put(company, "テスト_第1回.json", full("第1回", "要領1", 12, 2))
    same = copy.deepcopy(full("第2回", "要領2", 12, 2))
    put(company, "テスト_第2回.json", same)
    text = out(company.run("--diff"), 0)
    assert "変更なし" in text


# ---- 実物（downloads/ の第8回と第9回の公募要領） ----

REAL_CODE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib import doc_text, kaitei
def lines(path, doc_id):
    out = kaitei.DocLines(doc_id, "PDF")
    for n, text in enumerate(doc_text.pdf_pages(Path(path)), 1):
        out.page_list.append(n)
        for raw in text.splitlines():
            line = kaitei.norm_line(raw)
            if line:
                out.lines.append(line); out.raw.append(raw); out.pages.append(n)
    return out
d = kaitei.compare_docs(lines(sys.argv[2], "要領8"), lines(sys.argv[3], "要領9"))
print(json.dumps({"changed": d.changed_new_pages, "map": d.page_map, "blocks": len(d.changes),
                  "pages": len(set(p for p in lines(sys.argv[3], "要領9").pages))}))
"""


@pytest.mark.slow
@pytest.mark.skipif(not (YORYO8.is_file() and YORYO9.is_file()), reason="downloads/ に第8回と第9回の公募要領がない")
def test_real_guidelines_8_to_9() -> None:
    r = subprocess.run([hr.real_python(), "-I", "-B", "-c", REAL_CODE, str(REPO_ROOT), str(YORYO8), str(YORYO9)],
                       capture_output=True, timeout=300)
    assert r.returncode == 0, r.stderr.decode("utf-8")
    got = json.loads(r.stdout.decode("utf-8"))
    # 第9回は改訂履歴のページがなくなり、後ろのページが1つずつ前にずれる。ずれただけのページは変わったに数えない
    assert got["map"]["30"] == 29
    assert 0 < len(got["changed"]) <= got["pages"] // 2
    assert got["blocks"] < 40
