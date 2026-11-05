"""確かめと審査役1回の最小限（TASKS M7。SPEC F9、DESIGN 4.1・5章・8章「結果の保存」「完成とする条件」、実験 E3b）。

- コードの確かめが通らなければ、審査役に渡すものをまとめない（審査役を呼ばない）。
- 通ったら、審査役に渡すもの（計画書の本文・制度データの抜き出し・根拠対照表・文体の基準 C・コードの確かめの結果）を
  `記録/審査に渡すもの/` にまとめ、最後に控え（確かめの番号と申請書のハッシュ）を置く。
- 審査役の最後の報告は、hook が本体を通さずに `記録/審査役の結果/<確かめの番号>.json` に保存する。
  default・eval（dontAsk）は SubagentStop の last_assistant_message、auto は PreToolUse（SubagentHandback）の
  tool_input.message（SubagentStop には報告が来ない）。審査役（hojokin:shinsa）のときだけ。json の囲みを外して読む。
- 完成の記録は、確かめの道具だけが残す。コードの確かめが通り、今の控えの番号の結果があり、報告が保存したときの
  ままで、確かめた後に申請書が変わっておらず、要修正が0件のときだけ。
- 根拠対照表：行を足す・置き換える。出典のない行は「根拠のない記述」として数え、完成にしない。
- 会社のフォルダの外は読まない・書かない。別名（シンボリックリンク）を通して書かない。

道具は /usr/bin/python3 で、hook は hooks.json のコマンドから動かす（tests/kakunin_tool.py）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import hook_runner as hr
import kakunin_tool as kt
import pytest

from lib import shinsa_result


@pytest.fixture
def env(tmp_path: Path) -> kt.Env:
    return kt.Env(tmp_path)


def ready(env: kt.Env) -> None:
    """コードの確かめが通る申請書（試しの Word・入力シート・財務モデル・根拠対照表）。"""
    env.trial_application(kt.GOOD_BODIES, sheet_values=kt.GOOD_SHEET, model=[("単価_冷凍惣菜", "")])
    env.evidence(kt.GOOD_EVIDENCE)


def prepared(env: kt.Env) -> str:
    ready(env)
    text = kt.ok(env.tool("prepare"))
    number = env.note()["確かめの番号"]
    assert f"確かめの番号：{number}" in text
    return number


# ---------------------------------------------------------------- hooks.json の登録


def test_hooks_are_registered_for_shinsa_and_handback_only() -> None:
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    (stop,) = config["hooks"]["SubagentStop"]
    # 英字と「-」だけの matcher は名前そのものと比べられ、プラグインの名前の付いた agent_type に合わない（実験 E3b）
    assert stop["matcher"] == "^hojokin:shinsa$"
    assert hr.claude_matches(stop["matcher"], "hojokin:shinsa")
    for other in ("hojokin:yomitori", "shinsa", "other:shinsa", "hojokin:shinsa-2", "Explore"):
        assert not hr.claude_matches(stop["matcher"], other), other
    assert hr.hook_commands("SubagentStop", "hojokin:yomitori") == []
    handback = [e for e in config["hooks"]["PreToolUse"] if e["hooks"][0]["command"].endswith("PreToolUse handback")]
    assert len(handback) == 1
    assert hr.claude_matches(handback[0]["matcher"], "SubagentHandback")
    for tool in ("Write", "Bash", "Read", "Agent", "SubagentHandbackX", "mcp__x__SubagentHandback"):
        assert not hr.claude_matches(handback[0]["matcher"], tool), tool
    # SubagentHandback を、書き込み・Bash の守り（guard）や、外を読む判定の matcher が受け取らない
    assert hr.hook_commands("PreToolUse", "SubagentHandback") == [handback[0]["hooks"][0]["command"]]


# ---------------------------------------------------------------- 審査役に渡すもの


def test_prepare_refuses_until_code_checks_pass(env: kt.Env) -> None:
    """コードの確かめが通らなければ、何もまとめない（控えも置かないので、hook は結果を保存しない）。"""
    env.trial_application({**kt.GOOD_BODIES, "1-2 経営課題": ["【仮：断る注文は月30件ほど】"]}, sheet_values=kt.GOOD_SHEET)
    env.evidence(kt.GOOD_EVIDENCE)
    text = kt.code(env.tool("prepare"), 3)
    assert "審査役は呼ばないでください" in text
    assert "仮の印 1件" in text
    assert not (env.folder / kt.PACKAGE).exists()
    # 控えがないので、審査役の報告が届いても保存しない
    env.subagent_stop(kt.report_json("確かめ-0001"))
    assert not (env.folder / kt.RESULTS).exists()


def test_prepare_writes_the_package_and_note(env: kt.Env) -> None:
    number = prepared(env)
    assert number == "確かめ-0001"
    note = env.note()
    assert note["案件"] == kt.CASE and note["段階"] == kt.STAGE
    files = {kt.WORD, kt.SHEET, kt.EVIDENCE, kt.MODEL}
    assert set(note["ファイルのハッシュ"]) == files
    assert note["申請書のハッシュ"] == shinsa_result.combined_hash(
        {rel: shinsa_result.sha256_file(env.folder / rel) for rel in files})
    package = env.folder / kt.PACKAGE
    names = {p.name for p in package.iterdir()}
    assert {"控え.json", "計画書の本文.md", "制度データの抜き出し.json", "根拠対照表.md", "文体の基準C.md",
            "コードの確かめの結果.json", "財務モデルの前提.md"} <= names
    plan = (package / "計画書の本文.md").read_text(encoding="utf-8")
    for name, body in kt.GOOD_BODIES.items():
        assert f"### {name}" in plan and body[0] in plan
    assert "盛り付けの自動化で受注を断らない工場にする" in plan  # 入力シートの値
    assert "※ここに記載してください" not in plan  # 説明の青字は渡さない
    seido = json.loads((package / "制度データの抜き出し.json").read_text(encoding="utf-8"))
    assert seido["審査項目"][0]["名前"] == "事業の実現可能性（試し）"
    assert [i["名前"] for i in seido["様式"][0]["項目"]][:3] == ["（２）事業計画名", "1-1 現状分析", "1-2 経営課題"]
    style = (package / "文体の基準C.md").read_text(encoding="utf-8")
    assert "## C. 読んで判断する基準" in style and "12. 声に出して読んで" in style and "## 出典" not in style
    evidence = (package / "根拠対照表.md").read_text(encoding="utf-8")
    assert "受注の台帳（架空） p.1" in evidence
    checked = json.loads((package / "コードの確かめの結果.json").read_text(encoding="utf-8"))
    assert checked["通った"] is True and checked["仮の印"] == [] and checked["空欄"] == []
    # 渡していないもの（聞き取りの記録・会社の記録がまだない）は、控えに理由を書く
    assert set(note["渡していないもの"]) == {"聞き取りの記録.json", "会社の記録の抜き出し.json"}
    # 申請書そのものは変えない
    assert set(note["ファイルのハッシュ"].values()) == {shinsa_result.sha256_file(env.folder / r) for r in files}


def test_prepare_numbers_go_up_and_old_files_are_replaced(env: kt.Env) -> None:
    prepared(env)
    (env.folder / kt.PACKAGE / "聞き取りの記録.json").write_text("{}", encoding="utf-8")  # 前の回の残り
    kt.ok(env.tool("prepare"))
    assert env.note()["確かめの番号"] == "確かめ-0002"
    assert not (env.folder / kt.PACKAGE / "聞き取りの記録.json").exists()
    # 結果が保存された番号より後の番号にする（控えが消えても、同じ番号を使い直さない）
    env.subagent_stop(kt.report_json("確かめ-0002"))
    (env.folder / kt.NOTE).unlink()
    kt.ok(env.tool("prepare"))
    assert env.note()["確かめの番号"] == "確かめ-0003"


# ---------------------------------------------------------------- hook が結果を保存する


def test_subagent_stop_saves_the_report_without_the_main_agent(env: kt.Env) -> None:
    """default・eval のモード：SubagentStop の last_assistant_message を、json の囲みを外して読み、控えと結び付ける。"""
    number = prepared(env)
    report = kt.report_json(number, [kt.finding("要確認", "受注の伸びの出典を確かめる")])
    r = env.subagent_stop(report, mode="dontAsk")
    assert r.stdout == b""  # 何も出さない（審査役の終わりを止めない）
    saved = env.result(number)
    assert saved["報告"] == report
    assert saved["結果"]["指摘"][0]["内容"] == "受注の伸びの出典を確かめる"
    assert saved["取り出した所"] == "SubagentStop.last_assistant_message"
    assert saved["agent_type"] == "hojokin:shinsa" and saved["permission_mode"] == "dontAsk"
    assert saved["控えと合う"] is True and saved["ハッシュが合う"] is True
    assert saved["控えの申請書のハッシュ"] == env.note()["申請書のハッシュ"]
    assert saved["報告のハッシュ"] == shinsa_result.text_hash(report)
    status = json.loads(kt.ok(env.tool("result", "--json")))
    assert status["届いた"] and status["重さごとの数"] == {"要修正": 0, "要確認": 1, "助言": 0}
    assert "要確認 1件" in kt.ok(env.tool("result"))


def test_auto_mode_saves_from_handback_and_empty_stop_does_not_overwrite(env: kt.Env) -> None:
    """auto モード：報告は SubagentHandback の tool_input.message に来て、SubagentStop には来ない（実験 E3b）。"""
    number = prepared(env)
    report = kt.report_json(number, [kt.finding("助言")])
    assert env.handback(report).stdout == b""  # 道具を止めない
    env.subagent_stop(None, mode="auto")  # last_assistant_message のキーがない
    saved = env.result(number)
    assert saved["取り出した所"] == "PreToolUse.SubagentHandback.tool_input.message"
    assert saved["報告"] == report and saved["permission_mode"] == "auto"
    # 報告のある SubagentStop が後から来ても、先に保存したものを残す
    env.subagent_stop(kt.report_json(number, [kt.finding("要修正")]))
    assert env.result(number)["報告"] == report


def test_handback_without_agent_type_needs_the_number_of_the_note(env: kt.Env) -> None:
    """SubagentHandback の入力に subagent の名前がないときは、報告の確かめの番号が控えと合うときだけ保存する。"""
    number = prepared(env)
    env.handback("```json\n{\"files\": [\"a.md\"]}\n```", agent=None)  # 読み取り役などの報告
    env.handback(kt.report_json("確かめ-0009"), agent=None)
    assert not (env.folder / kt.RESULTS).exists()
    env.handback(kt.report_json(number), agent=None)
    assert env.result(number)["agent_type"] is None


def test_other_subagents_are_not_saved(env: kt.Env) -> None:
    prepared(env)
    env.handback(kt.report_json("確かめ-0001"), agent="hojokin:yomitori")
    # SubagentStop は matcher で審査役だけ。main.py を通して別の名前で呼んでも保存しない
    r = hr.run(f'sh "{env.plugin}/hooks/run.sh" SubagentStop',
               {"hook_event_name": "SubagentStop", "agent_type": "hojokin:yomitori", "cwd": str(env.folder),
                "last_assistant_message": kt.report_json("確かめ-0001")},
               plugin=env.plugin, folder=env.folder, path=env.path, home=env.home, data=env.data)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert not (env.folder / kt.RESULTS).exists()


def test_unreadable_report_is_saved_as_text(env: kt.Env) -> None:
    """JSON として読めなくても、報告の文はそのまま残す（落とさない）。完成には使わない。"""
    number = prepared(env)
    env.subagent_stop("確かめました。大きな問題はありません。")
    saved = env.result(number)
    assert saved["報告"] == "確かめました。大きな問題はありません。"
    assert saved["結果"] is None and "JSON として読めません" in saved["読めなかった理由"]
    text = kt.code(env.tool("finish"), 3)
    assert "JSON として読めませんでした" in text
    assert not (env.folder / kt.COMPLETION).exists()


def test_late_report_of_an_older_number_does_not_take_the_new_place(env: kt.Env) -> None:
    prepared(env)
    kt.ok(env.tool("prepare"))  # 確かめ-0002 の控えに置き換わる
    env.subagent_stop(kt.report_json("確かめ-0001"))  # 前の確かめの報告が遅れて届いた
    old = env.result("確かめ-0001")
    assert old["控えと合う"] is False and old["ハッシュが合う"] is False
    assert not (env.folder / kt.RESULTS / "確かめ-0002.json").exists()
    env.subagent_stop(kt.report_json("確かめ-0002"))
    assert env.result("確かめ-0002")["控えと合う"] is True


def test_results_folder_link_is_not_followed(env: kt.Env, tmp_path: Path) -> None:
    """記録/審査役の結果 が別名（外を指す）なら、hook は書かず、道具はそれを伝える。"""
    number = prepared(env)
    outside = tmp_path / "外"
    outside.mkdir()
    os.symlink(outside, env.folder / kt.RESULTS)
    env.subagent_stop(kt.report_json(number))
    assert list(outside.iterdir()) == []
    text = kt.code(env.tool("result"), 2)
    assert "別名" in text


def test_hook_records_when_the_application_changed_during_review(env: kt.Env) -> None:
    number = prepared(env)
    env.put(kt.WORD, kt.make_docx({**kt.GOOD_BODIES, "6. 補足事項": ["審査役が読んでいる間に直した。"]}))
    env.subagent_stop(kt.report_json(number))
    saved = env.result(number)
    assert saved["ハッシュが合う"] is False
    assert saved["保存したときの申請書のハッシュ"] != saved["控えの申請書のハッシュ"]


# ---------------------------------------------------------------- 完成の記録


def test_complete_records_only_when_everything_passes(env: kt.Env) -> None:
    number = prepared(env)
    # 結果がまだ届いていない
    text = kt.code(env.tool("finish"), 3)
    assert "まだ届いていません" in text
    assert not (env.folder / kt.COMPLETION).exists()
    env.subagent_stop(kt.report_json(number, [kt.finding("要確認"), kt.finding("助言")]))
    text = kt.ok(env.tool("finish"))
    assert "完成にしました" in text and "要確認 1件、助言 1件" in text
    (entry,) = env.completion()["記録"]
    assert entry["確かめの番号"] == number and entry["案件"] == kt.CASE and entry["段階"] == kt.STAGE
    assert entry["申請書のハッシュ"] == env.note()["申請書のハッシュ"]
    assert entry["審査役の結果"] == f"{kt.RESULTS}/{number}.json"
    assert entry["コードの確かめ"] == {"仮の印": 0, "空欄": 0, "根拠なし": 0}
    assert entry["重さごとの数"] == {"要修正": 0, "要確認": 1, "助言": 1}
    # もう一度動かしても、同じ記録を足さない
    assert "もう完成の記録にあります" in kt.ok(env.tool("finish"))
    assert len(env.completion()["記録"]) == 1


def test_complete_refuses_with_must_fix_findings(env: kt.Env) -> None:
    number = prepared(env)
    env.subagent_stop(kt.report_json(number, [kt.finding("要修正", "聞き取りでは5人だが、本文は4人"), kt.finding("助言")]))
    text = kt.code(env.tool("finish"), 3)
    assert "要修正の指摘が 1件" in text
    assert not (env.folder / kt.COMPLETION).exists()
    assert "[要修正]（1-2 経営課題） 聞き取りでは5人だが、本文は4人" in kt.ok(env.tool("result"))


def test_complete_refuses_when_the_application_changed_after_review(env: kt.Env) -> None:
    """審査役が確かめた後に申請書を直したら、その結果では完成にしない（今の版を確かめ直す）。"""
    number = prepared(env)
    env.subagent_stop(kt.report_json(number))
    env.put(kt.WORD, kt.make_docx({**kt.GOOD_BODIES, "6. 補足事項": ["後から直した。"]}))
    text = kt.code(env.tool("finish"), 3)
    assert "審査役が確かめた後に、申請書が変わっています" in text
    assert not (env.folder / kt.COMPLETION).exists()


def test_complete_refuses_when_the_saved_report_was_rewritten(env: kt.Env) -> None:
    """保存した報告の文が書き換えられていたら（報告のハッシュが合わない）、その結果を使わない（DESIGN 5章）。"""
    number = prepared(env)
    env.subagent_stop(kt.report_json(number, [kt.finding("要修正")]))
    path = env.folder / kt.RESULTS / f"{number}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["報告"] = kt.report_json(number)
    saved["結果"] = json.loads(shinsa_result.strip_fence(saved["報告"]))
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    text = kt.code(env.tool("finish"), 3)
    assert "報告のハッシュが合いません" in text
    assert not (env.folder / kt.COMPLETION).exists()


def test_complete_refuses_when_code_checks_fail(env: kt.Env) -> None:
    """審査役の結果がそろっていても、コードの確かめが通らなければ完成にしない。"""
    number = prepared(env)
    env.subagent_stop(kt.report_json(number))
    env.evidence([{"記述": "3台", "種類": "数字", "書いた場所": "1-2 経営課題", "出典": ""}])
    text = kt.code(env.tool("finish"), 3)
    assert "根拠のない記述 1件" in text
    assert not (env.folder / kt.COMPLETION).exists()


def test_complete_refuses_a_report_with_another_number(env: kt.Env) -> None:
    number = prepared(env)
    # 番号の書いていない報告（審査役が番号を写し忘れた）は、控えの番号に結び付けて残すが、完成には使わない
    env.subagent_stop(kt.report_json(number).replace(f'"確かめの番号": "{number}"', '"確かめの番号": ""'))
    assert env.result(number)["控えと合う"] is True
    text = kt.code(env.tool("finish"), 3)
    assert "報告の確かめの番号" in text


# ---------------------------------------------------------------- 根拠対照表


def test_evidence_table_add_replace_and_unsupported_rows(env: kt.Env) -> None:
    env.trial_application(kt.GOOD_BODIES, sheet_values=kt.GOOD_SHEET)
    text = env.evidence(kt.GOOD_EVIDENCE[:2])
    assert "作り、2行を足しました（いまは2行）" in text
    # 同じ記述・書いた場所の行は置き換え、新しい行は足す。出典のない行は知らせる
    text = env.evidence([{"記述": "4人", "書いた場所": "1-2 経営課題", "出典": "社員名簿（架空）"},
                         {"記述": "2027年3月", "種類": "日付", "書いた場所": "1-2 経営課題"}])
    assert "いまは3行" in text and "出典のない行が1行あります" in text
    from lib import konkyo

    rows = konkyo.read((env.folder / kt.EVIDENCE).read_bytes())
    assert [r["記述"] for r in rows] == ["月400件から月650件", "4人", "2027年3月"]
    assert rows[1]["出典"] == "社員名簿（架空）"
    code_, report = env.count()
    assert code_ == 3
    assert [(f["場所"], f["文字"]) for f in report["根拠なし"]] == [("3行目", "2027年3月")]
    env.evidence(kt.GOOD_EVIDENCE, replace=True)
    assert len(konkyo.read((env.folder / kt.EVIDENCE).read_bytes())) == 3
    assert env.count()[0] == 0
    # 同じ中身からは同じバイト列（版の履歴で、変わっていない回を見分けやすい）
    assert konkyo.build(konkyo.read((env.folder / kt.EVIDENCE).read_bytes())) == (env.folder / kt.EVIDENCE).read_bytes()


@pytest.mark.parametrize("rows, reason", [
    ([], "の形で渡してください"),
    ([{"出典": "決算書"}], "「記述」"),
    ([{"記述": "1億円", "種類": "金額"}], "「種類」は"),
    ([{"記述": "1億円", "ページ": 3}], "知らない欄"),
])
def test_evidence_table_refuses_wrong_rows(env: kt.Env, rows, reason) -> None:
    env.trial_application(kt.GOOD_BODIES)
    text = kt.code(env.tool("konkyo", stdin=json.dumps({"行": rows}, ensure_ascii=False).encode("utf-8")), 2)
    assert reason in text
    assert not (env.folder / kt.EVIDENCE).exists()


def test_count_requires_an_evidence_table(env: kt.Env) -> None:
    env.trial_application(kt.GOOD_BODIES, sheet_values=kt.GOOD_SHEET)
    code_, report = env.count()
    assert code_ == 3 and any("根拠対照表.xlsx がありません" in p for p in report["問題"])


def test_screen_forms_are_not_listed_as_unmapped() -> None:
    """入力先が画面の様式（入力シートで書く）は、「書き込む位置をまだ対応づけていない」に挙げない（B1b の前の直し）。"""
    from lib import kakunin

    def value(v):
        return {"値": v, "出典": [{"資料": "要領", "ページ": 1}], "根拠の文": "様式", "状態": "確認済み"}

    seido = {"様式": [
        {"名前": "画面の様式", "入力先": value({"種類": "画面"}), "項目": [{"名前": "経営計画"}]},
        {"名前": "ファイルの様式", "入力先": value({"種類": "ファイル", "提出の形式": "PDF"}),
         "項目": [{"名前": "事業計画"}, {"名前": "書いた項目", "書き込む位置": {"範囲": "word/document.xml#1"}}]},
    ]}
    assert kakunin._unmapped_items(seido) == ["事業計画"]


# ---------------------------------------------------------------- 外と別名、会社のフォルダでないとき


def test_tools_refuse_outside_company_folder(env: kt.Env, tmp_path: Path) -> None:
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    before = hr.snapshot(plain)
    for args in (["count"], ["prepare"], ["result"], ["finish"], ["konkyo"]):
        text = kt.code(env.tool(*args, folder=plain), 2)
        assert "会社のフォルダではありません" in text
    assert hr.snapshot(plain) == before


def test_tools_do_not_read_or_write_through_links(env: kt.Env, tmp_path: Path) -> None:
    ready(env)
    before_outside = env.outside()
    # 申請書のフォルダが外への別名
    outside = tmp_path / "外の申請書"
    outside.mkdir()
    (outside / "その1・2.docx").write_bytes(kt.make_docx({"1-2 経営課題": ["【仮：外のファイル】"]}))
    app = env.folder / kt.APP_DIR
    app.rename(tmp_path / "退けた申請書")
    os.symlink(outside, app)
    for args in (["count"], ["prepare"], ["finish"]):
        text = kt.code(env.tool(*args), 2)
        assert "別名" in text and "外のファイル" not in text
    os.unlink(app)
    (tmp_path / "退けた申請書").rename(app)
    # 審査に渡すもの の置き場が外への別名
    os.symlink(outside, env.folder / kt.PACKAGE)
    text = kt.code(env.tool("prepare"), 2)
    assert "別名" in text
    assert sorted(p.name for p in outside.iterdir()) == ["その1・2.docx"]
    os.unlink(env.folder / kt.PACKAGE)
    # 根拠対照表が外への別名
    target = tmp_path / "外の表.xlsx"
    target.write_bytes(b"x")
    (env.folder / kt.EVIDENCE).unlink()
    os.symlink(target, env.folder / kt.EVIDENCE)
    text = kt.code(env.tool("konkyo", stdin=json.dumps({"行": kt.GOOD_EVIDENCE}, ensure_ascii=False).encode("utf-8")), 2)
    assert "別名" in text and target.read_bytes() == b"x"
    assert env.outside() == before_outside


def test_hook_does_nothing_outside_company_folder(tmp_path: Path) -> None:
    """目印のないフォルダでは、審査役の報告が届いても何も書かない（T0-13）。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder = tmp_path / "ふつうのフォルダ"
    (folder / kt.PACKAGE).mkdir(parents=True)
    (folder / kt.NOTE).write_text(json.dumps({"確かめの番号": "確かめ-0001"}), encoding="utf-8")
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    data.mkdir()
    path = hr.make_bin(tmp_path / "bin", "本物", tmp_path / "ran")
    before = hr.snapshot(folder)
    for event, match, payload in (
        ("SubagentStop", kt.SHINSA, {"agent_type": kt.SHINSA, "last_assistant_message": kt.report_json("確かめ-0001")}),
        ("PreToolUse", "SubagentHandback", {"tool_name": "SubagentHandback",
                                            "tool_input": {"message": kt.report_json("確かめ-0001")}}),
    ):
        (command,) = hr.hook_commands(event, match)
        r = hr.run(command, {"hook_event_name": event, "cwd": str(folder), **payload}, plugin=plugin, folder=folder,
                   path=path, home=home, data=data)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert hr.snapshot(folder) == before
    assert not (tmp_path / "ran").exists()


def test_no_pycache_in_plugin_or_company_folder(env: kt.Env) -> None:
    number = prepared(env)
    env.subagent_stop(kt.report_json(number))
    kt.ok(env.tool("finish"))
    assert not list(env.plugin.rglob("__pycache__"))
    assert not list(env.folder.rglob("__pycache__"))
    assert not list(env.folder.rglob("*.書きかけ"))


# ---------------------------------------------------------------- 審査役と kaku の手順


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    head = text[4:text.index("\n---", 4)]
    return {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip() for line in head.splitlines() if ":" in line}


def test_shinsa_agent_reads_only_and_returns_the_fixed_json() -> None:
    path = hr.REPO_ROOT / "agents" / "shinsa.md"
    meta = frontmatter(path)
    assert meta["name"] == "shinsa"
    assert [t.strip() for t in meta["tools"].split(",")] == ["Read", "Grep", "Glob"]
    assert meta["model"] == "opus" and meta["effort"] == "high"
    body = path.read_text(encoding="utf-8")
    for word in ("記録/審査に渡すもの/", "確かめの番号", "要修正", "要確認", "助言", "```json", "指摘", "審査項目",
                 "書き換えません"):
        assert word in body, word


def test_kaku_skill_explains_the_check_steps() -> None:
    text = (hr.REPO_ROOT / "skills" / "kaku" / "SKILL.md").read_text(encoding="utf-8")
    for word in ("kakunin.py\" count", "kakunin.py\" konkyo", "kakunin.py\" prepare", "kakunin.py\" result",
                 "kakunin.py\" finish", "hojokin:shinsa", "記録/審査役の結果/", "審査役を呼ばない"):
        assert word in text, word
    assert len(text.splitlines()) < 500
