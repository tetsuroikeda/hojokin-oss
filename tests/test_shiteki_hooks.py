"""社長の発言の指摘らしい言葉への一言（TASKS B4、SPEC F13「指摘から学ぶ」「一度きりの指示は残さない」、DESIGN 10章）。

- 台本「4種類の指摘」「「今回だけ」の指示とどちらとも取れる指示」の発言に、一言が付く。
  「今回だけ」は残さない、「次から」「いつも」「どの計画書でも」「うちでは」は聞き返さずに残す、
  どちらとも取れるものは「次からもそうしますか」と確かめてから残す、の案内が、発言に合わせて付く。
- 指摘でないふだんの発言や、スラッシュの命令には付かない。
- 社長が送ったとき（UserPromptSubmit）の hook の出力に入り、手直しの差分の一言とも並んで残る。
"""

from __future__ import annotations

import sys
from pathlib import Path

import version_tool as vt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))

import shiteki_hooks  # noqa: E402

NUMBER = "会社の紹介の所で、スーパーが14社になっていますが、3社です。14は店の数です。直してください"
PHRASE = "「高齢者向け」という言い方は、うちでは使いません。病院や施設の方に失礼に聞こえるので、「やわらか食や減塩が必要な方」と書いてください"
POLICY = "うちがいちばん伝えたいのは、これからも「まちの台所」でいたいという思いです。どの計画書でも、締めくくりで必ずそのことに触れてください"
STRUCTURE = "うちの強みを書くときは、いつも、病院・介護施設向けの話とスーパー向けの話を分けて、別々の段落にしてください"
ONCE = "今回だけ、計画書の本文で「当社」と書いてある所を「やまぶき惣菜」にしてください"
EITHER = "金額の桁が多くて読みにくいので、本文の金額は万円で書いてください"


def note(prompt: str) -> str:
    return shiteki_hooks.note({"prompt": prompt})


def test_the_script_remarks_get_a_note() -> None:
    for prompt in (NUMBER, PHRASE, POLICY, STRUCTURE, ONCE, EITHER):
        text = note(prompt)
        assert text.startswith("【hojokin】社長の発言に、指摘・訂正らしい言葉"), prompt
        assert "記録に残すかを判断" in text and "kiroku" in text


def test_the_note_says_how_to_keep_it() -> None:
    assert "記録には残さない" in note(ONCE)
    for prompt in (PHRASE, POLICY, STRUCTURE):
        assert "聞き返さずに記録に残す" in note(prompt), prompt
    assert "次からもそうしますか" in note(EITHER) and "答える前に残さない" in note(EITHER)
    assert "そのまま記録を直す" in note(NUMBER)
    assert "避けたい言い方と好む言い方に分けて" in note(PHRASE)


def test_ordinary_words_get_nothing() -> None:
    for prompt in ("ありがとうございます", "持続化補助金の計画書を書いてください", "/hojokin:nyuryoku", "", "計画書を少し直しました"):
        assert note(prompt) == "", prompt


def test_the_hook_output_has_the_note(tmp_path: Path) -> None:
    c = vt.Company(tmp_path, name="やまぶき 惣菜")
    out = c.say(EITHER)
    text = (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "指摘・訂正らしい言葉" in text and (out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit")
    assert c.say("ありがとう") in (None, {}) or "指摘" not in str(c.say("ありがとう"))
