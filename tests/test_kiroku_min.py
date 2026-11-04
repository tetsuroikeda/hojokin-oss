"""事実を1つ記録して、2件目で使う（最小限。TASKS M11。SPEC F13、DESIGN 4.7 の5・10章）。

- kiroku の記録の道具（skills/kiroku/scripts/record.py）で、1件目（省力化）の聞き取りで分かった事実を、
  出典（質問と答えた日）と覚えた日を付けて `記録/会社の記録.json` に残す。
- 2件目（持続化）の日付で開くと、開いたときの情報（SessionStart）に記録の要約（変わりうる情報、最近増えた決まり）が入る。
- kaku の取り出しの道具（skills/kaku/scripts/relevant_records.py）が、書く項目に関係する事実を先に並べ、
  出典・覚えた日・根拠対照表の出典と、変わりうる情報の確かめ方（「前回は◯でしたが、変わりましたか」）を返す。

道具は Claude が Bash で動かすのと同じ形（/usr/bin/python3 -B、CLAUDE_* の環境変数なし、PATH は python3 と sh だけ）で、
hook は hooks.json のコマンドで動かす（tests/version_tool.py）。会社のフォルダは会社のフォルダを作る道具で用意する。
書いた記録は、毎回、本物の JSON Schema（jsonschema）でも確かめる（道具の中の小さな確かめとずれないように）。

確かめること：
- 足した事実が、名前・値・変わりうるか・出典・覚えた日・最後に確かめた日・状態を持ち、スキーマに合う。
- 応答の終わりに、記録の変更が「ツール」の版として残る。取り出しの道具は、会社のフォルダを何も変えない。
- 同じ名前で違う値は、上書きせずに終了コード2で両方を出典付きで出す。同じ値は、最後に確かめた日だけを今日にする。
- 出典の書類は会社のフォルダからの場所で残し、外・ない・ツールの置き場の中・外を指す別名は断る。
- 記録がない・読めない・形が違うときも、開いたときの hook は落ちず、読めないことを伝える。
- 要約の長さは上限まで。古い決まりは「最近増えた」に出ない。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest
import version_tool as vt
from jsonschema import Draft202012Validator

from lib import company_record, schema_check

RECORD = Path("skills") / "kiroku" / "scripts" / "record.py"
RELEVANT = Path("skills") / "kaku" / "scripts" / "relevant_records.py"
RECORD_FILE = "記録/会社の記録.json"
SCHEMA = json.loads((hr.REPO_ROOT / "schema" / "会社の記録.schema.json").read_text(encoding="utf-8"))
DOCS = hr.REPO_ROOT / "testdata" / "デモの会社" / "書類"

CASE1_DAY = "2026-11-04"  # 1件目（省力化）の聞き取りの日
CASE2_DAY = "2026-12-01"  # 2件目（持続化）を書き始める日
QUESTION = "常時使用する従業員は何人ですか（役員は入れません）。補助の上限と要件の判定に使います"
EMPLOYEES = "15人（正社員7人、パート8人。役員の2人は入れない）"


@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    # 道具と hook の写しに、会社の記録の形（schema/）も入れる（プラグインには schema/ がある。DESIGN 4.5）
    for plugin in (c.env.plugin, c.plugin):
        shutil.copytree(hr.REPO_ROOT / "schema", plugin / "schema")
    set_today(c, CASE1_DAY)
    return c


def set_today(c: vt.Company, day: str) -> None:
    settings = c.folder / ".hojokin" / "設定.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
    data["今日の日付"] = day
    settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def run(c: vt.Company, script: Path, *args: str, folder: Path = None) -> subprocess.CompletedProcess:
    """道具を、Claude が Bash で動かすのと同じ形で動かす。"""
    env = {"PATH": c.env.path, "HOME": str(c.env.home), "TMPDIR": str(c.env.tmp)}
    return subprocess.run(
        [hr.real_python(), "-B", str(c.env.plugin / script), *args, "--folder", str(folder or c.folder)],
        env=env, cwd=c.env.cwd, capture_output=True, timeout=120,
    )


def refused(r: subprocess.CompletedProcess) -> str:
    out = r.stdout.decode("utf-8")
    assert r.returncode == 2, (r.returncode, out, r.stderr.decode("utf-8"))
    assert r.stderr == b"", r.stderr.decode("utf-8")
    assert "Traceback" not in out
    return out


def record(c: vt.Company) -> dict:
    """会社の記録を読み、本物の JSON Schema でも確かめる。"""
    data = json.loads((c.folder / RECORD_FILE).read_text(encoding="utf-8"))
    errors = sorted(e.message for e in Draft202012Validator(SCHEMA).iter_errors(data))
    assert errors == [], errors
    return data


def add_employees(c: vt.Company) -> str:
    return ct.ok(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", EMPLOYEES, "--changeable",
                     "--source", "質問", "--question", QUESTION))


def relevant_json(c: vt.Company, *items: str) -> dict:
    args = []
    for item in items:
        args += ["--item", item]
    return json.loads(ct.ok(run(c, RELEVANT, *args, "--json")))


def files(folder: Path) -> dict:
    """会社のフォルダのファイル（版の履歴とその場限りの置き場を除く）の中身。"""
    found = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if rel.startswith((".git/", ".hojokin/一時/")) or not p.is_file():
            continue
        found[rel] = p.read_bytes()
    return found


# ---- 1件目で記録し、2件目で使う ----

def test_fact_recorded_in_case1_is_used_in_case2(company):
    c = company
    # 1件目（省力化）：書く前の質問の答えを、記録の道具で残す
    c.say("従業員は15人です。正社員7人とパート8人で、役員の2人は入れていません")
    out = add_employees(c)
    assert "覚えました" in out and "[事実-0001]" in out and f"覚えた日 {CASE1_DAY}" in out

    data = record(c)
    assert data["スキーマの版"] == 1
    assert data["項目"] == [{
        "id": "事実-0001", "種類": "事実", "名前": "従業員の数", "値": EMPLOYEES, "変わりうる": True,
        "出典": {"種類": "質問", "質問": QUESTION, "答えた日": CASE1_DAY},
        "覚えた日": CASE1_DAY, "最後に確かめた日": CASE1_DAY, "状態": "有効",
    }]

    # 応答の終わりに、記録の変更が「ツール」の版として残る（変更の履歴は版の履歴から作る。DESIGN 10章）
    c.stop()
    log = c.log(RECORD_FILE)
    assert len(log) == 1 and log[0]["だれ"] == "ツール" and log[0]["変更"] == "足した", log
    assert c.pending() == []

    # 2件目（持続化）の日付で開く：記録の要約が、開いたときの情報に入る
    set_today(c, CASE2_DAY)
    context = vt.start_context(c.start())
    assert "会社の記録（記録/会社の記録.json）の要約：事実 1件、書き方の決まり 0件" in context
    assert f"従業員の数＝15人（正社員7人、パート8人。役員の2人は入れない）（最後に確かめた日 {CASE1_DAY}。" in context
    assert "今日はまだ確かめていない" in context
    assert "「前回は◯でしたが、変わりましたか」と確かめる" in context
    assert "relevant_records.py" in context
    c.stop()

    # kaku が2件目の項目を書く前に取り出す：記録の事実が、出典・覚えた日・根拠対照表の出典つきで返る
    before = files(c.folder)
    found = relevant_json(c, "常時使用する従業員数")
    assert found["今日"] == CASE2_DAY and found["項目"] == ["常時使用する従業員数"]
    fact = found["事実"][0]
    assert fact["id"] == "事実-0001" and fact["当たる"] is True
    assert fact["値"] == EMPLOYEES
    assert fact["出典"] == {"種類": "質問", "質問": QUESTION, "答えた日": CASE1_DAY}
    assert fact["覚えた日"] == CASE1_DAY and fact["最後に確かめた日"] == CASE1_DAY
    assert fact["根拠対照表の出典"] == "会社の記録 事実-0001（従業員の数）"
    # 変わりうる情報は、使い回す前に確かめる（SPEC F13「変わりうる情報は確認する」）
    assert fact["使う前に確かめる"] is True
    assert fact["確かめ方"] == f"前回は「{EMPLOYEES}」でしたが、変わりましたか"

    text = ct.ok(run(c, RELEVANT, "--item", "常時使用する従業員数"))
    assert "## この項目に当たりそうな事実（1件）" in text
    assert f"- [事実-0001] 従業員の数：{EMPLOYEES}" in text
    assert f"出典：質問「{QUESTION}」（答えた日 {CASE1_DAY}）。覚えた日 {CASE1_DAY}" in text
    assert f"使い回す前に「前回は「{EMPLOYEES}」でしたが、変わりましたか」と確かめる" in text
    assert "根拠対照表の出典：会社の記録 事実-0001（従業員の数）" in text
    assert files(c.folder) == before  # 取り出しは何も変えない

    # 社長が「変わっていない」と答えた：確かめた日を今日にし、もう確かめ直さない
    out = ct.ok(run(c, RECORD, "confirm", "--id", "事実-0001"))
    assert f"確かめた日を {CASE2_DAY} にしました" in out
    item = record(c)["項目"][0]
    assert item["最後に確かめた日"] == CASE2_DAY and item["覚えた日"] == CASE1_DAY and item["値"] == EMPLOYEES
    again = relevant_json(c, "常時使用する従業員数")["事実"][0]
    assert again["使う前に確かめる"] is False and again["確かめ方"] == ""
    assert "今日確かめた（聞き直さない）" in ct.ok(run(c, RELEVANT, "--item", "常時使用する従業員数"))


def test_relevant_puts_matching_facts_first_and_adds_rules(company):
    c = company
    ct.ok(run(c, RECORD, "add-fact", "--name", "本店と工場の所在地", "--value", "本店と工場は同じ場所で、事業所は1か所",
              "--fixed", "--source", "社長の発言", "--utterance", "本店と工場は同じ場所です"))
    add_employees(c)
    ct.ok(run(c, RECORD, "add-fact", "--name", "いちばん低い時給", "--value", "1,330円（2026年10月1日から）",
              "--changeable", "--source", "質問", "--question", "いちばん低い時給はいくらですか"))
    ct.ok(run(c, RECORD, "add-fact", "--name", "資本金", "--value", "10000", "--json-value", "--fixed",
              "--source", "質問", "--question", "資本金はいくらですか（千円）"))
    ct.ok(run(c, RECORD, "add-rule", "--kind", "避けたい言い方", "--content", "「させていただく」を使わない",
              "--trigger", "させていただく、はやめて", "--case", "2026_省力化（一般型）第9回",
              "--source", "社長の発言", "--utterance", "させていただく、はやめて"))
    data = record(c)
    assert [it["id"] for it in data["項目"]] == ["事実-0001", "事実-0002", "事実-0003", "事実-0004", "決まり-0001"]
    assert data["項目"][3]["値"] == 10000  # --json-value は数のまま残す

    found = relevant_json(c, "常時使用する従業員数", "事業場内最低賃金（時給）")
    hits = [f["名前"] for f in found["事実"] if f["当たる"]]
    assert hits == ["従業員の数", "いちばん低い時給"] or hits == ["いちばん低い時給", "従業員の数"], hits
    assert [f["名前"] for f in found["事実"][2:]] == ["本店と工場の所在地", "資本金"]  # 当たらない事実も後ろに並ぶ
    assert all(not f["当たる"] for f in found["事実"][2:])
    rule = found["書き方の決まり"][0]
    assert rule["区分"] == "避けたい言い方" and rule["内容"] == "「させていただく」を使わない"
    assert rule["きっかけ"] == {"発言や手直し": "させていただく、はやめて", "日付": CASE1_DAY,
                            "案件": "2026_省力化（一般型）第9回"}
    assert rule["根拠対照表の出典"] == "会社の記録 決まり-0001（避けたい言い方）"

    text = ct.ok(run(c, RELEVANT, "--item", "常時使用する従業員数"))
    assert "## そのほかの事実（3件。使うかは内容で判断する）" in text
    assert "## 書き方の決まり（1件。どの申請書にも当てる。避けたい言い方は使わない）" in text
    assert "[決まり-0001] 避けたい言い方：「させていただく」を使わない" in text

    # 項目を指さなければ、すべての事実を並べる
    every = relevant_json(c)
    assert len(every["事実"]) == 4 and not any(f["当たる"] for f in every["事実"])

    # 同じ区分・同じ内容の決まりは足さない
    out = ct.ok(run(c, RECORD, "add-rule", "--kind", "避けたい言い方", "--content", "「させていただく」を 使わない",
                    "--trigger", "またさせていただくが出た", "--source", "社長の発言", "--utterance", "また出ている"))
    assert "もう覚えています" in out
    assert len(record(c)["項目"]) == 5

    # 一覧（何を、いつ、どこから）
    listing = ct.ok(run(c, RECORD, "list"))
    assert "## 事実（4件）" in listing and "## 書き方の決まり（1件）" in listing
    assert f"[事実-0002] 従業員の数＝{EMPLOYEES}（出典：質問「{QUESTION}」（答えた日 {CASE1_DAY}）。覚えた日 {CASE1_DAY}" in listing


# ---- 食い違いは上書きしない ----

def test_conflicting_value_is_not_overwritten(company):
    c = company
    add_employees(c)
    roster = c.write("原本/登記・名簿/2026-10-01_労働者名簿.xlsx", (DOCS / "労働者名簿.xlsx").read_bytes())
    before = (c.folder / RECORD_FILE).read_bytes()

    out = refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "17人", "--changeable",
                      "--source", "原本", "--file", str(roster.relative_to(c.folder)), "--page", "1"))
    assert "食い違い" in out and "上書きしていません" in out
    assert f"- 記録：[事実-0001] 従業員の数＝{EMPLOYEES}（出典：質問「{QUESTION}」（答えた日 {CASE1_DAY}）" in out
    assert "- 新しい値：17人（出典：原本 原本/登記・名簿/2026-10-01_労働者名簿.xlsx 1ページ）" in out
    assert "update-fact --id 事実-0001" in out and "confirm --id 事実-0001" in out
    assert (c.folder / RECORD_FILE).read_bytes() == before

    # 同じ値（空白や全角・半角の違いだけ）は、最後に確かめた日だけを今日にする
    set_today(c, CASE2_DAY)
    out = ct.ok(run(c, RECORD, "add-fact", "--name", "従業員 の数", "--value", "15人（正社員7人、パート8人。役員の2人は 入れない）",
                    "--changeable", "--source", "社長の発言", "--utterance", "15人のままです"))
    assert "もう覚えています" in out
    item = record(c)["項目"][0]
    assert item["最後に確かめた日"] == CASE2_DAY and item["覚えた日"] == CASE1_DAY
    assert item["出典"]["種類"] == "質問"  # 出典は前のまま
    assert len(record(c)["項目"]) == 1

    # 社長が新しい値に決めた
    out = ct.ok(run(c, RECORD, "update-fact", "--id", "事実-0001", "--value", "17人（正社員8人、パート9人）",
                    "--source", "原本", "--file", "原本/登記・名簿/2026-10-01_労働者名簿.xlsx"))
    assert f"直しました：事実-0001 従業員の数＝{EMPLOYEES} → 17人（正社員8人、パート9人）" in out
    item = record(c)["項目"][0]
    assert item["値"] == "17人（正社員8人、パート9人）" and item["変わりうる"] is True
    assert item["出典"] == {"種類": "原本", "ファイル": "原本/登記・名簿/2026-10-01_労働者名簿.xlsx"}
    assert item["覚えた日"] == CASE2_DAY and item["最後に確かめた日"] == CASE2_DAY and item["状態"] == "有効"

    # ない id は断る
    assert "事実-0009 がありません" in refused(run(c, RECORD, "confirm", "--id", "事実-0009"))


# ---- 出典 ----

def test_source_files_are_kept_inside_the_company_folder(company, tmp_path):
    c = company
    paper = c.write("原本/決算・税/2025-04-01_決算書.pdf", (DOCS / "決算書_第18期.pdf").read_bytes())
    # 会社のフォルダの中なら、絶対の場所で渡しても、会社のフォルダからの場所で残す
    ct.ok(run(c, RECORD, "add-fact", "--name", "売上高（第18期）", "--value", "180,000千円", "--changeable",
              "--source", "原本", "--file", str(paper), "--page", "2"))
    item = record(c)["項目"][0]
    assert item["出典"] == {"種類": "原本", "ファイル": "原本/決算・税/2025-04-01_決算書.pdf", "ページ": 2}
    text = (c.folder / RECORD_FILE).read_text(encoding="utf-8")
    assert str(c.folder) not in text and str(tmp_path) not in text  # フォルダを移しても使える

    before = (c.folder / RECORD_FILE).read_bytes()
    outside = tmp_path / "外の決算書.pdf"
    outside.write_bytes(b"%PDF-1.4")
    link = c.folder / "原本" / "決算・税" / "別名.pdf"
    os.symlink(outside, link)
    c.write(".hojokin/メモ.txt", "x")
    cases = [
        (["--file", str(outside)], "会社のフォルダの外"),
        (["--file", "../外の決算書.pdf"], "会社のフォルダの外"),
        (["--file", "原本/決算・税/別名.pdf"], "会社のフォルダの外"),  # 別名の先が外
        (["--file", "原本/決算・税/ない.pdf"], "会社のフォルダにありません"),
        (["--file", ".hojokin/メモ.txt"], "ツールの置き場"),
        (["--file", "原本/決算・税/2025-04-01_決算書.pdf", "--page", "0"], "1以上"),
        ([], "--file"),
    ]
    for extra, word in cases:
        out = refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable",
                          "--source", "原本", *extra))
        assert word in out, (extra, out)
    # 出典の種類に要るものがない・合わない
    for extra, word in [
        (["--source", "質問"], "--question"),
        (["--source", "社長の発言"], "--utterance"),
        (["--source", "社長の発言", "--utterance", "x", "--page", "3"], "--page"),
        (["--source", "質問", "--question", "何人？", "--answered-date", "11月4日"], "2026-11-04"),
        (["--source", "推測"], "invalid choice"),
    ]:
        out = refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable", *extra))
        assert word in out, (extra, out)
    assert "--changeable" in refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人",
                                         "--source", "質問", "--question", "何人？"))
    assert (c.folder / RECORD_FILE).read_bytes() == before

    # フォルダごと別の場所に写しても、取り出しの結果は同じ
    moved = tmp_path / "移した先" / "やまぶき 惣菜"
    shutil.copytree(c.folder, moved, symlinks=True)
    assert json.loads(ct.ok(run(c, RELEVANT, "--json", folder=moved))) == relevant_json(c)


# ---- 開いたとき ----

def test_session_start_without_or_with_broken_record(company):
    c = company
    # 記録がまだなければ、何も足さない
    assert "会社の記録" not in vt.start_context(c.start())
    c.stop()

    # JSON として読めない（社長が手で直して崩れた など）：hook は落ちず、読めないことを伝える
    c.write(RECORD_FILE, '{"スキーマの版": 1, "項目": [')
    broken = (c.folder / RECORD_FILE).read_bytes()
    context = vt.start_context(c.start(source="resume"))
    assert "【hojokin】会社の記録を使えません" in context and "JSON として読めません" in context
    assert "前の版に戻す" in context
    # 道具も、崩れた記録を上書きしない
    out = refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable",
                      "--source", "質問", "--question", "何人？"))
    assert "JSON として読めません" in out
    assert (c.folder / RECORD_FILE).read_bytes() == broken
    assert "JSON として読めません" in refused(run(c, RELEVANT, "--item", "従業員数"))

    # 形が違う（出典がない）
    item = {"id": "事実-0001", "種類": "事実", "名前": "従業員の数", "値": "15人", "変わりうる": True,
            "覚えた日": CASE1_DAY, "最後に確かめた日": CASE1_DAY, "状態": "有効"}
    c.write(RECORD_FILE, json.dumps({"スキーマの版": 1, "項目": [item]}, ensure_ascii=False))
    context = vt.start_context(c.start(source="clear"))
    assert "形が合いません" in context and "項目[0]：「出典」がありません" in context

    # UTF-8 でない
    c.write(RECORD_FILE, "従業員".encode("shift_jis"))
    assert "UTF-8 の文字ではありません" in vt.start_context(c.start(source="compact"))


def test_summary_lists_recent_rules_and_stays_short(company):
    c = company
    add_employees(c)
    ct.ok(run(c, RECORD, "add-rule", "--kind", "書き方の方針", "--content", "数字は前年と比べて示す",
              "--trigger", "前の年と比べて書いて", "--source", "社長の発言", "--utterance", "前の年と比べて書いて"))
    # compact の後も渡す（前の要約が文脈から消えるため）
    context = vt.start_context(c.start(source="compact"))
    assert f"- 最近増えた書き方の決まり（30日以内）：書き方の方針「数字は前年と比べて示す」（{CASE1_DAY}）" in context
    assert "（最後に確かめた日 2026-11-04）" in context  # 今日確かめたものに「まだ確かめていない」は付けない
    c.stop()

    # 40日たつと「最近増えた」には出ない（件数は出る）
    set_today(c, "2026-12-14")
    context = vt.start_context(c.start())
    assert "書き方の決まり 1件" in context and "最近増えた" not in context
    c.stop()

    # 事実がたくさんあっても、要約は上限まで
    data = record(c)
    for i in range(2, 80):
        fact = copy.deepcopy(data["項目"][0])
        fact.update({"id": f"事実-{i:04d}", "名前": f"設備{i}の台数とその使い方の説明", "値": "あ" * 200})
        data["項目"].append(fact)
    c.write(RECORD_FILE, json.dumps(data, ensure_ascii=False))
    note = company_record.session_note(c.folder)
    assert len(note) <= company_record.SUMMARY_MAX_CHARS
    assert "ほか" in note and "relevant_records.py" in note
    assert note in vt.start_context(c.start(source="resume"))


# ---- 会社のフォルダでないとき ----

def test_tools_do_nothing_outside_a_company_folder(company, tmp_path):
    c = company
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    out = refused(run(c, RECORD, "add-fact", "--name", "従業員の数", "--value", "15人", "--changeable",
                      "--source", "質問", "--question", "何人？", folder=plain))
    assert "会社のフォルダではありません" in out
    assert "会社のフォルダではありません" in refused(run(c, RELEVANT, "--item", "従業員数", folder=plain))
    assert list(plain.iterdir()) == []


# ---- skill の手順 ----

def test_skills_tell_how_to_record_and_take_out():
    kiroku = (hr.REPO_ROOT / "skills" / "kiroku" / "SKILL.md").read_text(encoding="utf-8")
    kaku = (hr.REPO_ROOT / "skills" / "kaku" / "SKILL.md").read_text(encoding="utf-8")
    for word in ("record.py\" add-fact", "record.py\" add-rule", "record.py\" confirm", "record.py\" update-fact",
                 "record.py\" list", "上書き", "今回だけ"):
        assert word in kiroku, word
    for word in ("relevant_records.py", "--item", "前回は◯でしたが、変わりましたか", "根拠対照表", "record.py add-fact"):
        assert word in kaku, word
    for text in (kiroku, kaku):
        assert len(text.splitlines()) < 500  # DESIGN 4.2


# ---- 小さな形の確かめが、本物の JSON Schema と同じ答えを出す ----

def _valid_record() -> dict:
    return {"スキーマの版": 1, "項目": [
        {"id": "事実-0001", "種類": "事実", "名前": "従業員の数", "値": {"正社員": 7, "パート": 8}, "変わりうる": True,
         "出典": {"種類": "原本", "ファイル": "原本/登記・名簿/名簿.xlsx", "ページ": 1},
         "覚えた日": CASE1_DAY, "最後に確かめた日": CASE1_DAY, "状態": "食い違いあり"},
        {"id": "決まり-0001", "種類": "書き方の決まり", "区分": "構成", "内容": "結論を先に書く",
         "きっかけ": {"発言や手直し": "結論から", "日付": CASE1_DAY},
         "出典": {"種類": "社長の手直し", "ファイル": "案件/a/1_申請/申請書/その1.docx", "日付": CASE1_DAY},
         "覚えた日": CASE1_DAY},
        {"id": "不備-0001", "種類": "不備と差し戻し", "案件": "a", "手続きの段階": "2_交付申請", "内容": "見積書の日付",
         "原因": "古い見積書", "次に注意する書類": ["見積書"], "照合の決まり": "発行日が3か月以内",
         "出典": {"種類": "原本", "ファイル": "原本/役所からの通知/差し戻し.txt"}, "受け取った日": CASE1_DAY,
         "覚えた日": CASE1_DAY},
        {"id": "採否-0001", "種類": "申請と採否", "案件": "b", "結果": "不採択", "指摘された審査項目": ["市場性"],
         "出典": {"種類": "社長の発言", "発言": "落ちた", "日付": CASE1_DAY}, "通知の日": CASE1_DAY,
         "覚えた日": CASE1_DAY},
    ]}


def _broken_records() -> list:
    def change(fn):
        data = _valid_record()
        fn(data)
        return data

    items = lambda d: d["項目"]  # noqa: E731
    return [
        change(lambda d: d.pop("スキーマの版")),
        change(lambda d: d.update({"スキーマの版": True})),  # true と 1 は別
        change(lambda d: d.update({"おまけ": 1})),
        change(lambda d: items(d)[0].pop("出典")),
        change(lambda d: items(d)[0].update({"変わりうる": "はい"})),
        change(lambda d: items(d)[0].update({"状態": "古い"})),
        change(lambda d: items(d)[0].update({"覚えた日": "2026/11/04"})),
        change(lambda d: items(d)[0].update({"id": "事実 1"})),
        change(lambda d: items(d)[0].update({"名前": ""})),
        change(lambda d: items(d)[0].update({"使う項目": ["従業員数"]})),
        change(lambda d: items(d)[0]["出典"].pop("ファイル")),
        change(lambda d: items(d)[0]["出典"].update({"ページ": 0})),
        change(lambda d: items(d)[0]["出典"].update({"ページ": 1.5})),
        change(lambda d: items(d)[0]["出典"].update({"種類": "推測"})),
        change(lambda d: items(d)[1]["出典"].pop("日付")),
        change(lambda d: items(d)[1].update({"区分": "好き"})),
        change(lambda d: items(d)[1]["きっかけ"].pop("日付")),
        change(lambda d: items(d)[2].update({"次に注意する書類": "見積書"})),
        change(lambda d: items(d)[3].update({"結果": "保留"})),
        change(lambda d: items(d)[3]["出典"].pop("発言")),
        change(lambda d: items(d)[3].update({"種類": "事実"})),
        change(lambda d: items(d).append("文字")),
        change(lambda d: d.update({"項目": {}})),
    ]


def test_schema_check_agrees_with_jsonschema():
    validator = Draft202012Validator(SCHEMA)
    good = _valid_record()
    assert validator.is_valid(good) and schema_check.validate(SCHEMA, good) == []
    for broken in _broken_records():
        assert not validator.is_valid(broken), broken
        errors = schema_check.validate(SCHEMA, broken)
        assert errors, broken
        assert all(isinstance(e, str) and e for e in errors)
    # 「種類」で形が決まる項目は、その形の理由を示す
    data = _valid_record()
    data["項目"][0].pop("出典")
    assert schema_check.validate(SCHEMA, data) == ["項目[0]：「出典」がありません"]
    # 知らない言葉は、黙って飛ばさない
    with pytest.raises(schema_check.SchemaUnsupported):
        schema_check.validate({"type": "string", "format": "date"}, "x")
