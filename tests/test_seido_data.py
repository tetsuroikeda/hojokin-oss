"""章ごとの読み取りを1つの制度データにまとめ、確かめ、段階のフォルダを作る道具（SPEC F3、DESIGN 4.5・9章・9.2、TASKS M2c）。

確かめること
- まとめる（--merge）
  - 章ごとの読み取り（裏取りの道具 urakadori.py に通して置いたもの）のうち1回目だけを、章の順（読んだページの順）にまとめる。
    2回目は使わず、使わなかったことを結果に書く（2回の読み取りの突き合わせは B25）
  - 「スキーマの版」「制度」「資料」は案件の資料の一覧から入れる。制度データの公募回は、資料の回
    （直近回の資料に基づくときは、その回）。置き場所は `記録/制度データ/<略称>_<公募回>.json`
  - できた制度データが、制度データのスキーマを通る（jsonschema でも確かめる）
  - どの章も読んでいない項目は推測で埋めない（空、または「読み取れない」）。「読み取れなかった項目」に並べる
  - 2つの章が同じ欄を違う値で読んだら、前の章の値を使い、そのことを結果に書く
  - 何度まとめても同じ中身になる（裏取りの注記が増えない。外れた値は要確認のまま）
  - 形が合わなければ（補助額がどの章にもない など）、何も書かない
- 確かめる（--check。--merge の後にも出す）
  - 重要な項目（締切・補助上限・補助率・数値の要件・必須書類・補助の対象にならない経費）が、1件以上あり、
    どの値も「値」か「要確認」で埋まっているか。読み取れない値、1件もない項目は、足りないとして終了コード 1
  - 確認済み（資料で食い違いも）なのに値が空のもの（""・空白だけ・[]・{}・中がどれも空）も、埋まっていないとして終了コード 1
  - 出典のない値の数（出典がない、根拠の文がない、出典の資料が「資料」にない）。1つでもあれば終了コード 1
  - 確かめるだけでは、制度データを書き換えない
- 段階のフォルダ（DESIGN 4.5）
  - まとめたときは、いちばん前の段階（1_申請）だけを作る。中は「申請書」と「添付する書類」
  - --stage-folders --stage で、手続きの段階にある名前の段階を作る。ない名前なら何も作らない
  - 段階のフォルダの名前が、段階の順に 1 から数えた「1_申請」「2_交付申請」…でなければ（申請の段階が抜けた読み取りなど）、どれも作らない（仮）
- 道具の動き：会社のフォルダでなければ何もしない。読み取りの結果がなければ何もしない。__pycache__ を書かない

テストの公募要領は、テストのためだけに作った架空の文（公式の公募要領の文は使わない）。制度データの正解（testdata/正解/）は読まない。
道具は、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす
（lib/seido_data.py は lib/urakadori.py → lib/doc_text.py → 同梱の pypdf を読み込むので、テストの Python の中では読み込まない）。
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
from jsonschema import Draft202012Validator

REPO_ROOT = hr.REPO_ROOT
TOOL = Path("skills") / "junbi" / "scripts" / "seido_data.py"
URAKADORI = Path("skills") / "junbi" / "scripts" / "urakadori.py"
SCHEMA = json.loads((REPO_ROOT / "schema" / "制度データ.schema.json").read_text(encoding="utf-8"))
CASE = "2026_テスト補助金（一般型）第4回"
DOC = "要領T"
DATA_REL = Path("記録") / "制度データ" / "テスト補助金_第3回.json"
READING_REL = Path("記録") / "制度データ" / "読み取り" / CASE

# ---- 小さな架空の公募要領（テストのためだけに作った文） ----

PAGES = [
    "テスト用 作業改善補助金（一般型）\n第３回 公募要領\n架空の資料（テストのためだけに作ったもの）\n",
    "１．補助の上限と割合 \n従業員 10 人まで 上限 500 万円（特例 700 万円） \n従業員 11 人以上 上限 1,000 万円 \n"
    "補助の割合 一般の事業者 1/2 \n労働時間あたりの出来高を、年平均で 3.0％以上 伸ばすこと。 \n"
    "出来高は、売上高から材料費を引いたものとする。 \n支援を受けた場合は「計画作成の支援者」の欄に名前を書く。 \n- 1 -\n",
    "２．対象にならない経費と書類 \n◼ 中古の機械の購入費 \n○ 委託費は、対象となる経費の合計の 2 分の 1 までとする。 \n"
    "申請の締切 ：2027 年 3 月 12 日（金）16:00 \n必ず出す書類：決算書 直近 2 期分、登記簿の写し（発行から 3 か月以内） \n- 2 -\n",
    "３．審査と手続き \n審査は書面で行う。 \n審査の観点：設備の効果、計画の確かさ。 \n"
    "交付の申請は、採択の発表から 30 日以内に行う。 \n実績の報告は、事業の完了から 20 日以内に行う。 \n- 3 -\n",
]

DOC_LIST = {
    "案件": CASE,
    "制度": {"名前": "テスト用 作業改善補助金", "略称": "テスト補助金", "枠": "一般型", "種類": "補助金", "公募回": "第4回"},
    "案件の回": "第4回",
    "直近回の資料に基づく": True,
    "案内": ["第4回の資料はまだ公表されていないため、直近回である第3回の資料に基づいています。"],
    "資料": [{"id": DOC, "名前": "公募要領", "公募回": "第3回", "URL": "https://example.invalid/test/koubo_03.pdf",
              "取得日": "2026-11-04", "ハッシュ": "0" * 64, "ページのずれ": 1}],
    "置き場所": {},
}


def sv(value, page, sentence, state="確認済み") -> dict:
    return {"値": value, "出典": [{"資料": DOC, "ページ": page}], "根拠の文": sentence, "状態": state}


def unread(reason: str) -> dict:
    return {"値": None, "状態": "読み取れない", "理由": reason}


def after(event: str, number: int, unit: str) -> dict:
    return {"種類": "出来事からの期間", "出来事": event, "期間": {"数": number, "単位": unit}}


CAP_10 = "従業員 10 人まで 上限 500 万円（特例 700 万円）"
DEADLINE = "申請の締切 ：2027 年 3 月 12 日（金）16:00"


def chapter_a() -> dict:
    return {
        "読み取り": {"章": "1 補助の上限と割合", "読んだページ": [{"資料": DOC, "ページ": 1}], "回目": 1},
        "制度データ": {
            "補助額": [
                {"区分": "従業員10人まで", "上限": sv(5000000, 1, CAP_10), "補助率": sv("1/2", 1, "補助の割合 一般の事業者 1/2"),
                 "特例": [{"名前": "特例", "種類": "上限の置き換え", "値": sv(7000000, 1, CAP_10)}]},
                {"区分": "従業員11人以上", "上限": sv(10000000, 1, "従業員 11 人以上 上限 1,000 万円"),
                 "補助率": sv("1/2", 1, "補助の割合 一般の事業者 1/2")},
            ],
            "数値の要件": [{
                "名前": "労働時間あたりの出来高",
                "基準": sv("年平均で3.0%以上伸ばす", 1, "労働時間あたりの出来高を、年平均で 3.0％以上 伸ばすこと。"),
                "元の数字の決め方": sv("出来高は、売上高から材料費を引いたもの", 1, "出来高は、売上高から材料費を引いたものとする。"),
            }],
            "支援者の欄": {"欄の名前": sv("計画作成の支援者", 1, "支援を受けた場合は「計画作成の支援者」の欄に名前を書く。")},
        },
    }


def chapter_b() -> dict:
    return {
        "読み取り": {"章": "2 対象にならない経費と書類", "読んだページ": [{"資料": DOC, "ページ": 2}], "回目": 1},
        "制度データ": {
            "補助の対象にならない経費": [
                {"名前": "中古の機械の購入費", "種類": "対象外", "内容": sv("中古の機械の購入費", 2, "中古の機械の購入費")},
                {"名前": "委託費の上限", "種類": "上限", "経費の区分": "委託費",
                 "内容": sv("委託費は対象となる経費の合計の2分の1まで", 2, "委託費は、対象となる経費の合計の 2 分の 1 までとする。"),
                 "上限": sv({"何の上限": "補助対象経費", "割合": "1/2", "基準": "対象となる経費の合計"}, 2,
                          "委託費は、対象となる経費の合計の 2 分の 1 までとする。")},
            ],
            "決まった期日": [{"名前": "申請の締切", "日時": sv({"日時": "2027-03-12T16:00+09:00"}, 2, DEADLINE)}],
            "書類": [
                {"名前": "決算書", "区分": "必須", "発行元": "自社", "手続き": ["申請"],
                 "内容": sv("決算書 直近2期分", 2, "必ず出す書類：決算書 直近 2 期分"), "期数": sv("直近2期分", 2, "決算書 直近 2 期分")},
                {"名前": "登記簿の写し", "区分": "必須", "発行元": "役所", "手続き": ["申請"],
                 "内容": sv("登記簿の写し", 2, "登記簿の写し（発行から 3 か月以内）"),
                 "有効期限": sv("発行から3か月以内", 2, "登記簿の写し（発行から 3 か月以内）")},
            ],
        },
    }


def chapter_c() -> dict:
    return {
        "読み取り": {"章": "3 審査と手続き", "読んだページ": [{"資料": DOC, "ページ": 3}, {"資料": DOC, "ページ": 2}], "回目": 1},
        "制度データ": {
            "審査の段階": [{"名前": "書面審査", "条件": sv("書面で行う", 3, "審査は書面で行う。")}],
            "審査項目": [{"名前": "審査の観点", "観点": sv(["設備の効果", "計画の確かさ"], 3, "審査の観点：設備の効果、計画の確かさ。")}],
            "手続きの段階": [
                {"id": "申請", "順番": 1, "名前": "申請", "フォルダ": "1_申請",
                 "期限": sv({"種類": "決まった日付", "日時": "2027-03-12T16:00+09:00"}, 2, DEADLINE)},
                {"id": "交付申請", "順番": 2, "名前": "交付申請", "フォルダ": "2_交付申請",
                 "期限": sv(after("採択の発表", 30, "日"), 3, "交付の申請は、採択の発表から 30 日以内に行う。")},
                {"id": "実績報告", "順番": 3, "名前": "実績報告", "フォルダ": "3_実績報告",
                 "期限": sv(after("事業の完了", 20, "日"), 3, "実績の報告は、事業の完了から 20 日以内に行う。")},
            ],
        },
    }


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


class Company:
    def __init__(self, tmp_path: Path) -> None:
        self.env = ct.Env(tmp_path)
        # 道具はプラグインの schema/ を読む（tests/company_tool.py の写しは lib/ と skills/ だけ）
        shutil.copytree(REPO_ROOT / "schema", self.env.plugin / "schema")
        self.folder = self.env.folder("架空 工業")
        (self.folder / ".hojokin").mkdir()
        (self.folder / "案件" / CASE / "公式資料").mkdir(parents=True)
        self.work = tmp_path / "作業"
        self.work.mkdir()

    @property
    def texts(self) -> Path:
        return self.folder / "記録" / "資料の本文" / CASE

    def add_docs(self) -> None:
        pdf = self.work / "要領T.pdf"
        pdf.write_bytes(b"")
        spec = {"source": str(pdf), "out": str(self.texts / DOC), "pages": PAGES,
                "doc": {"id": DOC, "名前": "公募要領", "公募回": "第3回", "ハッシュ": "0" * 64}}
        r = subprocess.run([hr.real_python(), "-I", "-B", "-c", BUILD_CODE, str(self.env.plugin)],
                           input=json.dumps(spec, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=300)
        assert r.returncode == 0, r.stderr.decode("utf-8")
        assert json.loads(r.stdout.decode("utf-8")) == {"ずれ": 1, "ページ数": 4}
        (self.texts / "資料の一覧.json").write_text(json.dumps(DOC_LIST, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run(self, tool: Path, args: list, payload: bytes = None) -> subprocess.CompletedProcess:
        env = {"PATH": self.env.path, "HOME": str(self.env.home), "TMPDIR": str(self.env.tmp)}
        return subprocess.run([hr.real_python(), "-B", str(self.env.plugin / tool), *args],
                              input=payload, env=env, cwd=self.env.cwd, capture_output=True, timeout=120)

    def read(self, chapter: dict, code: int = 0) -> str:
        """章の読み取りを、Claude が渡すのと同じく、裏取りの道具に標準入力で通す。"""
        r = self._run(URAKADORI, ["--folder", str(self.folder), "--input", "-"],
                      json.dumps(chapter, ensure_ascii=False).encode("utf-8"))
        return check_code(r, code)

    def tool(self, *args: str, folder: Path = None) -> subprocess.CompletedProcess:
        return self._run(TOOL, ["--folder", str(folder or self.folder), *args])

    def data(self) -> dict:
        return json.loads((self.folder / DATA_REL).read_text(encoding="utf-8"))

    def case_dir(self) -> Path:
        return self.folder / "案件" / CASE


def text(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode("utf-8")


def check_code(r: subprocess.CompletedProcess, code: int) -> str:
    out = text(r)
    assert r.returncode == code, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    return out


@pytest.fixture
def company(tmp_path) -> Company:
    c = Company(tmp_path)
    c.add_docs()
    return c


def read_all(company: Company, b: dict = None) -> None:
    company.read(chapter_a())
    company.read(b if b is not None else chapter_b())
    company.read(chapter_c())


def important_row(out: str, name: str) -> list:
    for line in out.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == name:
            return [int(c) for c in cells[1:]]
    raise AssertionError(f"重要な項目の行がありません：{name}\n{out}")


# ---- まとめる ----


def test_merge_makes_full_data_that_passes_schema(company) -> None:
    read_all(company)
    second = chapter_a()
    second["読み取り"]["回目"] = 2
    second["制度データ"]["補助額"][0]["上限"]["値"] = 6000000  # 2回目は使わない（B25 で突き合わせる）
    company.read(second, code=1)
    out = check_code(company.tool("--merge"), 0)

    data = company.data()
    assert not list(Draft202012Validator(SCHEMA).iter_errors(data))
    # 制度・資料は資料の一覧から。公募回は資料の回（直近回の資料に基づく）
    assert data["スキーマの版"] == 1
    assert data["制度"] == {"名前": "テスト用 作業改善補助金", "枠": "一般型", "種類": "補助金", "公募回": "第3回"}
    assert data["資料"] == DOC_LIST["資料"]
    assert "制度データの公募回：第3回" in out and f"置き場所：{DATA_REL}" in out
    # 章の順（読んだページの順）につないだ。2回目の値は入っていない
    assert [a["区分"] for a in data["補助額"]] == ["従業員10人まで", "従業員11人以上"]
    assert data["補助額"][0]["上限"]["値"] == 5000000
    assert "1 補助の上限と割合_2回目.json（2回目。" in out
    assert [s["id"] for s in data["手続きの段階"]] == ["申請", "交付申請", "実績報告"]
    assert len(data["書類"]) == 2 and len(data["補助の対象にならない経費"]) == 2
    # どの章も読んでいない項目は、推測で埋めず、読み取れなかった項目に並べる
    assert data["補助の対象になる経費"] == [] and data["様式"] == [] and data["資料どうしの食い違い"] == []
    assert data["加点"]["区分ごとの上限"]["状態"] == "読み取れない" and data["加点"]["項目"] == []
    assert data["申請画面"]["流れ"]["状態"] == "読み取れない" and data["申請画面"]["画面"] == []
    assert data["提出するファイルの決まり"]["形式"]["状態"] == "読み取れない"
    listed = {u["項目"] for u in data["読み取れなかった項目"]}
    assert {"加点", "申請画面", "提出するファイルの決まり", "補助の対象になる経費", "様式", "加点の区分ごとの上限"} <= listed
    assert "資料どうしの食い違い" not in listed
    assert all(u["理由"] for u in data["読み取れなかった項目"])
    # 確かめた結果
    assert "形（スキーマ）：合っています" in out and "出典のない値：0" in out
    for name in ("締切", "補助上限", "補助率", "数値の要件", "必須書類", "補助の対象にならない経費"):
        entries, values, filled, unfilled = important_row(out, name)
        assert entries > 0 and values == filled and unfilled == 0, name
    assert important_row(out, "補助上限") == [2, 3, 3, 0]   # 2区分の上限と、特例の上限
    assert important_row(out, "補助率") == [2, 2, 2, 0]
    assert important_row(out, "必須書類") == [2, 4, 4, 0]   # 内容と、有効期限・期数
    assert "重要な項目はすべて値か「要確認」で埋まり、出典のない値は0件です" in out
    # 段階のフォルダは、いちばん前の段階だけ
    assert sorted(p.name for p in company.case_dir().iterdir()) == ["1_申請", "公式資料"]
    assert sorted(p.name for p in (company.case_dir() / "1_申請").iterdir()) == ["添付する書類", "申請書"]
    assert "段階のフォルダを作りました：1_申請" in out
    assert not list(company.env.plugin.rglob("__pycache__")) and not list(company.folder.rglob("__pycache__"))


def test_merge_is_repeatable_and_keeps_downgraded_values(company) -> None:
    a = chapter_a()
    a["制度データ"]["補助額"][1]["上限"]["値"] = 1000  # 単位をかけていない（根拠の文は「1,000 万円」）
    company.read(a, code=1)
    company.read(chapter_b())
    company.read(chapter_c())
    out = check_code(company.tool("--merge"), 0)  # 要確認は「埋まっている」に数える
    first = (company.folder / DATA_REL).read_bytes()
    cap = company.data()["補助額"][1]["上限"]
    assert cap["状態"] == "要確認" and cap["注記"].count("裏取り：") == 1
    assert "要確認 1" in out and "裏取りで外れた値 1" in out
    out2 = check_code(company.tool("--merge"), 0)
    assert (company.folder / DATA_REL).read_bytes() == first
    assert "段階のフォルダは、もうあります：1_申請" in out2


def test_conflicting_chapters_use_the_first(company) -> None:
    read_all(company)
    other = {"読み取り": {"章": "4 支援者", "読んだページ": [{"資料": DOC, "ページ": 1}], "回目": 1},
             "制度データ": {"支援者の欄": {"欄の名前": sv("支援者", 1, "「計画作成の支援者」の欄")}}}
    company.read(other)
    out = check_code(company.tool("--merge"), 0)
    assert "「支援者の欄」の「欄の名前」を2つ以上の章が違う値で読んでいます" in out and "章「4 支援者」" in out
    assert company.data()["支援者の欄"]["欄の名前"]["値"] == "計画作成の支援者"


def test_unreadable_important_value_is_not_filled(company) -> None:
    b = chapter_b()
    b["制度データ"]["書類"][1]["内容"] = unread("資料のこのページが読めない")
    read_all(company, b)
    out = check_code(company.tool("--merge"), 1)
    assert important_row(out, "必須書類") == [2, 4, 3, 1]
    assert "必須書類の埋まっていない値：書類「登記簿の写し」の内容（読み取れない）" in out
    assert "まだ足りないところがあります" in out
    assert (company.folder / DATA_REL).is_file()  # 制度データは置いた
    assert any(u["項目"] == "書類「登記簿の写し」の内容" and u["理由"] == "資料のこのページが読めない"
               for u in company.data()["読み取れなかった項目"])


def test_empty_confirmed_important_value_is_not_filled(company) -> None:
    """読み取り役が「読み取れない」にせず空の文字を確認済みで返しても、埋まっているに数えない（差し戻し1回目）。"""
    a = chapter_a()
    a["制度データ"]["数値の要件"][0]["基準"]["値"] = ""
    b = chapter_b()
    b["制度データ"]["書類"][1]["内容"]["値"] = ""
    # 裏取りの道具は今、空の文字を照らさずに通す（確認済みのまま。M2b への申し送り）。
    # 道具が要確認にするよう直したら、ここで終了コード 1 になるので、この確かめも見直す
    company.read(a, code=0)
    company.read(b, code=0)
    company.read(chapter_c())
    out = check_code(company.tool("--merge"), 1)
    data = company.data()
    assert data["書類"][1]["内容"]["状態"] == "確認済み" and data["書類"][1]["内容"]["値"] == ""
    assert important_row(out, "必須書類") == [2, 4, 3, 1]
    assert important_row(out, "数値の要件") == [1, 2, 1, 1]   # 基準と、元の数字の決め方
    assert "必須書類の埋まっていない値：書類「登記簿の写し」の内容（値が空）" in out
    assert "数値の要件の埋まっていない値：数値の要件「労働時間あたりの出来高」の基準（値が空）" in out
    assert "まだ足りないところがあります" in out
    assert "重要な項目はすべて値か「要確認」で埋まり" not in out
    assert (company.folder / DATA_REL).is_file()  # 制度データは置いた（足りないところを読み直して、まとめ直す）


@pytest.mark.parametrize("empty", ["", "　 \n", [], {}, {"日時": ""}, [""]])
def test_check_counts_every_empty_form_as_unfilled(company, empty) -> None:
    """空は null・空白だけの文字・[]・{}・中の値がどれも空のもの。確かめるだけ（--check）でも埋まっていないに数え、書き換えない。"""
    read_all(company)
    check_code(company.tool("--merge"), 0)
    data = company.data()
    data["書類"][1]["内容"]["値"] = copy.deepcopy(empty)
    data["決まった期日"][0]["日時"]["値"] = copy.deepcopy(empty)
    data["補助の対象にならない経費"][0]["内容"]["状態"] = "資料で食い違い"
    data["補助の対象にならない経費"][0]["内容"]["値"] = copy.deepcopy(empty)
    path = company.folder / DATA_REL
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    out = check_code(company.tool("--check"), 1)
    assert important_row(out, "必須書類") == [2, 4, 3, 1]
    assert important_row(out, "締切") == [1, 1, 0, 1]
    assert important_row(out, "補助の対象にならない経費") == [2, 3, 2, 1]
    assert "必須書類の埋まっていない値：書類「登記簿の写し」の内容（値が空）" in out
    assert "締切の埋まっていない値：決まった期日「申請の締切」の日時（値が空）" in out
    assert "補助の対象にならない経費の埋まっていない値：補助の対象にならない経費「中古の機械の購入費」の内容（値が空）" in out
    assert "まだ足りないところがあります" in out
    assert path.read_bytes() == before


def test_missing_important_item_is_reported(company) -> None:
    b = chapter_b()
    del b["制度データ"]["補助の対象にならない経費"]
    read_all(company, b)
    out = check_code(company.tool("--merge"), 1)
    assert important_row(out, "補助の対象にならない経費") == [0, 0, 0, 0]
    assert "補助の対象にならない経費：1件もありません" in out
    assert any(u["項目"] == "補助の対象にならない経費" for u in company.data()["読み取れなかった項目"])


def test_check_counts_unsourced_values_and_does_not_rewrite(company) -> None:
    read_all(company)
    check_code(company.tool("--merge"), 0)
    out = check_code(company.tool("--check"), 0)
    assert "出典のない値：0" in out

    data = company.data()
    bad = copy.deepcopy(data)
    bad["書類"][0]["内容"]["出典"] = [{"資料": "ない資料", "ページ": 2}]  # 出典の資料が「資料」にない
    path = company.folder / DATA_REL
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    out = check_code(company.tool("--check"), 1)
    assert "出典のない値：1" in out
    assert "書類「決算書」の内容：出典の資料「ない資料」が、制度データの「資料」にありません" in out
    assert "形（スキーマ）：合っています" in out
    assert path.read_bytes() == before

    del bad["補助額"][0]["上限"]["出典"]  # 出典のない値（形も合わない）
    bad["補助額"][1]["補助率"]["根拠の文"] = ""
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    out = check_code(company.tool("--check"), 1)
    assert "出典のない値：3" in out
    assert "補助額「従業員10人まで」の上限：出典がありません" in out
    assert "補助額「従業員11人以上」の補助率：根拠の文がありません" in out
    assert "形（スキーマ）：合いません" in out


def test_shape_error_writes_nothing(company) -> None:
    a = chapter_a()
    del a["制度データ"]["補助額"]
    company.read(a)
    company.read(chapter_b())
    company.read(chapter_c())
    before = hr.snapshot(company.folder)
    out = check_code(company.tool("--merge"), 2)
    assert "制度データの形が合いません" in out and "何も書いていません" in out and "補助額" in out
    assert hr.snapshot(company.folder) == before


def test_refuses_without_company_folder_or_readings(company, tmp_path) -> None:
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    before = hr.snapshot(plain)
    out = check_code(company.tool("--merge", folder=plain), 2)
    assert "まだ会社のフォルダではありません" in out
    assert hr.snapshot(plain) == before
    # 読み取りの結果がない
    before = hr.snapshot(company.folder)
    out = check_code(company.tool("--merge"), 2)
    assert "章ごとの読み取りの結果" in out and "何も書いていません" in out
    assert hr.snapshot(company.folder) == before
    # 制度データがない
    out = check_code(company.tool("--check"), 2)
    assert "制度データ（記録/制度データ/テスト補助金_第3回.json）がありません" in out
    check_code(company.tool("--stage-folders"), 2)
    assert hr.snapshot(company.folder) == before


def test_stage_folders_need_numbering_from_one(company) -> None:
    """申請の段階が抜けて、いちばん前のフォルダが「2_交付申請」になった制度データでは、段階のフォルダを作らない（DESIGN 4.5）。"""
    c = chapter_c()
    c["制度データ"]["手続きの段階"] = c["制度データ"]["手続きの段階"][1:]  # 申請の段階を落とした読み取り
    company.read(chapter_a())
    company.read(chapter_b())
    company.read(c)
    out = check_code(company.tool("--merge"), 1)
    assert "段階のフォルダを作れませんでした" in out
    assert "1つ目の段階のフォルダが「2_交付申請」です" in out and "2つ目の段階のフォルダが「3_実績報告」です" in out
    assert "重要な項目はすべて値か「要確認」で埋まり" in out  # 確かめた結果はよい。段階のフォルダだけ作れない
    assert sorted(p.name for p in company.case_dir().iterdir()) == ["公式資料"]
    assert (company.folder / DATA_REL).is_file()
    before = hr.snapshot(company.folder)
    out = check_code(company.tool("--stage-folders", "--stage", "2_交付申請"), 2)
    assert "「1_申請」「2_交付申請」…の形になっていません" in out
    assert hr.snapshot(company.folder) == before


def test_stage_folders_from_seido_data(company) -> None:
    read_all(company)
    check_code(company.tool("--merge"), 0)
    out = check_code(company.tool("--stage-folders", "--stage", "2_交付申請"), 0)
    assert "段階のフォルダを作りました：2_交付申請" in out
    base = company.case_dir()
    assert sorted(p.name for p in base.iterdir()) == ["1_申請", "2_交付申請", "公式資料"]
    assert sorted(p.name for p in (base / "2_交付申請").iterdir()) == ["添付する書類", "申請書"]
    before = hr.snapshot(company.folder)
    out = check_code(company.tool("--stage-folders", "--stage", "9_ない段階"), 2)
    assert "手続きの段階にないフォルダの名前です：9_ない段階" in out
    assert hr.snapshot(company.folder) == before
    out = check_code(company.tool("--stage-folders"), 0)
    assert "段階のフォルダは、もうあります：1_申請" in out
    assert not list(company.env.plugin.rglob("__pycache__")) and not list(company.folder.rglob("__pycache__"))
