"""Artifact の道具（claude.ai に上げる）の守り（PreToolUse。DESIGN 5章「書類と履歴を、経営者が選んだ範囲のほかに送らない」の
文案。中身の画面は lib/status_artifact.py）。

Artifact の道具は、社長の頼みに応じて上げるとき、確かめの画面も分類器も通らずに claude.ai に上げる（公式文書）。道具の説明も、
仕上がった資料は自分から上げるよう促す。そのため会社のフォルダでは、次のときだけ通す。
- Artifact の publish（action を省いたときも publish）：上げるファイルが junbi の道具の作った今の状態の写し
  （`.hojokin/一時/今の状態_claudeai.html`）で、中身が控えのハッシュと同じで、社長の同意があり（`.hojokin/設定.json`）、
  ほかの値（添えるファイル・素材・型・実行の能力など）がなく、題・説明・印が決まった値で、URL を渡すなら残した URL のとき。
- Artifact の read・list・open・quickstart・pin・unpin・delete（上げることにならない。消すときは、道具の決まりで社長に確かめる）。
- ArtifactData の読み取り（get・list・query・profiles）と、ArtifactComments の read・resolve・watch。
それ以外（ほかのファイルの publish、ArtifactData の書き込み、ArtifactComments の返信、知らない action）は拒む。
hooks.json では guard の matcher で受け取るので、Python が動かないときも run.sh が拒む。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import outside_read

TOOLS = ("Artifact", "ArtifactData", "ArtifactComments")
PUBLISH_KEYS = {"action", "file_path", "url", "title", "description", "icon", "pin"}
ARTIFACT_PASS = {"read", "list", "open", "quickstart", "pin", "unpin", "delete"}
DATA_PASS = {"get", "list", "query", "profiles"}
COMMENTS_PASS = {"read", "resolve", "watch"}
WHY = "会社の書類と記録を、社長が選んだ置き場所のほかに送らないため"
HOW = ("社長が claude.ai でも今の状態を見たいと頼んだときは、junbi の手順で、道具（artifact.py --make）が作った画面を、"
       "同意を得てから上げてください")


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _only_copy(detail: str) -> dict:
    return _deny(f"会社のフォルダでは、claude.ai（Artifact）に上げられるのは、今の状態の写しだけです（{WHY}）。{detail}。{HOW}。")


def _publish(data: dict, folder: Path) -> Optional[dict]:
    from lib import status_artifact as sa

    tool_input = data.get("tool_input") or {}
    extra = sorted(k for k in tool_input if k not in PUBLISH_KEYS)
    if extra:
        return _only_copy(f"添えるファイル・素材・型などの値（{'、'.join(extra)}）は使えません")
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return _only_copy("上げるファイル（file_path）がありません")
    target = outside_read.resolve(raw, outside_read.tool_cwd(data, folder))
    expected = outside_read.real_path(sa.page_path(folder))
    if target != expected:
        return _only_copy(f"上げようとしたファイル（{raw}）は、写しではありません")
    for key, fixed in (("title", sa.TITLE), ("description", sa.DESCRIPTION), ("icon", sa.ICON)):
        value = tool_input.get(key)
        if value is not None and value != fixed:
            return _only_copy(f"{key} は「{fixed}」にしてください（ギャラリーのカードに出るので、会社名などを入れないため）")
    try:
        agreed = sa.agreed(folder)
        saved = sa.saved_url(folder)
    except ValueError as error:
        return _deny(f"社長の同意を確かめられないので、claude.ai に上げません（{error}）。")
    if not agreed:
        return _deny(f"claude.ai に上げることへの社長の同意が、まだありません（{WHY}）。上げるもの・上げないもの・だれが見られるかを"
                     "社長に示し、選択肢の画面で聞いてから、artifact.py --agree で残してください。")
    try:
        actual = sa.file_hash(target)
    except OSError as error:
        return _deny(f"写しを読めないので、claude.ai に上げません（{error}）。artifact.py --make で作り直してください。")
    if not sa.stamp(folder) or actual != sa.stamp(folder):
        return _deny("写しの中身が、道具が作ったときと違います（書き換えられたか、作り直しの途中です）。claude.ai に上げません。"
                     "artifact.py --make で作り直してから、直さずに上げてください。")
    url = tool_input.get("url")
    if url is not None and url != saved:
        return _deny(f"URL（{url}）は、残した上げ先（{saved or 'まだありません'}）と違います。ほかのページを上書きしないため、上げません。"
                     "前に上げたページを更新するときは、artifact.py --make の結果の URL を渡してください。")
    return None


def pre_tool_use(data: dict, folder: Path) -> Optional[dict]:
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    action = tool_input.get("action")
    if tool == "Artifact":
        if action in (None, "publish"):
            return _publish(data, folder)
        if action in ARTIFACT_PASS:
            return None
        return _only_copy(f"この使い方（action: {action}）は通しません")
    if tool == "ArtifactData":
        if action in DATA_PASS:
            return None
        return _deny(f"会社のフォルダでは、claude.ai のページのデータに書き込みません（{WHY}）。")
    if tool == "ArtifactComments":
        if action in COMMENTS_PASS:
            return None
        return _deny(f"会社のフォルダでは、claude.ai のページのコメントに返信しません（{WHY}）。返信は社長が claude.ai で行ってください。")
    return None
