"""版の名前のファイル（SPEC 共通の要件「書類の版の管理」、DESIGN 5章「版のファイルを増やさない」。TASKS M0a）。

書類ごとに1つのファイルを直して使う。「_v2」「最終」「修正版」「コピー」などの名前の別ファイルは作らない。
前の版は、版の履歴（lib/history.py）に自動で残る。
- PreToolUse：Write・Edit・NotebookEdit で、名前がこの型に当たる新しいファイルを作ることを拒む。
  前からあるファイル（社長が置いた「見積書_最終.pdf」など）を直すことは拒まない。
- Stop：その場のコード（Bash など）で作られたものを、応答の終わりに見つけ、元のファイルにまとめるよう伝える。

名前は、拡張子を除いた部分を、文字の形をそろえて（NFKC。全角の英数字・記号は半角に、濁点の分かれた形は1文字に）
小文字にしてから比べる。「富士コピー」「コピー機の見積書」「最終確認のメモ」のように、言葉の一部として出てくる
ものには当てない。版を表す言葉は、名前の端か区切りの記号（空白・「_」「-」「.」「・」・かっこなど）に挟まれた
ときだけ当てる。「最終版」「修正版」「のコピー」のように、それだけで版と分かる形は、どこにあっても当てる。

ここは文字の処理だけで、ファイルも版の履歴も読まない（PreToolUse の守りの中で動くため）。
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

# 区切りの記号（NFKC にそろえた後の形）。「ー」（長音）は言葉の一部なので入れない
_SEP = r"[\s_\-.・,、+~〜()\[\]【】「」『』—–]"
_B = rf"(?:^|(?<={_SEP}))"  # 名前の始まりか、区切りの記号の後
_A = rf"(?=$|{_SEP})"  # 名前の終わりか、区切りの記号の前

# (社長と Claude に見せる型の説明, 型)。DESIGN 5章に挙がった4つ（_v2・最終・修正版・コピー）を必ず含む。
# どこまで当てるかは SPEC・DESIGN に決まりがないので、仮の形（TASKS M0a の質問）。
RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        ("「_v2」のような版の番号", rf"{_B}(?:v|ver|version|rev)\.?\s?[0-9]+{_A}"),
        ("「第2版」のような版の番号", rf"{_B}第?\s?[0-9]+\s?(?:版|稿){_A}"),
        ("「最終」", rf"最終(?:版|稿)|{_B}最終{_A}"),
        ("「最新」", rf"最新版|{_B}最新{_A}"),
        ("「修正版」", rf"(?:修正|訂正|改訂|改定|差し?替え?)(?:版|稿)|{_B}(?:修正|訂正|差し?替え?)(?:済み?|後)?{_A}"),
        ("「コピー」", rf"の\s?コピー|{_B}(?:コピー|複製)(?:\s?[0-9]+)?{_A}"),
        ("「copy」", rf"^copy\s?of\s|{_B}copy(?:\s?[0-9]+)?{_A}"),
        ("「final」「old」などの版の言葉", rf"{_B}(?:final|latest|fixed|old|new|bak|backup|orig){_A}"),
        ("「旧」「新」", rf"旧版|新版|{_B}(?:旧|新){_A}"),
        ("「バックアップ」", r"バックアップ"),
        ("「(1)」のような複製の番号", r"\(\s?[0-9]+\s?\)$"),
    )
)
# 版を表す拡張子
BACKUP_SUFFIXES = (".bak", ".old", ".orig", ".backup")
BACKUP_LABEL = "「.bak」のような控えの拡張子"

# 応答の終わりに見つけるときに除く場所（会社のフォルダからの場所の始まり）。
# 原本と入れ口は社長が置いた書類の名前のまま、公式資料は公式の名前のまま、.hojokin・.claude はプラグインの設定。
# 書類を整理するスクリプトと公式資料を取るスクリプトは、決まった名前で書く（DESIGN 5章）。
STOP_EXCLUDED_TOP = ("原本", "入れ口", ".hojokin", ".claude")
OFFICIAL_DIR = "公式資料"
CASES_DIR = "案件"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _split(name: str) -> Tuple[str, str]:
    stem, suffix = os.path.splitext(name)
    if not stem:  # 「.bak」のような、点で始まる名前
        return name, ""
    return stem, suffix


def version_label(name: str) -> Optional[str]:
    """ファイルの名前（場所を含まない）が版の名前なら、当たった型の説明を返す。当たらなければ None。"""
    stem, suffix = _split(unicodedata.normalize("NFC", name))
    if _fold(suffix) in BACKUP_SUFFIXES:
        return BACKUP_LABEL
    folded = _fold(stem)
    for label, pattern in RULES:
        if pattern.search(folded):
            return label
    return None


def checked_at_stop(path: str) -> bool:
    """応答の終わりに、版の名前を見る場所か（会社のフォルダからの場所。区切りは「/」）。"""
    parts = unicodedata.normalize("NFC", path).split("/")
    if parts[0] in STOP_EXCLUDED_TOP:
        return False
    if len(parts) >= 3 and parts[0] == CASES_DIR and parts[2] == OFFICIAL_DIR:
        return False
    return True


def _without_version(stem: str) -> str:
    folded = _fold(stem)
    for _label, pattern in RULES:
        folded = pattern.sub("", folded)
    return re.sub(rf"^{_SEP}+|{_SEP}+$", "", folded)


def original_of(folder: Path, path: str) -> Optional[str]:
    """版の名前のファイルの、元のファイルらしいもの（同じフォルダにあり、版の言葉を除いた名前が同じもの）。

    path は会社のフォルダからの場所。見つかれば、その場所（会社のフォルダから）を返す。
    """
    path = unicodedata.normalize("NFC", path)
    directory, _, name = path.rpartition("/")
    stem, suffix = _split(name)
    if _fold(suffix) in BACKUP_SUFFIXES:
        # 「その1.docx.bak」の元は「その1.docx」
        stem, suffix = _split(stem)
        base = _fold(stem)
    else:
        base = _without_version(stem)
    if not base:
        return None
    try:
        siblings = sorted(os.listdir(folder / directory if directory else folder))
    except OSError:
        return None
    for sibling in siblings:
        candidate = unicodedata.normalize("NFC", sibling)
        if candidate == name or version_label(candidate) is not None:
            continue
        s_stem, s_suffix = _split(candidate)
        if _fold(s_suffix) == _fold(suffix) and _fold(s_stem) == base:
            return f"{directory}/{candidate}" if directory else candidate
    return None


RULE_TEXT = "書類ごとに1つのファイルを直して使う決まりです（前の版は、版の履歴に自動で残ります）"


def deny_reason(path: str, label: str, original: Optional[str]) -> str:
    """PreToolUse で拒むときの文。"""
    name = path.rsplit("/", 1)[-1]
    where = f"元のファイル（{original}）を直してください" if original else "元のファイルを直すか、版を表さない名前にしてください"
    return (
        f"版の名前のファイルは作れません（{name}：{label}）。{RULE_TEXT}。{where}。"
        "社長が別の書類として残したいときは、版を表さない名前を社長と決めてください（hojokin プラグインの決まり）。"
    )


def stop_reason(found: List[Tuple[str, str, Optional[str]]]) -> str:
    """Stop で Claude に伝える文。found は (場所, 型の説明, 元のファイル) の一覧。"""
    lines = [f"【hojokin】この応答の中で、版の名前のファイルが作られました。{RULE_TEXT}。"]
    for path, label, original in found:
        to = f" → 元のファイル：{original}" if original else " → 元のファイルが見つかりません"
        lines.append(f"- {path}（{label}）{to}")
    lines.append(
        "中身を元のファイルにまとめてから、版の名前のファイルを消してください（Word・Excel はスクリプトで書き込む）。"
        "元のファイルが分からないときは、社長に聞いてください。"
    )
    return "\n".join(lines)
