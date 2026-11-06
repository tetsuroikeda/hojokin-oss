"""skill の allowed-tools（DESIGN 4.1「スクリプトの動かし方」、4.7 の会社のフォルダの設定）。

会社のフォルダの `.claude/settings.json` の blockReadsOutsideWorkingDirectories があると、Claude Code（2.1.317）は、
Bash のコマンドが名指す会社のフォルダの外の場所（プラグインのスクリプト）を、次のように扱う（波3 の claude -p で確かめた）。
- プラグインを入れた場所（~/.claude/plugins/ の下）は、読む側の block で「作業フォルダの外」としては断られない。
  ただし、Read の許可の規則がその場所を含まないと「read block では確かめられない」として確かめになる（-p では拒まれる）。
- それ以外の場所（--plugin-dir で読み込んだ開発中のフォルダなど）は、許可の規則があっても断られる。
  開発の確かめでは、--settings の permissions.blockReadsExemptPaths にその場所を入れると、入れた場所と同じ扱いになる。
- そのため、各 skill の allowed-tools に、その skill のスクリプトを動かす Bash の規則と、その skill のフォルダを読む
  Read の規則を書く。場所は `${CLAUDE_PLUGIN_ROOT}` で書くので、入れ直して場所が変わっても効く。
- 会社のフォルダの設定（lib/company_init.py）には、プラグインの場所を書かない。block の2つもそのまま残す。

ここでは、SKILL.md の前置きと本文の形だけを確かめる（claude -p は使わない）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lib import company_init

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p.parent.name for p in REPO_ROOT.glob("skills/*/SKILL.md"))
ROOT = "${CLAUDE_PLUGIN_ROOT}"


# ほかの skill の道具を本文で使う skill と、その道具（M12b：kaku は、社長の答えを kiroku の record.py で会社の記録に残す）
SHARED_SCRIPTS = {"kaku": ["skills/kiroku/scripts/record.py"]}
# ほかの場所を読む skill と、その場所（11/6 の後：kaku は、書くときに作者の知見 knowledge/ の構成の型と審査の観点を読む）
SHARED_READS = {"kaku": ["knowledge"]}


def expected_rules(skill: str) -> list:
    rules = [
        f'Bash(python3 -B "{ROOT}/skills/{skill}/scripts/*)',
        f"Bash(python3 -B {ROOT}/skills/{skill}/scripts/*)",
        f"Read(/{ROOT}/skills/{skill}/**)",
    ]
    for script in SHARED_SCRIPTS.get(skill, []):
        rules += [
            f'Bash(python3 -B "{ROOT}/{script}*)',
            f"Bash(python3 -B {ROOT}/{script}*)",
            f"Read(/{ROOT}/{script.rsplit('/', 1)[0]}/**)",
        ]
    rules += [f"Read(/{ROOT}/{place}/**)" for place in SHARED_READS.get(skill, [])]
    return rules


def split_doc(skill: str):
    text = (REPO_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---", 4)
    return text[4:end], text[end + 4:]


def allowed_tools(front: str) -> list:
    """前置きの `allowed-tools:` の下に「  - 」で並べた規則。"""
    lines = front.splitlines()
    rules = []
    for i, line in enumerate(lines):
        if line.rstrip() == "allowed-tools:":
            for item in lines[i + 1:]:
                if not item.startswith("  - "):
                    break
                rules.append(item[4:].strip())
    return rules


def script_commands(body: str) -> list:
    """本文に書いた、プラグインのスクリプトを動かすコマンド（行の頭の空白は除く）。"""
    return [line.strip() for line in body.splitlines() if line.strip().startswith("python3 ") and ROOT in line]


def covered_by_bash_rule(command: str, rules: list) -> bool:
    """Claude Code の Bash の規則のように、末尾の * の前までが、コマンドの頭と同じなら当たるとみなす。"""
    for rule in rules:
        m = re.fullmatch(r"Bash\((.*)\*\)", rule)
        if m and command.startswith(m.group(1)):
            return True
    return False


def plugin_paths(command: str) -> list:
    """コマンドが名指すプラグインの中の場所（`${CLAUDE_PLUGIN_ROOT}/` の後ろ）。"""
    return re.findall(re.escape(ROOT) + r"/([^\"'\s]+)", command)


def test_every_skill_is_checked() -> None:
    assert SKILLS == ["junbi", "kaku", "kiroku", "nyuryoku", "sagasu", "shorui"]


@pytest.mark.parametrize("skill", SKILLS)
def test_allowed_tools_cover_only_own_scripts(skill) -> None:
    """allowed-tools は、その skill のスクリプトを動かす Bash と、その skill のフォルダを読む Read だけ。"""
    front, _ = split_doc(skill)
    assert allowed_tools(front) == expected_rules(skill)


@pytest.mark.parametrize("skill", SKILLS)
def test_commands_in_body_match_allowed_tools(skill) -> None:
    """本文に書いたコマンドは、allowed-tools の Bash の規則に当たり、名指すプラグインの場所はその skill のフォルダの中にある。"""
    front, body = split_doc(skill)
    rules = allowed_tools(front)
    commands = script_commands(body)
    assert commands, skill
    for command in commands:
        assert covered_by_bash_rule(command, rules), command
        for path in plugin_paths(command):
            assert path.startswith(f"skills/{skill}/") or path in SHARED_SCRIPTS.get(skill, []), (command, path)
            # 本文に書いたスクリプトや資料の一覧が、本当にある（名前の書き違いがない）
            if "<" not in path:
                assert (REPO_ROOT / path).exists(), path


def test_rule_shapes_do_not_allow_other_commands() -> None:
    """規則の形の確かめ：ほかの skill のスクリプト、その場のコード、会社のフォルダの中の Python には当たらない。"""
    rules = expected_rules("kiroku")
    root = ROOT
    assert covered_by_bash_rule(f'python3 -B "{root}/skills/kiroku/scripts/record.py" list --folder "x"', rules)
    assert covered_by_bash_rule(f"python3 -B {root}/skills/kiroku/scripts/versions.py log", rules)
    assert not covered_by_bash_rule(f'python3 -B "{root}/skills/kaku/scripts/yoshiki.py" outline', rules)
    assert not covered_by_bash_rule('python3 -B -c "print(1)"', rules)
    assert not covered_by_bash_rule("python3 -B 記録/書いた.py", rules)
    # kaku が使えるほかの skill の道具は、kiroku の record.py だけ（versions.py などには当たらない）
    kaku = expected_rules("kaku")
    assert covered_by_bash_rule(f'python3 -B "{root}/skills/kiroku/scripts/record.py" add-fact --folder "x"', kaku)
    assert not covered_by_bash_rule(f'python3 -B "{root}/skills/kiroku/scripts/versions.py" revert', kaku)
    assert not covered_by_bash_rule(f'python3 -B "{root}/skills/junbi/scripts/stage_switch.py"', kaku)


def test_company_settings_keep_blocks_and_name_no_plugin_place() -> None:
    """会社のフォルダの設定は、block の2つを残し、プラグインの場所やスクリプトを許す規則を足さない。"""
    settings = company_init.merged_settings(None)
    permissions = settings["permissions"]
    assert permissions["blockReadsOutsideWorkingDirectories"] is True
    assert permissions["blockWritesOutsideWorkingDirectories"] is True
    assert not [r for r in permissions["allow"] if r.startswith(("Bash", "Read"))]
    assert "additionalDirectories" not in permissions
