"""claude.ai に上げる今の状態（Artifact）の画面と、社長の同意・上げた先の記録（SPEC F6、共通の要件「書類の版の管理」の②、
DESIGN 4.4・4.6・5章の文案。作者が案 (c) に決めた。2026-11-06）。

- 正本は、パソコンの中の 今の状態.html（lib/status_view.py）のまま。ここで作るのは、社長が頼んだときだけ claude.ai の
  Artifact に上げる「写し」で、上げた時点のまま古くなる（hook も道具も Artifact を呼べず、上げられるのは会話の中の Claude だけ）。
- 入れるのは、②の期限の一覧と同じ範囲（SPEC 共通の要件：書類の中身・金額・決算の数字・会社の記録・版の履歴を入れない）。
  案件名、工程表、期限と作業（締切・あと何日・すること・見込みか確定か・だれがするか・依頼の状態）、外部への依頼の書類の種類と
  状態、今の段階の必須の書類の揃い具合、不備の件数、様式の項目ごとの進み具合、長い期限。
- 入れないもの：会社名（会社のフォルダの名前）、金額、相手先と依頼先、書類のファイルの名前と場所、メモ・出典の文・不備の中身と
  直し方、義務の文（会社の数字が入ることがある）、会社の記録、版の履歴。依頼の作業の「すること」と「だれがするか」には依頼先が
  入るので、書類の種類から作り直し、括弧の中を落とす。
- 作った後に、会社のフォルダの名前・会社の記録の会社名・書類の台帳の相手先・「円」が入っていないかを照らし、入っていれば
  書かない（結果で確かめる。DESIGN 5章の型）。
- 画面は `.hojokin/一時/` に置く（Claude は Write・Edit で書けない場所。版の履歴に入れない）。中身のハッシュも同じ所に控え、
  PreToolUse の hook（hooks/artifact_hooks.py）は、このファイルが控えと同じ中身で、社長の同意があるときだけ、上げることを通す。
- 社長の同意と上げた先の URL は `.hojokin/設定.json` の「claude.ai の今の状態」に残す（版の履歴に入る）。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lib import company, dates, deadlines, place_text, places

PAGE_REL = f"{company.MARKER_DIR}/{company.TEMP_DIR}/今の状態_claudeai.html"
STAMP_REL = f"{company.MARKER_DIR}/{company.TEMP_DIR}/今の状態_claudeai.json"
SETTINGS_KEY = "claude.ai の今の状態"
AGREED = "同意した日"
STOPPED = "やめた日"
URL_KEY = "URL"
PLACE_KEY = "置き先"
PLACE_TEXT = "claude.ai の Artifact（社長の claude.ai のアカウント。既定では本人だけが見られる）"
URL_PREFIXES = ("https://claude.ai/artifact/", "https://claude.ai/code/artifact/")
URL_PATTERN = re.compile(r"^https://claude\.ai/(code/)?artifact/[A-Za-z0-9_-]{6,64}$")

# Artifact の道具に渡す値（hook はこの値のときだけ通す。ギャラリーのカードに出るので、会社名を入れない決まった文にする）
TITLE = "今の状態"
DESCRIPTION = "補助金の申請の期限と進み具合（会社名・金額・相手先は入れていません）"
ICON = "calendar"

INCLUDED = ["案件名", "工程表（段階の帯・期限の月・今日の線）", "期限と作業（締切・あと何日・すること・見込みか確定か・だれがするか・依頼の状態）",
            "外部への依頼（書類の種類・状態・始める日・締切）", "今の段階の必須の書類の揃い具合", "不備の件数（重さごと）",
            "様式の項目ごとの進み具合（文字数と上限）", "長い期限（効果報告など、年ごと）"]
EXCLUDED = ["会社名", "金額", "相手先と依頼先", "書類のファイルの名前と場所", "メモ・出典の文・不備の中身と直し方",
            "事業期間中と事業後の義務の文", "会社の記録", "版の履歴"]
WHO_CAN_SEE = ("上げた先は Anthropic のサーバー（claude.ai）です。既定では、社長の claude.ai のアカウントだけが見られます。"
               "Team・Enterprise の契約では、組織の管理者が残す期間を決め、記録の道具で中身を取り出せます。"
               "しばらく開かないと消えることがあります。やめるときは「claude.ai の今の状態をやめて」と伝えてください。")
COMPANY_FACT_WORDS = ("会社名", "屋号", "代表者")
_PAREN = re.compile(r"[（(][^）)]*[）)]")


class ArtifactPageError(Exception):
    """写しを作れない・記録を残せないわけ（社長に見せる文）。"""


# ---- 記録 ----


def page_path(folder: Path) -> Path:
    return Path(folder) / PAGE_REL


def record(folder: Path) -> dict:
    """設定の「claude.ai の今の状態」。なければ空。"""
    value = company.load_settings(Path(folder)).get(SETTINGS_KEY)
    return dict(value) if isinstance(value, dict) else {}


def agreed(folder: Path) -> bool:
    rec = record(folder)
    return bool(rec.get(AGREED)) and not rec.get(STOPPED)


def saved_url(folder: Path) -> str:
    url = record(folder).get(URL_KEY)
    return url if isinstance(url, str) else ""


def _write_settings(folder: Path, rec: Optional[dict], action: str) -> None:
    rel = f"{company.MARKER_DIR}/{company.SETTINGS_FILE}"
    problem = place_text.write_problem(folder, rel, action)
    if problem:
        raise ArtifactPageError(problem)
    try:
        settings = company.load_settings(folder)
    except ValueError as error:
        raise ArtifactPageError(f"{error}。{action}") from error
    if rec is None:
        settings.pop(SETTINGS_KEY, None)
    else:
        settings[SETTINGS_KEY] = rec
    _replace(places.actual(folder, rel, partial=True), (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _replace(path: Optional[Path], data: bytes) -> None:
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"~{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(str(tmp), str(path))
    except OSError as error:
        raise ArtifactPageError(f"{path.name} を書けませんでした（{error}）") from error
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def agree(folder: Path) -> str:
    """社長の同意を残す（日付は今日の日付。差し替えに従う）。"""
    folder = Path(folder)
    rec = record(folder)
    rec.pop(STOPPED, None)
    rec[AGREED] = dates.today(folder).isoformat()
    rec[PLACE_KEY] = PLACE_TEXT
    _write_settings(folder, rec, "同意を残していません")
    return rec[AGREED]


def set_url(folder: Path, url: str) -> None:
    """上げた先の URL を残す（次から同じ URL を上げ直すため）。同意がなければ残さない。"""
    folder = Path(folder)
    url = url.strip()
    if not URL_PATTERN.match(url):
        raise ArtifactPageError(f"URL（{url}）は、claude.ai の Artifact の URL（{URL_PREFIXES[0]}…）ではありません。残していません")
    if not agreed(folder):
        raise ArtifactPageError("社長の同意がまだないので、URL を残していません")
    rec = record(folder)
    rec[URL_KEY] = url
    _write_settings(folder, rec, "URL を残していません")


def stop(folder: Path) -> Optional[str]:
    """同意をやめる（hook は、次から上げることを拒む）。上げた先の URL は、消すときのために残す。

    記録がなければ None、あれば上げた先の URL（まだ上げていなければ空）。
    """
    folder = Path(folder)
    rec = record(folder)
    if not rec:
        return None
    rec[STOPPED] = dates.today(folder).isoformat()
    _write_settings(folder, rec, "やめたことを残していません")
    return rec.get(URL_KEY) or ""


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(folder: Path) -> str:
    """控えたハッシュ（なければ空）。"""
    try:
        data = json.loads((Path(folder) / STAMP_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = data.get("ハッシュ") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


# ---- 入れてはいけない言葉 ----


def forbidden_words(folder: Path) -> List[Tuple[str, str]]:
    """（言葉, 種類）の並び。会社のフォルダの名前、会社の記録の会社名など、書類の台帳の相手先。"""
    folder = Path(folder)
    out: List[Tuple[str, str]] = []
    name = places.nfc(folder.name).strip()
    for word in {name, re.sub(r"\s+", "", name)}:
        if len(word) >= 2:
            out.append((word, "会社のフォルダの名前"))
    facts = _json(folder / "記録" / "会社の記録.json")
    for item in (facts.get("項目") or []) if isinstance(facts, dict) else []:
        if isinstance(item, dict) and any(w in str(item.get("名前") or "") for w in COMPANY_FACT_WORDS):
            value = places.nfc(str(item.get("値") or "")).strip()
            if len(value) >= 2:
                out.append((value, "会社の記録の" + str(item.get("名前"))))
    ledger = _json(folder / "記録" / "書類の台帳.json")
    for entry in (ledger.get("原本") or []) if isinstance(ledger, dict) else []:
        if isinstance(entry, dict):
            value = places.nfc(str(entry.get("相手先") or "")).strip()
            if len(value) >= 2:
                out.append((value, "書類の相手先"))
    return out


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def leaks(page: str, words: List[Tuple[str, str]]) -> List[str]:
    """画面の文字（タグの外）に入っている、入れてはいけないものの種類。"""
    text = html.unescape(re.sub(r"<[^>]*>", " ", page))
    found = []
    if "円" in text:
        found.append("金額（「円」）")
    for word, kind in words:
        if word in text and kind not in found:
            found.append(kind)
    return found


# ---- 画面 ----

STYLE = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#57606a;--line:#d0d7de;--head:#f6f8fa;--card:#f6f8fa;--bar:#9ec5fe;
--mark:#cf222e;--late:#ffebe9;--near:#fff8c5;--today:#cf222e;--accent:#0969da}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;
--line:#30363d;--head:#161b22;--card:#161b22;--bar:#1f6feb;--mark:#ff7b72;--late:#3d1d20;--near:#3b3216;--today:#ff7b72;
--accent:#58a6ff}}
:root[data-theme="dark"]{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;--head:#161b22;--card:#161b22;
--bar:#1f6feb;--mark:#ff7b72;--late:#3d1d20;--near:#3b3216;--today:#ff7b72;--accent:#58a6ff}
*{box-sizing:border-box}
body{font-family:-apple-system,"Hiragino Sans","Yu Gothic",sans-serif;margin:0;padding:24px 16px 48px;color:var(--fg);
background:var(--bg);line-height:1.6}
main{max-width:1080px;margin:0 auto}
h1{font-size:1.6em;margin:0 0 4px}
h2{font-size:1.2em;border-bottom:2px solid var(--line);padding-bottom:4px;margin-top:32px}
h3{font-size:1.02em;margin:20px 0 6px}
.note{color:var(--muted);font-size:.9em}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .case{font-weight:bold}
.card .next{margin-top:6px}
.days{font-weight:bold;color:var(--accent)}
.wide{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;margin:6px 0 14px;font-size:.92em}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--head);white-space:nowrap}
tr.overdue td{background:var(--late)}
tr.strong td{background:var(--near)}
.mark{font-weight:bold;color:var(--mark)}
.gantt{width:auto;font-size:.8em}
.gantt th,.gantt td{padding:2px 4px;white-space:nowrap}
.gantt td.g,.gantt th.g{width:16px;min-width:16px;padding:0;text-align:center;white-space:nowrap}
.gantt td.g-bar{background:var(--bar)}
.gantt td.g-mark{background:var(--bar);color:var(--mark);font-weight:bold}
.gantt .g-today{border-left:3px solid var(--today)}
details{margin:4px 0 12px}
summary{cursor:pointer;color:var(--accent)}
"""

STRONG_MARK = "【7日以内】"


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _no_paren(text: str) -> str:
    return _PAREN.sub("", text or "").strip()


def what_text(t: deadlines.Task) -> str:
    """すること。依頼の作業は依頼先が入るので、書類の種類から作り直す。"""
    if t.kind == deadlines.REQUEST:
        return f"{_no_paren(t.doc) or t.doc}を頼む"
    return t.what


def who_text(t: deadlines.Task) -> str:
    """だれがするか。括弧の中（依頼先）を落とす。"""
    return _no_paren(t.who) or "—"


def _task_table(tasks: List[deadlines.Task], today, overdue: bool = False) -> List[str]:
    if not tasks:
        return ['<p class="note">ありません</p>']
    out = ['<div class="wide"><table>', "<tr><th>締切</th><th>あと何日</th><th>案件</th><th>すること</th>"
           "<th>見込みか確定か</th><th>だれがするか</th><th>依頼の状態</th></tr>"]
    for t in tasks:
        d = t.due
        strong = d.strong(today) and not overdue
        cls = "overdue" if overdue else ("strong" if strong else "")
        mark = f' <span class="mark">{_e(STRONG_MARK)}</span>' if strong else ""
        out.append(f'<tr class="{cls}"><td>{_e(d.label())}{mark}</td><td>{_e(d.days_text(today) or "—")}</td>'
                   f"<td>{_e(t.case)}</td><td>{_e(what_text(t))}</td><td>{_e(d.state_word)}</td>"
                   f"<td>{_e(who_text(t))}</td><td>{_e(t.state or '—')}</td></tr>")
    out.append("</table></div>")
    return out


def _table(head: List[str], rows: List[List[object]], empty: str) -> List[str]:
    if not rows:
        return [f'<p class="note">{_e(empty)}</p>']
    out = ['<div class="wide"><table>', "<tr>" + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr>"]
    out += ["<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>" for row in rows]
    out.append("</table></div>")
    return out


def _cards(ov: deadlines.Overview) -> List[str]:
    if not ov.cases:
        return ['<p class="note">案件はまだありません。</p>']
    out = ['<div class="cards">']
    for case in ov.cases:
        out.append(f'<div class="card"><div class="case">{_e(case.name)}</div>')
        if case.problem:
            out.append('<div class="note">期限を組み立てられませんでした（パソコンの 今の状態.html を見てください）</div></div>')
            continue
        out.append(f"<div>今の段階：{_e(case.current or '—')}{'（提出済み）' if case.submitted else ''}</div>")
        nxt = case.next_task()
        if nxt is not None:
            days = nxt.due.days_text(ov.today)
            out.append(f'<div class="next">次の締切：{_e(what_text(nxt))}<br>{_e(nxt.due.label())}'
                       + (f' <span class="days">{_e(days)}</span>' if days else "") + "</div>")
        out.append("</div>")
    out.append("</div>")
    return out


def _gantt(ov: deadlines.Overview) -> List[str]:
    from lib import status_book

    months, found = status_book.gantt(ov)
    out = ["<h2>工程表</h2>"]
    if not found:
        return out + ['<p class="note">期限の日付が出せる手続きの段階が、まだありません。</p>']
    today_col = (ov.today.year, ov.today.month)
    out.append('<p class="note">横の帯が手続きの段階（効果報告は年ごとの提出期間）、◆ が期限の月、赤い縦線が今日の月です。'
               "表は横に動かせます。</p>")
    head = ["<tr><th>案件</th><th>手続き</th><th>期限</th>"]
    for y, m in months:
        cls = "g g-today" if (y, m) == today_col else "g"
        label = f"{y}<br>{m}" if m == 1 or (y, m) == months[0] else f"{m}"
        head.append(f'<th class="{cls}" title="{_e(f"{y}年{m}月")}">{label}</th>')
    out += ['<div class="wide"><table class="gantt">', "".join(head) + "</tr>"]
    for b in found:
        row = [f"<tr><td>{_e(b.case)}</td><td>{_e(b.label)}（{_e(b.state)}）</td><td>{_e(b.due_label)}</td>"]
        for ym, mark in zip(months, status_book.cells(months, b, ov.today)):
            cls = ["g"] + ([f"g-{mark}"] if mark else []) + (["g-today"] if ym == today_col else [])
            row.append(f'<td class="{" ".join(cls)}">{"◆" if mark == "mark" else ""}</td>')
        out.append("".join(row) + "</tr>")
    out.append("</table></div>")
    return out


def _defect_counts(folder: Path) -> List[str]:
    from lib import status_book

    items = status_book.defects(folder)
    if not items:
        return []
    left = [i for i in items if not i.get("直した")]
    counts = "、".join(f"{w} {sum(1 for i in left if i.get('重さ') == w)}件" for w in ("重大", "要確認", "助言"))
    return ["<h2>不備</h2>", f"<p>直していない不備：{_e(counts)}（中身と直し方は、パソコンの 今の状態.html にあります）</p>"]


def render(ov: deadlines.Overview, folder: Path) -> str:
    """claude.ai に上げる画面の中身。"""
    from lib import status_book as sb

    folder = Path(folder)
    today = ov.today
    when = dates.format_date(today) + ("（日付を差し替えています）" if ov.substituted else "")
    out = [
        "<!doctype html>",
        '<html lang="ja"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(TITLE)}</title>",
        f"<style>{STYLE}</style></head><body><main>",
        f"<h1>{_e(TITLE)}</h1>",
        f'<p class="note">{_e(when)}時点の写しです（日本時間）。いちばん新しいものは、パソコンの会社のフォルダにある 今の状態.html です。'
        "会社名・金額・相手先・書類のファイルの名前は入れていません。新しくするときは、Claude に「claude.ai の今の状態を新しくして」"
        "と伝えてください。</p>",
    ]
    out += _cards(ov)
    out += _gantt(ov)
    out += ["<h2>期限と作業</h2>",
            f'<p class="note">近い締切は{ov.near_days}日以内。{deadlines.STRONG_DAYS}日以内は色を付けています。'
            "「見込み」は予定の日付から出した期限、「確定」は確かめた日付から出した期限です。</p>"]
    for group in deadlines.GROUPS:
        title = f"{group}（{ov.near_days}日以内）" if group == deadlines.NEAR else group
        out.append(f"<h3>{_e(title)}</h3>")
        out += _task_table(ov.groups.get(group) or [], today, overdue=group == deadlines.OVERDUE)
    out.append(f"<h3>{_e(f'{ov.near_days}日より先の期限')}</h3>")
    out += _task_table(ov.later, today)
    rest = []
    if ov.undated:
        rest.append(f"日付がまだ出せない期限が{len(ov.undated)}件")
    if ov.done:
        rest.append(f"済んだものが{len(ov.done)}件")
    if rest:
        out.append(f'<p class="note">ほかに、{_e("、".join(rest))}あります（パソコンの 今の状態.html）。</p>')

    out.append("<h2>外部への依頼と待ち</h2>")
    out += _table(["書類", "案件", "依頼の状態", "だれがするか", "始める日", "締切"],
                  [[_no_paren(t.doc) or t.doc, t.case, t.state or "—", who_text(t), t.start_label() or "—", t.due.label()]
                   for t in ov.requests()], "ありません。")

    out.append("<h2>今の段階の必須の書類</h2>")
    shown = False
    for case in ov.cases:
        if case.problem or not case.documents:
            continue
        shown = True
        collect = [d for d in case.documents if d.state != "様式で作る"]
        have = sum(1 for d in collect if d.state in ("台帳にあり", "添付する書類にあり"))
        out.append(f"<h3>{_e(case.name)}（{_e(case.current)}）：集める書類のうち、そろった {have}/{len(collect)}件</h3>")
        out += _table(["書類", "状態"], [[d.name, d.state] for d in case.documents], "")
    if not shown:
        out.append('<p class="note">ありません。</p>')
    out += _defect_counts(folder)

    out.append("<h2>申請書（様式の項目ごとの進み具合）</h2>")
    forms = sb.forms(folder, ov)
    if not forms:
        out.append('<p class="note">様式の項目は、まだありません。</p>')
    for case in dict.fromkeys(f.case for f in forms):
        items = [f for f in forms if f.case == case]
        counts = "・".join(f"{s} {n}" for s in (sb.NOT_YET, sb.DRAFT, sb.PROVISIONAL, sb.CHECKING, sb.DONE)
                          for n in [sum(1 for f in items if f.state == s)] if n)
        out.append(f"<h3>{_e(case)}：{_e(counts)}（{len(items)}項目）</h3>")
        out.append("<details><summary>項目ごとに見る</summary>")
        out += _table(["案件", "様式", "項目", "進み具合", "文字数", "上限"],
                      [[f.case, f.form, f.item, f.state, f.chars, f.limit or "—"] for f in items], "")
        out.append("</details>")
    out.append("<h2>長い期限（効果報告など、年ごと）</h2>")
    out += _table(sb.YEAR_HEAD, [sb.year_values(y) for y in sb.long_deadlines(ov)],
                  "年ごとの期限は、事業の完了の日と決算の月が分かってから出ます。")
    duties = sum(len(c.duties) for c in ov.cases if c.period)
    if duties:
        out.append(f'<p class="note">事業期間中と事業後の義務の知らせが{duties}件あります（中身は、パソコンの 今の状態.html）。</p>')
    out.append("</main></body></html>")
    return "\n".join(out) + "\n"


def make(folder: Path, ov: Optional[deadlines.Overview] = None) -> Path:
    """画面を作って書き、ハッシュを控える。入れてはいけないものが入っていれば、書かずに ArtifactPageError。"""
    folder = Path(folder)
    if ov is None:
        ov = deadlines.build(folder)
    page = render(ov, folder)
    found = leaks(page, forbidden_words(folder))
    if found:
        raise ArtifactPageError(f"画面に入れてはいけないもの（{'、'.join(found)}）が入ったので、作っていません。"
                                "案件の名前や書類の名前に入っていないかを確かめてください")
    for rel in (PAGE_REL, STAMP_REL):
        problem = place_text.write_problem(folder, rel, "claude.ai に上げる画面を作っていません")
        if problem:
            raise ArtifactPageError(problem)
    data = page.encode("utf-8")
    path = places.actual(folder, PAGE_REL, partial=True)
    _replace(path, data)
    stamp_data = {"ハッシュ": hashlib.sha256(data).hexdigest(), "作った日": dates.today(folder).isoformat(),
                  "画面": PAGE_REL}
    _replace(places.actual(folder, STAMP_REL, partial=True),
             (json.dumps(stamp_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return path


def call_values(folder: Path) -> Dict[str, str]:
    """Artifact の道具に渡す値（hook が通す形）。URL を残してあれば、同じ URL を上げ直す。"""
    values = {"file_path": str(page_path(folder)), "description": DESCRIPTION, "icon": ICON}
    url = saved_url(folder)
    if url:
        values = {"file_path": str(page_path(folder)), "url": url}
    return values
