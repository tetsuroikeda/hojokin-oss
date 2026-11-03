"""読み取り役の結果の形と、裏取りの道具（SPEC F3・T3-8、DESIGN 5章・9章・9.2、TASKS M2b）。

確かめること
- 形：読み取り役が返す JSON（章ごと）と、制度データの全体を、制度データのスキーマで確かめる。
  - 道具の形の確かめ（lib/schema_lite.py。/usr/bin/python3 で動くよう jsonschema を使わない）が、jsonschema と同じ判定になる
  - 形が合わなければ、何も書かずに、場所つきの誤りの一覧を返す（終了コード 2）
- 裏取り：根拠の文が出典のページに本当にあるか、値がその文の中にあるか（SPEC F3「外れた値は要確認として示す」）
  - 小さな架空の公募要領（PDF 4ページ＋表紙と、HTML の日程表）で、正しい読み取りは1つも要確認にしない
  - T3-8 のうち、出典のページと違う値と、そのページにない根拠の文を混ぜると、混ぜたものを1つ残らず「要確認」にし、
    注記と結果の表に理由を書く。ほかに、文の中にない値（金額・数・割合・日付・時刻・旬・税・言葉）、「…」だけの根拠の文、
    ない資料・ないページ、長すぎる根拠の文なども混ぜる（2回の読み取りで食い違う重要な項目は B25 で足す）
  - 金額は単位まで照らす（「1,500万円」の根拠の文で、上限 1500 円や、区分の人数・割合の数字を金額として通さない）
  - PDF の文字の崩れ（空白・改行・全角・康熙部首の字）で外れにしない。「※３ 3/4」を「33/4」と読まない
  - 道具は、読み取り役が付けた状態より上げない（読み取り役の要確認は要確認のまま）。読み取れない値は照らさない
  - 照らせる値が0件のときに、「どれも合っていた」と言わない
- 実物の小さな資料：公募要領（downloads/ の第8回）の補助額のページで、制度データの正解の値と、その場でページから拾った文で照らす
  （公式資料の文はリポに入れない。downloads/ がなければ飛ばす）
- 道具の動き：
  - 会社のフォルダでなければ何もしない。案件を決められなければ何もしない
  - 決まった場所（記録/制度データ/ の決まった名前）にしか書かない。置き場所は渡せない。
    版の名前の語のある名前、別名で 記録/制度データ/ の外を指す場所には書かない（DESIGN 5章）
  - 読み取りの結果のファイルは、会社のフォルダの中のものだけを読む
  - 同じ章を読み直して通すと、渡された項目だけを差し替え、ほかの項目は残す。直した値は外れなくなり、
    何度通しても注記が増えない
  - 補助プログラムが動かないときは、終了コード 3（外れた値があるときの 1 と分ける）

テストの公募要領は、テストのためだけに作った架空の文（区分の名前・金額・言い回しは、公式の公募要領と別のもの）。
崩れ方（数字の間の空白、全角の数字、行の途中の改行、康熙部首の字）だけを、PDF の文字で起きる形にそろえた。

道具は、Claude が Bash で動かすのと同じく、社長の Mac と同じ /usr/bin/python3 で、プラグインの写しから動かす。
lib/urakadori.py は同梱の pypdf の場所を読み込む lib/doc_text.py を使うので、テストの Python の中では読み込まない（tests/company_tool.py）。
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
from jsonschema import Draft202012Validator

from lib.schema_lite import SchemaError, Validator

REPO_ROOT = hr.REPO_ROOT
TOOL = Path("skills") / "junbi" / "scripts" / "urakadori.py"
SCHEMA = json.loads((REPO_ROOT / "schema" / "制度データ.schema.json").read_text(encoding="utf-8"))
COMPANY_SCHEMA = json.loads((REPO_ROOT / "schema" / "会社の記録.schema.json").read_text(encoding="utf-8"))
ANSWER = REPO_ROOT / "testdata" / "正解" / "省力化_第8回.json"
YORYO8 = REPO_ROOT / "downloads" / "shoryokuka_ippan" / "application_guidelines_ippan_08.pdf"
CASE = "2026_テスト補助金（一般型）第1回"
CHAPTER = "1 補助の上限と日程"
READING_REL = Path("記録") / "制度データ" / "読み取り" / CASE
OUT_REL = READING_REL / f"{CHAPTER}_1回目.json"

# ---- 小さな架空の公募要領（テストのためだけに作った文。公式資料の文は写していない） ----

KANGXI_KOU = "⼯"  # 「工」の康熙部首の字（PDF の文字で出ることがある）
PAGES = [
    "テスト用 作業改善設備補助金（一般型）\n第１回 公募要領\n架空の資料（テストのためだけに作ったもの）\n",
    "１．補助の上限と割合 \n従業員の数 上限の額 \n3 人まで 400 万円（600 万円） \n4～15 人 900 万円（1,200 万円） \n"
    "51 人以上 6,000 万円（1 億 2,000 万円） \n※ かっこの中は、特例を使うときの上限 \n申請する者 補助の割合 \n"
    "一般の事業者 １／２ （３／４）※１ \n小さな事業者 \n創業間もない事業者※３ 3/4 \n"
    "事業を行う期間は、交付決定の日から 14 か月まで（採択の発表から \n16 か月まで）とする。 \n- 1 -\n",
    "２．日程 \n申請の締切 ：2027 年 1 月 22 日（金）15:00 \n採択の発表 ：令和 9 年 4 月中旬（予定） \n"
    f"{KANGXI_KOU}具の購入は、申請の締切の後に行うこと。 \n交付の申請は、採択の発表から 45 日以内に行う。 \n- 2 -\n",
    "３．補助の対象にならない経費 \n◼ ほかの用途にも使えるもの（例：ノートパソコン、携帯電話、事務机など） \n"
    "◼ 使ったことのある品の購入費 \n○ 設備費のほかの経費は、合わせて 300 万円（税抜き）までとする。 \n"
    "○ 委託費は、対象となる経費の合計の 3 分の 1 までとする。 \n- 3 -\n",
    "４．数値の要件 \n作業時間あたりの出来高を、年平均で 2.5％以上 伸ばすこと。 \n従業員に払う給与の合計を、年平均で 1.8％以上 増やすこと。 \n"
    "出来高は、売上高から材料費と外注費を引いたものとする。 \n- 4 -\n",
]
SCHEDULE_HTML = ("<html><head><meta charset=\"utf-8\"></head><body><table>"
                 "<tr><th>回</th><th>項目</th><th>日時</th></tr>"
                 "<tr><td>第1回</td><td>申請の締切</td><td>2027年1月22日（金）15:00</td></tr>"
                 "</table></body></html>")


def sv(value, doc: str, page, sentence: str, state: str = "確認済み", end=None, note=None) -> dict:
    """出典つき値。page が None なら、ページのない資料（HTML など）。"""
    source = {"資料": doc}
    if page is not None:
        source["ページ"] = page
    if end is not None:
        source["終わりのページ"] = end
    item = {"値": value, "出典": [source], "根拠の文": sentence, "状態": state}
    if note:
        item["注記"] = note
    return item


def good_chapter() -> dict:
    """正しい読み取り（どの値も、根拠の文がページにあり、値がその文の中にある）。"""
    return {
        "読み取り": {"章": CHAPTER, "読んだページ": [{"資料": "要領T", "ページ": 1, "終わりのページ": 4}, {"資料": "日程表"}]},
        "制度データ": {
            "資料どうしの食い違い": [{
                "項目": "締切の書き方",
                "値": [
                    {"値": "2027年1月22日15:00", "出典": [{"資料": "要領T", "ページ": 2}], "根拠の文": "2027 年 1 月 22 日（金）15:00"},
                    {"値": "2027年1月22日15:00", "出典": [{"資料": "日程表"}], "根拠の文": "申請の締切 2027年1月22日（金）15:00"},
                ],
            }],
            "補助額": [
                {
                    "区分": "従業員3人まで",
                    # 空白・全角を変えて写しても合う
                    "上限": sv(4000000, "要領T", 1, "3人まで400万円（600万円）"),
                    "補助率": sv("1/2", "要領T", 1, "一般の事業者 1/2 (3/4)"),
                    "特例": [
                        {"名前": "特例の上限", "種類": "上限の置き換え",
                         "値": sv(6000000, "要領T", 1, "3 人まで 400 万円（600 万円）…※ かっこの中は、特例を使うときの上限")},
                        # 「※３ 3/4」を「33/4」と読まない
                        {"名前": "創業間もない事業者", "種類": "補助率の置き換え", "値": sv("3/4", "要領T", 1, "創業間もない事業者※３ 3/4")},
                    ],
                },
                {
                    "区分": "従業員51人以上",
                    "上限": sv(60000000, "要領T", 1, "51 人以上 6,000 万円（1 億 2,000 万円）"),
                    "補助率": sv("1/2", "要領T", 1, "一般の事業者 １／２"),
                    "特例": [
                        # 読み取り役が要確認とした値は、裏取りで外れなくても要確認のまま
                        {"名前": "特例の上限", "種類": "上限の置き換え",
                         "値": sv(120000000, "要領T", 1, "51 人以上 6,000 万円（1 億 2,000 万円）", state="要確認", note="特例の条件は別の章")},
                    ],
                },
            ],
            "補助の対象にならない経費": [
                {"名前": "ほかの用途にも使えるもの", "種類": "対象外",
                 "内容": sv("ノートパソコン・携帯電話など、ほかの用途にも使えるもの", "要領T", 3,
                           "ほかの用途にも使えるもの（例：ノートパソコン、携帯電話、事務机など）")},
                {"名前": "設備費のほかの経費", "種類": "上限",
                 "内容": sv("設備費のほかの経費の合わせた上限", "要領T", 3,
                           "設備費のほかの経費は、合わせて 300 万円（税抜き）までとする。"),
                 "上限": sv({"何の上限": "補助対象経費", "金額": 3000000, "税": "税抜き"}, "要領T", 3,
                           "設備費のほかの経費は、合わせて 300 万円（税抜き）までとする。")},
                {"名前": "委託費", "種類": "上限", "経費の区分": "委託費",
                 "内容": sv("委託費は対象となる経費の合計の3分の1まで", "要領T", 3, "委託費は、対象となる経費の合計の 3 分の 1 までとする。"),
                 "上限": sv({"何の上限": "補助対象経費", "割合": "1/3", "基準": "対象となる経費の合計"}, "要領T", 3,
                           "委託費は、対象となる経費の合計の 3 分の 1 までとする。")},
            ],
            "数値の要件": [
                {"名前": "作業時間あたりの出来高の伸び",
                 "計算式": sv("出来高＝売上高－材料費－外注費", "要領T", 4, "出来高は、売上高から材料費と外注費を引いたものとする。"),
                 "基準": sv("出来高を年平均で2.5%以上伸ばす", "要領T", 4, "作業時間あたりの出来高を、年平均で 2.5％以上 伸ばすこと。"),
                 "満たせないとき": {"値": None, "状態": "読み取れない", "理由": "この資料には返還の定めがない"}},
            ],
            "数値でない要件": [
                # ページの字は康熙部首の「⼯」。写した文は普通の「工」
                {"名前": "購入の時期", "種類": "満たすこと",
                 "内容": sv("工具の購入は申請の締切の後に行う", "要領T", 2, "工具の購入は、申請の締切の後に行うこと。")},
            ],
            "決まった期日": [
                {"名前": "締切", "日時": sv({"日時": "2027-01-22T15:00+09:00"}, "要領T", 2, "申請の締切 ：2027 年 1 月 22 日（金）15:00")},
                {"名前": "締切（日程表）", "日時": sv({"日時": "2027-01-22T15:00+09:00"}, "日程表", None, "申請の締切 2027年1月22日（金）15:00")},
                {"名前": "採択の発表", "日時": sv({"年月": "2027-04", "旬": "中旬"}, "要領T", 2, "採択の発表 ：令和 9 年 4 月中旬（予定）"), "注記": "予定"},
            ],
            "手続きの段階": [
                {"id": "koufu", "順番": 1, "名前": "交付申請",
                 "期限": sv({"種類": "出来事からの期間", "出来事": "採択発表", "期間": {"数": 45, "単位": "日"}}, "要領T", 2,
                           "交付の申請は、採択の発表から 45 日以内に行う。")},
                # ページの中で改行をまたぐ文
                {"id": "jisshi", "順番": 2, "名前": "事業の実施",
                 "期限": sv({"種類": "出来事からの期間", "出来事": "交付決定", "期間": {"数": 14, "単位": "か月"}}, "要領T", 1,
                           "事業を行う期間は、交付決定の日から14か月まで（採択の発表から16か月まで）とする。")},
            ],
        },
        "メモ": ["特例の条件は別の章にある"],
    }


def value_nodes(node, path=()):
    """出典つき値（値と状態を持つもの）と、その場所。"""
    if isinstance(node, dict):
        if "値" in node and "状態" in node:
            yield path, node
            return
        for k, v in node.items():
            yield from value_nodes(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from value_nodes(v, path + (i,))


def get(node, path):
    for p in path:
        node = node[p]
    return node


# ---- 道具を動かす ----


BUILD_CODE = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib import doc_text
spec = json.loads(sys.stdin.read())
if spec.get("pages") is not None:
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
        self.folder = self.env.folder("架空 製作所")
        (self.folder / ".hojokin").mkdir()
        self.work = tmp_path / "作業"  # 会社のフォルダの外（資料の元のファイルを置く）
        self.work.mkdir()

    def texts(self, case: str = CASE) -> Path:
        return self.folder / "記録" / "資料の本文" / case

    def add_doc(self, doc_id: str, name: str, source: Path, pages=None, case: str = CASE) -> dict:
        """資料をページごとの文字にして置く（lib/doc_text.py の書き方のまま）。pages を渡すと、PDF の文字の代わりに使う。"""
        spec = {"source": str(source), "out": str(self.texts(case) / doc_id), "pages": pages,
                "doc": {"id": doc_id, "名前": name, "公募回": "第1回", "ハッシュ": ""}}
        r = subprocess.run([hr.real_python(), "-I", "-B", "-c", BUILD_CODE, str(self.env.plugin)],
                           input=json.dumps(spec, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=300)
        assert r.returncode == 0, r.stderr.decode("utf-8")
        return json.loads(r.stdout.decode("utf-8"))

    def add_small_docs(self, case: str = CASE) -> None:
        pdf = self.work / "要領T.pdf"
        pdf.write_bytes(b"")
        index = self.add_doc("要領T", "テスト用の公募要領", pdf, pages=PAGES, case=case)
        assert index == {"ずれ": 1, "ページ数": 5}  # 表紙の後の4ページに、1〜4 の番号が印刷されている
        html = self.work / "日程表.html"
        html.write_text(SCHEDULE_HTML, encoding="utf-8")
        self.add_doc("日程表", "日程表のページ", html, case=case)

    def run(self, data=None, *extra: str, folder: Path = None, raw: bytes = None, input_file: Path = None,
            args: list = None) -> subprocess.CompletedProcess:
        """道具を動かす。読み取りの結果は、Claude が渡すのと同じく標準入力から渡す（input_file を渡すとファイルで）。"""
        env = {"PATH": self.env.path, "HOME": str(self.env.home), "TMPDIR": str(self.env.tmp)}
        payload = None
        if args is None:
            args = ["--folder", str(folder or self.folder)]
            if input_file is not None:
                args += ["--input", str(input_file)]
            else:
                args += ["--input", "-"]
                payload = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        return subprocess.run([hr.real_python(), "-B", str(self.env.plugin / TOOL), *args, *extra],
                              input=payload, env=env, cwd=self.env.cwd, capture_output=True, timeout=120)

    def out(self, rel: Path = OUT_REL) -> dict:
        return json.loads((self.folder / rel).read_text(encoding="utf-8"))


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
    c.add_small_docs()
    return c


# ---- 形：道具の形の確かめが jsonschema と同じ判定になる ----


def schema_mutations() -> list:
    """制度データの正解を少しずつ変えたもの（形が合うものと、合わないもの）。"""
    base = json.loads(ANSWER.read_text(encoding="utf-8"))
    out = [("そのまま", base)]

    def m(name, fn):
        data = copy.deepcopy(base)
        fn(data)
        out.append((name, data))

    m("必須の項目がない", lambda d: d.pop("補助額"))
    m("知らない項目", lambda d: d.__setitem__("おまけ", 1))
    m("スキーマの版が違う", lambda d: d.__setitem__("スキーマの版", 2))
    m("金額が文字", lambda d: d["補助額"][0]["上限"].__setitem__("値", "750万円"))
    m("金額が負", lambda d: d["補助額"][0]["上限"].__setitem__("値", -1))
    m("金額が true", lambda d: d["補助額"][0]["上限"].__setitem__("値", True))
    m("金額が 1.0（整数として扱う）", lambda d: d["補助額"][0]["上限"].__setitem__("値", 7500000.0))
    m("補助率の書き方", lambda d: d["補助額"][0]["補助率"].__setitem__("値", "2分の1"))
    m("状態が決まった言葉でない", lambda d: d["補助額"][0]["上限"].__setitem__("状態", "たぶん"))
    m("確認済みなのに根拠の文がない", lambda d: d["補助額"][0]["上限"].pop("根拠の文"))
    m("確認済みなのに出典が空", lambda d: d["補助額"][0]["上限"].__setitem__("出典", []))
    m("読み取れないのに値がある", lambda d: d["補助額"][0]["上限"].update({"状態": "読み取れない", "理由": "x"}))
    m("読み取れないに理由がない", lambda d: d["補助額"][0]["上限"].update({"状態": "読み取れない", "値": None}))
    m("読み取れない（正しい形）", lambda d: d["補助額"][0].__setitem__(
        "上限", {"値": None, "状態": "読み取れない", "理由": "表が読めない"}))
    m("出典のページが0", lambda d: d["補助額"][0]["上限"]["出典"][0].__setitem__("ページ", 0))
    m("出典に知らない欄", lambda d: d["補助額"][0]["上限"]["出典"][0].__setitem__("行", 3))
    m("日時の書き方", lambda d: d["決まった期日"][2]["日時"]["値"].__setitem__("日時", "2026/10/16"))
    m("期日の形が2つに当たらない", lambda d: d["決まった期日"][2]["日時"].__setitem__("値", {"日時": "2026-10-16", "年月": "2026-10"}))
    m("旬の言葉", lambda d: d["決まった期日"].__setitem__(0, {"名前": "x", "日時": {
        "値": {"年月": "2027-02", "旬": "はじめ"}, "出典": [{"資料": "要領8", "ページ": 1}], "根拠の文": "x", "状態": "要確認"}}))
    m("上限の種類なのに上限がない", lambda d: d["補助の対象にならない経費"].__setitem__(0, {
        "名前": "x", "種類": "上限", "内容": {"値": "x", "状態": "読み取れない", "理由": "x"}}))
    m("対象外の種類に上限がある", lambda d: d["補助の対象にならない経費"].__setitem__(0, {
        "名前": "x", "種類": "対象外", "内容": {"値": "x", "状態": "読み取れない", "理由": "x"},
        "上限": {"値": None, "状態": "読み取れない", "理由": "x"}}))
    m("経費の上限に金額も割合もない", lambda d: d["補助の対象にならない経費"].__setitem__(0, {
        "名前": "x", "種類": "上限", "内容": {"値": "x", "状態": "読み取れない", "理由": "x"},
        "上限": {"値": {"何の上限": "補助対象経費"}, "出典": [{"資料": "要領8", "ページ": 1}], "根拠の文": "x", "状態": "要確認"}}))
    m("資料が空", lambda d: d.__setitem__("資料", []))
    m("資料のハッシュの書き方", lambda d: d["資料"][0].__setitem__("ハッシュ", "abc"))
    m("食い違いの値が1つ", lambda d: d["資料どうしの食い違い"][0].__setitem__("値", d["資料どうしの食い違い"][0]["値"][:1]))
    m("段階のフォルダの名前", lambda d: d["手続きの段階"][0].__setitem__("フォルダ", "申請"))
    m("支援者の欄が null（形が合う）", lambda d: d.__setitem__("支援者の欄", None))
    m("支援者の欄が文字", lambda d: d.__setitem__("支援者の欄", "支援者"))
    m("注記を足す（形が合う）", lambda d: d["補助額"][0]["上限"].__setitem__("注記", "メモ"))
    return out


@pytest.mark.parametrize("name,data", schema_mutations(), ids=[n for n, _d in schema_mutations()])
def test_schema_lite_agrees_with_jsonschema(name, data) -> None:
    expected = Draft202012Validator(SCHEMA).is_valid(data)
    errors = Validator(SCHEMA).errors(data)
    assert (not errors) == expected, (name, errors[:5])
    if errors:
        # 誤りは「場所：理由」の形で、場所が分かる
        assert all("：" in e for e in errors), errors


def test_schema_lite_reads_both_schemas_and_refuses_unknown_keywords() -> None:
    Validator(SCHEMA)
    Validator(COMPANY_SCHEMA)
    with pytest.raises(SchemaError):
        Validator({"type": "object", "minProperties": 1})
    with pytest.raises(SchemaError):
        Validator({"$ref": "other.json#/x"}).errors({})


# ---- 裏取り：正しい読み取りは外れにしない ----


def test_good_reading_stays_confirmed(company) -> None:
    data = good_chapter()
    out = check_code(company.run(data), 0)
    assert "根拠の文はどれも出典のページにあり、値はどれも根拠の文の中にありました" in out
    assert "出典つき値：21（確認済み 19、要確認 1、資料で食い違い 0、読み取れない 1）" in out
    assert "照らした値：22（読み取れない値は照らしていません。資料どうしの食い違いの値 2 を含む）" in out
    assert f"置き場所：{OUT_REL}" in out
    saved = company.out()
    assert saved["読み取り"]["案件"] == CASE and saved["読み取り"]["回目"] == 1
    assert saved["メモ"] == data["メモ"]
    before = dict(value_nodes(data["制度データ"]))
    after = dict(value_nodes(saved["制度データ"]))
    assert before.keys() == after.keys() and len(after) == 21
    for path, node in after.items():
        assert node["状態"] == before[path]["状態"], path   # 上げも下げもしない
        assert "裏取り" not in node.get("注記", ""), path
    states = saved["裏取り"]["状態ごとの数"]
    assert states == {"確認済み": 19, "要確認": 1, "読み取れない": 1}
    assert saved["裏取り"]["出典つき値"] == 21
    assert saved["裏取り"]["照らした値"] == 22  # 読み取れないを除く出典つき値 20 と、資料どうしの食い違いの値 2
    assert saved["裏取り"]["要確認にした値"] == [] and saved["裏取り"]["食い違いで外れた値"] == []
    assert "注記" not in saved["制度データ"]["資料どうしの食い違い"][0]
    assert "前の結果に差し替えた項目" not in saved["裏取り"]


# ---- 裏取り：混ぜた誤りを1つ残らず要確認にする ----

# （場所、変え方、結果の表と注記に出る言葉）
def _set(path, key, value):
    def fn(d):
        get(d, path)[key] = value
    return fn


INJECTED = [
    # T3-8 出典のページと違う値（文は p.1 にあるのに、出典を p.2 にした）
    (("補助額", 0, "上限"), _set(("補助額", 0, "上限", "出典", 0), "ページ", 2), "出典のページ（要領T p.2）にありません"),
    # 値が文の中にない（金額）
    (("補助額", 1, "上限"), _set(("補助額", 1, "上限"), "値", 70000000), "金額「70000000円」が根拠の文にありません"),
    # 値が文の中にない（割合）。文はページにある
    (("補助額", 0, "補助率"), lambda d: get(d, ("補助額", 0, "補助率")).update({"値": "2/3", "根拠の文": "一般の事業者 １／２"}),
     "割合「2/3」が根拠の文にありません"),
    # T3-8 そのページにない根拠の文（作った文）
    (("補助の対象にならない経費", 0, "内容"),
     _set(("補助の対象にならない経費", 0, "内容"), "根拠の文", "ほかの用途にも使えるものは、すべて対象とする。"),
     "が、出典のページ（要領T p.3）にありません"),
    # 税込みと税抜き
    (("補助の対象にならない経費", 1, "上限"), _set(("補助の対象にならない経費", 1, "上限", "値"), "税", "税込み"), "「税込み」"),
    # 根拠の文が「…」だけ（切れ端が1つもない）
    (("補助の対象にならない経費", 2, "内容"), _set(("補助の対象にならない経費", 2, "内容"), "根拠の文", "…"), "根拠の文がありません"),
    # 割合（3分の1 と書かれている）
    (("補助の対象にならない経費", 2, "上限"), _set(("補助の対象にならない経費", 2, "上限", "値"), "割合", "1/4"), "割合「1/4」"),
    # 日付
    (("決まった期日", 0, "日時"), _set(("決まった期日", 0, "日時", "値"), "日時", "2027-01-23T15:00+09:00"), "日付（2027年1月23日）"),
    # 時刻（ページのない資料）
    (("決まった期日", 1, "日時"), _set(("決まった期日", 1, "日時", "値"), "日時", "2027-01-22T14:00+09:00"), "時刻（14:00）"),
    # 旬
    (("決まった期日", 2, "日時"), _set(("決まった期日", 2, "日時", "値"), "旬", "下旬"), "「下旬」が根拠の文にありません"),
    # 文字の値の中の数
    (("数値の要件", 0, "基準"), _set(("数値の要件", 0, "基準"), "値", "出来高を年平均で3.0%以上伸ばす"), "数「3」が根拠の文にありません"),
    # 文字の値が、文と関わりのない言葉
    (("数値の要件", 0, "計算式"), _set(("数値の要件", 0, "計算式"), "値", "車両の購入費は対象にならない"), "に当たる言葉が根拠の文にありません"),
    # ない資料
    (("数値でない要件", 0, "内容"), _set(("数値でない要件", 0, "内容", "出典", 0), "資料", "要領99"), "出典の資料「要領99」の本文がありません"),
    # 期限の中の数
    (("手続きの段階", 0, "期限"), _set(("手続きの段階", 0, "期限", "値", "期間"), "数", 60), "数「60」が根拠の文にありません"),
    # ないページ
    (("手続きの段階", 1, "期限"), _set(("手続きの段階", 1, "期限", "出典", 0), "ページ", 40), "p.40 がありません"),
    # 資料で食い違い とした値も、外れたら要確認にする（切れ端が短すぎる）
    (("補助額", 1, "補助率"), lambda d: get(d, ("補助額", 1, "補助率")).update({"状態": "資料で食い違い", "根拠の文": "1/2"}),
     "短すぎます"),
    # 長すぎる根拠の文（どの切れ端もページにある）
    (("補助額", 0, "特例", 1, "値"),
     _set(("補助額", 0, "特例", 1, "値"), "根拠の文", "…".join([PAGES[1].replace("- 1 -", "")] * 3) + "…創業間もない事業者※３ 3/4"),
     "長すぎます"),
    # PDF の資料なのにページがない
    (("補助額", 0, "特例", 0, "値"), lambda d: get(d, ("補助額", 0, "特例", 0, "値", "出典", 0)).pop("ページ"), "印刷されたページ番号を書いてください"),
]


def test_mixed_errors_all_become_check(company) -> None:
    data = good_chapter()
    for _path, change, _word in INJECTED:
        change(data["制度データ"])
    # 資料どうしの食い違いの2つ目の値にも、ページにない文を混ぜる
    data["制度データ"]["資料どうしの食い違い"][0]["値"][1]["根拠の文"] = "申請の締切 2027年1月21日（木）15:00"
    out = check_code(company.run(data), 1)
    saved = company.out()
    injected = {path for path, _c, _w in INJECTED}
    assert len(injected) == len(INJECTED)
    for path, node in value_nodes(saved["制度データ"]):
        if path in injected:
            word = next(w for p, _c, w in INJECTED if p == path)
            assert node["状態"] == "要確認", path
            assert "裏取り：" in node["注記"] and word in node["注記"], (path, node["注記"])
            assert word in out, (path, word)
        else:
            original = get(good_chapter()["制度データ"], path)
            assert node["状態"] == original["状態"], path
            assert "裏取り" not in node.get("注記", ""), (path, node.get("注記"))
    # 読み取り役が別の状態にしていたことも注記に残る
    assert "読み取り役は「確認済み」としていた" in get(saved["制度データ"], ("補助額", 0, "上限"))["注記"]
    assert "読み取り役は「資料で食い違い」としていた" in get(saved["制度データ"], ("補助額", 1, "補助率"))["注記"]
    summary = saved["裏取り"]
    assert len(summary["要確認にした値"]) == len(INJECTED)
    # 混ぜなかった確認済みの1つ（設備費のほかの経費の内容）と、読み取り役が要確認とした1つと、読み取れない1つはそのまま
    assert summary["状態ごとの数"] == {"確認済み": 1, "要確認": len(INJECTED) + 1, "読み取れない": 1}
    # 資料どうしの食い違い：外れた値は、その食い違いの注記と結果の表に出る
    conflict = saved["制度データ"]["資料どうしの食い違い"][0]
    assert "裏取り：2つ目の値" in conflict["注記"]
    assert "出典のページ（日程表）にありません" in conflict["注記"] and "数「22」が根拠の文にありません" in conflict["注記"]
    assert len(summary["食い違いで外れた値"]) == 1
    # 結果の表は、社長にも分かる場所の書き方
    for label in ("補助額「従業員3人まで」の上限", "補助額「従業員51人以上」の上限", "決まった期日「締切（日程表）」の日時",
                  "補助額「従業員3人まで」の特例「創業間もない事業者」の値", "手続きの段階「交付申請」の期限",
                  "資料どうしの食い違い「締切の書き方」の2つ目の値"):
        assert label in out, label
    assert out.count("\n| ") == len(INJECTED) + 1 + 1  # 見出しの行と、外れた値の行
    assert "根拠の文はどれも" not in out


@pytest.mark.parametrize("sentence", ["…", "...", "・・・", "… …", "‥", "  ", "\n"])
@pytest.mark.parametrize("state", ["確認済み", "資料で食い違い"])
def test_evidence_with_no_text_becomes_check(company, sentence, state) -> None:
    """根拠の文が「…」や空白だけで照らす文字がないとき（スキーマの minLength は通る）、
    ページの照合も値の照合も素通りさせずに要確認にする。"""
    data = good_chapter()
    get(data["制度データ"], ("補助額", 0, "上限")).update({"根拠の文": sentence, "状態": state})
    out = check_code(company.run(data), 1)
    node = get(company.out()["制度データ"], ("補助額", 0, "上限"))
    assert node["状態"] == "要確認" and "根拠の文がありません" in node["注記"], node
    assert "根拠の文がありません" in out and "根拠の文はどれも" not in out


def test_empty_evidence_is_a_shape_error(company) -> None:
    """空の根拠の文は、スキーマで形が合わない（何も書かない）。"""
    data = good_chapter()
    get(data["制度データ"], ("補助額", 0, "上限"))["根拠の文"] = ""
    before = hr.snapshot(company.folder)
    out = check_code(company.run(data), 2)
    assert "根拠の文" in out and "何も書いていません" in out
    assert hr.snapshot(company.folder) == before


def test_doc_id_cannot_point_outside(company) -> None:
    """出典の資料の id で、資料の本文の外のフォルダを読ませない。"""
    data = good_chapter()
    get(data["制度データ"], ("補助額", 0, "上限"))["出典"][0]["資料"] = "../" + CASE + "/要領T"
    out = check_code(company.run(data), 1)
    node = get(company.out()["制度データ"], ("補助額", 0, "上限"))
    assert node["状態"] == "要確認" and "形が違います" in node["注記"]
    assert "形が違います" in out


@pytest.mark.parametrize("value,sentence,ok", [
    # 金額（補助額の上限。円）：万円・億円・円の付いた数を円にしたものだけを金額と読む
    (40000000, "16～50 人 4,000 万円（5,000 万円）", True),
    (50000000, "16～50 人 4,000 万円（5,000 万円）", True),    # かっこの中の値
    (40000000, "１６～５０人　４，０００万円", True),           # 全角
    (120000000, "51 人以上 6,000 万円（1 億 2,000 万円）", True),
    (100000000, "上限は 1 億円とする", True),
    (500000, "1 日あたり 500,000 円まで", True),               # 円の数
    (500000, "1 日あたり 50 万円まで", True),
    (3000000, "上限は 3,000 千円", True),
    (4000, "16～50 人 4,000 万円", False),                    # 単位をかける前の数は、金額と読まない
    (4000, "16～50 人 4,000 万円（5,000 万円）", False),
    (16, "16～50 人 4,000 万円", False),                      # 区分の人数は、金額と読まない
    (50, "16～50 人 4,000 万円", False),
    (3, "合計の 3 分の 1 まで", False),                       # 割合の数は、金額と読まない
    (2000000, "16～50 人 1,200 万円", False),                 # 1200万 の中の 200万 は拾わない
    (30000000, "16～50 人 4,000 万円（5,000 万円）", False),
    (10000, "従業員 1 万人以上", False),                      # 円の付かない「万」は、金額と読まない
    # 補助率・割合
    ("1/2", "一般の事業者 １／２ （３／４）※１", True),
    ("3/4", "創業間もない事業者※３ 3/4", True),
    ("33/4", "創業間もない事業者※３ 3/4", False),
    ("1/3", "合計の 3 分の 1 まで", True),
    ("1/3", "合計の三分の一まで", True),
    ("1/4", "合計の 3 分の 1 まで", False),
    # 文字の値の中の数（年）
    ("2027年度から", "令和9年度から", True),                  # 元号
    ("2026年度から", "令和9年度から", False),
    # 日付と時刻
    ({"日時": "2027-01-22T15:00+09:00"}, "1 月 22 日（金）15:00 まで", True),   # 年が書いていない日付
    ({"日時": "2027-01-22T15:00+09:00"}, "2026 年 1 月 22 日 15:00", False),    # 年が違う
    ({"日時": "2027-01-22T15:00+09:00"}, "2027/1/22 15時", True),
    ({"日時": "2027-01-22"}, "令和9年1月22日", True),
    ({"日時": "2027-01-22T15:00+09:00"}, "2027年1月22日", False),              # 時刻がない
    ({"年月": "2027-04", "旬": "中旬"}, "2027 年 4 月中旬", True),
    ({"年月": "2027-04"}, "2027年5月", False),
])
def test_value_forms(company, value, sentence, ok) -> None:
    """値の書き方ごとに、根拠の文の中にあるかを見分ける（文はページにあるものとして、ページに書き足す）。"""
    page = company.texts() / "要領T" / "ページ_002.txt"  # PDF の 2 ページ目（印刷された p.1）
    page.write_text(page.read_text(encoding="utf-8") + sentence + "\n", encoding="utf-8")
    data = {"読み取り": {"章": "書き方", "読んだページ": [{"資料": "要領T", "ページ": 1}]},
            "制度データ": {"数値でない要件": [{"名前": "x", "種類": "満たすこと", "内容": sv(value, "要領T", 1, sentence)}]}}
    if isinstance(value, int):
        # 整数は、補助額の上限（金額の場所）に置く
        data["制度データ"] = {"補助額": [{"区分": "x", "上限": sv(value, "要領T", 1, sentence),
                                          "補助率": sv("1/2", "要領T", 1, "一般の事業者 １／２")}]}
    elif isinstance(value, dict):
        data["制度データ"] = {"決まった期日": [{"名前": "x", "日時": sv(value, "要領T", 1, sentence)}]}
    r = company.run(data)
    out = check_code(r, 0 if ok else 1)
    if not ok:
        # 外れた理由は値のほう（根拠の文は、どれもページにある）
        assert "出典のページ" not in out and "が根拠の文にありません" in out, out
        if isinstance(value, int):
            assert f"金額「{value}円」" in out


@pytest.mark.parametrize("place,value,sentence,ok", [
    # 経費の上限の「金額」も金額として照らす
    ("経費の上限", 3000000, "設備費のほかの経費は、合わせて 300 万円（税抜き）までとする。", True),
    ("経費の上限", 300, "設備費のほかの経費は、合わせて 300 万円（税抜き）までとする。", False),
    ("経費の上限", 2, "委託費は、対象となる経費の合計の 3 分の 1 までとする。", False),
    # 上限の特例の値も金額。補助率の置き換えは割合
    ("上限の置き換え", 6000000, "3 人まで 400 万円（600 万円）", True),
    ("上限の置き換え", 600, "3 人まで 400 万円（600 万円）", False),
    ("上限の置き換え", 3, "3 人まで 400 万円（600 万円）", False),
    # 金額でない数（期間の数）は、元の数字で照らす
    ("期間", 45, "交付の申請は、採択の発表から 45 日以内に行う。", True),
])
def test_money_places(company, place, value, sentence, ok) -> None:
    """どの文も、架空の公募要領のそのページにある（外れる理由は値のほうだけ）。"""
    if place == "経費の上限":
        page = 3
        part = {"補助の対象にならない経費": [{"名前": "x", "種類": "上限", "内容": sv(sentence, "要領T", page, sentence),
                                              "上限": sv({"何の上限": "補助対象経費", "金額": value}, "要領T", page, sentence)}]}
    elif place == "上限の置き換え":
        page = 1
        part = {"補助額": [{"区分": "x", "上限": sv(4000000, "要領T", page, sentence),
                            "補助率": sv("1/2", "要領T", page, "一般の事業者 １／２"),
                            "特例": [{"名前": "x", "種類": "上限の置き換え", "値": sv(value, "要領T", page, sentence)}]}]}
    else:
        page = 2
        part = {"手続きの段階": [{"id": "x", "順番": 1, "名前": "x", "期限": sv(
            {"種類": "出来事からの期間", "出来事": "採択発表", "期間": {"数": value, "単位": "日"}}, "要領T", page, sentence)}]}
    data = {"読み取り": {"章": "金額", "読んだページ": [{"資料": "要領T", "ページ": page}]}, "制度データ": part}
    out = check_code(company.run(data), 0 if ok else 1)
    if not ok:
        assert "出典のページ" not in out and f"金額「{value}円」が根拠の文にありません" in out, out


# ---- 形が合わなければ、何も書かない ----


def bad_shapes() -> list:
    """（名前、読み取りの結果、誤りが制度データの中身にあるか）。"""
    def m(name, fn, inner=False):
        data = good_chapter()
        fn(data)
        return name, data, inner
    return [
        m("読み取りがない", lambda d: d.pop("読み取り")),
        m("章がない", lambda d: d["読み取り"].pop("章")),
        m("回目が3", lambda d: d["読み取り"].__setitem__("回目", 3)),
        m("制度データが空", lambda d: d.__setitem__("制度データ", {})),
        m("知らない項目", lambda d: d["制度データ"].__setitem__("補助金額", [])),
        m("いちばん外側の知らない欄", lambda d: d.__setitem__("おまけ", 1)),
        m("金額が文字", lambda d: d["制度データ"]["補助額"][0]["上限"].__setitem__("値", "400万円"), True),
        m("状態が決まった言葉でない", lambda d: d["制度データ"]["補助額"][0]["上限"].__setitem__("状態", "OK"), True),
        m("根拠の文がない", lambda d: d["制度データ"]["補助額"][0]["上限"].pop("根拠の文"), True),
        m("読み取れないに理由がない", lambda d: d["制度データ"]["数値の要件"][0]["満たせないとき"].pop("理由"), True),
        m("期日の形", lambda d: d["制度データ"]["決まった期日"][0]["日時"].__setitem__("値", {"日時": "2027/01/22"}), True),
    ]


@pytest.mark.parametrize("name,data,inner", bad_shapes(), ids=[n for n, _d, _i in bad_shapes()])
def test_bad_shape_writes_nothing(company, name, data, inner) -> None:
    if inner:
        # 制度データの中身の誤りは、jsonschema でも形が合わない
        schema = {"$defs": SCHEMA["$defs"], "type": "object", "properties": SCHEMA["properties"]}
        assert not Draft202012Validator(schema).is_valid(data["制度データ"]), name
    before = hr.snapshot(company.folder)
    out = check_code(company.run(data), 2)
    assert "何も書いていません" in out and "直して返し直して" in out
    assert re.search(r"^- \S+：", out, re.M), out  # 場所つきの誤り
    assert hr.snapshot(company.folder) == before
    # 正しい形なら通る（同じ会社のフォルダで）
    check_code(company.run(good_chapter()), 0)


@pytest.mark.parametrize("raw,word", [
    (b"{ \xe3\x81\x82", "JSON の形で渡してください"),
    (b"[1, 2]", "いちばん外側を { } の形に"),
])
def test_unreadable_input_writes_nothing(company, raw, word) -> None:
    before = hr.snapshot(company.folder)
    out = check_code(company.run(raw=raw), 2)
    assert word in out
    assert hr.snapshot(company.folder) == before


# ---- 道具の動き：会社のフォルダ・案件 ----


def test_refuses_outside_company_folder(company) -> None:
    other = company.env.folder("ふつうのフォルダ")
    out = check_code(company.run(good_chapter(), folder=other), 2)
    assert "まだ会社のフォルダではありません" in out
    assert list(other.iterdir()) == []


def test_case_must_be_decided(company) -> None:
    # 案件が2つあると、--case なしでは何もしない
    company.add_doc("要領T", "テスト用の公募要領", company.work / "要領T.pdf", pages=PAGES, case="2027_別の補助金第2回")
    before = hr.snapshot(company.folder)
    out = check_code(company.run(good_chapter()), 2)
    assert "案件が2つ以上あります" in out and "--case" in out
    out = check_code(company.run(good_chapter(), "--case", "2026_ない案件"), 2)
    assert "資料の本文" in out
    assert hr.snapshot(company.folder) == before
    check_code(company.run(good_chapter(), "--case", CASE), 0)
    assert (company.folder / OUT_REL).is_file()


# ---- 道具の動き：決まった場所にしか書かない（DESIGN 5章） ----


def changed(before: dict, after: dict) -> set:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def test_writes_only_the_fixed_place(company) -> None:
    """章ごとの結果は決まった名前の1つのファイルだけ。会社のフォルダのほかも、外も変えない（__pycache__ も書かない）。"""
    outside = company.env.outside()
    before = hr.snapshot(company.folder)
    check_code(company.run(good_chapter()), 0)
    after = hr.snapshot(company.folder)
    made = {str(company.folder / p) for p in (Path("記録") / "制度データ", Path("記録") / "制度データ" / "読み取り", READING_REL, OUT_REL)}
    assert changed(before, after) == made
    assert company.env.outside() == outside
    assert not list(company.env.plugin.rglob("__pycache__"))


@pytest.mark.parametrize("place", [".claude/settings.json", ".hojokin/設定.json", ".git/config", "原本/x.json",
                                   "記録/版/x.json", "記録/制度データ/省力化_第8回_v2.json", "../外.json"])
def test_out_cannot_be_given(company, place) -> None:
    """置き場所は渡せない（前の版の --out は無くした）。守る場所にも、版の名前にも、外にも書かない。"""
    for rel in (".claude", ".git", "原本"):
        (company.folder / rel).mkdir(exist_ok=True)
    (company.folder / ".claude" / "settings.json").write_text('{"permissions": {"deny": ["Edit(/原本/**)"]}}\n', encoding="utf-8")
    before = hr.snapshot(company.folder)
    outside = company.env.outside()
    r = company.run(good_chapter(), "--out", place)
    assert r.returncode == 2, text(r)   # 知らない引数（argparse が stderr に使い方を出す）
    assert hr.snapshot(company.folder) == before
    assert company.env.outside() == outside
    assert not (company.env.root / "外.json").exists()


@pytest.mark.parametrize("chapter", ["1 補助の上限_v2", "1 補助の上限（最終）", "1 補助の上限 修正版", "1 補助の上限のコピー",
                                     "1 補助の上限 ver2", "1 補助の上限 copy"])
def test_version_words_in_chapter_name_are_refused(company, chapter) -> None:
    """章の名前で版のようなファイルを増やさない（DESIGN 5章「版のファイルを増やさない」）。"""
    data = good_chapter()
    data["読み取り"]["章"] = chapter
    before = hr.snapshot(company.folder)
    out = check_code(company.run(data), 2)
    assert "版の名前の語" in out and "何も書いていません" in out
    assert hr.snapshot(company.folder) == before


@pytest.mark.parametrize("chapter", ["../../../.claude/settings", "..", "../原本/x", "a/../../b"])
def test_chapter_name_cannot_leave_the_place(company, chapter) -> None:
    """章の名前に「/」や「..」があっても、記録/制度データ/読み取り/<案件>/ の外に書かない。"""
    data = good_chapter()
    data["読み取り"]["章"] = chapter
    before = hr.snapshot(company.folder)
    r = company.run(data)
    after = hr.snapshot(company.folder)
    for path in changed(before, after):
        rel = Path(path).relative_to(company.folder)
        assert rel.parts[:2] == ("記録", "制度データ"), rel
        assert len(rel.parts) <= 5, rel
    assert r.returncode in (0, 2), text(r)


def test_alias_folder_cannot_redirect_the_place(company) -> None:
    """記録/制度データ が別名で .claude/ を指していても、そこに書かない。"""
    claude = company.folder / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{}\n", encoding="utf-8")
    seido = company.folder / "記録" / "制度データ"
    os.symlink(claude, seido)
    before = hr.snapshot(company.folder, claude)
    out = check_code(company.run(good_chapter()), 2)
    assert "記録/制度データ/ の中の JSON になりません" in out and "何も書いていません" in out
    assert hr.snapshot(company.folder, claude) == before


def test_input_file_must_be_inside(company) -> None:
    """読み取りの結果のファイルは、会社のフォルダの中のものだけを読む。"""
    secret = company.work / "secret.json"
    secret.write_text(json.dumps(good_chapter(), ensure_ascii=False), encoding="utf-8")
    before = hr.snapshot(company.folder)
    for given in (str(secret), "../作業/secret.json"):
        out = check_code(company.run(input_file=Path(given)), 2)
        assert "会社のフォルダの外" in out and "何も書いていません" in out
    # 別名で外を指すファイルも読まない
    link = company.folder / "記録" / "入力.json"
    os.symlink(secret, link)
    out = check_code(company.run(input_file=link), 2)
    assert "会社のフォルダの外" in out
    link.unlink()
    assert hr.snapshot(company.folder) == before
    # 中のファイルは読む（相対の場所は会社のフォルダから）
    inner = company.folder / "記録" / "入力.json"
    inner.write_text(json.dumps(good_chapter(), ensure_ascii=False), encoding="utf-8")
    check_code(company.run(input_file=Path("記録/入力.json")), 0)
    assert (company.folder / OUT_REL).is_file()


# ---- 道具の動き：読み直して通す ----


def test_rerun_does_not_repeat_notes(company) -> None:
    data = good_chapter()
    for _path, change, _word in INJECTED[:3]:
        change(data["制度データ"])
    check_code(company.run(data), 1)
    first = company.out()
    # 置いた結果を、そのままもう一度通す（何度通しても同じ）
    merge_keys = ("前の結果に差し替えた項目", "前の結果のまま残した項目")
    for _ in range(2):
        check_code(company.run(first), 1)
        second = company.out()
        assert second["制度データ"] == first["制度データ"]
        assert {k: v for k, v in second["裏取り"].items() if k not in merge_keys} == first["裏取り"]
        # 章の全体を渡したので、どの項目も差し替わり、前の結果のまま残した項目はない
        assert [r["項目"] for r in second["裏取り"]["前の結果に差し替えた項目"]] == list(first["制度データ"])
        assert second["裏取り"]["前の結果のまま残した項目"] == []


def test_fixed_value_is_no_longer_check(company) -> None:
    """前の結果の外れた値を直して通し直すと、直した値は読み取り役の状態に戻り、古い注記は消える。直していない値は要確認のまま。"""
    data = good_chapter()
    for _path, change, _word in INJECTED[:3]:
        change(data["制度データ"])
    get(data["制度データ"], ("補助額", 0, "上限"))["注記"] = "読み取り役のメモ"
    check_code(company.run(data), 1)
    saved = company.out()
    fixed = get(saved["制度データ"], ("補助額", 0, "上限"))
    assert fixed["状態"] == "要確認" and "裏取り：" in fixed["注記"]
    fixed["出典"][0]["ページ"] = 1  # 出典のページを直す
    out = check_code(company.run(saved), 1)
    again = company.out()
    node = get(again["制度データ"], ("補助額", 0, "上限"))
    assert node["状態"] == "確認済み" and node["注記"] == "読み取り役のメモ", node
    for path in (("補助額", 1, "上限"), ("補助額", 0, "補助率")):
        node = get(again["制度データ"], path)
        assert node["状態"] == "要確認" and node["注記"].count("裏取り：") == 1, (path, node)
    assert len(again["裏取り"]["要確認にした値"]) == 2
    assert "補助額「従業員3人まで」の上限" not in out
    # 読み取り役が要確認とした値は、外れなくても要確認のまま（道具は上げない）
    assert get(again["制度データ"], ("補助額", 1, "特例", 0, "値"))["状態"] == "要確認"


def test_reread_replaces_only_the_given_items(company) -> None:
    """外れた項目だけを読み直して通すと、その項目だけが差し替わり、ほかの項目は前の結果のまま残る。"""
    data = good_chapter()
    for path, change, _word in INJECTED:
        if path[0] in ("決まった期日", "数値の要件"):
            change(data["制度データ"])
    check_code(company.run(data), 1)
    first = company.out()
    keys = list(first["制度データ"])
    # 決まった期日だけを読み直した（項目ごと全部）
    reread = {"読み取り": {"章": CHAPTER, "読んだページ": [{"資料": "要領T", "ページ": 2}, {"資料": "日程表"}]},
              "制度データ": {"決まった期日": good_chapter()["制度データ"]["決まった期日"]},
              "メモ": ["決まった期日を読み直した"]}
    out = check_code(company.run(reread), 1)  # 数値の要件は、まだ外れている
    second = company.out()
    assert list(second["制度データ"]) == keys   # どの項目も消えない
    assert second["制度データ"]["決まった期日"] == good_chapter()["制度データ"]["決まった期日"]
    for key in keys:
        if key != "決まった期日":
            assert second["制度データ"][key] == first["制度データ"][key], key
    assert "差し替えました：決まった期日（3件 → 3件）" in out
    assert "前の結果のまま残した項目（照らし直しました）：資料どうしの食い違い、補助額" in out
    assert second["裏取り"]["前の結果に差し替えた項目"] == [{"項目": "決まった期日", "前の件数": 3, "今の件数": 3}]
    assert second["メモ"] == ["特例の条件は別の章にある", "決まった期日を読み直した"]
    assert {"資料": "要領T", "ページ": 1, "終わりのページ": 4} in second["読み取り"]["読んだページ"]
    assert {"資料": "要領T", "ページ": 2} in second["読み取り"]["読んだページ"]
    assert len(second["裏取り"]["要確認にした値"]) == 2   # 数値の要件の2つだけ
    assert second["裏取り"]["出典つき値"] == 21          # 章の全体を照らし直す
    # 残りも読み直すと、外れた値はなくなる
    reread["制度データ"] = {"数値の要件": good_chapter()["制度データ"]["数値の要件"]}
    out = check_code(company.run(reread), 0)
    assert "根拠の文はどれも出典のページにあり" in out
    assert company.out()["裏取り"]["状態ごとの数"] == {"確認済み": 19, "要確認": 1, "読み取れない": 1}


def test_broken_previous_result_is_kept(company) -> None:
    """前の結果が読めないときは、上書きせずに何も書かない。"""
    check_code(company.run(good_chapter()), 0)
    path = company.folder / OUT_REL
    path.write_text("{ 壊れた", encoding="utf-8")
    before = hr.snapshot(company.folder)
    out = check_code(company.run(good_chapter()), 2)
    assert "前の結果" in out and "何も書いていません" in out
    assert hr.snapshot(company.folder) == before


def test_second_reading_is_kept_apart(company) -> None:
    data = good_chapter()
    data["読み取り"]["回目"] = 2
    check_code(company.run(data), 0)
    assert (company.folder / READING_REL / f"{CHAPTER}_2回目.json").is_file()
    assert not (company.folder / OUT_REL).exists()


# ---- 道具の動き：照らせる値がない・補助プログラムが動かない ----


def test_nothing_to_check_is_not_reported_as_all_good(company) -> None:
    data = {"読み取り": {"章": "加点", "読んだページ": [{"資料": "要領T", "ページ": 4}]},
            "制度データ": {"数値の要件": [{"名前": "x", "基準": {"値": None, "状態": "読み取れない", "理由": "この章にない"}}]}}
    out = check_code(company.run(data), 0)
    assert "照らせる値がありませんでした" in out and "根拠の文はどれも" not in out
    assert "照らした値：0" in out


def test_broken_helper_exits_3(company) -> None:
    """補助プログラムが動かない・途中で止まったときは、外れた値があるとき（1）と分けて 3 を返す。"""
    shutil.rmtree(company.env.plugin / "schema")
    before = hr.snapshot(company.folder)
    out = check_code(company.run(good_chapter()), 3)
    assert "裏取りの途中で止まりました" in out
    assert hr.snapshot(company.folder) == before
    out = check_code(company.run(args=["--form", "補助額"]), 3)
    assert "形を出せませんでした" in out
    (company.env.plugin / "lib" / "urakadori.py").write_text("raise ImportError('壊れた')\n", encoding="utf-8")
    out = check_code(company.run(good_chapter()), 3)
    assert "補助プログラムを読み込めませんでした" in out


def test_form_for_reading_role(company) -> None:
    r = company.run(args=["--form", "補助額", "決まった期日"])
    form = json.loads(check_code(r, 0))
    assert set(form["制度データの項目"]) == {"補助額", "決まった期日"}
    assert {"出典つき値", "出典", "出典の一覧", "出典つきの金額", "出典つきの補助率", "期日の形", "日時"} <= set(form["$defs"])
    # 形だけで、読み取り役の結果を確かめられる（ほかの $defs に頼らない）
    for key in ("補助額", "決まった期日"):
        schema = dict(form["制度データの項目"][key], **{"$defs": form["$defs"]})
        Draft202012Validator.check_schema(schema)
        assert Draft202012Validator(schema).is_valid(good_chapter()["制度データ"][key])
    wrapper = dict(form["読み取りの結果の形"], **{"$defs": form["$defs"]})
    assert Draft202012Validator(wrapper).is_valid(good_chapter())
    out = check_code(company.run(args=["--form", "補助金額"]), 2)
    assert "制度データにない項目" in out


# ---- 制度データの全体 ----


def write_list(company: Company, seido: dict) -> None:
    path = company.texts() / "資料の一覧.json"
    path.write_text(json.dumps({"案件": CASE, "制度": seido, "資料": []}, ensure_ascii=False), encoding="utf-8")


def test_full_seido_data(company) -> None:
    """制度データの全体（正解の下書き）を通す。全体の形で確かめ、置き場所は 記録/制度データ/<制度の略称>_<公募回>.json。
    出典の資料がこの案件にないので、出典つきの値はすべて要確認になる。"""
    answer = json.loads(ANSWER.read_text(encoding="utf-8"))
    write_list(company, {"名前": answer["制度"]["名前"], "略称": "省力化", "枠": "一般型", "種類": "補助金", "公募回": "第9回"})
    before = hr.snapshot(company.folder)
    out = check_code(company.run(answer), 1)
    assert "制度データの全体" in out and "置き場所：記録/制度データ/省力化_第8回.json" in out
    rel = Path("記録") / "制度データ" / "省力化_第8回.json"
    made = {str(company.folder / p) for p in (Path("記録") / "制度データ", rel)}
    assert changed(before, hr.snapshot(company.folder)) == made
    saved = company.out(rel)
    nodes = [n for _p, n in value_nodes(saved)]
    unreadable = [n for n in nodes if n["状態"] == "読み取れない"]
    assert len(unreadable) == 16
    assert all(n["状態"] == "要確認" for n in nodes if n["状態"] != "読み取れない")
    # 出典のない値は0件（読み取れない値のほかは、すべて出典と根拠の文がある）
    assert all(n.get("出典") and n.get("根拠の文") for n in nodes if n["状態"] != "読み取れない")
    assert Draft202012Validator(SCHEMA).is_valid(saved)
    # もう一度通しても同じ（注記が増えない）
    check_code(company.run(saved), 1)
    assert company.out(rel) == saved
    # 全体の形が合わなければ何も書かない
    del answer["補助額"]
    before = hr.snapshot(company.folder)
    out = check_code(company.run(answer), 2)
    assert "（全体）：「補助額」がありません" in out
    assert hr.snapshot(company.folder) == before


@pytest.mark.parametrize("name,expected", [
    ("中小企業省力化投資補助金", "中小企業省力化投資補助金_第8回.json"),  # 資料の一覧の制度と名前が違うときは、制度の名前
    ("../../.claude/settings", "・..・.claude・settings_第8回.json"),   # 「/」は使えない文字なので、記録/制度データ/ の中に置く
])
def test_full_seido_data_name(company, name, expected) -> None:
    answer = json.loads(ANSWER.read_text(encoding="utf-8"))
    answer["制度"]["名前"] = name
    write_list(company, {"名前": "別の補助金", "略称": "別", "公募回": "第8回"})
    before = hr.snapshot(company.folder)
    check_code(company.run(answer), 1)
    rel = Path("記録") / "制度データ" / expected
    assert changed(before, hr.snapshot(company.folder)) == {str(company.folder / p) for p in (Path("記録") / "制度データ", rel)}


def test_full_seido_data_with_version_words_is_refused(company) -> None:
    answer = json.loads(ANSWER.read_text(encoding="utf-8"))
    answer["制度"]["公募回"] = "第8回_最終"
    before = hr.snapshot(company.folder)
    out = check_code(company.run(answer), 2)
    assert "版の名前の語" in out
    assert hr.snapshot(company.folder) == before


# ---- 実物の小さな資料（公募要領 第8回の補助額のページ） ----

_AMOUNT = re.compile(r"(\d[\d,]*)万円|(\d+)億円")


def amounts(line: str) -> set:
    found = set()
    for m in _AMOUNT.finditer(re.sub(r"\s+", "", line)):
        if m.group(1):
            found.add(int(m.group(1).replace(",", "")) * 10000)
        else:
            found.add(int(m.group(2)) * 100000000)
    return found


@pytest.fixture
def real_company(tmp_path) -> Company:
    if not YORYO8.is_file():
        pytest.skip("downloads/ に公募要領（第8回）がありません（公式資料を取ってから流す）")
    c = Company(tmp_path)
    index = c.add_doc("要領8", "公募要領", YORYO8)
    assert index["ずれ"] == 0
    return c


def test_real_guideline_page(real_company) -> None:
    """正解の補助額（要領8 p.9 の上限と特例の上限）を、その場でページから拾った行を根拠の文にして照らす。"""
    answer = json.loads(ANSWER.read_text(encoding="utf-8"))
    page = (real_company.texts() / "要領8" / "ページ_009.txt").read_text(encoding="utf-8")
    lines = [l for l in page.splitlines() if l.strip()]
    rate_line = next(l for l in lines if "1/2" in l)
    items = []
    for item in answer["補助額"]:
        values = [item["上限"]["値"]] + [t["値"]["値"] for t in item.get("特例", []) if t["種類"] == "上限の置き換え"]
        assert all(any({"資料": "要領8", "ページ": 9} == s for s in item["上限"]["出典"]) for _v in values)
        line = next(l for l in lines if set(values) <= amounts(l))   # 上限と特例の上限が並ぶ行
        items.append({"区分": item["区分"],
                      "上限": sv(values[0], "要領8", 9, line),
                      "補助率": sv(item["補助率"]["値"], "要領8", 9, rate_line),
                      "特例": [{"名前": "特例の上限", "種類": "上限の置き換え", "値": sv(v, "要領8", 9, line)} for v in values[1:]]})
    assert len(items) == 5
    chapter = "1-4 補助対象事業"
    data = {"読み取り": {"章": chapter, "読んだページ": [{"資料": "要領8", "ページ": 9}]}, "制度データ": {"補助額": items}}
    out = check_code(real_company.run(data), 0)
    assert "出典つき値：15（確認済み 15" in out

    saved_rel = Path("記録") / "制度データ" / "読み取り" / CASE / f"{chapter}_1回目.json"
    # 出典のページを1つ前にする → すべて要確認（同じ章なので、補助額の項目が差し替わる）
    moved = copy.deepcopy(data)
    for _p, node in value_nodes(moved["制度データ"]):
        node["出典"][0]["ページ"] = 8
    out = check_code(real_company.run(moved), 1)
    assert "出典つき値：15（確認済み 0、要確認 15" in out
    # 値を変える（ページと文はそのまま） → 変えた値だけが要確認
    changed_data = copy.deepcopy(data)
    for item in changed_data["制度データ"]["補助額"]:
        item["上限"]["値"] += 10000  # 1万円だけ違う
    out = check_code(real_company.run(changed_data), 1)
    assert "出典つき値：15（確認済み 10、要確認 5" in out
    saved = real_company.out(saved_rel)
    assert all(i["上限"]["状態"] == "要確認" and "が根拠の文にありません" in i["上限"]["注記"] for i in saved["制度データ"]["補助額"])
    # 単位をかける前の数（万円の数）を上限にしても通さない
    unit = copy.deepcopy(data)
    for item in unit["制度データ"]["補助額"]:
        item["上限"]["値"] //= 10000
    out = check_code(real_company.run(unit), 1)
    assert "出典つき値：15（確認済み 10、要確認 5" in out
