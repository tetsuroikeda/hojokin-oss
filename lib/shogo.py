"""計画書の本文の数字・固有名詞・日付を、根拠対照表と財務モデルの数字の控えに照らす（SPEC F9「事実の照合」T9-1、
F8「財務モデル」T8-11、DESIGN 6章・8.1。TASKS B16）。

1. 根拠のない記述（T9-1）：本文の数字（単位つき）と日付を、決まった書き方で探して見つける（DESIGN 6章「数字と日付は、
   『1,500万円』『2027年3月』のような決まった書き方を探して見つける」）。固有名詞は、会社の記録と書類の台帳から
   作った一覧と、会社の形（株式会社〇〇など）で見つける。見つけたものが、根拠対照表のどの行の「記述」にも
   含まれなければ、根拠のない記述とする（書いた場所は問わない）。
2. 食い違い（T9-1）：根拠対照表の行の「記述」が、その行の「書いた場所」の本文にない（本文を直した後に、表を
   直していない）。書いた場所が本文の項目でなければ、本文の全体で探す。
3. 本文への出典の書き込み（T9-1）：「出典」「p.12」「12ページ」「回答表」「社長の答え」「事実-0001」など、出典を書く
   ときの形が本文にある（計画書の本文には出典を書かない。SPEC F8）。
4. 財務モデルとの食い違い（T8-11）：根拠対照表の出典が財務モデルを指す行（「財務モデル P-07」「財務モデル 合算 売上
   5年目」「財務モデル.xlsx（労働生産性_5年目）」など）の数字を、数字の控え（記録/財務モデルの数字.json）の値と
   比べる。表に書いた桁で丸めた差を超えれば食い違い。参照の先が控えにないときも食い違いに数える。
5. 様式（その3 などの Excel の入力の欄）と入力シート（値の出どころが財務モデル・その3 の欄）の数のセル（T8-11）：
   そのセルを書いた場所にした根拠対照表の行があれば、行の記述の数とセルの数を比べ（違えば食い違い）、行の出典が
   財務モデルなら 4 で控えと比べる。行がなければ、セルの数が控えの数（セルに書いた桁で丸めたもの）のどれかで
   なければ、財務モデルとの食い違いとする（控えがないときは見ない）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

NO_SOURCE = "根拠なし"
MISMATCH = "食い違い"
CITATION = "本文の出典"
MODEL_MISMATCH = "財務モデルとの食い違い"
KINDS = (NO_SOURCE, MISMATCH, CITATION, MODEL_MISMATCH)

UNITS = ("千円", "万円", "億円", "円", "%", "ポイント", "人", "名", "時間", "分", "日", "か月", "カ月", "ヶ月", "週",
         "年間", "年", "台", "個", "パック", "件", "品目", "店舗", "社", "か所", "箇所", "回", "倍", "㎡", "食",
         "歳", "kg", "円/時", "時")
# 「1日に」「1台あたり」「1パック」のような、単位の1つ分を言うだけの書き方（事実の数ではない）
PER_ONE = ("日", "台", "個", "パック", "件", "食", "時間", "か月", "カ月", "ヶ月", "年", "週", "回", "品目")
_UNIT_RE = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_NUM = r"[0-9][0-9,]*(?:\.[0-9]+)?"
_NEGATIVE_MARK = re.compile(r"(?:^|[^0-9A-Za-z])[-\u2212\u2012\u2013\u25b2\u25b3]\s*$")
_DATE = re.compile(r"(?:令和|平成)[0-9]{1,2}年(?:[0-9]{1,2}月(?:[0-9]{1,2}日)?)?|[0-9]{4}年(?:[0-9]{1,2}月(?:[0-9]{1,2}日)?)?"
                   r"(?:度|期)?|[0-9]{4}[/-][0-9]{1,2}(?:[/-][0-9]{1,2})?")
_AMOUNT = re.compile(rf"(?:約|およそ)?{_NUM}\s*(?:{_UNIT_RE})")
_NAME_BODY = r"[^\s、。，．（）「」『』・/とのはがをにでやへ]{1,20}"
_COMPANY = re.compile(rf"(?:株式会社|有限会社|合同会社|一般社団法人|社会福祉法人|医療法人){_NAME_BODY}"
                      rf"|{_NAME_BODY}(?:株式会社|有限会社|合同会社)")
_CITATION = re.compile(r"出典|[pP][.．]\s*[0-9]|[0-9]+\s*ページ|[0-9]+\s*頁|回答表|社長の答え|事実-[0-9]{3,}|"
                       r"財務モデル\s*[PJS]-[0-9]|財務モデル\.xlsx|要領[0-9]|手引[0-9]|（[^）]{0,30}\.pdf[^）]{0,20}）")


def norm(text: Any) -> str:
    """比べるための形（NFKC、空白とカンマを除く、全角の％も % に）。"""
    t = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"[\s,、]", "", t)


def _strip_about(token: str) -> str:
    return re.sub(r"^(?:約|およそ)", "", token)


def facts(text: str) -> List[Tuple[str, str]]:
    """本文の数字（単位つき）・日付・会社の名前の（種類, 見つけた文字）。重なる所は、日付を先に取る。"""
    t = unicodedata.normalize("NFKC", text or "")
    taken: List[Tuple[int, int]] = []
    out: List[Tuple[int, str, str]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for kind, pattern in (("日付", _DATE), ("数字", _AMOUNT), ("固有名詞", _COMPANY)):
        for m in pattern.finditer(t):
            a, b = m.span()
            if not free(a, b):
                continue
            taken.append((a, b))
            token = m.group(0)
            if kind == "数字" and re.fullmatch(r"1\s*(?:" + "|".join(map(re.escape, PER_ONE)) + ")", token):
                continue  # 「1日に」「1パックあたり」のような書き方
            out.append((a, kind, token))
    return [(kind, tok) for _a, kind, tok in sorted(out)]


def citations(text: str) -> List[str]:
    t = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in _CITATION.finditer(t):
        a, b = max(0, m.start() - 12), min(len(t), m.end() + 12)
        out.append(t[a:b].replace("\n", " "))
    return out


def covered(token: str, descriptions: Sequence[str]) -> bool:
    """見つけた文字が、根拠対照表のどれかの「記述」に含まれるか（「約」の有無は問わない）。"""
    n = norm(_strip_about(token))
    if not n:
        return True
    return any(n in d for d in descriptions)


# ---------------------------------------------------------------- 財務モデルの数字

YEAR_RE = re.compile(r"(基準年度|[0-9]+年目)")
_REF_IN_PAREN = re.compile(r"財務モデル(?:\.xlsx)?\s*[（(]([^）)]+)[）)]")
_REF_AFTER = re.compile(r"財務モデル(?:\.xlsx)?\s+(.+)$")
BUSINESS_KEYS = ("売上", "原材料費", "給与支給総額", "その他の人件費", "減価償却費", "その他の経費", "人件費", "営業利益")
SHORYOKU_KEYS = ("省力化指数", "投資回収期間", "削減工数", "増加した付加価値額", "削減される業務に要していた時間",
                 "導入後に発生する業務に要する時間")


def model_ref(source: str) -> Optional[str]:
    """出典が財務モデルを指すなら、その参照の文字（「P-07」「合算 売上 5年目」「労働生産性_5年目」など）。"""
    s = unicodedata.normalize("NFKC", source or "").strip()
    if not s.startswith("財務モデル"):
        return None  # 出典の頭が「財務モデル」の行だけを、財務モデルを指す行とみる
    m = _REF_IN_PAREN.search(s) or _REF_AFTER.search(s)
    return m.group(1).strip() if m else ""


def _year_index(text: str) -> Optional[int]:
    if text == "基準年度":
        return 0
    m = re.fullmatch(r"([0-9]+)年目", text)
    return int(m.group(1)) if m else None


def model_value(numbers: Dict[str, Any], ref: str) -> Optional[Tuple[float, str]]:
    """参照の値と単位（"円"・"%"・""）。見つからなければ None。率の前提（単位 %）は百分率にして返す。"""
    body = numbers.get("中身") or {}
    assumptions = numbers.get("前提") or []
    r = unicodedata.normalize("NFKC", ref).strip()
    by_no = {a.get("番号"): a for a in assumptions}
    by_name = {a.get("名前"): a for a in assumptions}
    hit = by_no.get(r.split()[0]) if r else None
    if hit is None:
        hit = by_name.get(r) or by_name.get(r.replace(" ", "_"))
    if hit is not None:
        unit = hit.get("単位") or ""
        value = float(hit.get("値"))
        return (value * 100, "%") if unit == "%" else (value, "円" if unit.startswith("円") else "")
    sh = body.get("省力化") or {}
    if r in SHORYOKU_KEYS and sh.get(r) is not None:
        return float(sh[r]), ("円" if r == "増加した付加価値額" else "")
    if r == "計画の年数" and body.get("計画の年数") is not None:
        return float(body["計画の年数"]), ""
    parts = [p for p in re.split(r"[\s_]+", r) if p]
    if not parts:
        return None
    year = _year_index(parts[-1])
    if year is None:
        return None
    names = parts[:-1]
    indicators = body.get("指標") or {}
    people = body.get("人数") or {}
    totals = body.get("合算") or {}
    by_business = body.get("事業ごと") or {}

    def pick(series):
        if not isinstance(series, list) or year >= len(series) or series[year] is None:
            return None
        v = series[year]
        return float(v) if isinstance(v, (int, float)) else None

    if len(names) == 1:
        key = names[0]
        aliases = {"労働生産性の伸び": "労働生産性の伸び", "1人当たり給与支給総額": "1人当たり給与",
                   "1人当たり給与支給総額の伸び": "1人当たり給与の伸び", "付加価値額の伸び": "付加価値額の伸び"}
        key = aliases.get(key, key)
        if key in indicators:
            v = pick(indicators[key])
            return None if v is None else (v, "%" if key.endswith("の伸び") else ("円" if key == "付加価値額" else ""))
        if key in totals:
            v = pick(totals[key])
            return None if v is None else (v, "円")
        if key in people:
            v = pick(people[key])
            return None if v is None else (v, "")
        return None
    if len(names) == 2:
        group, key = names
        series = None
        if group == "合算":
            series = totals.get(key)
        elif group == "人数":
            series = people.get(key)
        elif group == "指標":
            series = indicators.get(key)
        elif group == "別紙4":
            # 様式（別紙4）に写す、円に丸めた値（lib/zaimu.py の「様式（別紙4）に写す数字」。11/6 のリハーサルの後）
            series = ((body.get("別紙4") or {}).get("年ごと") or {}).get(key)
            people_like = key.endswith("数")
            v = pick(series)
            if v is None:
                return None
            return v, ("" if people_like else ("%" if key.endswith("の伸び") else "円"))
        elif group in by_business:
            series = by_business[group].get(key)
        v = pick(series)
        if v is None:
            return None
        return v, ("" if group == "人数" else ("%" if key.endswith("の伸び") else "円"))
    return None


_SCALE = {"千円": 1000.0, "万円": 10000.0, "億円": 100000000.0, "円": 1.0}


def shown_number(description: str) -> Optional[Tuple[float, float, str]]:
    """記述の中の数（値、表に書いた桁の半分の幅、単位の種類 "円"・"%"・""）。"""
    t = unicodedata.normalize("NFKC", description or "")
    m = re.search(rf"({_NUM})\s*({_UNIT_RE})?", t)
    if not m:
        return None
    raw, unit = m.group(1).replace(",", ""), m.group(2) or ""
    value = float(raw)
    # 数の前の負の印（-・−・▲・△）は、負の数として読む（11/6 のリハーサルで、営業利益の「-169,440円」を
    # 169,440円と読み、財務モデルの -169,440円と食い違うと数えたため）
    if _NEGATIVE_MARK.search(t[:m.start()]):
        value = -value
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    half = 0.5 * (10 ** -decimals)
    if unit in _SCALE:
        scale = _SCALE[unit]
        return value * scale, half * scale, "円"
    if unit in ("%", "ポイント"):
        return value, half, "%"
    return value, half, ""


def model_findings(rows: Sequence[Dict[str, str]], numbers: Optional[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """（行の番号, 記述, 理由）の並び。"""
    out = []
    for n, row in enumerate(rows, 1):
        ref = model_ref(row.get("出典", ""))
        if ref is None:
            continue
        desc = row.get("記述", "")
        if numbers is None:
            out.append((n, desc, "財務モデルの数字の控え（記録/財務モデルの数字.json）がありません"))
            continue
        got = model_value(numbers, ref)
        if got is None:
            out.append((n, desc, f"財務モデルに「{ref}」が見つかりません（P-07 のような前提の番号か、"
                                 "「合算 売上 5年目」の形で書く）"))
            continue
        shown = shown_number(desc)
        if shown is None:
            out.append((n, desc, "記述に数がありません"))
            continue
        value, half, unit = shown
        model, model_unit = got
        if abs(model - value) > half + 1e-9 * max(1.0, abs(model)):
            out.append((n, desc, f"財務モデルの「{ref}」は {_fmt(model, model_unit)} です"))
    return out


def _fmt(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "円":
        return f"{value:,.0f}円"
    return f"{value:,.4g}"


# ---------------------------------------------------------------- 様式と入力シートの数のセル（B16 の直し。T8-11）


def _flat_numbers(node: Any, out: List[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, list):
        for x in node:
            _flat_numbers(x, out)
    elif isinstance(node, dict):
        for x in node.values():
            _flat_numbers(x, out)


def model_number_values(numbers: Dict[str, Any]) -> List[float]:
    """数字の控えにある数（前提の値と、率の前提の百分率、計画の年ごとの数、指標、人数、省力化の数と作業の分）。"""
    out: List[float] = []
    for a in numbers.get("前提") or []:
        if isinstance(a, dict) and isinstance(a.get("値"), (int, float)) and not isinstance(a.get("値"), bool):
            out.append(float(a["値"]))
            if a.get("単位") == "%":
                out.append(float(a["値"]) * 100)
    body = numbers.get("中身") or {}
    for key in ("合算", "事業ごと", "指標", "人数", "省力化", "まとめ", "計画の年数", "別紙4"):
        _flat_numbers(body.get(key), out)
    _flat_numbers(numbers.get("省力化の作業"), out)
    return out


def _half(text: str) -> float:
    raw = text.replace(",", "")
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    return 0.5 * (10 ** -decimals)


def cell_in_model(value: str, values: Sequence[float]) -> bool:
    """セルの数が、数字の控えのどれかの数を、セルに書いた桁で丸めたものか。"""
    v, half = float(value.replace(",", "")), _half(value)
    return any(abs(v - m) <= half + 1e-9 * max(1.0, abs(m)) for m in values)


def cell_findings(cells: Dict[str, str], rows: Sequence[Dict[str, str]], numbers: Optional[Dict[str, Any]]
                  ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """（食い違い, 財務モデルとの食い違い）。セルに根拠対照表の行があれば、行の記述の数とセルの数を比べる。
    行がなければ、セルの数が財務モデルの数字の控えにあるかを見る（控えがなければ見ない）。"""
    mismatch, model = [], []
    values = model_number_values(numbers) if numbers is not None else None
    for place, value in cells.items():
        mine = [(n, r) for n, r in enumerate(rows, 1) if r.get("書いた場所") == place]
        v, half = float(value.replace(",", "")), _half(value)
        if mine:
            for n, r in mine:
                shown = shown_number(r.get("記述", ""))
                if shown is None or abs(shown[0] - v) > shown[1] + half + 1e-9 * max(1.0, abs(v)):
                    mismatch.append({"場所": f"根拠対照表 {n}行目", "文字": r.get("記述", ""),
                                     "理由": f"「{place}」の値は {value} です（様式や入力シートを直したら、根拠対照表も直す）"})
            continue
        if values is not None and not cell_in_model(value, values):
            model.append({"場所": place, "文字": value,
                          "理由": "財務モデルの数字の控えにも、根拠対照表にもない数です（数字は財務モデルの道具の出力から取る。"
                                  "ほかの出典の数なら、書いた場所をこのセルにして根拠対照表に行を作る）"})
    return mismatch, model


# ---------------------------------------------------------------- まとめて照らす


def check(texts: Dict[str, str], rows: Sequence[Dict[str, str]], numbers: Optional[Dict[str, Any]],
          nouns: Iterable[str] = (), cells: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict[str, str]]]:
    """texts は（書いた場所 → 本文）、cells は（書いた場所 → 様式・入力シートの数）。種類ごとの指摘
    （{"場所", "文字", "理由"}）を返す。"""
    cells = cells or {}
    descriptions = [norm(r.get("記述", "")) for r in rows]
    found: Dict[str, List[Dict[str, str]]] = {k: [] for k in KINDS}
    noun_list = sorted({n for n in nouns if n and len(n) >= 2}, key=len, reverse=True)
    for where, text in texts.items():
        seen = set()
        for kind, token in facts(text):
            key = norm(_strip_about(token))
            if key in seen:
                continue
            seen.add(key)
            if not covered(token, descriptions):
                found[NO_SOURCE].append({"場所": where, "文字": token, "理由": f"{kind}の出典が根拠対照表にありません"})
        t = norm(text)
        for noun in noun_list:
            if norm(noun) in t and norm(noun) not in seen and not covered(noun, descriptions):
                seen.add(norm(noun))
                found[NO_SOURCE].append({"場所": where, "文字": noun, "理由": "固有名詞の出典が根拠対照表にありません"})
        for snippet in citations(text):
            found[CITATION].append({"場所": where, "文字": snippet, "理由": "計画書の本文に出典を書いています（出典は根拠対照表に書く）"})
    all_text = norm("\n".join(texts.values()))
    by_place = {k: norm(v) for k, v in texts.items()}
    for n, row in enumerate(rows, 1):
        desc = norm(_strip_about(row.get("記述", "")))
        if not desc:
            continue
        place = row.get("書いた場所", "")
        if place in cells:
            continue  # 様式・入力シートの数のセルの行は、数で比べる（cell_findings）
        target = by_place.get(place, all_text)
        if desc not in target and norm(row.get("記述", "")) not in target:
            where = place if place in by_place else "本文の全体"
            found[MISMATCH].append({"場所": f"根拠対照表 {n}行目", "文字": row.get("記述", ""),
                                    "理由": f"「{where}」の本文にこの記述がありません（本文を直したら、根拠対照表も直す）"})
    for n, desc, reason in model_findings(rows, numbers):
        found[MODEL_MISMATCH].append({"場所": f"根拠対照表 {n}行目", "文字": desc, "理由": reason})
    cell_mismatch, cell_model = cell_findings(cells, rows, numbers)
    found[MISMATCH] += cell_mismatch
    found[MODEL_MISMATCH] += cell_model
    return found
