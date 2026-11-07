"""T0-13 会社のフォルダでないフォルダ（hooks と道具。TASKS S3・Z1）。

SPEC：会社のフォルダでないフォルダで、プラグインの hooks と道具を動かす。
合格ライン：hooks は何も止めず、何も書かない。道具は、補助金を探すことと会社のフォルダを作ること以外は動かない。

hooks の部分：hooks.json にあるコマンドを、Claude Code と同じように場面ごとの入力を渡して動かす。
Python が動くとき・見つからないとき・壊れているときのどれでも、
- 終了コードは0で、標準出力にも標準エラーにも何も出さない（止める判定も、差し戻しも、文もない）
- 目印のないフォルダ、HOME、一時ファイルの置き場、プラグインのデータの置き場、プラグインのフォルダの中身が変わらない
- Python を動かさない（目印の確かめは run.sh が先に行う）
hook は hooks/hooks.json にしか書かない（plugin.json・skill・subagent には書かない）ことも確かめる。
hooks.json のすべての場面と matcher の組に当たる入力を流すこと、hooks/ のすべての処理が main.py から動くこと
（run.sh の目印の確かめを通らずに動く処理がないこと）も確かめる。

道具の部分：skills/*/scripts/ のすべての道具を、小さな命令ごとに、SKILL.md と同じ形で動かす（TOOL_CALLS）。
会社のフォルダでないフォルダを --folder で渡したときと、--folder なしでそのフォルダで動かしたときのどちらでも、
- 補助金を探す道具（jgrants_search・reinen）は動いてよい。会社のフォルダを作る道具（init_company）は、渡したフォルダの中だけに作る
- ほかの道具は、0でない終了コードで「会社のフォルダ」でないことを伝えて断る
- 目印のないフォルダ、HOME、一時ファイルの置き場、今いるフォルダ、プラグインの写しの中身が変わらない
道具を足したら、TOOL_CALLS に足す（R2 の決まり。表にない道具や小さな命令があれば落ちる）。
同じ表で、原本と公式資料を変えないこと（T0-7）も、すべての道具で確かめる（tests/test_T0_7.py）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import company_tool as ct
import hook_runner as hr
import pytest

# ---- 道具の一覧と呼び方（T0-7 でも使う） ----

SKILLS_DIR = hr.REPO_ROOT / "skills"
CASE = "2026_省力化（一般型）第9回"
ORIGINAL = "原本/見積・契約・請求/2026-10-20_見積書_つばさ台フードシステム.pdf"
SCAN = "原本/見積・契約・請求/2026-11-04_見積書_スキャン.pdf"  # 画像の PDF の原本（T0-7 では、整理の道具で置いてから動かす）
APPLICATION = f"案件/{CASE}/1_申請/申請書/その1・2.docx"
JGRANTS_RECORD = hr.REPO_ROOT / "tests" / "data" / "jgrants" / "道具の実行_補助金.json"

# 道具と呼び方（SKILL.md に書いた形）。小さな命令のある道具は、命令ごとに1つ以上。会社のフォルダは --folder で
# 命令の後ろに渡す。{case}・{original}・{scan}・{application}・{jgrants} は、動かすときに置き換える。ほかの場所は会社のフォルダからの
# 相対（T0-7 では、渡すファイルを先に置いてから、会社のフォルダで動かす）。
TOOL_CALLS = (
    # junbi
    ("junbi/scripts/fetch_documents.py", None, ("--list", "記録/一時/取る資料.json", "--case-round", "第9回")),
    ("junbi/scripts/gaiyou_word.py", None, ("--case", "{case}", "--input", "記録/一時/概要と流れ.json")),
    ("junbi/scripts/kaitei.py", None, ("--case", "{case}", "--pages")),
    ("junbi/scripts/kaitei.py", None, ("--case", "{case}", "--carry")),
    ("junbi/scripts/kaitei.py", None, ("--case", "{case}", "--apply", "記録/一時/読み直し.json")),
    ("junbi/scripts/kaitei.py", None, ("--case", "{case}", "--diff")),
    ("junbi/scripts/kigen.py", None, ("--show",)),
    ("junbi/scripts/kigen.py", None, ("--case", "{case}", "--requests")),
    ("junbi/scripts/kigen.py", None, ("--case", "{case}", "--add", "見積書", "--days", "見積書=14日", "--who", "見積書=社長")),
    ("junbi/scripts/kigen.py", None, ("--case", "{case}", "--status", "見積書=依頼した", "--to", "見積書=つばさ台フードシステム")),
    ("junbi/scripts/kigen.py", None, ("--case", "{case}", "--received", "見積書={original}")),
    ("junbi/scripts/kigen.py", None, ("--near-days", "20")),
    ("junbi/scripts/nittei.py", None, ("--case", "{case}")),
    ("junbi/scripts/nittei.py", None, ("--case", "{case}", "--docs")),
    ("junbi/scripts/seido_data.py", None, ("--case", "{case}", "--check")),
    ("junbi/scripts/seido_data.py", None, ("--case", "{case}", "--stage-folders")),
    ("junbi/scripts/seido_data.py", None, ("--case", "{case}", "--merge")),
    ("junbi/scripts/stage_switch.py", None, ("--case", "{case}", "--show")),
    ("junbi/scripts/stage_switch.py", None, ("--case", "{case}", "--event", "採択発表日=2027-03-10")),
    ("junbi/scripts/urakadori.py", None, ("--form", "補助額", "補助の対象になる経費")),
    ("junbi/scripts/urakadori.py", None, ("--case", "{case}", "--input", "記録/一時/読み取り.json")),
    # kaku
    ("kaku/scripts/kakunin.py", "count", ()),
    ("kaku/scripts/kakunin.py", "konkyo", ("--input", "記録/一時/根拠.json")),
    ("kaku/scripts/kakunin.py", "prepare", ()),
    ("kaku/scripts/kakunin.py", "result", ()),
    ("kaku/scripts/kakunin.py", "finish", ()),
    ("kaku/scripts/kakunin.py", "chiken", ()),
    ("kaku/scripts/keihi.py", "save", ("--case", "{case}", "--input", "記録/一時/経費明細.json")),
    ("kaku/scripts/keihi.py", "show", ()),
    ("kaku/scripts/moji.py", None, ("--file", "{original}")),
    ("kaku/scripts/relevant_records.py", None, ("--item", "1-1 現状分析")),
    ("kaku/scripts/renshu.py", None, ()),
    ("kaku/scripts/sashimodoshi.py", "show", ("--case", "{case}", "--stage", "1_申請")),
    ("kaku/scripts/sashimodoshi.py", "diff", ("--case", "{case}", "--stage", "1_申請")),
    ("kaku/scripts/yoshiki.py", "outline", ()),
    ("kaku/scripts/yoshiki.py", "outline", ("--excel",)),
    ("kaku/scripts/yoshiki.py", "map", ("--input", "記録/一時/様式の対応.json")),
    ("kaku/scripts/yoshiki.py", "write", ("--item", "1-1 現状分析", "--input", "記録/一時/書く文.txt")),
    ("kaku/scripts/yoshiki.py", "cells", ("--input", "記録/一時/その3の値.json")),
    ("kaku/scripts/yoshiki.py", "recalc", ()),
    ("kaku/scripts/yoshiki.py", "sheet", ("--values", "記録/一時/入力シートの値.json")),
    ("kaku/scripts/yoshiki.py", "pdf", ()),
    ("kaku/scripts/zaimu_model.py", "build", ("--spec", "記録/財務モデルの指定.json", "--replace")),
    ("kaku/scripts/zaimu_model.py", "kijun", ("--input", "記録/一時/決算の内訳.json")),
    ("kaku/scripts/zaimu_model.py", "compare", ("--spec", "記録/財務モデルの指定.json", "--actual", "記録/一時/実績.json")),
    # kiroku
    ("kiroku/scripts/init_company.py", None, ()),
    ("kiroku/scripts/record.py", "list", ()),
    ("kiroku/scripts/record.py", "add-fact", ("--source", "社長の発言", "--utterance", "取引先が1社増えた", "--name", "取引先の数",
                                              "--value", "4社", "--changeable")),
    ("kiroku/scripts/record.py", "update-fact", ("--source", "社長の発言", "--utterance", "18人になった", "--id", "x",
                                                 "--value", "18人")),
    ("kiroku/scripts/record.py", "confirm", ("--id", "x")),
    ("kiroku/scripts/record.py", "add-rule", ("--source", "社長の発言", "--utterance", "「弊社」と書かないで", "--kind",
                                              "避けたい言い方", "--content", "弊社", "--trigger", "「弊社」と書かないで")),
    ("kiroku/scripts/record.py", "add-result", ("--source", "社長の発言", "--utterance", "去年は落ちた", "--case",
                                                "2025_ものづくり", "--result", "不採択", "--notice-date", "2025-09-01")),
    ("kiroku/scripts/record.py", "add-defect", ("--case", "{case}", "--stage", "1_申請", "--content", "見積書の期限切れ",
                                                "--cause", "取り直しの時期を見ていなかった", "--watch", "見積書",
                                                "--rule", "有効期限を照らす", "--file", "{original}", "--received", "2026-11-06")),
    ("kiroku/scripts/versions.py", "log", ()),
    ("kiroku/scripts/versions.py", "show", ("--document", "{original}", "--back", "0")),
    ("kiroku/scripts/versions.py", "revert", ("--document", "{application}", "--back", "1", "--reason", "前の書き方に戻して")),
    ("kiroku/scripts/versions.py", "revert", ("--document", "{original}", "--back", "1", "--reason", "前の版に戻して")),
    ("kiroku/scripts/versions.py", "submit", ("--case", "{case}", "--stage", "1_申請", "--reason", "電子申請で出した")),
    ("kiroku/scripts/versions.py", "submissions", ()),
    ("kiroku/scripts/versions.py", "show-submitted", ("--case", "{case}", "--stage", "1_申請")),
    # nyuryoku
    ("nyuryoku/scripts/nyuryoku.py", "sheet", ()),
    ("nyuryoku/scripts/nyuryoku.py", "list", ("--screen", "加点項目")),
    ("nyuryoku/scripts/nyuryoku.py", "check", ("--screen", "加点項目")),
    # sagasu
    ("sagasu/scripts/jgrants_search.py", None, ("--keyword", "省力化", "--response-file", "{jgrants}")),
    ("sagasu/scripts/kimeru.py", "gimu", ()),
    ("sagasu/scripts/kimeru.py", "nijuu", ("--input", "記録/一時/二重受給.json")),
    ("sagasu/scripts/kouho_word.py", None, ("--input", "記録/一時/補助金の候補.json")),
    ("sagasu/scripts/reinen.py", None, ()),
    # shorui
    ("shorui/scripts/fubi.py", "rules", ("--case", "{case}", "--stage", "1_申請")),
    ("shorui/scripts/fubi.py", "check", ("--case", "{case}", "--input", "記録/一時/書類の読み取り.json")),
    ("shorui/scripts/fubi.py", "record", ("--case", "{case}", "--input", "記録/一時/不備.json")),
    ("shorui/scripts/fubi.py", "list", ()),
    ("shorui/scripts/kingaku.py", "image", ("--path", "{scan}", "--rotate", "180", "--band", "0.55,0.75")),
    ("shorui/scripts/kingaku.py", "check", ("--path", "{scan}", "--input", "記録/一時/読み取り.json", "--model", "sonnet",
                                            "--round", "1")),
    ("shorui/scripts/kingaku.py", "confirm", ("--path", "{scan}", "--field", "明細1.単価", "--value", "1000")),
    ("shorui/scripts/kingaku.py", "show", ()),
    ("shorui/scripts/seiri.py", "scan", ()),
    ("shorui/scripts/seiri.py", "text", ("--path", "{original}")),
    ("shorui/scripts/seiri.py", "organize", ("--path", "入れ口/見積2.pdf", "--category", "見積・契約・請求", "--kind", "見積書",
                                             "--date", "2026-11-05", "--partner", "ほしみ機工")),
    ("shorui/scripts/seiri.py", "keep", ("--path", "入れ口/メモ.txt", "--reason", "書類ではないので、そのまま置く")),
    ("shorui/scripts/seiri.py", "list", ()),
    ("shorui/scripts/torikomi.py", "list", ()),
    ("shorui/scripts/torikomi.py", "import", ("--number", "1", "--name", "見積書.pdf")),
    ("shorui/scripts/utsushi.py", "make", ("--original", "{original}", "--case", "{case}", "--stage", "1_申請",
                                           "--document", "見積書")),
    ("shorui/scripts/utsushi.py", "stale", ()),
    ("shorui/scripts/utsushi.py", "remake", ("--copy", f"案件/{CASE}/1_申請/添付する書類/見積書.pdf")),
    ("shorui/scripts/utsushi.py", "list", ()),
)

# 会社のフォルダでなくても動いてよい道具（SPEC T0-13「補助金を探すこと」）と、会社のフォルダを作る道具
SEARCH_TOOLS = {"sagasu/scripts/jgrants_search.py", "sagasu/scripts/reinen.py"}
INIT_TOOL = "kiroku/scripts/init_company.py"
# どのフォルダも読み書きせず、プラグインの中の決まった形（読み取り役に返させる JSON の形）だけを出す呼び方。
# --help と同じく、会社のフォルダでなくても出してよいとした（Z1 で決めた。何も書かないことは同じく確かめる）
FORM_ONLY_CALLS = {("junbi/scripts/urakadori.py", ("--form", "補助額", "補助の対象になる経費"))}
# --folder が要る道具（今いるフォルダからは決めない）と、--folder を持たない道具（会社のフォルダを使わない）
FOLDER_REQUIRED = {"junbi/scripts/nittei.py", "sagasu/scripts/kimeru.py"}
NO_FOLDER_OPTION = {"sagasu/scripts/jgrants_search.py"}


def tool_argv(plugin: Path, script: str, sub, args, folder=None, values=None) -> list:
    """Claude が Bash で動かすのと同じ形のコマンド（/usr/bin/python3 -B <道具> [命令] --folder <フォルダ> ...）。"""
    values = {"case": CASE, "original": ORIGINAL, "scan": SCAN, "application": APPLICATION,
              "jgrants": str(JGRANTS_RECORD), **(values or {})}
    argv = [hr.real_python(), "-B", str(plugin / "skills" / script)]
    if sub:
        argv.append(sub)
    if folder is not None and script not in NO_FOLDER_OPTION:
        argv += ["--folder", str(folder)]
    return argv + [a.format(**values) for a in args]


def tool_env(tmp_path: Path) -> ct.Env:
    """道具を動かす環境（プラグインの写しに、道具が読む schema/ と knowledge/ も足す）。"""
    env = ct.Env(tmp_path)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("schema", "knowledge"):
        shutil.copytree(hr.REPO_ROOT / name, env.plugin / name, ignore=ignore)
    return env


def run_tool(env: ct.Env, argv: list, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """Claude が Bash で動かすのと同じく、CLAUDE_* の環境変数を入れずに、標準入力も渡さずに動かす。"""
    return subprocess.run(argv, env={"PATH": env.path, "HOME": str(env.home), "TMPDIR": str(env.tmp)}, cwd=cwd,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)


def subcommands(script: Path) -> set:
    """道具の小さな命令の一覧（--help の usage の「[-h] {a,b,c} ...」から読む）。"""
    r = subprocess.run([hr.real_python(), "-B", str(script), "--help"], capture_output=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, (script, r)
    usage = " ".join(r.stdout.decode("utf-8").split("\n\n")[0].split())
    found = re.search(r"\[-h\] \{([a-z0-9,\-]+)\} \.\.\.", usage)
    return set(found.group(1).split(",")) if found else set()


def extra_inputs(folder: Path) -> list:
    """hr.event_inputs に足す場面の入力（開き直し・compact、選択肢の画面の答え、添付、LS、続けているときの応答の終わり）。"""
    base = {"session_id": "test", "transcript_path": str(folder / "t.jsonl"), "cwd": str(folder)}
    question = "従業員は今も15人ですか（理由：前回の値を使うため）"
    return [
        ("SessionStart", {**base, "hook_event_name": "SessionStart", "source": "resume"}),
        ("SessionStart", {**base, "hook_event_name": "SessionStart", "source": "compact"}),
        ("PostToolUse", {**base, "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
                         "tool_input": {"questions": [{"question": question, "header": "人数",
                                                       "options": [{"label": "はい"}, {"label": "いいえ"}]}]},
                         "tool_response": {"answers": {question: "はい"}}}),
        ("PreToolUse", {**base, "hook_event_name": "PreToolUse", "tool_name": "mcp__claude-in-chrome__file_upload",
                        "tool_input": {"paths": [str(folder / "原本" / "見積書.pdf")], "ref": "ref_5"}}),
        ("PreToolUse", {**base, "hook_event_name": "PreToolUse", "tool_name": "LS", "tool_input": {"path": str(folder.parent)}}),
        ("Stop", {**base, "hook_event_name": "Stop", "stop_hook_active": True}),
    ]


def all_inputs(folder: Path) -> list:
    return hr.event_inputs(folder) + extra_inputs(folder)


def make_plain_folder(tmp_path):
    folder = tmp_path / "ふつうのフォルダ"
    folder.mkdir()
    (folder / "メモ.txt").write_text("会社のフォルダではない", encoding="utf-8")
    # 目印と紛らわしい名前のファイル（フォルダではない）があっても、会社のフォルダとみなさない
    (folder / ".hojokin").write_text("", encoding="utf-8")
    home = tmp_path / "home"
    data = tmp_path / "plugin-data"
    home.mkdir()
    data.mkdir()
    return folder, home, data


def test_every_scene_goes_through_run_sh() -> None:
    """どの場面の hook も run.sh から動く（目印の確かめを通らずに動くものがない）。"""
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    assert set(config["hooks"]) == set(hr.EVENTS)
    for event, entries in config["hooks"].items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command"
                assert h["command"].startswith('sh "${CLAUDE_PLUGIN_ROOT}/hooks/run.sh" ' + event), h["command"]


def frontmatter(path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ""
    return text[4:text.index("\n---", 4)]


def test_hooks_only_in_hooks_json() -> None:
    """hooks/hooks.json のほかに hook を書いた所がない（あれば、run.sh を通らずに動くおそれがある）。"""
    manifest = json.loads((hr.REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest.get("hooks") in (None, "./hooks/hooks.json"), manifest.get("hooks")
    docs = sorted(hr.REPO_ROOT.glob("skills/*/SKILL.md")) + sorted(hr.REPO_ROOT.glob("agents/*.md"))
    assert docs
    for doc in docs:
        keys = [line.split(":", 1)[0] for line in frontmatter(doc).splitlines() if line and not line[0].isspace()]
        assert "hooks" not in keys, doc


@pytest.mark.parametrize("python", ["本物", "なし", "壊れた", "固まる"])
@pytest.mark.parametrize("project_dir_env", [True, False], ids=["CLAUDE_PROJECT_DIRあり", "今いるフォルダだけ"])
def test_hooks_do_nothing_outside_company_folder(tmp_path, python, project_dir_env) -> None:
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_plain_folder(tmp_path)
    ran = tmp_path / "python-ran"
    path = hr.make_bin(tmp_path / "bin", python, ran)
    (tmp_path / "tmp").mkdir()
    # 目印のないフォルダ・HOME・一時ファイルの置き場・プラグインのデータ・プラグインの写しを、まとめて見る
    before = hr.snapshot(tmp_path)

    count = 0
    tools = set()
    for event, payload in all_inputs(folder):
        for command in hr.hook_commands(event, hr.match_name(payload)):
            tools.add(payload.get("tool_name", event))
            r = hr.run(command, payload, plugin=plugin, folder=folder, path=path, home=home, data=data,
                       project_dir_env=project_dir_env)
            assert r.returncode == 0, (event, payload.get("tool_name"), r)
            assert r.stdout == b"", (event, payload.get("tool_name"), r.stdout.decode("utf-8"))
            assert r.stderr == b"", (event, payload.get("tool_name"), r.stderr.decode("utf-8"))
            count += 1

    # 5つの場面と、守る道具（書き込み・Bash・ブラウザ）と外を読む道具の PreToolUse をすべて動かした
    assert count >= len(hr.EVENTS) + 5
    assert {"Write", "Edit", "NotebookEdit", "Bash", "Read", "Grep", "Glob",
            "mcp__Claude_Browser__computer", "mcp__computer-use__left_click"} <= tools
    assert not ran.exists(), "目印のないフォルダで Python が動いた"
    assert hr.snapshot(tmp_path) == before


def test_python_side_also_checks_marker(tmp_path) -> None:
    """run.sh を通さずに main.py を動かしても、目印がなければ何もしない（DESIGN 5章）。"""
    plugin = hr.copy_plugin(tmp_path / "plugin")
    folder, home, data = make_plain_folder(tmp_path)
    before = hr.snapshot(folder, home, data, plugin)
    for event, payload in all_inputs(folder):
        r = subprocess.run(
            [hr.real_python(), "-B", str(plugin / "hooks" / "main.py"), event, "guard"],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_PROJECT_DIR": str(folder)},
            cwd=folder,
            capture_output=True,
            timeout=30,
        )
        assert r.returncode == 0, r
        assert r.stdout == b"" and r.stderr == b"", r
    assert hr.snapshot(folder, home, data, plugin) == before


def test_every_hook_group_gets_an_input(tmp_path) -> None:
    """hooks.json のすべての場面と matcher の組に、上で流す入力のどれかが当たる（流していない hook がない）。"""
    config = json.loads(hr.HOOKS_JSON.read_text(encoding="utf-8"))
    inputs = all_inputs(tmp_path / "ふつうのフォルダ")
    for event, entries in config["hooks"].items():
        for entry in entries:
            matcher = entry.get("matcher", "")
            hit = [p for e, p in inputs if e == event and hr.claude_matches(matcher, hr.match_name(p))]
            assert hit, (event, matcher)


def test_every_hook_module_runs_through_main() -> None:
    """hooks/ のすべての処理は、main.py から読み込まれて動く（run.sh と main.py の目印の確かめを通らずに動くものがない）。"""
    hooks_dir = hr.REPO_ROOT / "hooks"
    modules = {p.stem for p in hooks_dir.glob("*.py")}
    imports = {m: set(re.findall(r"^\s*(?:import|from)\s+(\w+)", (hooks_dir / f"{m}.py").read_text(encoding="utf-8"),
                                 re.M)) & modules for m in modules}
    seen, todo = {"main"}, ["main"]
    while todo:
        for name in imports[todo.pop()] - seen:
            seen.add(name)
            todo.append(name)
    assert seen == modules, sorted(modules - seen)
    for m in modules - {"main"}:
        assert "__main__" not in (hooks_dir / f"{m}.py").read_text(encoding="utf-8"), m


# ---- 道具の部分（Z1） ----


def test_every_tool_and_subcommand_is_listed() -> None:
    """skills/*/scripts/ のすべての道具と、その小さな命令のすべてが TOOL_CALLS にある（R2 の決まり）。"""
    scripts = {p.relative_to(SKILLS_DIR).as_posix() for p in SKILLS_DIR.glob("*/scripts/*.py")}
    assert scripts
    assert {s for s, _sub, _args in TOOL_CALLS} == scripts
    for script in sorted(scripts):
        listed = {sub for s, sub, _args in TOOL_CALLS if s == script and sub}
        assert listed == subcommands(SKILLS_DIR / script), script
    assert SEARCH_TOOLS | {INIT_TOOL} | FOLDER_REQUIRED | NO_FOLDER_OPTION <= scripts


def make_plain(tmp_path: Path) -> Path:
    """会社のフォルダでないフォルダ（目印と紛らわしい名前のファイルもある）。"""
    plain = tmp_path / "ふつうのフォルダ"
    plain.mkdir()
    (plain / "メモ.txt").write_text("会社のフォルダではない", encoding="utf-8")
    (plain / ".hojokin").write_text("", encoding="utf-8")
    (plain / "記録" / "一時").mkdir(parents=True)
    (plain / "記録" / "一時" / "補助金の候補.json").write_text('{"候補": []}', encoding="utf-8")
    return plain


@pytest.mark.parametrize("script", sorted({s for s, _sub, _args in TOOL_CALLS} - {INIT_TOOL}))
def test_tool_does_nothing_outside_company_folder(tmp_path, script) -> None:
    """会社のフォルダでないフォルダでは、補助金を探す道具のほかは、何も書かずに断る（--folder で渡しても、そこで動かしても）。"""
    env = tool_env(tmp_path)
    plain = make_plain(tmp_path)
    watched = (plain, env.home, env.tmp, env.cwd, env.plugin)
    before = hr.snapshot(*watched)
    calls = [(sub, args) for s, sub, args in TOOL_CALLS if s == script]
    assert calls
    for sub, args in calls:
        modes = [("--folder で渡す", plain, env.cwd)]
        if script not in FOLDER_REQUIRED:
            modes.append(("そのフォルダで動かす", None, plain))
        for mode, folder, cwd in modes:
            r = run_tool(env, tool_argv(env.plugin, script, sub, args, folder=folder), cwd)
            out = (r.stdout + r.stderr).decode("utf-8", "replace")
            where = (script, sub, mode, r.returncode, out[:600])
            assert "Traceback" not in out, where
            if script in SEARCH_TOOLS:
                assert r.returncode == 0, where
            elif (script, args) in FORM_ONLY_CALLS:
                assert r.returncode == 0 and json.loads(r.stdout.decode("utf-8")), where
            else:
                assert r.returncode != 0, where
                assert "会社のフォルダ" in out, where
            assert hr.snapshot(*watched) == before, where


def test_init_company_writes_only_inside_the_folder(tmp_path) -> None:
    """会社のフォルダを作る道具は、渡したフォルダ（とそこで動かしたフォルダ）の中だけに作る。"""
    env = tool_env(tmp_path)
    outside = (env.home, env.tmp, env.cwd, env.plugin)
    before = hr.snapshot(*outside)
    for mode in ("--folder で渡す", "そのフォルダで動かす"):
        target = tmp_path / f"新しい会社（{mode}）"
        target.mkdir()
        folder, cwd = (target, env.cwd) if mode == "--folder で渡す" else (None, target)
        r = run_tool(env, tool_argv(env.plugin, INIT_TOOL, None, (), folder=folder), cwd)
        assert r.returncode == 0, (mode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8"))
        assert (target / ".hojokin").is_dir(), mode
        assert hr.snapshot(*outside) == before, mode
