"""版の名前のファイル（TASKS M0a。SPEC 共通の要件「書類の版の管理」、DESIGN 5章「版のファイルを増やさない」）。

- 名前に「_v2」「最終」「修正版」「コピー」などを含む新しいファイルを、Write・Edit・NotebookEdit で作ることを
  PreToolUse で拒む。前からあるファイルを直すこと、ふつうの名前のファイルを作ることは拒まない。
- その場のコード（Bash など）で作られたら、Stop で見つけ、元のファイルにまとめるよう Claude に伝える。
  社長が置いたもの、原本・入れ口・公式資料の名前（社長や公式の名前のまま）は、見つける対象にしない。
  Stop の hook で続けているとき（stop_hook_active）も、新しく足された分は伝える（1つの応答で3回まで。
  超えた分と、途中で止めた応答の分は、次の応答の終わりに伝える）。
- フォルダの名前も見る（「申請書_v2/その1.md」、cp -r で写した「申請書_バックアップ/」）。新しいフォルダだけに当て、
  前からあるフォルダと、案件・段階のふつうの名前（「…第9回」「1_申請」「1年目」）には当てない。
- 言葉の一部として出てくるもの（「富士コピー」「最終確認のメモ」など）には当てない。

名前の判定（lib/version_names.py）はテストの Python で、hook は hooks.json のコマンドから動かして確かめる。
"""

from __future__ import annotations

import shutil
import unicodedata

import pytest
import version_tool as vt

from lib import version_names as vn

SONO1 = f"{vt.APPLICATION}/その1.docx"
VERSION_REASON = "版の名前のファイルは作れません"


# ---- 名前の判定 ----

def test_design_names_are_in_the_rules() -> None:
    """DESIGN 5章に挙がった4つ（_v2・最終・修正版・コピー）と、SPEC の「_最終」は、必ず当たる。"""
    for name in ("計画書_v2.docx", "計画書_最終.docx", "計画書_修正版.docx", "計画書_コピー.docx", "計画書 のコピー.docx"):
        assert vn.version_label(name) is not None, name


@pytest.mark.parametrize("name", [
    "その1_v3.docx", "その1-ver2.xlsx", "その1 Ver.2.docx", "その1_version10.md", "その1_rev2.docx",
    "その1_Ｖ２.docx", "v2_その1.docx", "その1_v2.1.docx",
    "その1_第2版.docx", "その1 2版.docx", "その1_第３稿.md",
    "その1_最終版.docx", "最終_その1.docx", "その1（最終）.docx", "その1_最終稿.docx", "その1最終版.docx",
    "その1_最新.docx", "その1_最新版.xlsx",
    "その1_修正済み.docx", "その1_修正後.docx", "その1_修正.docx", "その1_訂正版.docx", "その1_改訂版.docx",
    "その1_差し替え.docx", "その1_差替版.docx",
    "その1 - コピー.docx", "その1 のコピー.docx", "その1 のコピー 2.docx", "コピー 〜 その1.docx", "その1_コピー.docx",
    "その1_複製.docx", "その1 copy.docx", "その1 copy 2.docx", "Copy of その1.docx",
    "その1_final.docx", "その1_FINAL.docx", "その1_old.xlsx", "その1-new.docx", "その1_bak.docx", "その1_backup.md",
    "その1_旧.docx", "その1_新.docx", "その1_旧版.docx", "その1_新版.docx", "その1_バックアップ.docx",
    "その1 (1).docx", "その1（２）.docx", "その1.docx.bak", "その1.old", "その1.md.orig",
])
def test_version_names_are_caught(name) -> None:
    assert vn.version_label(name) is not None, name


def test_nfd_and_full_width_names_are_caught() -> None:
    """濁点が分かれた形（NFD）や全角の英数字でも当たる。"""
    for name in ("その1_コピー.docx", "その1_バックアップ.docx", "その1 のコピー.docx"):
        nfd = unicodedata.normalize("NFD", name)
        assert nfd != name
        assert vn.version_label(nfd) is not None, name
    assert vn.version_label("その１＿ｖ２.docx") is not None
    assert vn.version_label("その1（コピー）.docx") is not None


@pytest.mark.parametrize("name", [
    # ツールが作る書類の決まった名前（DESIGN 4.5）
    "その1・2.docx", "その3.xlsx", "入力シート.xlsx", "根拠対照表.xlsx", "財務モデル.xlsx", "概要と流れ.docx",
    "補助金の候補.docx", "今の状態.html", "今の状態.xlsx", "会社の記録.json", "期限の台帳.json", "制度データ.json",
    # 原本の決まった名前と、写し
    "2026-10-20_見積書_富士コピー.pdf", "見積書の写し.pdf", "決算書_第18期.pdf", "納税証明書_その2.pdf",
    "2026-10-20_見積書_つばさ台フードシステム.pdf", "履歴事項全部証明書.pdf",
    # 言葉の一部として出てくるもの
    "コピー機の見積書.pdf", "最終確認のメモ.md", "最新の制度の一覧.md", "新事業の計画.md", "修正点のメモ.md",
    "差し替え用の説明.md", "旧工場の写真.jpg", "最終年度の目標.md", "公募要領_第8回.pdf", "第8回の要点.md",
    "overview.md", "renewal.md", "copyright.txt", "development.md", "version_names.md", "r6_koubover8_ip20.pdf",
    "p001.txt", "1年目.md", "様式第1.docx", "バージョン管理の説明.md",
])
def test_ordinary_names_pass(name) -> None:
    assert vn.version_label(name) is None, (name, vn.version_label(name))


def test_stop_skips_places_named_by_the_owner_or_officially() -> None:
    """応答の終わりに見ない場所：原本・入れ口（社長の名前のまま）、公式資料（公式の名前のまま）、プラグインの設定。"""
    skipped = ["原本/見積・契約・請求/2026-10-20_見積書_最終.pdf", "入れ口/見積書 のコピー.pdf",
               f"案件/{vt.CASE}/公式資料/公募要領_第8版.pdf", ".hojokin/設定_old.json", ".claude/settings_bak.json"]
    checked = [f"{vt.APPLICATION}/その1_v2.docx", "記録/会社の記録_v2.json", "今の状態_最終.html",
               f"案件/{vt.CASE}/概要と流れ_コピー.docx", f"案件/{vt.CASE}/{vt.STAGE}/添付する書類/見積書の写し (1).pdf"]
    for path in skipped:
        assert not vn.checked_at_stop(path), path
    for path in checked:
        assert vn.checked_at_stop(path), path


def test_original_of_finds_the_file_without_the_version_words(tmp_path) -> None:
    folder = tmp_path
    (folder / "申請書").mkdir()
    for name in ("その1.docx", "その1.md", "入力シート.xlsx"):
        (folder / "申請書" / name).write_bytes(b"x")
    assert vn.original_of(folder, "申請書/その1_v2.docx") == "申請書/その1.docx"
    assert vn.original_of(folder, "申請書/その1 のコピー.docx") == "申請書/その1.docx"
    assert vn.original_of(folder, "申請書/その1（最終版）.docx") == "申請書/その1.docx"
    assert vn.original_of(folder, "申請書/その1_修正版.md") == "申請書/その1.md"
    assert vn.original_of(folder, "申請書/その1.docx.bak") == "申請書/その1.docx"
    assert vn.original_of(folder, "申請書/入力シート (1).xlsx") == "申請書/入力シート.xlsx"
    assert vn.original_of(folder, "申請書/その2_v2.docx") is None
    assert vn.original_of(folder, "申請書/v2.docx") is None


def test_messages_name_the_file_the_rule_and_the_original() -> None:
    deny = vn.deny_reason(f"{vt.APPLICATION}/その1_v2.md", "「_v2」のような版の番号", f"{vt.APPLICATION}/その1.md")
    assert deny.startswith(VERSION_REASON)
    for text in ("その1_v2.md", "「_v2」のような版の番号", "書類ごとに1つのファイルを直して使う", "版の履歴に自動で残ります",
                 f"元のファイル（{vt.APPLICATION}/その1.md）を直してください", "hojokin プラグインの決まり"):
        assert text in deny, text
    stop = vn.stop_reason([(f"{vt.APPLICATION}/その1_v2.docx", "「_v2」のような版の番号", SONO1),
                           ("記録/メモ (1).md", "「(1)」のような複製の番号", None)])
    for text in (f"{vt.APPLICATION}/その1_v2.docx", f"元のファイル：{SONO1}", "記録/メモ (1).md",
                 "元のファイルが見つかりません", "元のファイルにまとめてから", "消してください", "社長に聞いてください"):
        assert text in stop, text


# ---- PreToolUse（Write・Edit・NotebookEdit） ----

@pytest.fixture
def company(tmp_path) -> vt.Company:
    c = vt.Company(tmp_path)
    c.write(f"{vt.APPLICATION}/その1.md", "元のファイル")
    c.write("入れ口/見積書_最終.txt", "社長が置いた")
    c.say("はじめに")
    assert c.stop() is None
    return c


def test_pre_tool_use_denies_new_version_files(company) -> None:
    folder = company.folder
    reason = vt.denied_reason(company.pre("Write", {"file_path": str(folder / vt.APPLICATION / "その1_v2.md"),
                                                    "content": "x"}))
    assert reason.startswith(VERSION_REASON)
    assert "その1_v2.md" in reason and f"元のファイル（{vt.APPLICATION}/その1.md）を直してください" in reason
    reason = vt.denied_reason(company.pre("NotebookEdit", {"notebook_path": str(folder / "記録" / "分析_コピー.ipynb"),
                                                           "new_source": "x"}))
    assert "分析_コピー.ipynb" in reason and "元のファイルを直すか、版を表さない名前にしてください" in reason
    reason = vt.denied_reason(company.pre("Write", {"file_path": str(folder / "今の状態_最終.html"), "content": "x"}))
    assert "「最終」" in reason
    assert not (folder / vt.APPLICATION / "その1_v2.md").exists()


def test_pre_tool_use_resolves_relative_and_nfd_paths(company) -> None:
    """相対の場所は hook の入力の cwd から解き、NFD の名前でも拒む。"""
    folder = company.folder
    reason = vt.denied_reason(company.pre("Write", {"file_path": "その1 のコピー.md", "content": "x"},
                                          cwd=folder / vt.APPLICATION))
    assert f"元のファイル（{vt.APPLICATION}/その1.md）" in reason
    nfd = unicodedata.normalize("NFD", "その1_バックアップ.md")
    vt.denied_reason(company.pre("Write", {"file_path": str(folder / vt.APPLICATION / nfd), "content": "x"}))


def test_pre_tool_use_passes_existing_files_and_ordinary_names(company) -> None:
    """前からあるファイル（社長が置いた「見積書_最終.txt」など）を直すことと、ふつうの名前は拒まない。"""
    folder = company.folder
    assert company.pre("Edit", {"file_path": str(folder / "入れ口" / "見積書_最終.txt"),
                                "old_string": "社長", "new_string": "社長が"}) is None
    assert company.pre("Write", {"file_path": str(folder / "入れ口" / "見積書_最終.txt"), "content": "x"}) is None
    assert company.pre("Write", {"file_path": str(folder / vt.APPLICATION / "その1.md"), "content": "x"}) is None
    assert company.pre("Write", {"file_path": str(folder / "記録" / "最終確認のメモ.md"), "content": "x"}) is None
    assert company.pre("Write", {"file_path": str(folder / "記録" / "打ち合わせ.md"), "content": "x"}) is None


def test_pre_tool_use_outside_is_denied_as_outside(company, tmp_path) -> None:
    """会社のフォルダの外は、外への書き込みとして拒む（版の名前の文にしない）。"""
    reason = vt.denied_reason(company.pre("Write", {"file_path": str(tmp_path / "別の会社" / "計画_v2.md"),
                                                    "content": "x"}))
    assert "会社のフォルダの外には書き込めません" in reason
    assert VERSION_REASON not in reason


# ---- Stop（その場のコードで作られたもの） ----

def test_stop_finds_version_files_made_by_code(company) -> None:
    """Bash などで作られた版の名前のファイルを見つけ、元のファイルにまとめるよう伝える。ファイルは版に残す。"""
    company.say("その1を直して")
    company.write(f"{vt.APPLICATION}/その1_v2.md", "直した中身")
    company.write("記録/会社の記録 (1).json", "{}")
    output = company.stop()
    assert output["decision"] == "block"
    reason = output["reason"]
    assert f"{vt.APPLICATION}/その1_v2.md（「_v2」のような版の番号） → 元のファイル：{vt.APPLICATION}/その1.md" in reason
    assert "記録/会社の記録 (1).json（「(1)」のような複製の番号） → 元のファイルが見つかりません" in reason
    assert "元のファイルにまとめてから" in reason
    docs = {r["書類"]: (r["だれ"], r["理由"]) for r in company.log() if r["版"] == company.log()[0]["版"]}
    assert docs == {f"{vt.APPLICATION}/その1_v2.md": ("ツール", "その1を直して"),
                    "記録/会社の記録 (1).json": ("ツール", "その1を直して")}

    # 続けて（stop_hook_active）、Claude が元のファイルにまとめて消した
    (company.folder / vt.APPLICATION / "その1.md").write_text("直した中身", encoding="utf-8")
    (company.folder / vt.APPLICATION / "その1_v2.md").unlink()
    assert company.stop(active=True) is None
    changes = {r["書類"]: (r["変更"], r["だれ"], r["理由"]) for r in company.log()
               if r["版"] == company.log()[0]["版"]}
    assert changes == {f"{vt.APPLICATION}/その1.md": ("変えた", "ツール", "その1を直して"),
                       f"{vt.APPLICATION}/その1_v2.md": ("消した", "ツール", "その1を直して")}


def test_stop_reports_version_files_made_while_continuing(company) -> None:
    """Stop の hook で続けているとき（stop_hook_active。後のタスクの Word・Excel の書式の戻しなどで続けさせたとき）も、
    その続きの中で新しく足された版の名前のファイルは伝える。一度伝えたものは繰り返さない。"""
    company.say("直して")
    company.write(f"{vt.APPLICATION}/その1.md", "直した")
    assert company.stop() is None
    # 続きの中で、その場のコードが作った
    company.write(f"{vt.APPLICATION}/その1_最終.md", "x")
    output = company.stop(active=True)
    assert output["decision"] == "block"
    assert f"{vt.APPLICATION}/その1_最終.md（「最終」） → 元のファイル：{vt.APPLICATION}/その1.md" in output["reason"]
    assert company.log()[0]["書類"] == f"{vt.APPLICATION}/その1_最終.md"
    # まとめないまま応答を終えても、同じものを繰り返さない（続けさせ続けない）
    assert company.stop(active=True) is None
    company.say("ほかを直して")
    assert company.stop() is None


def test_stop_blocks_a_limited_number_of_times_and_tells_the_rest_later(company) -> None:
    """1つの応答で続けさせるのは3回まで。超えた分は控えて、次の応答の終わりに伝える（まだあれば）。"""
    company.say("直して")
    company.write(f"{vt.APPLICATION}/その1_v1.md", "x")
    assert "その1_v1.md" in company.stop()["reason"]
    for n in (2, 3):
        company.write(f"{vt.APPLICATION}/その1_v{n}.md", "x")
        assert f"その1_v{n}.md" in company.stop(active=True)["reason"], n
    company.write(f"{vt.APPLICATION}/その1_v4.md", "x")
    company.write(f"{vt.APPLICATION}/その1_v5.md", "x")
    assert company.stop(active=True) is None
    assert company.stop(active=True) is None
    # 次の応答の終わり。v5 は Claude が消したので伝えない。v1〜v3 は伝え済み
    (company.folder / vt.APPLICATION / "その1_v5.md").unlink()
    company.say("続けて")
    reason = company.stop()["reason"]
    assert f"{vt.APPLICATION}/その1_v4.md（「_v2」のような版の番号）" in reason
    for n in (1, 2, 3, 5):
        assert f"その1_v{n}.md" not in reason, n
    assert company.stop(active=True) is None


def test_version_files_of_an_interrupted_response_are_told_at_the_next_stop(company) -> None:
    """応答を途中で止めて次を送ったとき（ツールの分として残す）に足されていた版の名前のファイルも、次の Stop で伝える。"""
    company.say("その1を直して")
    company.write(f"{vt.APPLICATION}/その1_v2.md", "途中")
    company.say("やっぱり別の書き方で")
    assert (company.log()[0]["書類"], company.log()[0]["だれ"]) == (f"{vt.APPLICATION}/その1_v2.md", "ツール")
    reason = company.stop()["reason"]
    assert f"{vt.APPLICATION}/その1_v2.md（「_v2」のような版の番号） → 元のファイル：{vt.APPLICATION}/その1.md" in reason


# ---- フォルダの名前 ----

@pytest.mark.parametrize("name", [
    "申請書_v2", "申請書 v2.1", "申請書-ver2", "申請書_第2版", "申請書_最終", "申請書_最終版", "最終_申請書",
    "申請書_修正版", "申請書 のコピー", "申請書のコピー", "申請書 - コピー", "申請書_コピー", "申請書_バックアップ",
    "申請書_旧", "旧_申請書", "申請書_old", "申請書_backup", "backup", "old", "申請書 (2)", "申請書.bak", "申請書 copy",
])
def test_version_folder_names_are_caught(name) -> None:
    assert vn.version_label(name, is_dir=True) is not None, name


@pytest.mark.parametrize("name", [
    # 会社のフォルダの決まった形（DESIGN 4.5）と、案件・段階の名前
    vt.CASE, "2026_省力化（一般型）第10回", "2026_持続化（一般型）第20回", "1_申請", "2_交付申請", "2_見積書等の提出",
    "3_実績報告", "4_効果報告", "1年目", "2年目", "申請書", "添付する書類", "公式資料", "概要と流れ", "入れ口", "原本",
    "登記・名簿", "決算・税", "見積・契約・請求", "役所からの通知", "会社の資料", "写真・カタログ", "記録", "見るだけ",
    "資料の本文", "要領8", "審査役の結果", "版",
    # 言葉の一部として出てくるもの
    "新規事業", "旧工場の写真", "コピー機の資料", "最終確認", "development", "renewal",
])
def test_ordinary_folder_names_pass(name) -> None:
    assert vn.version_label(name, is_dir=True) is None, (name, vn.version_label(name, is_dir=True))


def test_version_part_checks_only_new_parts() -> None:
    """場所の各部分のうち、新しい部分だけに当てる。前からあるフォルダ（社長が作った「旧資料」など）には当てない。"""
    known = {"案件", f"案件/{vt.CASE}", f"案件/{vt.CASE}/{vt.STAGE}", vt.APPLICATION, "記録", "記録/旧資料"}

    def is_known(prefix):
        return prefix in known

    assert vn.version_part(f"{vt.CASE_DIR}/{vt.STAGE}/申請書_v2/その1.md", is_known) == (
        f"{vt.CASE_DIR}/{vt.STAGE}/申請書_v2", "「_v2」のような版の番号", True)
    assert vn.version_part(f"{vt.APPLICATION}/その1 のコピー.md", is_known)[1:] == ("「コピー」", False)
    assert vn.version_part("記録/旧資料/メモ.md", is_known) is None
    assert vn.version_part("記録/旧資料/メモ_v2.md", is_known)[0] == "記録/旧資料/メモ_v2.md"
    # 案件・段階のフォルダが新しくても、ふつうの名前には当てない
    assert vn.version_part("案件/2026_省力化（一般型）第10回/4_効果報告/1年目/申請書/効果報告.md", is_known) is None


def test_found_at_stop_reports_a_copied_folder_once_with_the_original(tmp_path) -> None:
    folder = tmp_path
    (folder / vt.APPLICATION).mkdir(parents=True)
    (folder / f"{vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ").mkdir(parents=True)
    known = {"案件", vt.CASE_DIR, f"{vt.CASE_DIR}/{vt.STAGE}", vt.APPLICATION}
    added = [f"{vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ/{name}" for name in ("その1.md", "入力シート.xlsx", "その1_v2.md")]
    assert vn.found_at_stop(folder, added, known) == [
        (f"{vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ/", "「バックアップ」", f"{vt.APPLICATION}/")]
    assert vn.original_of(folder, f"{vt.CASE_DIR}/{vt.STAGE}/申請書のコピー", is_dir=True) == vt.APPLICATION
    assert vn.original_of(folder, f"{vt.CASE_DIR}/{vt.STAGE}/計画_v2", is_dir=True) is None


def test_folder_messages_name_the_folder_and_the_original() -> None:
    deny = vn.deny_reason(f"{vt.CASE_DIR}/{vt.STAGE}/申請書_v2", "「_v2」のような版の番号", vt.APPLICATION, is_dir=True)
    for text in ("版の名前のフォルダは作れません（申請書_v2/：「_v2」のような版の番号）", "書類ごとに1つのファイルを直して使う",
                 f"元のフォルダ（{vt.APPLICATION}/）の中のファイルを直してください", "hojokin プラグインの決まり"):
        assert text in deny, text
    stop = vn.stop_reason([(f"{vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ/", "「バックアップ」", f"{vt.APPLICATION}/"),
                           ("記録/旧/", "「旧」「新」", None)])
    for text in (f"{vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ/（「バックアップ」） → 元のフォルダ：{vt.APPLICATION}/",
                 "記録/旧/（「旧」「新」） → 元のフォルダが見つかりません", "フォルダごと消す"):
        assert text in stop, text


def test_pre_tool_use_denies_files_in_new_version_folders(company) -> None:
    """まだないフォルダの名前に版の言葉があれば、その中に書くことも拒む（申請書_v2/その1.md など）。"""
    folder = company.folder
    for name in ("申請書_v2", "申請書のコピー", "申請書 - コピー", "申請書_バックアップ"):
        target = folder / vt.CASE_DIR / vt.STAGE / name / "その1.md"
        reason = vt.denied_reason(company.pre("Write", {"file_path": str(target), "content": "x"}))
        assert reason.startswith(f"版の名前のフォルダは作れません（{name}/："), reason
        assert f"元のフォルダ（{vt.APPLICATION}/）の中のファイルを直してください" in reason
        assert not target.parent.exists()
    # 深い所の新しいフォルダでも
    reason = vt.denied_reason(company.pre("Write", {"file_path": str(folder / "記録" / "旧" / "メモ" / "a.md"),
                                                    "content": "x"}))
    assert "版の名前のフォルダは作れません（旧/：" in reason


def test_pre_tool_use_passes_new_ordinary_folders_and_existing_version_folders(company) -> None:
    """新しい案件・段階のふつうの名前のフォルダと、前からある版の言葉のフォルダ（社長が作ったもの）の中は通す。"""
    folder = company.folder
    for rel in ("案件/2026_省力化（一般型）第10回/1_申請/申請書/その1.md",
                f"{vt.CASE_DIR}/4_効果報告/1年目/申請書/効果報告.md", "記録/新規事業/メモ.md",
                f"{vt.CASE_DIR}/公式資料/要領8/p001.txt"):
        assert company.pre("Write", {"file_path": str(folder / rel), "content": "x"}) is None, rel
    company.write("入れ口/見積書_最終/メモ.txt", "社長が作った")
    company.say("見て")
    assert company.pre("Write", {"file_path": str(folder / "入れ口" / "見積書_最終" / "まとめ.md"), "content": "x"}) is None


def test_stop_finds_a_folder_copied_by_code(company) -> None:
    """その場のコードが申請書のフォルダを丸ごと写したら（cp -r 申請書 申請書_バックアップ）、フォルダを1件として伝える。"""
    company.write(f"{vt.APPLICATION}/入力シート.md", "入力")
    company.say("直す前に写しを取って直して")
    shutil.copytree(company.folder / vt.APPLICATION, company.folder / vt.CASE_DIR / vt.STAGE / "申請書_バックアップ")
    company.write(f"{vt.APPLICATION}/その1.md", "直した")
    output = company.stop()
    assert output["decision"] == "block"
    reason = output["reason"]
    assert (f"- {vt.CASE_DIR}/{vt.STAGE}/申請書_バックアップ/（「バックアップ」） → 元のフォルダ：{vt.APPLICATION}/"
            in reason)
    assert "申請書_バックアップ/その1.md" not in reason and "フォルダごと消す" in reason
    # ふつうの名前の新しい案件・段階のフォルダでは伝えない
    company.say("次の案件の準備をして")
    company.write("案件/2026_省力化（一般型）第10回/1_申請/申請書/その1.md", "x")
    company.write(f"{vt.CASE_DIR}/4_効果報告/1年目/申請書/効果報告.md", "x")
    assert company.stop() is None


def test_stop_skips_version_folders_in_owner_and_official_places(company) -> None:
    """原本・入れ口（社長の名前のまま）と公式資料（公式の名前のまま）の中のフォルダには当てない。"""
    company.say("取り込んで")
    company.write("入れ口/コピー/見積書.pdf", b"%PDF")
    company.write("原本/会社の資料/旧/会社案内.pdf", b"%PDF")
    company.write(f"{vt.CASE_DIR}/公式資料/第8版/公募要領.pdf", b"%PDF")
    assert company.stop() is None


def test_stop_ignores_owner_files_and_names_kept_as_given(company) -> None:
    """社長が置いた版の名前のファイルと、原本・入れ口・公式資料の名前は、見つける対象にしない。"""
    company.write(f"{vt.APPLICATION}/その1 のコピー.md", "社長が Finder で複製")
    company.say("取り込んで整理して")
    assert company.log()[0]["だれ"] == "社長"
    company.write("入れ口/見積書 - コピー.pdf", b"%PDF")
    company.write("原本/見積・契約・請求/2026-10-20_見積書_最終.pdf", b"%PDF")
    company.write(f"案件/{vt.CASE}/公式資料/公募要領_第8版.pdf", b"%PDF")
    company.write(f"{vt.APPLICATION}/その1.md", "ツールが直した")
    assert company.stop() is None
    assert {r["書類"] for r in company.log() if r["版"] == company.log()[0]["版"]} == {
        "入れ口/見積書 - コピー.pdf", "原本/見積・契約・請求/2026-10-20_見積書_最終.pdf",
        f"案件/{vt.CASE}/公式資料/公募要領_第8版.pdf", f"{vt.APPLICATION}/その1.md"}
