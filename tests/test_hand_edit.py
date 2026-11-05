"""社長が申請書を手で直したときの差分（TASKS B5、SPEC F13「申請書の手直しから学ぶ」、DESIGN 10章）。

- ツールが書いた計画書（Word）を、社長が Word で1か所の言い回しだけ直すと、次に送ったとき（UserPromptSubmit）の
  hook の出力に、直した段落の前と後が入り、記録の道具で残すよう案内が付く。
- 空白・改行・タブだけの違い（保存し直しのずれ）は差分にしない。同じ手直しは2回伝えない。
- ツールが変えた分（応答の終わりの版）は伝えない。開いたとき（SessionStart）も、閉じている間の手直しを伝える。
- 差分が長いときは、直した書類と数だけを渡す（3,000字まで）。
"""

from __future__ import annotations

from pathlib import Path

import version_tool as vt

from lib.docx_min import Document

PLAN = "案件/2026_省力化（一般型）第9回/1_申請/申請書/その1・2.docx"
TOOL_SENTENCE = "盛り付けラインの自動化を図ることで、生産性の向上を図る。"
OWNER_SENTENCE = "盛り付けラインを機械にして、同じ人数で作れる量を増やす。"


def docx(paragraphs) -> bytes:
    d = Document()
    d.heading("1-2 経営課題")
    for p in paragraphs:
        d.paragraph(p)
    return d.to_bytes()


def context(output) -> str:
    if not output:
        return ""
    return (output.get("hookSpecificOutput") or {}).get("additionalContext") or ""


def test_owner_rewording_is_passed_once(tmp_path: Path) -> None:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    c.say("計画書を書いて")
    c.write(PLAN, docx(["人手が足りない。", TOOL_SENTENCE, "検品も手作業である。"]))
    c.stop()  # ツールの版
    assert "手で直しました" not in context(c.say("ありがとう"))
    c.stop()

    # 社長が Word で1か所だけ言い回しを直す（ほかの段落は空白の入り方だけ変わる）
    c.write(PLAN, docx(["人手が 足りない。", OWNER_SENTENCE, "検品も　手作業である。"]))
    text = context(c.say("計画書を少し直しました"))
    assert "【hojokin】社長が申請書を手で直しました" in text
    assert f"- 前：{TOOL_SENTENCE}" in text and f"  後：{OWNER_SENTENCE}" in text
    assert "人手が" not in text and "検品" not in text  # 空白だけの違いは差分にしない
    assert "record.py add-rule" in text and "--source 社長の手直し" in text and PLAN in text
    assert len(text) <= 3000
    c.stop()
    # 同じ手直しは2回伝えない
    assert "手で直しました" not in context(c.say("続けて"))


def test_session_start_tells_edits_made_while_closed_and_long_diffs_are_summarized(tmp_path: Path) -> None:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    c.say("計画書を書いて")
    c.write(PLAN, docx([f"段落{i}の文。" for i in range(80)]))
    c.stop()
    # 閉じている間に、社長がたくさん直した
    c.write(PLAN, docx([f"段落{i}の文を、社長が長く書き直した。" + "あ" * 40 for i in range(80)]))
    text = context(c.start_raw())
    assert "【hojokin】社長が申請書を手で直しました" in text
    assert "差分が長いので" in text and "直した段落 80か所" in text and "versions.py" in text
