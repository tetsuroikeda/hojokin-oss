"""Stop（応答を終えたとき）：答えの引用が、示した資料のページに本当にあるかを照らす（SPEC F4・T4-2、DESIGN 9.2。TASKS B26）。

答えの形は「結論 → 根拠（資料名・ページ・どの回の資料かと、短い引用）→ 注意」。引用は「」で囲み、資料名とページを添える。
最後の応答（last_assistant_message）から、資料名とページが「」のすぐ前か後ろにある引用を拾い、
`記録/資料の本文/<案件>/` のそのページの文字（形をそろえたもの。空白と改行を除く）に、引用が本当にあるかを照らす。
- 資料名は、資料の一覧（`記録/資料の本文/<案件>/資料の一覧.json` の「資料」と「前の回の資料」）の id か名前で引く。
  回（「（第8回）」）があれば、その回の資料に絞る。どの資料にも当たらない名前（Web のページなど）の引用は照らさない。
- 「…」で区切った引用は、切れ端（4字以上）がどれもそのページにあればよい。ページの範囲（p.26–27）は、続けた文字でも見る。
- 短い引用（形をそろえて6字未満。「要確認」のような語）は照らさない。
外れた引用があれば、照らした結果の文を返す（hooks/stop.py が応答を終わらせずに Claude に渡し、答え直させる。
Stop の hook で続けているとき〈stop_hook_active〉は、知らせるだけにして止めない。hooks/originals_hooks.stop）。
会社のフォルダの中だけを読む（lib/places.py。lib/urakadori.Texts）。何も書かない。hook を落とさないよう、例外は握りつぶす。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

QUOTE = re.compile(r"「([^「」\n]{4,400})」")
REF = re.compile(
    r"(?P<doc>[^\s「」、。，,：:（）()\[\]【】|｜*]{2,30}?)\s*"
    r"(?:[（(](?P<round>第\s*[0-9０-９]+\s*回)[^）)]{0,20}[）)])?\s*"
    r"(?:[pPｐＰ]\.?\s*|ページ\s*)(?P<page>[0-9０-９]{1,3})(?:\s*[–\-−〜~ー－]\s*(?P<end>[0-9０-９]{1,3}))?(?![0-9０-９])"
)
NEAR = 8          # 引用の「」と資料名・ページの間に置いてよい字数
MIN_QUOTE = 6     # 照らす引用の長さ（形をそろえた後）
MIN_PIECE = 4     # 「…」で区切った切れ端の長さ
TEXT_DIR = ("記録", "資料の本文")
LIST_FILE = "資料の一覧.json"


def _int(text: str) -> int:
    return int(unicodedata.normalize("NFKC", text))


def _round_no(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"([0-9]+)", unicodedata.normalize("NFKC", text))
    return int(m.group(1)) if m else None


def find_quotes(message: str) -> List[Tuple[str, str, Optional[int], int, Optional[int]]]:
    """（引用、資料名、回、ページ、終わりのページ）の一覧。資料名とページが「」のすぐ前か後ろにあるものだけ。"""
    out = []
    for m in QUOTE.finditer(message):
        before = message[max(0, m.start() - 60):m.start()]
        after = message[m.end():m.end() + 60]
        ref = None
        refs_before = [r for r in REF.finditer(before) if len(before) - r.end() <= NEAR]
        if refs_before:
            ref = refs_before[-1]
        else:
            first_after = next(iter(REF.finditer(after)), None)
            if first_after is not None and first_after.start() <= NEAR:
                ref = first_after
        if ref is None:
            continue
        end = _int(ref.group("end")) if ref.group("end") else None
        out.append((m.group(1), ref.group("doc"), _round_no(ref.group("round")), _int(ref.group("page")), end))
    return out


def _lists(folder: Path) -> List[Tuple[str, Dict]]:
    """（案件、資料の一覧）の並び。会社のフォルダの外を指すものは読まない。"""
    from lib import place_text

    root = folder.joinpath(*TEXT_DIR)
    if place_text.read_problem(folder, root, "資料の本文") or not root.is_dir():
        return []
    out = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = case_dir / LIST_FILE
        if place_text.read_problem(folder, path, "資料の一覧") or not path.is_file():
            continue
        try:
            listed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(listed, dict):
            out.append((case_dir.name, listed))
    return out


def _norm_name(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))


def resolve(lists: List[Tuple[str, Dict]], doc: str, round_no: Optional[int]) -> List[Tuple[str, str]]:
    """資料名（と回）に当たる（案件、資料の id）の並び。"""
    name = _norm_name(doc)
    exact, partial = [], []
    for case, listed in lists:
        entries = [d for key in ("資料", "前の回の資料") for d in listed.get(key) or [] if isinstance(d, dict)]
        for d in entries:
            did, dname = _norm_name(d.get("id")), _norm_name(d.get("名前"))
            if round_no is not None and _round_no(str(d.get("公募回") or "")) not in (None, round_no):
                continue
            if name == did:
                exact.append((case, str(d.get("id"))))
            elif dname and (name == dname or (len(name) >= 2 and (dname.endswith(name) or name.endswith(dname)))):
                partial.append((case, str(d.get("id"))))
    return exact or partial


def check_quote(folder: Path, hits: List[Tuple[str, str]], quote: str, page: int, end: Optional[int]) -> Optional[str]:
    """引用が、当たる資料のどれかの、そのページにあれば None。なければ、わけ。"""
    from lib import urakadori

    pieces = [p for p in urakadori.fragments(quote) if len(p) >= MIN_PIECE]
    if not pieces:
        return None
    reasons = []
    for case, doc_id in hits:
        texts = urakadori.Texts(folder, case)
        try:
            pages, problems = texts.pages({"資料": doc_id, "ページ": page, "終わりのページ": end or page})
        except Exception:  # 外を指す本文などは読まない
            continue
        if problems and not pages:
            reasons.append("；".join(problems))
            continue
        if any(all(piece in text for piece in pieces) for _label, text in pages):
            return None
        reasons.append(f"{doc_id} p.{page}{'–' + str(end) if end else ''} の文字にありません")
    return reasons[0] if reasons else None


def notes(data: dict, folder: Path) -> List[str]:
    """外れた引用ごとの知らせ（なければ空）。"""
    message = (data or {}).get("last_assistant_message")
    if not isinstance(message, str) or "「" not in message:
        return []
    try:
        from lib import urakadori

        lists = None
        out = []
        for quote, doc, round_no, page, end in find_quotes(message):
            if len(urakadori.normalize(quote)) < MIN_QUOTE:
                continue
            if lists is None:
                lists = _lists(folder)
                if not lists:
                    return []
            hits = resolve(lists, doc, round_no)
            if not hits:
                continue  # 資料の一覧にない資料（Web のページなど）は照らさない
            why = check_quote(folder, hits, quote, page, end)
            if why:
                shown = quote if len(quote) <= 40 else quote[:38] + "…"
                out.append(f"「{shown}」（{doc} p.{page}）：{why}")
        if not out:
            return []
        return ["答えの引用が、示した資料のページに見つかりませんでした（SPEC F4。引用はページの文字のとおりに写す）：\n- "
                + "\n- ".join(out)
                + "\n資料の本文（記録/資料の本文/<案件>/<資料の id>/）のそのページを読み直し、引用とページを直して、答え直してください。"
                "ページをまたぐ引用は、ページごとに分けて示してください。会社の記録や社長の言葉は、資料名とページを付けずに書いてください。"
                "答え直すときは、直した所だけでなく、答えの全体（ほかの問も含めて）をもう一度示してください（社長が最後の答えだけを読めばよいように）。"
                "資料に見つからないことは「資料には書かれていません」と答え、問い合わせ文の案を作ってください。"]
    except Exception:
        return []  # hook を落とさない（落ちると、run.sh が書き込みと Bash を拒んでしまう）
