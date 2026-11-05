"""決める前に示す「義務と返還の条件」の一覧を、制度データから組み立てる（SPEC F2・T2-1、DESIGN 4.2・9章）。

決める（sagasu）で、要件・義務・返還の条件・日程を漏れなく示すための下ごしらえ。Claude が公募要領を読んで並べると、
件数が多い（省力化では50件を超える）ので漏れやすい。そこで、制度データにある次の所から、出典つきで1件ずつ並べる。
- 申請と審査：してはいけないこと、審査の段階（口頭審査を本人が受けることなど）、支援者の欄の決まり
- 採択後の手続き：手続きの段階ごとの期限（決め方の文）と、注意（申請の段階の注意は申請のところに置く）
- 採択後に出す書類の決まり（相見積もり、保険・保守の契約、賃金引き上げの表明など。申請より後の手続きで使う書類の中身）
- 数値の要件：基準（取り組むこと）と、満たせないとき（返還など）。補助額の特例の条件
- 数値でない要件の、満たせないとき
制度データにない決まり（省力化では、証拠の書類を残す期間など）は、Claude が公募要領の「補助事業者の義務」
「補助金の返還」などの章を読んで足す（一覧の終わりに、その案内を出す。案内には個々の決まりの名前を書かない。
読まずに名前だけを写して済ませないため）。

種類の目安（文の言葉で分ける。最後は Claude が読んで直してよい）：返還（返還・納付）、取消など（取消・不採択・無効・対象外・
申請できない）、義務（ほか）。読み取れない値は「資料には書かれていません」として出す（推測で埋めない）。

何も書かない。標準のライブラリと lib/ だけで動く（/usr/bin/python3 3.9）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from lib import gaiyou

RETURN = "返還"
CANCEL = "取消など"
DUTY = "義務"
NOTE = "注意"

_RETURN_WORDS = re.compile(r"返還|納付|返納")
_CANCEL_WORDS = re.compile(r"取消|取り消|不採択|無効|対象外|申請できない|応募できない|減点|公表")
_NOTE_WORDS = re.compile(r"ことがある|場合がある|かかる|課税|後払い|精算払")


@dataclass
class Duty:
    section: str  # 申請と審査／採択後の手続き／採択後に出す書類／数値の要件／数値でない要件
    kind: str
    name: str
    text: str
    sources: List[str]
    unreadable: bool = False


def kind_of(text: str, default: str = DUTY) -> str:
    if _RETURN_WORDS.search(text):
        return RETURN
    if _CANCEL_WORDS.search(text):
        return CANCEL
    if default == DUTY and _NOTE_WORDS.search(text):
        return NOTE
    return default


def _add(out: List[Duty], ctx: "gaiyou.Context", section: str, name: str, node: Any,
         default: str = DUTY, fmt=None, prefix: str = "") -> None:
    if not gaiyou.is_sv(node):
        return
    text = ctx.text(node, fmt)
    unreadable = node.get("状態") == gaiyou.UNREADABLE
    if unreadable:
        text = "資料には書かれていません" + (f"（{node.get('理由')}）" if node.get("理由") else "")
    body = prefix + text
    out.append(Duty(section, NOTE if unreadable else kind_of(body, default), name, body,
                    ctx.sources(node), unreadable))


def collect(seido: Dict) -> List[Duty]:
    """制度データから、義務・返還・取消などの一覧を組み立てる。"""
    ctx = gaiyou.Context(seido, {})
    out: List[Duty] = []

    # 申請と審査
    for item in seido.get("してはいけないこと") or []:
        if isinstance(item, dict):
            _add(out, ctx, "申請と審査", str(item.get("名前")), item.get("内容"), default=CANCEL)
    for item in seido.get("審査の段階") or []:
        if isinstance(item, dict):
            _add(out, ctx, "申請と審査", f"審査の段階「{item.get('名前')}」", item.get("条件"))
    helper = seido.get("支援者の欄")
    if isinstance(helper, dict):
        _add(out, ctx, "申請と審査", "支援者の欄", helper.get("案内の文"))
    first_stage = ctx.stages[0] if ctx.stages else None
    if first_stage:
        for note in first_stage.get("注意") or []:
            _add(out, ctx, "申請と審査", f"{first_stage.get('名前')}の注意", note)

    # 採択後の手続き（順番の順）
    for stage in ctx.stages[1:]:
        name = str(stage.get("名前"))
        cond = stage.get("条件付き")
        limit = stage.get("期限")
        _add(out, ctx, "採択後の手続き", f"{name}（いつ・どんなとき）", stage.get("始まる条件"))
        if gaiyou.is_sv(limit):
            prefix = f"（必要なときだけ：{ctx.text(cond)}）" if gaiyou.is_sv(cond) else ""
            _add(out, ctx, "採択後の手続き", f"{name}の期限", limit, fmt=ctx.limit_text, prefix=prefix)
        for note in stage.get("注意") or []:
            _add(out, ctx, "採択後の手続き", f"{name}の注意", note)

    # 採択後に出す書類の決まり
    first_id = first_stage.get("id") if first_stage else None
    for doc in seido.get("書類") or []:
        if not isinstance(doc, dict):
            continue
        steps = doc.get("手続き") or []
        if not steps or (first_id and first_id in steps):
            continue
        cond = doc.get("条件")
        prefix = f"（{ctx.text(cond)} のとき）" if gaiyou.is_sv(cond) and cond.get("状態") != gaiyou.UNREADABLE else ""
        _add(out, ctx, "採択後に出す書類", f"書類「{doc.get('名前')}」", doc.get("内容"), prefix=prefix)

    # 数値の要件・補助額の特例・数値でない要件
    for req in seido.get("数値の要件") or []:
        if not isinstance(req, dict):
            continue
        name = str(req.get("名前"))
        _add(out, ctx, "数値の要件", f"{name}（基準）", req.get("基準"))
        if "満たせないとき" in req:
            _add(out, ctx, "数値の要件", f"{name}（満たせないとき）", req.get("満たせないとき"), default=RETURN)
    seen_special = set()
    for row in seido.get("補助額") or []:
        for special in (row.get("特例") or []) if isinstance(row, dict) else []:
            if not isinstance(special, dict) or special.get("名前") in seen_special:
                continue
            seen_special.add(special.get("名前"))
            _add(out, ctx, "数値の要件", f"補助額の特例「{special.get('名前')}」の条件", special.get("条件"))
    for req in seido.get("数値でない要件") or []:
        if isinstance(req, dict) and "満たせないとき" in req:
            _add(out, ctx, "数値でない要件", f"{req.get('名前')}（満たせないとき）", req.get("満たせないとき"),
                 default=CANCEL)
    return out


SECTIONS = ("申請と審査", "採択後の手続き", "採択後に出す書類", "数値の要件", "数値でない要件")
MORE = ("この一覧は制度データにある分だけです。制度データにない義務と返還の条件もあるので、公募要領の「補助事業者の義務」"
        "「補助金の返還」「交付規程」に当たる章を全部読み、この一覧にないものを、出典のページを付けて足してください。")


def report(seido: Dict, duties: Optional[List[Duty]] = None) -> str:
    duties = collect(seido) if duties is None else duties
    seido_info = seido.get("制度") or {}
    title = f"{seido_info.get('名前') or ''}（{seido_info.get('公募回') or ''}の資料に基づく）"
    counts = {k: sum(1 for d in duties if d.kind == k) for k in (DUTY, RETURN, CANCEL, NOTE)}
    lines = [f"# 義務と返還の条件の一覧：{title}", "",
             f"件数：義務 {counts[DUTY]}、返還 {counts[RETURN]}、取消など {counts[CANCEL]}、注意 {counts[NOTE]}"
             "（種類は文の言葉で分けた目安）", ""]
    for section in SECTIONS:
        items = [d for d in duties if d.section == section]
        if not items:
            continue
        lines += [f"## {section}（{len(items)}件）", "", "| 種類 | 項目 | 中身 | 出典 |", "|---|---|---|---|"]
        for d in items:
            body = d.text.replace("\n", " ").replace("|", "／")
            src = "、".join(d.sources) if d.sources else "（出典なし）"
            lines.append(f"| {d.kind} | {d.name} | {body} | {src} |")
        lines.append("")
    lines.append(MORE)
    return "\n".join(lines)
