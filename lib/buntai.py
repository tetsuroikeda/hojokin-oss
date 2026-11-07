"""文体の数え上げ（SPEC F9「文体」T9-3、DESIGN 6章・8.2。TASKS B17）。

docs/style-criteria.md の A（数えられる基準）と B（避ける言い回し）、会社の記録の「避けたい言い方」を、計画書の本文で数える。
文体の基準の表は、そのたびにファイルから読む（作者が A14 で表を直しても、そのまま数える）。

- 合否に使うもの（SPEC F9 の完成の条件）：
  - A の「要修正」：`**`・`##` などの記号の残り、です・ます調とである調の混在。
  - 会社の「避けたい言い方」に当たる言い回し（社長が決めたこと）。
- 合否に使わないもの（数えて社長に示すだけ）：A の「注意」「弱い注意」（100字を超える文を含む）と、B の避ける言い回し
  （11/7 の作者の決定。言葉の一覧で縛ると、書き手が文脈に合う言葉まで避けて回りくどくなるため）。B は「避ける言い回し」として
  別に数えて示し、書き手は自然に言い換えられる所だけ直す。社長が残すと決めたもの（会社の記録の「好む言い方」に「」で書いた
  言い回し）は数えない。A と B が重なる項目（「等」「など」「さまざまな」、定着していないカタカナ語）は A に従い、注意として数える。
- B の表の言い回しの読み方は、testdata/計画書/check_plans.py と同じ（「〜」は間の何文字か。「〇〇」・かぎかっこの例・
  かっこの中の条件の文は数えない。2字以下の短い語は数えない）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

MUST_FIX = "要修正"
CAUTION = "注意"
WEAK = "弱い注意"
B_HIT = "避ける言い回し"
COMPANY_HIT = "避けたい言い方"
LONG_MUST, LONG_CAUTION = 100, 60
TOO_MANY_COMMAS = 4
KANJI_RUN = 7
KANJI_SHARE = 0.4
B_SKIP = ("〇〇", "「", "（", "毎回")
# A と B が重なる言い回し（A に従い、注意として数える）
A_OVERLAP_WORDS = ("さまざまな", "等", "など")
A_OVERLAP_KINDS = ("カタカナ語",)
_MARKS = re.compile(r"\*\*|##|__")
_DESUMASU = re.compile(r"(?:です|ます|でした|ました|ません|でしょう|ください|ましょう)[。．]$")
# である調（常体）：「。」で終わる文のうち、です・ます調でなく、「る・た・だ・い・ない・ぬ」で終わるもの
_DEARU = re.compile(r"(?:である|であった|だ|だった|る|た|い|ぬ)[。．]$")
_KANJI = re.compile(r"[一-鿿々〆ヶ]")


class Criteria:
    """文体の基準の B（避ける言い回し）と、A と重なる言い回し。"""

    def __init__(self, b_rules: List[Tuple[str, str, str, str]]) -> None:
        self.b_rules = b_rules  # (区分, 避ける表現, 言い換えの例, 正規表現)


def load(path: Path) -> Criteria:
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"^## B\..*?(?=^## |\Z)", text, flags=re.M | re.S)
    rules = []
    for line in (m.group(0).splitlines() if m else []):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("区分", "---") or set(cells[0]) <= {"-"}:
            continue
        for part in re.split(r"[、，]", cells[1]):
            part = re.sub(r"（.*?）", "", part).strip()
            chunks = [c for c in part.split("〜") if c]
            if not chunks or any(s in part for s in B_SKIP) or max(len(c) for c in chunks) <= 2:
                continue
            rules.append((cells[0], part, cells[2], "[^。\n]*?".join(re.escape(c) for c in chunks)))
    return Criteria(rules)


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=。)|\n", text or "") if s.strip()]


def _quoted(text: str) -> List[str]:
    found = re.findall(r"「([^」]+)」", text or "")
    return [f for f in found if f.strip()]


def company_phrases(rules: Iterable[dict]) -> Tuple[List[str], List[str]]:
    """会社の記録の書き方の決まりから、（避けたい言い方, 社長が残すと決めた言い回し）。言い回しは「」の中。

    避けたい言い方は、区分が「避けたい言い方」の決まりの内容の「」の中（なければ内容の全体）。
    残すと決めた言い回しは、区分が「好む言い方」の決まりの内容の「」の中。
    """
    avoid, keep = [], []
    for r in rules:
        kind, content = r.get("区分"), str(r.get("内容") or "")
        if kind == "避けたい言い方":
            avoid += _quoted(content) or ([content.strip()] if content.strip() else [])
        elif kind == "好む言い方":
            keep += _quoted(content)
    return avoid, keep


def count(texts: Dict[str, str], criteria: Criteria, avoid: Sequence[str] = (), keep: Sequence[str] = ()
          ) -> Dict[str, List[Dict[str, str]]]:
    """texts は（書いた場所 → 本文）。種類ごとの該当（{"場所", "文字", "基準", "直し方"}）を返す。"""
    out: Dict[str, List[Dict[str, str]]] = {MUST_FIX: [], CAUTION: [], WEAK: [], B_HIT: [], COMPANY_HIT: []}
    keep_n = {unicodedata.normalize("NFKC", k) for k in keep}

    def add(kind: str, where: str, snippet: str, rule: str, fix: str = "") -> None:
        out[kind].append({"場所": where, "文字": snippet[:60], "基準": rule, "直し方": fix})

    all_sentences = [(w, s) for w, t in texts.items() for s in sentences(t)]
    desumasu = [(w, s) for w, s in all_sentences if _DESUMASU.search(s)]
    dearu = [(w, s) for w, s in all_sentences if not _DESUMASU.search(s) and _DEARU.search(s)]
    if dearu and desumasu:
        minority = dearu if len(dearu) <= len(desumasu) else desumasu
        for w, s in minority:
            add(MUST_FIX, w, s, "です・ます調とである調の混在", "文末をです・ます調にそろえる")
    for where, text in texts.items():
        for m in _MARKS.finditer(text):
            add(MUST_FIX, where, text[max(0, m.start() - 10):m.end() + 10], "記号の残り（** や ##）", "記号を消す")
        sents = sentences(text)
        for s in sents:
            n = len(s)
            if n > LONG_MUST:  # 11/7 の作者の決定で、要修正から注意に下げた
                add(CAUTION, where, s, f"一文が{LONG_MUST}字を超える（{n}字）", "読みにくければ分ける")
            elif n > LONG_CAUTION:
                add(CAUTION, where, s, f"一文が{LONG_CAUTION}字を超える（{n}字）")
            if s.count("、") >= TOO_MANY_COMMAS:
                add(CAUTION, where, s, f"一文の読点が{s.count('、')}個")
            run = re.search(rf"{_KANJI.pattern}{{{KANJI_RUN},}}", s)
            if run:
                add(CAUTION, where, run.group(0), f"漢字が{len(run.group(0))}字続く")
        # 文末の繰り返し（最後の4字が同じ文が3つ続く。「ます」だけでは数えない）
        endings = [re.sub(r"[。．]$", "", s)[-4:] for s in sents]
        for i in range(len(endings) - 2):
            if len(endings[i]) >= 4 and endings[i] == endings[i + 1] == endings[i + 2]:
                add(CAUTION, where, sents[i + 2], f"文末「{endings[i]}」が3文続く")
        for para in [p for p in text.split("\n") if p.strip()]:
            for word in A_OVERLAP_WORDS:
                if para.count(word) >= 2:
                    add(CAUTION, where, para, f"1段落に「{word}」が{para.count(word)}回")
        chars = [c for c in text if not c.isspace()]
        if len(chars) >= 200:
            share = sum(1 for c in chars if _KANJI.match(c)) / len(chars)
            if share > KANJI_SHARE:
                add(WEAK, where, "", f"漢字の割合が{share:.0%}")
        norm = unicodedata.normalize("NFKC", text)
        for kind, phrase, fix, pattern in criteria.b_rules:
            for m in re.finditer(pattern, norm):
                hit = m.group(0)
                if any(k in hit for k in keep_n):
                    continue
                if kind in A_OVERLAP_KINDS or phrase in A_OVERLAP_WORDS:
                    add(CAUTION, where, hit, f"文体の基準 B「{phrase}」（A と重なるので注意）", fix)
                else:
                    add(B_HIT, where, hit, f"文体の基準 B「{phrase}」（{kind}）", fix)
        for phrase in avoid:
            p = unicodedata.normalize("NFKC", phrase)
            if p and p in norm and p not in keep_n:
                add(COMPANY_HIT, where, p, "会社の記録の避けたい言い方")
    return out


def failing(result: Dict[str, List[Dict[str, str]]]) -> int:
    """合否に使う件数（A の要修正と、会社の避けたい言い方）。B の避ける言い回しは注意として示すだけ（11/7 の作者の決定）。"""
    return len(result[MUST_FIX]) + len(result[COMPANY_HIT])
