"""T13-4 記録から書いた箇所（SPEC F13「記録から書いた箇所は根拠対照表で分かるようにする」、DESIGN 10章
「書くとき：記録から書いた箇所は、根拠対照表に記録の項目として残る」、TASKS B3）。

合格ライン：2件目の根拠対照表を見る → 記録から書いた箇所すべてに、出典として記録の項目が示される。

流れ（2件目＝持続化の入力シートを書く場面）：
1. 1件目（省力化）で、事実（書類から・聞き取りから・社長の発言から）を会社の記録に残す。
2. 2件目で、書く前の取り出し（relevant_records.py）が、事実ごとに「根拠対照表の出典」（会社の記録 <id>（名前））を返す。
3. 記録から書いた値を、根拠対照表の道具（kakunin.py konkyo）で残す。出典には、取り出しが返した記録の項目を書く
   （id だけを書いても、道具が名前付きの形にそろえる。書類の出典と並べて書いてもよい）。
4. できた根拠対照表.xlsx を読むと、記録から書いた行のすべてで、出典が記録の項目（id と名前）になっている。

道具は、記録にない id や、id のない「会社の記録」を出典にした行を断る（何も書かない）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from test_kiroku_min import RECORD, RELEVANT, run, set_today  # noqa: F401

from lib import company_record, konkyo

KAKUNIN = Path("skills") / "kaku" / "scripts" / "kakunin.py"
CASE2 = "2026_持続化（一般型・通常枠）第20回"
APP = f"案件/{CASE2}/1_申請/申請書"
EVIDENCE = f"{APP}/{konkyo.FILE_NAME}"


@pytest.fixture
def c(tmp_path: Path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    for plugin in (c.env.plugin, c.plugin):
        shutil.copytree(hr.REPO_ROOT / "schema", plugin / "schema")
    set_today(c, "2026-11-04")
    # 1件目で学んだこと
    c.write("原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf", b"%PDF-1.4 dummy")
    ct.ok(run(c, RECORD, "add-fact", "--name", "資本金", "--value", "1,000万円", "--changeable", "--source", "原本",
              "--file", "原本/登記・名簿/2026-10-22_履歴事項全部証明書.pdf", "--page", "1"))
    ct.ok(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable", "--source", "質問",
              "--question", "常時使用する従業員は何人ですか"))
    ct.ok(run(c, RECORD, "add-fact", "--name", "会社名", "--value", "株式会社やまぶき惣菜", "--fixed",
              "--source", "社長の発言", "--utterance", "うちは株式会社やまぶき惣菜です"))
    ct.ok(run(c, RECORD, "add-fact", "--name", "強み", "--value", "病院・介護施設ごとの細かい注文に応えられる",
              "--changeable", "--source", "社長の発言", "--utterance", "細かい注文に応えられるのが強み"))
    c.stop()
    # 2件目：持続化の段階のフォルダ
    (c.folder / APP).mkdir(parents=True)
    set_today(c, "2026-12-01")
    return c


def write_rows(c: vt.Company, rows: list):
    path = c.folder / "記録" / "一時" / "根拠.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import json
    path.write_text(json.dumps({"行": rows}, ensure_ascii=False), encoding="utf-8")
    return run(c, KAKUNIN, "konkyo", "--case", CASE2, "--input", "記録/一時/根拠.json")


def test_rows_written_from_the_record_show_the_record_item(c: vt.Company) -> None:
    import json

    found = json.loads(ct.ok(run(c, RELEVANT, "--item", "常時使用する従業員数", "--item", "企業概要", "--json")))
    facts = {f["名前"]: f for f in found["事実"]}
    # 記録から書いた値（取り出しが返した出典をそのまま書く行と、id だけを書いた行と、書類と並べた行）
    rows = [
        {"記述": "15人", "種類": "数字", "書いた場所": "応募者概要入力：常時使用する従業員数",
         "出典": facts["従業員の数"]["根拠対照表の出典"]},
        {"記述": "株式会社やまぶき惣菜", "種類": "固有名詞", "書いた場所": "基本情報入力：法人名/屋号",
         "出典": f"会社の記録 {facts['会社名']['id']}"},
        {"記述": "1,000万円", "種類": "数字", "書いた場所": "応募者概要入力：資本金額",
         "出典": f"会社の記録：{facts['資本金']['id']}（履歴事項全部証明書 1ページ）"},
        {"記述": "病院・介護施設ごとの細かい注文", "種類": "そのほか", "書いた場所": "経営計画入力：3.自社の強み",
         "出典": f"会社の記録 {facts['強み']['id']}（強み）、商品のご案内.pdf 2ページ"},
        # 記録からではない行（書類だけ）はそのまま
        {"記述": "2026年12月15日", "種類": "日付", "書いた場所": "補助事業計画入力：実施期間", "出典": "公募要領 第20回 p.22"},
    ]
    out = ct.ok(write_rows(c, rows))
    assert "5行を足しました" in out

    table = konkyo.read((c.folder / EVIDENCE).read_bytes())
    by_text = {r["記述"]: r for r in table}
    record_rows = {"15人": "従業員の数", "株式会社やまぶき惣菜": "会社名", "1,000万円": "資本金",
                   "病院・介護施設ごとの細かい注文": "強み"}
    for text, name in record_rows.items():
        fact = facts[name]
        label = f"会社の記録 {fact['id']}（{name}）"
        assert label in by_text[text]["出典"], (text, by_text[text]["出典"])
    # 書類の出典と並べた行は、書類の出典も残る。書いた人が添えた補足も残り、名前と同じ補足は重ねない
    assert "商品のご案内.pdf 2ページ" in by_text["病院・介護施設ごとの細かい注文"]["出典"]
    assert by_text["1,000万円"]["出典"] == f"会社の記録 {facts['資本金']['id']}（資本金）（履歴事項全部証明書 1ページ）"
    assert by_text["病院・介護施設ごとの細かい注文"]["出典"].count("（強み）") == 1
    assert by_text["2026年12月15日"]["出典"] == "公募要領 第20回 p.22"
    # 記録から書いた箇所のすべてが、記録の項目を出典に持つ（記録の事実の値が入った行を、表から数え直す）
    values = {company_record.value_text(f["値"]): f for f in found["事実"]}
    for row in table:
        for value, fact in values.items():
            if row["記述"] and row["記述"] in value:
                assert f"会社の記録 {fact['id']}（{fact['名前']}）" in row["出典"], row


def test_unknown_record_item_or_missing_id_is_refused(c: vt.Company) -> None:
    r = write_rows(c, [{"記述": "15人", "種類": "数字", "書いた場所": "応募者概要入力", "出典": "会社の記録 事実-0099"}])
    assert r.returncode == 2 and "事実-0099 は、会社の記録にありません" in r.stdout.decode("utf-8")
    r = write_rows(c, [{"記述": "15人", "種類": "数字", "書いた場所": "応募者概要入力", "出典": "会社の記録"}])
    assert r.returncode == 2 and "会社の記録の項目の id" in r.stdout.decode("utf-8")
    assert not (c.folder / EVIDENCE).exists()  # 何も書かない
